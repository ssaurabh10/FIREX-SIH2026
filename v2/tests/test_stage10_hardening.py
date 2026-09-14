"""
FIREX v2 Stage 10 Comprehensive Hardening, Testing, Performance & Failure Injection Suite
Implements validation for:
1. Security & API Key verification (authentication toggle)
2. Rate Limiting Middleware (HTTP 429, Retry-After header, exempt paths)
3. In-Memory Cache (TTL expiration, invalidation, size tracking)
4. Health & Readiness Probes (Liveness, DB connectivity, asset readiness, status)
5. Database Composite Indexes verification
6. Failure Injection:
   - OpenRouter API timeout / total outage -> graceful fallback report, pipeline completes successfully
   - FIRMS API network error / timeout -> handled cleanly without crash
   - Concurrent pipeline execution -> pipeline lock enforces single-flight (HTTP 409 Conflict)
"""
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.config import settings
from app.core.security import verify_api_key
from app.core.cache import InMemoryCache, cache
from app.storage.database import Base, get_db
from app.storage.models import Observation, Incident, IndustrialAsset, AnalysisRun
from app.orchestration.lock import pipeline_lock, AnalysisAlreadyRunningError
from app.orchestration.pipeline import execute_analysis_pipeline
import requests

# Test in-memory DB setup
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    cache.clear()
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    cache.clear()


# ============================================================================
# 1. SECURITY & AUTHENTICATION TESTS
# ============================================================================
def test_security_auth_disabled_by_default():
    """Verify that when API_KEY_AUTH_ENABLED is False, all requests pass freely."""
    with patch.object(settings, "API_KEY_AUTH_ENABLED", False):
        test_app = FastAPI()
        @test_app.get("/protected", dependencies=[Depends(verify_api_key)])
        def protected_route():
            return {"status": "authorized"}

        c = TestClient(test_app)
        res = c.get("/protected")
        assert res.status_code == 200
        assert res.json()["status"] == "authorized"

def test_security_auth_enforced_when_enabled():
    """Verify that when API_KEY_AUTH_ENABLED is True, invalid keys return 401."""
    with patch.object(settings, "API_KEY_AUTH_ENABLED", True), \
         patch.object(settings, "ADMIN_API_KEY", "secret-test-key-123"):
        test_app = FastAPI()
        @test_app.get("/protected", dependencies=[Depends(verify_api_key)])
        def protected_route():
            return {"status": "authorized"}

        c = TestClient(test_app)
        # Missing key
        res1 = c.get("/protected")
        assert res1.status_code == 401
        assert "Invalid or missing sovereign API key" in res1.json()["detail"]

        # Wrong key
        res2 = c.get("/protected", headers={"X-FIREX-KEY": "wrong-key"})
        assert res2.status_code == 401

        # Correct key
        res3 = c.get("/protected", headers={"X-FIREX-KEY": "secret-test-key-123"})
        assert res3.status_code == 200
        assert res3.json()["status"] == "authorized"


# ============================================================================
# 2. RATE LIMITING TESTS
# ============================================================================
def test_rate_limiting_middleware_enforcement():
    """Verify rate limiter blocks IPs exceeding limit with HTTP 429 and Retry-After."""
    from app.core.ratelimit import RateLimitMiddleware
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=5)

    @test_app.get("/api/test-rate")
    def rate_tested():
        return {"ok": True}

    c = TestClient(test_app)
    # First 5 requests must succeed
    for _ in range(5):
        r = c.get("/api/test-rate")
        assert r.status_code == 200

    # 6th request must be rejected with 429
    r6 = c.get("/api/test-rate")
    assert r6.status_code == 429
    assert "Rate limit exceeded" in r6.json()["error"]
    assert "Retry-After" in r6.headers

def test_rate_limiting_exempt_paths():
    """Verify console, docs, and crops static paths bypass rate limiting."""
    from app.core.ratelimit import RateLimitMiddleware
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=2)

    @test_app.get("/console/index.html")
    def console():
        return "html"

    c = TestClient(test_app)
    # 5 requests to exempt path should all succeed
    for _ in range(5):
        r = c.get("/console/index.html")
        assert r.status_code == 200


# ============================================================================
# 3. HIGH-PERFORMANCE IN-MEMORY CACHE TESTS
# ============================================================================
def test_in_memory_cache_ttl_and_expiry():
    """Test cache operations: get, set, TTL expiry, delete, and size."""
    test_cache = InMemoryCache(default_ttl_seconds=1)
    test_cache.set("key1", {"data": 42}, ttl=1)
    assert test_cache.get("key1") == {"data": 42}
    assert test_cache.size() == 1

    # Wait for expiry
    time.sleep(1.1)
    assert test_cache.get("key1") is None
    assert test_cache.size() == 0

    # Delete test
    test_cache.set("key2", "val", ttl=60)
    assert test_cache.get("key2") == "val"
    test_cache.delete("key2")
    assert test_cache.get("key2") is None


# ============================================================================
# 4. HEALTH CHECKS & READINESS PROBES
# ============================================================================
def test_liveness_probe_health():
    """GET /health must return 200 OK with liveness details."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "version" in data
    assert "timestamp" in data

def test_readiness_probe_health():
    """GET /health/readiness must verify database connectivity, assets count, and cache."""
    db = TestingSessionLocal()
    asset = IndustrialAsset(
        id="IND-TEST-001",
        name="Test Refiner",
        facility_type="Refinery",
        industry="Petroleum",
        category="Petrochemical",
        latitude=22.0,
        longitude=71.0,
        buffer_radius_meters=1000.0
    )
    db.add(asset)
    db.commit()
    db.close()

    res = client.get("/health/readiness")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert data["assets_registered"] >= 1
    assert data["pipeline_busy"] is False
    assert "cache_entries" in data

def test_system_status_hardening_metrics():
    """GET /status must include hardening configuration: rate limits, cache, lock."""
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] in ["FIREX-SIH2026", "FIREX v2 Engine"]
    assert "hardening" in data
    assert data["hardening"]["rate_limiting"] is not None
    assert data["hardening"]["cache_enabled"] is not None
    assert "cache_size" in data["hardening"]
    assert "pipeline_locked" in data["hardening"]


# ============================================================================
# 5. DATABASE COMPOSITE INDEXES VERIFICATION
# ============================================================================
def test_database_composite_indexes():
    """Verify that composite indexes defined in Blueprint Stage 10 are active on models."""
    obs_index_names = [idx.name for idx in Observation.__table__.indexes]
    inc_index_names = [idx.name for idx in Incident.__table__.indexes]

    # Observations composite indexes
    assert "ix_obs_lat_lon" in obs_index_names
    assert "ix_obs_acquired_frp" in obs_index_names

    # Incidents composite indexes
    assert "ix_incidents_lat_lon" in inc_index_names
    assert "ix_incidents_status_priority" in inc_index_names
    assert "ix_incidents_status_severity" in inc_index_names
    assert "ix_incidents_last_detected" in inc_index_names


# ============================================================================
# 6. FAILURE INJECTION & RESILIENCE TESTS
# ============================================================================
TEST_CSV_PAYLOAD = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
22.4707,70.0577,365.2,0.4,0.4,2026-09-14,0230,N,VIIRS,nominal,2.0NRT,310.2,250.0,D
"""

def test_failure_injection_openrouter_outage_pipeline_survives():
    """
    FAILURE INJECTION 1:
    Simulate complete OpenRouter provider failure (timeout / HTTP 500 across all keys).
    The pipeline must NOT crash. It must fall back to deterministic multi-source AI
    investigation rules, generate valid evidence, and complete the analysis run with status 'COMPLETED'.
    """
    db = TestingSessionLocal()
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out to OpenRouter")):
        summary = execute_analysis_pipeline(
            db=db,
            firms_csv=TEST_CSV_PAYLOAD,
            force_reinvestigate=True,
            export_to_dashboard=False
        )

        assert summary["status"] == "COMPLETED"
        assert summary["candidates_investigated"] >= 1

        from app.storage.models import AIInvestigation
        inv = db.query(AIInvestigation).first()
        assert inv is not None
        assert inv.uncertainty.lower() in ["high", "medium"]
        assert inv.evidence_points.get("needs_reinvestigation") is True
    db.close()


def test_failure_injection_firms_network_error_pipeline_survives():
    """
    FAILURE INJECTION 2:
    Simulate NASA FIRMS API network disconnect / HTTP 503 error.
    The pipeline must log the failure, gracefully continue with existing/zero observations,
    and finish without taking down the server.
    """
    db = TestingSessionLocal()
    with patch("app.ingestion.firms.FIRMSClient.fetch_live_csv", side_effect=RuntimeError("NASA FIRMS 503 Service Unavailable")):
        summary = execute_analysis_pipeline(db=db, export_to_dashboard=False)
        assert summary["status"] == "COMPLETED"
        assert summary["new_observations"] == 0
    db.close()


def test_failure_injection_concurrent_pipeline_locking():
    """
    FAILURE INJECTION 3:
    Simulate two concurrent calls to trigger analysis.
    The backend pipeline lock must reject the second call with AnalysisAlreadyRunningError / 409 Conflict.
    """
    db = TestingSessionLocal()
    lock_id = "LOCK-TEST-STG10"
    acquired = pipeline_lock.acquire(lock_id)
    assert acquired is True
    try:
        with pytest.raises(AnalysisAlreadyRunningError):
            execute_analysis_pipeline(db=db, export_to_dashboard=False)
    finally:
        pipeline_lock.release(lock_id)
    db.close()
