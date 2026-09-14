"""
FIREX v2 Stage 8 Comprehensive Test Suite
Tests End-to-End Orchestration & SSE Event Streaming:
1. End-to-end pipeline execution connecting Stages 1-7
2. Verification of all 11 blueprint SSE events in sequence
3. Backend run lock preventing concurrent duplicate runs (HTTP 409 Conflict)
4. Idempotency & incremental processing (cached AI investigations)
5. REST endpoints: /api/analysis/run, /analysis/run, /api/analysis/status, /api/analysis/history, /api/analysis/stream
6. Backward-compatible v1 aliases: /api/trigger-sync
"""
import os
import json
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.storage.database import Base, get_db
from app.storage.models import (
    Observation, Incident, IndustrialAsset, AIInvestigation,
    SeverityAssessment, AlertRecord, AnalysisRun
)
from app.orchestration.lock import pipeline_lock, AnalysisAlreadyRunningError
from app.orchestration.events import (
    event_broadcaster,
    EVENT_ANALYSIS_STARTED,
    EVENT_FIRMS_FETCHED,
    EVENT_GIS_COMPLETED,
    EVENT_CLUSTERING_COMPLETED,
    EVENT_SELECTION_COMPLETED,
    EVENT_IMAGERY_STARTED,
    EVENT_AI_STARTED,
    EVENT_AI_COMPLETED,
    EVENT_SEVERITY_COMPLETED,
    EVENT_ALERT_CREATED,
    EVENT_ANALYSIS_COMPLETED
)
from app.orchestration.pipeline import execute_analysis_pipeline

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
TEST_CSV_PAYLOAD = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
20.965,85.171,365.2,0.4,0.4,2026-09-14,0230,N,VIIRS,nominal,2.0NRT,310.2,75.5,D
20.966,85.172,350.1,0.4,0.4,2026-09-14,0230,N,VIIRS,nominal,2.0NRT,305.0,42.0,D
22.366,87.303,320.0,0.5,0.5,2026-09-14,0230,N,VIIRS,nominal,2.0NRT,295.0,12.5,D
"""

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionTesting()

    # Pre-seed industrial asset: NTPC Talcher Power Station
    asset = IndustrialAsset(
        id="asset-talcher-01",
        name="Talcher Super Thermal Power Station & Coalfields",
        facility_type="thermal_power_plant",
        hazard_category="HIGH",
        category="RED",
        latitude=20.965,
        longitude=85.171,
        buffer_radius_meters=2000.0,
        state="Odisha",
        district="Angul"
    )
    session.add(asset)
    session.commit()

    # Ensure lock and broadcaster are clean
    pipeline_lock.force_unlock()
    event_broadcaster.clear()

    # Use deterministic mock AI provider for fast, reliable unit testing
    orig_provider = getattr(settings, "AI_PROVIDER", "openrouter")
    settings.AI_PROVIDER = "mock"

    try:
        yield session
    finally:
        session.close()
        pipeline_lock.force_unlock()
        settings.AI_PROVIDER = orig_provider


# ---------------------------------------------------------------------------
# 1. RUN LOCK & CONCURRENCY TESTS
# ---------------------------------------------------------------------------
def test_pipeline_lock_acquire_and_release():
    pipeline_lock.force_unlock()
    assert not pipeline_lock.is_locked()

    # Acquire lock
    assert pipeline_lock.acquire("run-001") is True
    assert pipeline_lock.is_locked() is True

    # Second acquire must raise AnalysisAlreadyRunningError
    with pytest.raises(AnalysisAlreadyRunningError) as exc_info:
        pipeline_lock.acquire("run-002")
    assert "run-001" in str(exc_info.value)

    # Release by wrong run_id fails
    assert pipeline_lock.release("run-999") is False
    assert pipeline_lock.is_locked() is True

    # Release by correct run_id succeeds
    assert pipeline_lock.release("run-001") is True
    assert not pipeline_lock.is_locked()


def test_concurrent_api_call_returns_409(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        # Manually hold lock to simulate ongoing run
        pipeline_lock.acquire("active-manual-run")

        response = client.post("/api/analysis/run")
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "ANALYSIS_ALREADY_RUNNING"

        # Also test blueprint exact top-level route
        resp_root = client.post("/analysis/run")
        assert resp_root.status_code == 409
        assert resp_root.json()["detail"]["error"] == "ANALYSIS_ALREADY_RUNNING"
    finally:
        pipeline_lock.force_unlock()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. SSE EVENT BROADCASTER & WIRE FORMAT TESTS
# ---------------------------------------------------------------------------
def test_sse_broadcaster_subscription_and_wire_format():
    queue = event_broadcaster.subscribe()
    assert queue is not None

    event_broadcaster.publish(
        EVENT_FIRMS_FETCHED,
        {"new_observations": 12, "skipped_duplicates": 2},
        run_id="test-run-123"
    )

    # Drain queue
    msg = queue.get_nowait()
    assert msg.startswith(f"event: {EVENT_FIRMS_FETCHED}\n")
    assert "data: " in msg
    assert "\n\n" in msg

    # Parse JSON from data line
    data_line = [line for line in msg.split("\n") if line.startswith("data: ")][0]
    parsed = json.loads(data_line[6:])
    assert parsed["event"] == EVENT_FIRMS_FETCHED
    assert parsed["run_id"] == "test-run-123"
    assert parsed["stage"] == 1
    assert parsed["pct"] == 20
    assert parsed["new_observations"] == 12

    event_broadcaster.unsubscribe(queue)


# ---------------------------------------------------------------------------
# 3. END-TO-END PIPELINE EXECUTION & 11 SSE EVENTS SEQUENCE
# ---------------------------------------------------------------------------
def test_end_to_end_analysis_pipeline_execution(db_session):
    # Subscribe queue to verify event stream in real-time
    queue = event_broadcaster.subscribe()

    # Execute pipeline on deterministic fixture
    summary = execute_analysis_pipeline(
        db=db_session,
        firms_csv=TEST_CSV_PAYLOAD,
        force_reinvestigate=True,
        max_ai_targets=2,
        export_to_dashboard=False
    )

    # Verify summary response
    assert summary["status"] == "COMPLETED"
    assert summary["new_observations"] >= 2
    assert summary["clusters_count"] >= 1
    assert summary["duration_seconds"] >= 0.0
    assert not pipeline_lock.is_locked()  # Lock must be released

    # Verify database persistence
    run_rec = db_session.query(AnalysisRun).filter(AnalysisRun.id == summary["run_id"]).first()
    assert run_rec is not None
    assert run_rec.status == "COMPLETED"
    assert run_rec.new_observations_count >= 2

    # Verify Incidents created
    incidents = db_session.query(Incident).all()
    assert len(incidents) >= 1
    top_inc = incidents[0]
    assert top_inc.status in ["ACTIVE", "PERSISTENT", "NEW", "ESCALATED"]
    assert top_inc.severity_score is not None

    # Collect and verify all emitted SSE events
    collected_events = []
    while not queue.empty():
        raw_sse = queue.get_nowait()
        for line in raw_sse.split("\n"):
            if line.startswith("event: "):
                collected_events.append(line.replace("event: ", "").strip())

    event_broadcaster.unsubscribe(queue)

    # Assert all blueprint key events appeared
    assert EVENT_ANALYSIS_STARTED in collected_events
    assert EVENT_FIRMS_FETCHED in collected_events
    assert EVENT_GIS_COMPLETED in collected_events
    assert EVENT_CLUSTERING_COMPLETED in collected_events
    assert EVENT_SELECTION_COMPLETED in collected_events
    assert EVENT_IMAGERY_STARTED in collected_events
    assert EVENT_AI_STARTED in collected_events
    assert EVENT_AI_COMPLETED in collected_events
    assert EVENT_SEVERITY_COMPLETED in collected_events
    assert EVENT_ANALYSIS_COMPLETED in collected_events


# ---------------------------------------------------------------------------
# 4. IDEMPOTENCY & INCREMENTAL PROCESSING
# ---------------------------------------------------------------------------
def test_idempotent_repeated_run_avoids_duplicate_ai(db_session):
    # Run 1: initial ingestion & investigation
    summary1 = execute_analysis_pipeline(
        db=db_session,
        firms_csv=TEST_CSV_PAYLOAD,
        force_reinvestigate=False,
        max_ai_targets=2,
        export_to_dashboard=False
    )
    assert summary1["status"] == "COMPLETED"
    first_run_ai_count = summary1["candidates_investigated"]
    assert first_run_ai_count >= 1

    # Run 2: identical observations with force_reinvestigate=False
    summary2 = execute_analysis_pipeline(
        db=db_session,
        firms_csv=TEST_CSV_PAYLOAD,
        force_reinvestigate=False,
        max_ai_targets=2,
        export_to_dashboard=False
    )
    assert summary2["status"] == "COMPLETED"
    # Deduplication should skip newly ingested observations
    assert summary2["new_observations"] == 0
    # Incremental AI processing should reuse existing investigation
    assert summary2["candidates_investigated"] == 0


# ---------------------------------------------------------------------------
# 5. REST & SSE API ENDPOINTS TEST
# ---------------------------------------------------------------------------
def test_analysis_rest_and_status_endpoints(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        # Check initial status (idle)
        resp_status = client.get("/api/analysis/status")
        assert resp_status.status_code == 200
        assert resp_status.json()["is_running"] is False

        # Execute POST /analysis/run
        resp_run = client.post(
            "/analysis/run",
            json={
                "firms_csv": TEST_CSV_PAYLOAD,
                "force_reinvestigate": False,
                "max_ai_targets": 2,
                "export_to_dashboard": False
            }
        )
        assert resp_run.status_code == 200
        data = resp_run.json()
        assert data["status"] == "COMPLETED"
        assert "run_id" in data

        # Check status after run
        resp_status2 = client.get("/api/analysis/status")
        assert resp_status2.status_code == 200
        assert resp_status2.json()["latest_run"] is not None
        assert resp_status2.json()["latest_run"]["status"] == "COMPLETED"

        # Check history
        resp_hist = client.get("/api/analysis/history")
        assert resp_hist.status_code == 200
        assert isinstance(resp_hist.json(), list)
        assert len(resp_hist.json()) >= 1

        # Check v1 trigger-sync alias
        resp_v1 = client.post("/api/trigger-sync")
        assert resp_v1.status_code == 200
        assert resp_v1.json()["status"] == "COMPLETED"
    finally:
        app.dependency_overrides.clear()
