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

    @test_app.get("/api/not-exempt")
    def not_exempt():
        return {"ok": True}

    c = TestClient(test_app)
    # 5 requests to exempt path should all succeed
    for _ in range(5):
        r = c.get("/console/index.html")
        assert r.status_code == 200

    # The loop above only shows exempt requests are not *blocked*. It cannot
    # show they are not *counted*, which is the claim that matters: counting
    # them would let console traffic consume the API's budget, so a client that
    # had merely loaded the UI would be throttled on its first data call. With
    # the limit at 2, five counted requests would have blocked this one (E9,
    # F-093).
    r = c.get("/api/not-exempt")
    assert r.status_code == 200, (
        "requests to an exempt path consumed the rate-limit budget: the "
        "non-exempt request after 5 exempt ones was throttled"
    )


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
    # Section 12 advertises "Rate limiting (120 req/min)" and the shipped value
    # is config.RATE_LIMIT_PER_MINUTE, wired at main.py:40. Asserting only that
    # the flag is non-None left the number itself unguarded -- it could have been
    # changed to any value without a failure, which is the half of this test that
    # was missing (E9, F-093).
    assert data["hardening"]["rate_limit_per_minute"] == 120, (
        f"shipped rate limit is {data['hardening']['rate_limit_per_minute']}, "
        f"but V2_LOGIC_SPECIFICATION.md section 12 documents 120 req/min"
    )
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


# NASA's area/csv API names its sources as satellite+latency pairs; the list is
# published at https://firms.modaps.eosdis.nasa.gov/api/area/ and holds no bare
# instrument-series name. The pipeline used to request "VIIRS_NRT", which the API
# rejects with HTTP 400 "Invalid source." -- measured directly against the live
# endpoint with a dummy key -- so fetch_live_csv returned None on every run and
# the live branch silently degraded to already-stored observations.
SERVED_FIRMS_PRODUCTS = {
    "LANDSAT_NRT",
    "MODIS_NRT",
    "MODIS_SP",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "VIIRS_SNPP_SP",
}


def test_live_branch_requests_a_product_nasa_serves():
    """
    The live branch is the default path for the console's "Sync Analysis" action
    (the SSE route reaches execute_analysis_pipeline with firms_csv and file_path
    both None), so a product the API refuses means the primary operator action
    can never ingest anything. Assert the product actually passed at the call
    site, not just the constant it is built from.
    """
    db = TestingSessionLocal()
    requested = []

    def _capture(product, days=1):
        requested.append(product)
        return None  # exercise the "no live payload" fallback the API produces

    with patch("app.ingestion.firms.FIRMSClient.fetch_live_csv", side_effect=_capture):
        summary = execute_analysis_pipeline(db=db, export_to_dashboard=False)
    db.close()

    assert summary["status"] == "COMPLETED"
    assert requested, "the live branch was never reached; this test proves nothing"
    for product in requested:
        assert product in SERVED_FIRMS_PRODUCTS, (
            f"the live fetch requested {product!r}, which NASA's area/csv API does "
            f"not serve: the request 400s on the source and the branch never ingests"
        )


def test_every_ingestion_default_names_a_served_firms_product():
    """
    A rejected id as a *default* is worse than a rejected id at one call site:
    it is reached by every caller that does not name a product, and it stamps the
    bogus id onto whatever it parses. `product` is a label and an instrument hint
    (it is not part of the observation's dedup identity), so the defaults are
    assertable directly through the signatures.
    """
    import inspect

    from app.ingestion.firms import FIRMSClient
    from app.ingestion.normalizer import normalize_raw_firms

    targets = (
        FIRMSClient.parse_csv,
        FIRMSClient.ingest_from_file,
        normalize_raw_firms,
    )
    for fn in targets:
        default = inspect.signature(fn).parameters["product"].default
        assert default in SERVED_FIRMS_PRODUCTS, (
            f"{fn.__qualname__} defaults product to {default!r}, which NASA's "
            f"area/csv API does not serve"
        )

    assert all(p in SERVED_FIRMS_PRODUCTS for p in settings.FIRMS_DEFAULT_PRODUCTS), (
        f"FIRMS_DEFAULT_PRODUCTS holds an unserved id: {settings.FIRMS_DEFAULT_PRODUCTS}"
    )


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


# ============================================================================
# PHASE 1 AUDIT REMEDIATION VERIFICATION TESTS (H-8, H-4, H-5, H-7)
# ============================================================================

def test_phase1_sovereign_mask_territorial_integrity():
    """
    Verify Invariant INV-3: Sovereign mask must encompass all real Indian sovereign territory
    (including North Sikkim, Arunachal McMahon line, Hazira, and coastlines) while rejecting open sea (H-8).
    """
    from app.gis.boundaries import is_within_indian_sovereign_territory

    benchmark_points = [
        # Formerly rejected points in North Sikkim, Arunachal, Hazira, and coasts
        ("Lachen", 27.72, 88.56, True),
        ("Lachung", 27.69, 88.75, True),
        ("Chungthang", 27.60, 88.65, True),
        ("Tawang", 27.59, 91.86, True),
        ("Ziro", 27.59, 93.83, True),
        ("Daporijo", 27.99, 94.22, True),
        ("Hazira_ONGC_AMNS", 21.103, 72.649, True),
        ("Paradip_IOCL", 20.26, 86.66, True),
        ("Kakinada", 16.99, 82.25, True),
        ("Machilipatnam", 16.17, 81.13, True),
        ("Kannur", 11.87, 75.37, True),
        ("Alappuzha", 9.50, 76.34, True),
        ("Kozhikode", 11.25, 75.78, True),
        # Established major mainland cities
        ("Gangtok", 27.33, 88.61, True),
        ("Surat", 21.17, 72.83, True),
        ("Delhi", 28.61, 77.21, True),
        ("Mumbai", 19.07, 72.88, True),
        ("Kolkata", 22.57, 88.36, True),
        # Genuinely offshore points must remain False
        ("Sea_Paradip", 20.0, 87.2, False),
        ("Sea_Chennai", 13.0, 80.9, False),
        ("Sea_Kochi", 9.5, 75.5, False),
        ("Sea_Gujarat", 21.0, 71.5, False),
        ("Sea_Kolkata", 21.5, 88.3, False),
    ]

    for name, lat, lon, expected in benchmark_points:
        result = is_within_indian_sovereign_territory(lat, lon)
        assert result == expected, (
            f"Sovereign mask check failed for {name} ({lat}, {lon}): got {result}, expected {expected}"
        )


def test_phase1_mutating_endpoints_auth_enforcement():
    """
    Verify mutating endpoints are authenticated with verify_api_key when enabled (H-4).
    """
    test_key = "sovereign-audit-key-2026"
    with patch.object(settings, "API_KEY_AUTH_ENABLED", True), \
         patch.object(settings, "ADMIN_API_KEY", test_key):

        # 1. POST /api/analysis/run
        r1_no_key = client.post("/api/analysis/run", json={})
        assert r1_no_key.status_code == 401, f"Expected 401, got {r1_no_key.status_code}"

        r1_wrong_key = client.post("/api/analysis/run", json={}, headers={"X-FIREX-KEY": "bad-key"})
        assert r1_wrong_key.status_code == 401

        # 2. POST /api/observations/ingest
        r2_no_key = client.post("/api/observations/ingest", json={"product": "VIIRS_NOAA20_NRT"})
        assert r2_no_key.status_code == 401

        # 3. POST /api/incidents/cluster-sync
        r3_no_key = client.post("/api/incidents/cluster-sync")
        assert r3_no_key.status_code == 401

        # 4. POST /api/alerts/{id}/ack
        r4_no_key = client.post("/api/alerts/ALT-NONEXIST/ack")
        assert r4_no_key.status_code == 401

        # 5. POST /api/industries/seed
        r5_no_key = client.post("/api/industries/seed")
        assert r5_no_key.status_code == 401


def test_phase1_file_path_containment_and_security():
    """
    Verify caller-controlled file_path is strictly validated and contained (H-5).
    """
    from app.core.security import validate_fixture_path

    # Sensitive files must be denied
    with pytest.raises(ValueError, match="Access to sensitive file denied"):
        validate_fixture_path("backend/.env")

    with pytest.raises(ValueError, match="Access to sensitive file denied"):
        validate_fixture_path("backend/data/firex_v2.db")

    # Non-CSV files must be denied
    with pytest.raises(ValueError, match="Unauthorized file type"):
        validate_fixture_path("README.md")

    # Non-existent files must be denied
    with pytest.raises(ValueError, match="does not exist"):
        validate_fixture_path("non_existent_fixture.csv")

    # API endpoint returns 400 Bad Request on path violation
    res = client.post("/api/observations/ingest", json={"file_path": "backend/.env"})
    assert res.status_code == 400


def test_phase1_crops_rate_limiting():
    """
    Verify /crops route is NOT exempt from rate limiting (H-7).
    """
    from app.core.ratelimit import RateLimitMiddleware
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=3)

    @test_app.get("/crops/{incident_id}/{filename}")
    def fake_crop(incident_id: str, filename: str):
        return {"crop": True}

    c = TestClient(test_app)
    # First 3 requests succeed
    for _ in range(3):
        r = c.get("/crops/INC-001/crop.jpg")
        assert r.status_code == 200

    # 4th request must be throttled with 429
    r_throttled = c.get("/crops/INC-001/crop.jpg")
    assert r_throttled.status_code == 429


def test_phase2_chronic_clamp_cache_shortcut():
    """
    Verify H-1: HistoricalBaseline cache shortcut returns active_days and enables chronic clamp.
    """
    import uuid
    from datetime import datetime, timedelta
    from app.storage.models import HistoricalBaseline, BehaviorProfile
    from app.behavior.baseline import get_or_create_location_baseline
    from app.severity.scoring import compute_incident_severity

    db = TestingSessionLocal()
    try:
        lat, lon = 22.50, 85.50
        spatial_key = "GRID_22.50_85.50"

        prof = BehaviorProfile(
            profile_type="location",
            spatial_reference=spatial_key,
            window_start=datetime.utcnow() - timedelta(days=365),
            window_end=datetime.utcnow(),
            observation_count=150,
            active_days=110,
            median_frp=15.0,
            mean_frp=16.0,
            p90_frp=25.0,
            p95_frp=30.0,
            max_frp=50.0
        )
        db.add(prof)
        db.flush()

        hb = HistoricalBaseline(
            spatial_key=spatial_key,
            profile_id=prof.id,
            detection_count_365d=150,
            median_frp=15.0,
            mean_frp=16.0,
            p90_frp=25.0,
            p95_frp=30.0,
            last_updated_at=datetime.utcnow()
        )
        db.add(hb)
        db.commit()

        # Call baseline helper - hits 24h cache shortcut
        bl = get_or_create_location_baseline(lat, lon, db)
        assert bl.get("active_days") == 110
        assert bl.get("active_days_365d") == 110

        # Test scoring with active_days=110 and FRP under P95
        res = compute_incident_severity(
            frp_mw=20.0,
            median_frp=15.0,
            p95_frp=30.0,
            active_days_365=bl["active_days"],
            observation_count=bl["observation_count"],
            classification="uncertain",
            ai_confidence=50.0,
            firms_confidence=70.0
        )
        assert res["factors"]["is_chronic_source"] is True
        assert res["severity_level"] == "LOW"
        assert res["severity_score"] <= 20.0
    finally:
        db.close()


def test_phase2_chronic_clamp_does_not_demote_forced_overrides():
    """
    Verify H-2: Operational overrides (forced CRITICAL / industrial_fire) are NEVER demoted
    to LOW/20.0 by chronic suppression. Overrides raise, never lower.
    """
    from app.severity.scoring import compute_incident_severity

    res = compute_incident_severity(
        frp_mw=25.0,
        median_frp=15.0,
        p95_frp=30.0,
        active_days_365=120,  # >= 90 days (chronic site)
        classification="industrial_fire",  # Forces CRITICAL
        ai_confidence=92.0,
        firms_confidence=90.0,
        is_inside_facility=True
    )
    # Forced override must stay CRITICAL and score >= 80.0
    assert res["severity_level"] == "CRITICAL"
    assert res["severity_score"] >= 80.0
    assert res["has_override"] is True
    assert "CHRONIC_SOURCE_SUPPRESSION" not in res["override_reasons"]


def test_phase2_frp_curve_adheres_to_spec_4_6_1():
    """
    Verify H-3: Effective FRP score uses raw curve unless routine flare.
    """
    from app.severity.scoring import compute_incident_severity

    # Non-routine flare must use raw FRP curve
    res_raw = compute_incident_severity(
        frp_mw=40.0,
        firms_confidence=80.0,
        classification="wildfire",
        ai_confidence=70.0,
        is_routine_flare=False
    )
    assert res_raw["factors"]["frp_curve"] == "raw"

    # Routine flare must use india_calibrated FRP curve
    res_calib = compute_incident_severity(
        frp_mw=40.0,
        firms_confidence=80.0,
        classification="wildfire",
        ai_confidence=70.0,
        is_routine_flare=True
    )
    assert res_calib["factors"]["frp_curve"] == "india_calibrated"


def test_phase2_selection_override_raw_ratio():
    """
    Verify M-5: Selection override compares raw ratio against 3.0, not rounded ratio.
    """
    from app.selection.scoring import compute_investigation_priority

    # Case A: 8.988 / 3.0 = 2.996 (< 3.0 raw, but rounds to 3.00)
    res_sub3 = compute_investigation_priority(
        frp_mw=8.988,
        historical_median_frp=3.0,
        has_history=True
    )
    assert res_sub3["is_override_triggered"] is False
    assert not any("STRONG_HISTORICAL_ANOMALY" in r for r in res_sub3["override_reasons"])

    # Case B: 9.006 / 3.0 = 3.002 (>= 3.0 raw)
    res_over3 = compute_investigation_priority(
        frp_mw=9.006,
        historical_median_frp=3.0,
        has_history=True
    )
    assert res_over3["is_override_triggered"] is True
    assert any("STRONG_HISTORICAL_ANOMALY" in r for r in res_over3["override_reasons"])


def test_phase2_cluster_association_idempotency_and_no_duplicate_audit_events():
    """
    Verify M-9 and M-10: Repeated cluster synchronization is idempotent.
    Mean FRP does not drift and duplicate incident.updated events are not emitted.
    """
    import uuid
    from datetime import datetime, timedelta
    from app.storage.models import Observation, IncidentEvent, IncidentObservation
    from app.incidents.clustering import cluster_observations
    from app.incidents.association import sync_clusters_to_incidents

    db = TestingSessionLocal()
    try:
        obs1 = Observation(
            id=str(uuid.uuid4()),
            latitude=21.15,
            longitude=72.80,
            frp_mw=100.0,
            acquired_at=datetime.utcnow() - timedelta(hours=2),
            satellite="N20",
            sensor="VIIRS"
        )
        obs2 = Observation(
            id=str(uuid.uuid4()),
            latitude=21.151,
            longitude=72.801,
            frp_mw=50.0,
            acquired_at=datetime.utcnow() - timedelta(hours=1),
            satellite="N20",
            sensor="VIIRS"
        )
        db.add_all([obs1, obs2])
        db.commit()

        clusters = cluster_observations([obs1, obs2])
        assert len(clusters) == 1

        # Pass 1: creates the incident
        incidents_p1 = sync_clusters_to_incidents(db, clusters)
        assert len(incidents_p1) == 1
        inc = incidents_p1[0]
        expected_mean = round((100.0 + 50.0) / 2.0, 2)
        assert inc.current_mean_frp == expected_mean
        assert inc.current_max_frp == 100.0

        events_p1 = db.query(IncidentEvent).filter(IncidentEvent.incident_id == inc.id).count()

        # Pass 2: syncs the exact same cluster again over the 72h window
        incidents_p2 = sync_clusters_to_incidents(db, clusters)
        assert len(incidents_p2) == 1
        inc_p2 = incidents_p2[0]

        # M-9 verification: mean FRP must NOT drift or double count
        assert inc_p2.current_mean_frp == expected_mean

        # M-10 verification: no duplicate incident.updated event written
        events_p2 = db.query(IncidentEvent).filter(IncidentEvent.incident_id == inc.id).count()
        assert events_p2 == events_p1
    finally:
        db.close()


# ============================================================================
# PHASE 3 REGRESSION TESTS (M-2, M-3, M-6, M-11, M-12)
# ============================================================================
def test_m12_invalid_incident_state_validation():
    """M-12: Reject invalid state values with ValueError / HTTP 422."""
    from datetime import datetime
    from app.incidents.state import transition_incident_state
    db = TestingSessionLocal()
    try:
        now = datetime.utcnow()
        inc = Incident(
            id="test-m12-inc",
            latitude=20.0,
            longitude=75.0,
            first_detected_at=now,
            last_detected_at=now,
            status="PENDING",
            classification="unclassified"
        )
        db.add(inc)
        db.commit()

        # Direct function call must raise ValueError
        with pytest.raises(ValueError, match="Invalid state 'SUPERNOVA'"):
            transition_incident_state(db, inc, "SUPERNOVA", reason="testing invalid state")

        # API endpoint must return 422 Unprocessable Entity
        res = client.post(
            f"/api/incidents/{inc.id}/state",
            json={"new_state": "INVALID_STATE", "reason": "testing API validation"}
        )
        assert res.status_code == 422
        assert "Invalid state" in res.json()["detail"]
    finally:
        db.close()


def test_m2_severity_assessment_state_transition_audit():
    """M-2: Severity assessment state change creates an audit trail event."""
    from datetime import datetime
    from app.severity.service import evaluate_incident_severity
    from app.storage.models import IncidentEvent
    db = TestingSessionLocal()
    try:
        now = datetime.utcnow()
        inc = Incident(
            id="test-m2-inc",
            incident_code="INC-M2-001",
            latitude=21.15,
            longitude=72.80,
            first_detected_at=now,
            last_detected_at=now,
            status="PENDING",
            classification="industrial_fire",
            current_max_frp=150.0,
            current_mean_frp=120.0
        )
        db.add(inc)
        db.commit()

        result = evaluate_incident_severity(inc.id, db)
        assert result["severity_level"] in ("HIGH", "CRITICAL")
        
        # Incident status should have transitioned from PENDING to ACTIVE/ESCALATED
        db.refresh(inc)
        assert inc.status != "PENDING"

        # An incident.state_changed event must have been recorded
        events = db.query(IncidentEvent).filter(
            IncidentEvent.incident_id == inc.id,
            IncidentEvent.event_type == "incident.state_changed"
        ).all()
        assert len(events) >= 1
        assert events[0].payload["from_state"] == "PENDING"
        assert events[0].payload["to_state"] == inc.status
    finally:
        db.close()


def test_m3_lru_cache_bounds_and_query_validation():
    """M-3: LRU bounded cache evicts oldest entries and query params are strictly bounded."""
    # 1. Test LRU capacity and eviction
    bounded_cache = InMemoryCache(default_ttl_seconds=3600, max_size=3)
    bounded_cache.set("k1", "v1")
    bounded_cache.set("k2", "v2")
    bounded_cache.set("k3", "v3")
    assert bounded_cache.size() == 3

    # Access k1 so k2 becomes LRU
    assert bounded_cache.get("k1") == "v1"

    # Insert k4, which should evict k2
    bounded_cache.set("k4", "v4")
    assert bounded_cache.size() == 3
    assert bounded_cache.get("k2") is None
    assert bounded_cache.get("k1") == "v1"
    assert bounded_cache.get("k3") == "v3"
    assert bounded_cache.get("k4") == "v4"

    # 2. Query param bounds
    # window_days must be between 1 and 365
    res1 = client.get("/api/incidents/some-id/history?window_days=0")
    assert res1.status_code == 422

    res2 = client.get("/api/incidents/some-id/history?window_days=400")
    assert res2.status_code == 422

    # q in search_industries must be <= 100 characters
    long_q = "a" * 105
    res3 = client.get(f"/api/industries/search?q={long_q}")
    assert res3.status_code == 422


def test_m11_external_id_unique_constraint_and_race_recovery():
    """M-11: Observation.external_id is unique, and firms.py recovers gracefully from race conditions."""
    from datetime import datetime
    from app.ingestion.firms import FIRMSClient
    from app.ingestion.validator import NormalizedObservation
    from sqlalchemy.exc import IntegrityError

    db = TestingSessionLocal()
    try:
        obs1 = Observation(
            id="obs-m11-1",
            external_id="EXT-UNIQUE-001",
            latitude=20.0,
            longitude=75.0,
            frp_mw=10.0,
            acquired_at=datetime.utcnow()
        )
        db.add(obs1)
        db.commit()

        # Inserting duplicate external_id directly should trigger IntegrityError
        obs2 = Observation(
            id="obs-m11-2",
            external_id="EXT-UNIQUE-001",
            latitude=20.1,
            longitude=75.1,
            frp_mw=20.0,
            acquired_at=datetime.utcnow()
        )
        db.add(obs2)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        # Ingestion save_to_db fallback when concurrent inserts collide
        client_firms = FIRMSClient()
        norm_obs1 = NormalizedObservation(
            external_id="EXT-UNIQUE-001", # Existing in DB
            latitude=20.0,
            longitude=75.0,
            frp_mw=15.0,
            confidence_raw="nominal",
            confidence_score=75.0,
            satellite="N20",
            sensor="VIIRS",
            product="VIIRS_SNPP_NRT",
            daynight="D",
            acquired_at=datetime.utcnow(),
            raw_payload={}
        )
        norm_obs3 = NormalizedObservation(
            external_id="EXT-UNIQUE-003", # Fresh
            latitude=20.2,
            longitude=75.2,
            frp_mw=25.0,
            confidence_raw="nominal",
            confidence_score=80.0,
            satellite="N20",
            sensor="VIIRS",
            product="VIIRS_SNPP_NRT",
            daynight="D",
            acquired_at=datetime.utcnow(),
            raw_payload={}
        )

        # Ingest batch containing 1 collision and 1 new record
        res = client_firms.save_to_db(db, [norm_obs1, norm_obs3])
        assert res["ingested"] == 1
        assert res["skipped_duplicate"] == 1
    finally:
        db.close()


# ============================================================================
# PHASE 4 REGRESSION TESTS (H-6, M-8, L-1, L-4, M-14)
# ============================================================================
def test_h6_get_anomaly_endpoint_does_not_write_db():
    """H-6: GET /api/incidents/{id}/anomaly evaluates without committing a HistoricalAnomaly row."""
    from datetime import datetime
    from app.storage.models import HistoricalAnomaly

    db = TestingSessionLocal()
    try:
        now = datetime.utcnow()
        inc = Incident(
            id="inc-h6-test",
            incident_code="INC-H6-001",
            latitude=21.15,
            longitude=72.80,
            first_detected_at=now,
            last_detected_at=now,
            status="ACTIVE",
            current_max_frp=85.0
        )
        db.add(inc)
        db.commit()

        initial_count = db.query(HistoricalAnomaly).filter(HistoricalAnomaly.incident_id == inc.id).count()
        assert initial_count == 0

        # Invoke GET endpoint
        res = client.get(f"/api/incidents/{inc.id}/anomaly")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert data["incident_id"] == inc.id

        # Verify no record was inserted
        after_count = db.query(HistoricalAnomaly).filter(HistoricalAnomaly.incident_id == inc.id).count()
        assert after_count == 0
    finally:
        db.close()


def test_l1_sql_like_wildcard_escaping():
    """L-1: LIKE/ILIKE wildcards (% and _) are escaped and do not trigger full table matching."""
    from datetime import datetime
    from app.core.security import escape_like_pattern

    assert escape_like_pattern("test%_val") == "test\\%\\_val"
    assert escape_like_pattern("") == ""

    db = TestingSessionLocal()
    try:
        now = datetime.utcnow()
        obs = Observation(
            id="obs-l1-test",
            external_id="EXT-L1-001",
            satellite="NOAA-20",
            sensor="VIIRS",
            latitude=20.0,
            longitude=75.0,
            frp_mw=10.0,
            acquired_at=now
        )
        db.add(obs)
        db.commit()

        # Querying with a raw wildcard "%" should NOT match "NOAA-20" when escaped
        res = client.get("/api/observations?satellite=%25")
        assert res.status_code == 200
        # When % is escaped to \% literal, it shouldn't match NOAA-20
        matching = [item for item in res.json() if item["id"] == "obs-l1-test"]
        assert len(matching) == 0
    finally:
        db.close()


def test_l4_unguarded_current_max_frp_resilience():
    """L-4: None or 0.0 for current_max_frp is guarded in severity scoring and alert formatting."""
    from app.severity.scoring import calculate_frp_severity, compute_incident_severity

    # calculate_frp_severity must handle None or 0
    assert calculate_frp_severity(0.0) == 0.0

    # compute_incident_severity must handle frp_mw=0 or None without crashing
    res = compute_incident_severity(
        frp_mw=0.0,
        firms_confidence=80.0,
        classification="industrial_fire",
        ai_confidence=90.0,
        median_frp=10.0,
        p95_frp=20.0,
        history_reliability=1.0,
        is_routine_flare=False
    )
    assert res["severity_score"] >= 0.0
    assert "severity_level" in res




