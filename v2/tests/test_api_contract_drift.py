"""
FIREX v2 API Contract Drift & Orchestration Event Tests

Guards the spec's own route table and SSE protocol block
(V2_LOGIC_SPECIFICATION.md:461-507) against the code:

1. F-055 — SSE wire event names carry the spec's SCREAMING_SNAKE spelling.
2. F-056 — GET /api/severity/incident/{id} computes on a miss, retrieves on a hit.
3. F-057 — /health and /api/health report a real process memory metric.
4. F-059 — POST /api/imagery/incident/{id} exists, mirrors the GET, and is idempotent.
5. J5   — the sync worker's failure branch logs instead of raising NameError.
"""
import logging
from datetime import datetime, timedelta

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api import analysis as analysis_api
from app.api import health as health_api
from app.core.config import settings
from app.storage.database import Base, get_db
from app.storage.models import (
    Incident, IndustrialAsset, ImageryRecord, SeverityAssessment
)
from app.imagery import service as imagery_service
from app.orchestration import events as events_module
from app.orchestration import pipeline as pipeline_module
from app.orchestration.events import event_broadcaster
from app.orchestration.lock import pipeline_lock

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """The suite shares one app and one 120-req/min counter; this file must not add to it."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# 1. F-055 — SSE WIRE EVENT NAMES
# ---------------------------------------------------------------------------
# The eight names the spec's protocol block spells out, plus the four the wire
# emits without a spec entry. All twelve share one casing rule.
SPEC_LISTED_EVENTS = {
    "ANALYSIS_STARTED", "FIRMS_FETCHED", "CLUSTERING_COMPLETED", "SELECTION_COMPLETED",
    "IMAGERY_STARTED", "AI_COMPLETED", "SEVERITY_COMPLETED", "ANALYSIS_COMPLETED",
}
SPEC_UNLISTED_EVENTS = {"GIS_COMPLETED", "AI_STARTED", "ALERT_CREATED", "ANALYSIS_FAILED"}


def test_sse_event_values_are_the_spec_uppercase_names():
    """F-055: the constant's value is what lands on the `event:` line."""
    constants = {
        name: value for name, value in vars(events_module).items()
        if name.startswith("EVENT_") and isinstance(value, str)
    }
    assert len(constants) == 12

    for name, value in constants.items():
        # An uppercase identifier was the only place the spec's spelling existed
        # before; now the value has to be that same spelling.
        assert value == name.removeprefix("EVENT_"), f"{name} = {value!r}"
        assert value.isupper() and "." not in value, f"{name} = {value!r}"

    values = set(constants.values())
    assert SPEC_LISTED_EVENTS | SPEC_UNLISTED_EVENTS == values


def test_sse_wire_line_uses_the_spec_spelling():
    """Every event type must reach the wire as `event: UPPERCASE`."""
    queue = event_broadcaster.subscribe()
    try:
        for value in SPEC_LISTED_EVENTS | SPEC_UNLISTED_EVENTS:
            event_broadcaster.publish(value, {"message": value})
        for _ in range(12):
            msg = queue.get_nowait()
            event_line = msg.split("\n")[0]
            assert event_line.startswith("event: ")
            wire_name = event_line[len("event: "):]
            assert wire_name in SPEC_LISTED_EVENTS | SPEC_UNLISTED_EVENTS
            assert wire_name.isupper() and "." not in wire_name
    finally:
        event_broadcaster.unsubscribe(queue)


def test_stream_analysis_events_terminator_matches_uppercase_wire():
    """
    F-055: the direct-stream branch of POST /api/analysis/run broke its loop on the
    literal "analysis.completed". With the wire renamed that literal could no longer
    match, leaving the SSE generator open forever; it resolves the constants instead.

    This checks the wire text only. The loop itself is exercised end to end by
    test_direct_stream_closes_when_the_worker_dies_without_reporting below (F-102).
    """
    terminating = event_broadcaster.publish("ANALYSIS_COMPLETED", {"status": "COMPLETED"})
    wire = terminating.to_sse_format()
    assert events_module.EVENT_ANALYSIS_COMPLETED in wire
    assert events_module.EVENT_ANALYSIS_FAILED not in wire


def test_pipeline_publishes_terminal_event_when_the_run_record_cannot_be_written(
    monkeypatch, db_session
):
    """
    F-102, pipeline half: every failure after the lock is taken must publish a
    terminal event.

    The AnalysisRun insert and the ANALYSIS_STARTED publish used to sit outside the
    try block that reports failures, so a run that died there -- a database that
    refused the insert, a broken broadcaster -- raised into the executor thread with
    nothing on the wire. The direct SSE stream blocks on exactly that event, so the
    operator's console hung with no error and no run id.

    The injected failure lands in the worst spot on purpose: the audit-record
    constructor itself raises, so the handler's own attempt to *write* the failure
    record raises too. Recording the failure is best-effort; publishing it is not.
    """
    class _ExplodingRunRecord:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("synthetic audit-record failure")

    monkeypatch.setattr(pipeline_module, "AnalysisRun", _ExplodingRunRecord)

    queue = event_broadcaster.subscribe()
    try:
        with pytest.raises(RuntimeError, match="synthetic audit-record failure"):
            pipeline_module.execute_analysis_pipeline(
                db=db_session, export_to_dashboard=False, run_id="RUN-F102-RECORD"
            )
        messages = []
        while not queue.empty():
            messages.append(queue.get_nowait())
    finally:
        event_broadcaster.unsubscribe(queue)

    failed = [m for m in messages if events_module.EVENT_ANALYSIS_FAILED in m]
    assert failed, (
        "the run died before its audit record existed and published no terminal "
        f"event; the SSE stream would never close. Messages seen: {messages}"
    )
    assert "synthetic audit-record failure" in failed[0]
    # The lock is the other half of the guarantee: a run that fails this early must
    # not wedge the pipeline for every later caller.
    assert not pipeline_lock.is_locked()


def test_direct_stream_closes_when_the_worker_dies_without_reporting(monkeypatch):
    """
    F-102, endpoint half: POST /api/analysis/run?stream=true must close its stream
    even when the worker dies before publishing anything.

    The executor future was discarded, so a worker that raised without publishing --
    lock contention, a crash in the first stage -- left the generator awaiting a
    queue that would never receive a terminal event. Pre-fix this request does not
    return: the client waits until its own read timeout expires. The test therefore
    asserts on the exact text the done-callback injects, which is what tells this
    apart from the pipeline's own EVENT_ANALYSIS_FAILED.
    """
    def _die(*args, **kwargs):
        raise RuntimeError("synthetic worker crash")

    monkeypatch.setattr(analysis_api, "execute_analysis_pipeline", _die)

    resp = client.post("/api/analysis/run", params={"stream": True})
    assert resp.status_code == 200
    assert "analysis_failed" in resp.text.lower() or "ANALYSIS_FAILED" in resp.text
    assert "synthetic worker crash" in resp.text, (
        "the stream closed but never explained why; body was: " + resp.text[:500]
    )
    # The subscriber must not be left behind: this queue is the generator's own, and
    # leaking it would keep every later publish doing dead work.
    assert not event_broadcaster._subscribers, (
        "the direct stream did not unsubscribe on the way out"
    )


# ---------------------------------------------------------------------------
# 2. J5 — SYNC WORKER FAILURE BRANCH
# ---------------------------------------------------------------------------
def test_sync_worker_binds_logger_and_logs_failure(monkeypatch, caplog):
    """
    J5: the worker's except branch called `logger`, which the module never bound -- so a
    pipeline failure inside it became `NameError: name 'logger' is not defined` at exactly
    the moment the code was trying to report the failure.
    """
    def _boom(**kwargs):
        raise RuntimeError("synthetic sync failure")

    monkeypatch.setattr(analysis_api, "execute_analysis_pipeline", _boom)

    with caplog.at_level(logging.ERROR):
        analysis_api.run_sync_worker_pipeline()  # must not raise

    records = [r for r in caplog.records if "synthetic sync failure" in r.getMessage()]
    assert records, "the worker's failure was not logged"
    # exc_info is what gives the operator the diagnosis the finding says was lost.
    assert records[0].exc_info is not None


def test_sync_endpoint_reports_pipeline_failure_as_clean_json(monkeypatch):
    """
    J5, endpoint level: a failing pipeline must come back through the endpoint's own error
    envelope. The unbound logger meant the one branch that was supposed to diagnose this
    failure raised NameError instead, so what an operator saw was a bare traceback.
    """
    from app.orchestration.lock import pipeline_lock
    pipeline_lock.force_unlock()
    monkeypatch.setattr(
        analysis_api, "execute_analysis_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic sync failure"))
    )

    res = client.post("/api/trigger-sync")
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert detail["error"] == "ANALYSIS_RUN_FAILED"
    assert "synthetic sync failure" in detail["message"]
    assert "NameError" not in res.text


# ---------------------------------------------------------------------------
# 3. F-056 — GET /api/severity/incident/{id}
# ---------------------------------------------------------------------------
def _seed_severity_incident(db, incident_id="inc-contract-sev"):
    asset = IndustrialAsset(
        id="asset-contract-sev",
        name="Paradip Petrochemical Complex",
        facility_type="petrochemical",
        industry="Chemicals",
        category="RED",
        latitude=20.3,
        longitude=86.6
    )
    incident = Incident(
        id=incident_id,
        incident_code="INC-CONTRACT-SEV",
        status="ACTIVE",
        latitude=20.3,
        longitude=86.6,
        first_detected_at=datetime.utcnow() - timedelta(hours=2),
        last_detected_at=datetime.utcnow(),
        current_max_frp=75.0,
        nearest_asset_id=asset.id,
        distance_to_asset_km=0.0,
        is_inside_facility=True,
        classification="industrial_fire",
        classification_confidence=92.0
    )
    db.add(asset)
    db.add(incident)
    db.commit()
    return incident


def test_severity_incident_route_computes_then_retrieves(db_session):
    """F-056: the documented URL must exist and answer 'compute or retrieve'."""
    _seed_severity_incident(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        # Nothing persisted yet: the documented GET computes and persists one.
        first = client.get("/api/severity/incident/inc-contract-sev")
        assert first.status_code == 200
        body = first.json()
        assert body["level"] == "CRITICAL"
        assert body["assessment_id"] is not None

        # Second call retrieves rather than recomputing: one row, not two, and the
        # same assessment_id -- re-evaluating also re-fires alerts, so this matters.
        second = client.get("/api/severity/incident/inc-contract-sev")
        assert second.status_code == 200
        assert second.json() == body

        rows = db_session.query(SeverityAssessment).filter(
            SeverityAssessment.incident_id == "inc-contract-sev"
        ).all()
        assert len(rows) == 1
    finally:
        app.dependency_overrides.clear()


def test_severity_incident_route_404s_for_unknown_incident(db_session):
    """The compute branch must not turn a missing incident into a 500."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        res = client.get("/api/severity/incident/inc-does-not-exist")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_legacy_severity_routes_still_work(db_session):
    """F-056: the pre-existing routes stay, and the 404 must cite a documented path."""
    _seed_severity_incident(db_session, incident_id="inc-contract-sev-legacy")
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        # Retrieve-only route still evaluates nothing.
        missing = client.get("/api/severity/inc-contract-sev-legacy")
        assert missing.status_code == 404
        assert "/api/severity/incident/" in missing.json()["detail"]

        # The legacy evaluate route is untouched.
        evaluated = client.post("/api/severity/evaluate/inc-contract-sev-legacy")
        assert evaluated.status_code == 200
        assert evaluated.json()["severity_level"] == "CRITICAL"

        # ...and the retrieve-only route now serves that assessment.
        retrieved = client.get("/api/severity/inc-contract-sev-legacy")
        assert retrieved.status_code == 200
        assert retrieved.json()["level"] == "CRITICAL"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. F-057 — HEALTH MEMORY METRIC
# ---------------------------------------------------------------------------
def test_health_reports_memory_metrics_on_both_paths():
    """F-057: /health and /api/health promise memory metrics; both mount one router."""
    for path in ("/health", "/api/health"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()

        # Existing consumers must keep finding everything they read today.
        for key in ("status", "service", "version", "timestamp", "database"):
            assert key in data

        memory = data["memory"]
        assert memory["peak_rss_bytes"] > 0
        assert memory["peak_rss_mb"] > 0
        assert memory["source"]


def test_memory_metric_normalises_ru_maxrss_kib_to_bytes(monkeypatch):
    """
    F-057: ru_maxrss is KiB on Linux but bytes on macOS, and `resource` does not exist
    on Windows at all. Stubbing the POSIX module pins the conversion, and the platform is
    stubbed explicitly so both conventions are covered.
    """
    class _StubUsage:
        ru_maxrss = 2048

    class _StubResource:
        RUSAGE_SELF = 0

        @staticmethod
        def getrusage(who):
            return _StubUsage()

    monkeypatch.setattr(health_api, "_resource", _StubResource)

    # Linux getrusage(2): ru_maxrss is KiB, so 2048 means 2 MiB.
    monkeypatch.setattr(health_api.sys, "platform", "linux")
    assert health_api._peak_rss_bytes() == 2048 * 1024

    # Darwin getrusage(2): ru_maxrss is already bytes, so 2048 means 2 KiB unscaled.
    monkeypatch.setattr(health_api.sys, "platform", "darwin")
    assert health_api._peak_rss_bytes() == 2048

    monkeypatch.setattr(health_api, "_resource", None)
    monkeypatch.setattr(health_api, "_peak_rss_bytes", lambda: None)
    assert health_api._memory_metrics() == {"status": "unavailable"}


# ---------------------------------------------------------------------------
# 5. F-059 — POST /api/imagery/incident/{id}
# ---------------------------------------------------------------------------
def _seed_imagery_incident(db, incident_id="inc-contract-img"):
    incident = Incident(
        id=incident_id,
        incident_code="INC-CONTRACT-IMG",
        status="ACTIVE",
        latitude=22.456,
        longitude=88.789,
        current_max_frp=32.5,
        current_mean_frp=28.0,
        observation_count=4,
        first_detected_at=datetime.utcnow() - timedelta(days=2),
        last_detected_at=datetime.utcnow()
    )
    db.add(incident)
    db.commit()
    return incident


@pytest.fixture
def stubbed_imagery(monkeypatch, tmp_path):
    """Keep the test off the network and out of the repo's imagery cache."""
    monkeypatch.setattr(imagery_service, "CACHE_DIR", str(tmp_path / "imagery_cache"))
    monkeypatch.setattr(
        imagery_service, "get_stitched_crop",
        lambda **kwargs: (Image.new("RGB", (640, 640), (28, 33, 40)), "Test Stub")
    )


def test_post_imagery_incident_mirrors_get_and_is_idempotent(db_session, stubbed_imagery):
    """F-059: the spec documents POST; a repeat POST must not duplicate records."""
    _seed_imagery_incident(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        posted = client.post("/api/imagery/incident/inc-contract-img")
        assert posted.status_code == 200
        body = posted.json()
        assert body["incident_id"] == "inc-contract-img"
        assert body["annotated_image_url"]
        assert body["raw_image_url"]
        assert body["cached"] is False

        # Same payload shape as the GET, so a client can use either verb.
        fetched = client.get("/api/imagery/incident/inc-contract-img")
        assert fetched.status_code == 200
        assert set(fetched.json()) == set(body)

        # Second POST with default force_refresh: served from cache, no new record.
        again = client.post("/api/imagery/incident/inc-contract-img")
        assert again.status_code == 200
        assert again.json()["cached"] is True

        records = db_session.query(ImageryRecord).filter(
            ImageryRecord.incident_id == "inc-contract-img"
        ).all()
        assert len(records) == 1
    finally:
        app.dependency_overrides.clear()


def test_post_imagery_incident_404s_for_unknown_incident(db_session, stubbed_imagery):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        res = client.post("/api/imagery/incident/inc-does-not-exist")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
