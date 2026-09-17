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
import asyncio
import threading
import time
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
from app.orchestration.pipeline import (
    execute_analysis_pipeline,
    _apportion_tenths,
    _weighted_risk_factors,
    UNRECONCILED_FACTOR_LABEL,
)

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
today_str = datetime.utcnow().strftime("%Y-%m-%d")
TEST_CSV_PAYLOAD = f"""latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
20.965,85.171,365.2,0.4,0.4,{today_str},0230,N,VIIRS,nominal,2.0NRT,310.2,75.5,D
20.966,85.172,350.1,0.4,0.4,{today_str},0230,N,VIIRS,nominal,2.0NRT,305.0,42.0,D
22.366,87.303,320.0,0.5,0.5,{today_str},0230,N,VIIRS,nominal,2.0NRT,295.0,12.5,D
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
        Base.metadata.drop_all(bind=engine)
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
    # F-055: the spec's protocol block (V2_LOGIC_SPECIFICATION.md:485-507) spells events in
    # SCREAMING_SNAKE, and the `event:` line is the dispatch key. Assert the literal spec
    # spelling, not just the constant, so a lowercased value cannot pass unnoticed.
    assert msg.startswith("event: FIRMS_FETCHED\n")
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


def test_sse_broadcaster_delivers_an_event_published_from_a_worker_thread():
    """The pipeline does not have to run on the SSE loop. POST
    /api/analysis/run?stream=true hands it to loop.run_in_executor
    (api/analysis.py:192) and GET /api/trigger-sync-stream starts it on a bare
    threading.Thread (api/analysis.py:299), so publish runs off the loop that
    owns the subscriber's asyncio.Queue. asyncio.Queue is not thread-safe, and a
    bare put_nowait from that thread cannot wake the loop: the subscriber waits
    out its own keep-alive timeout before the event is delivered, and under a
    debug loop (-X dev) the put raises RuntimeError, which publish reads as "this
    subscriber is dead" and drops the client.

    Pre-fix the event is not delivered until the consumer's own 5 s deadline
    wakes that loop, so the delivery-latency assertion below fails (or the wait
    times out outright under a debug loop, where the put raises).
    """
    state = {}
    subscribed = threading.Event()

    async def subscribe_then_wait_for_one_event():
        loop = asyncio.get_running_loop()
        queue = event_broadcaster.subscribe()
        try:
            consumer = loop.create_task(queue.get())
            await asyncio.sleep(0.05)  # let the consumer park on its getter
            subscribed.set()
            return await asyncio.wait_for(consumer, timeout=5.0)
        finally:
            event_broadcaster.unsubscribe(queue)

    def run_loop():
        try:
            state["message"] = asyncio.run(subscribe_then_wait_for_one_event())
        except BaseException as exc:  # noqa: BLE001 - re-raised as a test failure
            state["error"] = exc

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()
    assert subscribed.wait(timeout=5.0), "the subscriber never reached the loop"
    # The loop is parked in its selector now, with nothing pending but the
    # consumer's own deadline: the publish below is the only thing that can
    # deliver the event before it fires.
    time.sleep(0.1)
    published_at = time.monotonic()
    event_broadcaster.publish(EVENT_FIRMS_FETCHED, {"new_observations": 1})
    loop_thread.join(timeout=10.0)
    latency = time.monotonic() - published_at

    assert "error" not in state, (
        "an event published from a worker thread never reached the subscriber's "
        f"loop: {state.get('error')!r}"
    )
    assert state["message"].startswith(f"event: {EVENT_FIRMS_FETCHED}\n")
    assert latency < 1.0, (
        f"the event took {latency:.2f}s to reach the subscriber: publish woke no "
        "loop, so the event waited for the consumer's own timeout"
    )
    # The publisher must not have dropped the subscriber it could not hand to.
    assert not event_broadcaster._subscribers


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
    assert top_inc.status in ["ACTIVE", "PERSISTENT", "NEW", "ESCALATED", "SUBSIDING"]
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


# ---------------------------------------------------------------------------
# 6. CONSOLE FACTOR BREAKDOWN RECONCILIATION
#
# J3: the published risk_factors could not be added up to the risk_score beside
# them. The rows are what the operator reads as the explanation for the score,
# so an explanation that does not arrive at the number is worse than none --
# and in the shipped payload it arrived somewhere else entirely (the linear
# FRP/64.49 normalisation, F-027) or, for a suppressed flare, *above* it, since
# INV-4's clamp was rendered as a row worth 0.0.
# ---------------------------------------------------------------------------
def _assessment(
    frp=62.5, calib=41.0, dev=43.0, ai=88.6, gis=15.0,
    routine=False, with_history=True, severity=None, reasons=None, augmented=True,
):
    """The augmented factor dict `severity/service.py` persists.

    ``base_score`` is derived from the components rather than passed in, because
    in the engine it *is* their weighted sum -- a fixture that sets it
    independently describes an assessment the engine cannot produce, and would
    test the renderer against a state that never occurs.
    """
    effective = calib if routine else frp
    if with_history:
        base = 0.35 * effective + 0.30 * dev + 0.20 * ai + 0.15 * gis
    else:
        base = 0.50 * effective + 0.30 * ai + 0.20 * gis
    base = round(base, 2)
    factors = {
        "frp_score": frp,
        "india_calibrated_frp_score": calib,
        "historical_deviation_score": dev,
        "ai_source_severity_score": ai,
        "gis_context_score": gis,
        "p95_ratio": 0.86 if dev else None,
        "is_routine_flare": routine,
    }
    if augmented:
        final = round(base, 1) if severity is None else severity
        factors.update({
            "model_used": "KNOWN_HOTSPOT_WITH_HISTORY" if with_history else "NEW_HOTSPOT_NO_HISTORY",
            "base_score": base,
            "base_level": "HIGH",
            "severity_score": final,
            "severity_level": "HIGH",
            "override_reasons": list(reasons or []),
        })
    return factors


def _sum_tenths(rows) -> int:
    """The rows' own sum, in tenths, so equality is exact rather than a
    tolerance someone picked."""
    return sum(int(round(row["score"] * 10.0)) for row in rows)


def _row(rows, name):
    return next(r for r in rows if r["factor"] == name)


def test_factor_rows_sum_exactly_to_the_recorded_score():
    """The rows reach the score on their own -- without inventing a reason why.

    The sum is the easy half of this, and on its own it cannot fail. The
    reconciliation row is *sized* as the shortfall, so a breakdown that has
    stopped adding up is repaired into an exact sum by the very row that reports
    the repair, and the assertion passes either way. Measured, it does: replacing
    the apportionment with independent per-row rounding leaves four of the five
    cases below byte-identical and the fifth summing to the same total, so this
    test passed on the arithmetic it exists to pin.

    What pins the apportionment is the other half -- that an assessment with
    neither an override nor a clamp needs no reconciliation row at all. Each
    component row is then the correctly rounded one *and* the rows arrive at the
    score together; independent rounding satisfies the first without the second,
    and the gap it leaves gets attributed to a cause the record does not have.
    The last case below is that shape: rounded independently its four rows sum to
    206 against a published 207, and it comes back as a +0.1 "Operational
    Escalation -- deterministic override raised the tier floor" on an incident
    that no override ever touched. A breakdown that explains a score with an
    event that did not happen is worse than one that explains it with nothing.
    """
    cases = {
        "known hotspot, no override": _assessment(),
        "new hotspot, no history": _assessment(
            with_history=False, dev=0.0, severity=None,
        ),
        "half-tenth components": _assessment(
            frp=61.0, calib=61.0, dev=61.0, ai=61.0, gis=61.0,
        ),
        "half-tenths that do not balance": _assessment(
            frp=20.0, calib=20.0, dev=20.0, ai=21.7, gis=22.3,
        ),
        "override raised the floor": _assessment(
            frp=30.0, dev=20.0, ai=50.0, gis=10.0,
            severity=55.0, reasons=["EXTREME_FRP (>= 250MW) forces CRITICAL"],
        ),
        "clamp suppressed a routine flare": _assessment(
            frp=5000.0, calib=100.0, dev=16.67, ai=39.2, gis=15.0,
            routine=True, severity=20.0,
            reasons=["ROUTINE_FLARE_SUPPRESSION (composite 80.0 -> 20.0)"],
        ),
    }
    # Nothing raised or clamped these four, so their components alone must arrive
    # at the score. The other two carry a real override and a real clamp, whose
    # reconciliation rows are the point of those cases.
    cause_free = {
        "known hotspot, no override",
        "new hotspot, no history",
        "half-tenth components",
        "half-tenths that do not balance",
    }
    for name, factors in cases.items():
        rows = _weighted_risk_factors(factors)
        assert _sum_tenths(rows) == int(round(factors["severity_score"] * 10)), (
            f"{name}: rows sum to {_sum_tenths(rows) / 10} but the assessment "
            f"recorded {factors['severity_score']}: {rows}"
        )
        if name in cause_free:
            invented = [r for r in rows if r["factor"] in (
                UNRECONCILED_FACTOR_LABEL, "Operational Escalation",
                "Routine Flare Suppression",
            )]
            assert not invented, (
                f"{name}: no override and no clamp is on this assessment, so the "
                f"components must reach the score between them -- a reconciliation "
                f"row here attributes the difference to a cause the record does not "
                f"have: {invented}"
            )


def test_a_half_tenth_base_is_not_reported_as_a_gap():
    """The base's own tenth, lost on the way to the published precision, is not
    an unexplained adjustment.

    `base_score` is recorded to two decimals and `severity_score` published to
    one, and rounding twice is not rounding once: the nearest double to 32.15 is
    32.1499999999999986, which rounds *down* to 32.1, while the same value times
    ten is 321.5 exactly and rounds *up* -- half-to-even -- to 322. Apportioning
    the rows to the two-decimal base therefore added a tenth the published score
    does not have, and the reconciliation row named it: on the live queue this
    was INC-2026-0353, INC-2026-0276, INC-2026-0246 and INC-2026-0241, each
    carrying a -0.1 "Recorded Adjustment" whose own detail text admitted no
    override or clamp accounted for it. Each also risked the opposite label: a
    base whose tenth rounds the other way produced +0.1 rows attributed to
    *Operational Escalation*, naming a deterministic override as the cause of a
    rounding artefact.

    The fixture is INC-2026-0353's real arithmetic, components and all.
    """
    factors = _assessment(frp=28.44, calib=28.44, dev=33.15, ai=50.0, gis=15.0)

    assert factors["base_score"] == 32.15, factors["base_score"]
    assert factors["severity_score"] == 32.1, factors["severity_score"]

    rows = _weighted_risk_factors(factors)
    assert _sum_tenths(rows) == 321, (
        f"the rows must add up to the 32.1 that is published, not to the 32.2 the "
        f"two-decimal base rounds to: {rows}"
    )
    named = [r for r in rows if r["factor"] in (
        UNRECONCILED_FACTOR_LABEL, "Operational Escalation", "Routine Flare Suppression",
    )]
    assert not named, (
        f"nothing raised or clamped this incident, so there is nothing to "
        f"reconcile -- the tenth is the base's own: {named}"
    )


def test_suppressed_routine_flare_cannot_be_overstated_by_its_breakdown():
    """INV-4's clamp is a subtraction in the breakdown, not a zero row.

    The shipped renderer emitted "Routine Flare Suppression" with
    ``score: 0.0, max: 0.0``: it described the clamp and contributed nothing to
    the arithmetic, so a suppressed flare's rows summed to the *unsuppressed*
    composite. On the live queue that published INC-2026-0284 at 34.2 when the
    engine had clamped it to 20.1 -- 14.1 points of INV-4 bypassed in the one
    place an operator could have checked it.

    This fixture is the case scoring.py's own comment describes: 5,000 MW
    against a 6,000 MW P95 ceiling reaches 80.0 (an EXTREME_FRP override on top
    of a 50.09 base) and INV-4 then clamps the composite to 20.0.
    """
    factors = _assessment(
        frp=5000.0, calib=100.0, dev=16.67, ai=39.2, gis=15.0,
        routine=True, severity=20.0,
        reasons=[
            "EXTREME_FRP (>= 250MW) forces CRITICAL",
            "ROUTINE_FLARE_SUPPRESSION (composite 80.0 -> 20.0)",
        ],
    )
    assert factors["base_score"] == 50.09, factors["base_score"]
    rows = _weighted_risk_factors(factors)
    suppression = _row(rows, "Routine Flare Suppression")
    assert suppression["score"] == -30.1, (
        f"the clamp removed 30.1 (50.1 -> 20.0) and the row must carry it; got "
        f"{suppression['score']}"
    )
    assert "20.0" in suppression["detail"]
    assert _sum_tenths(rows) == 200, (
        f"a suppressed flare's breakdown must arrive at the clamped 20.0, not the "
        f"50.1 the clamp removed: {rows}"
    )


def test_routine_flare_breakdown_uses_the_calibrated_frp_the_engine_scored():
    """A suppressed flare is scored on the Indian-calibrated FRP map.

    `compute_incident_severity` substitutes ``S_FRP_calib`` for ``S_FRP`` on the
    routine branch, so a renderer that reads ``frp_score`` regardless explains
    the score with a component the engine never used -- and at the wrong weight,
    since only an augmented dict carries the model label that selects the set.
    INC-2026-0284 carries both ratings, 39.14 raw against 14.24 calibrated, so
    the two are 12.5 points apart on the largest row of the breakdown.
    """
    factors = _assessment(
        frp=39.14, calib=14.24, dev=17.12, ai=38.6, gis=15.0,
        routine=True, severity=20.0,
    )
    rows = _weighted_risk_factors(factors, published_score=20.0)
    frp = next(r for r in rows if "FRP" in r["factor"])
    assert frp["factor"] == "Indian-calibrated FRP", frp
    assert "14.2/100" in frp["detail"], frp["detail"]
    assert frp["max"] == 35.0, f"the known-hotspot weight is 0.35; got {frp['max']}"
    assert _sum_tenths(rows) == 200
    assert "Historical Deviation" in [r["factor"] for r in rows], (
        "the 0.30 deviation component must be present, not silently dropped"
    )


def test_legacy_assessment_renders_with_the_right_weights_and_flags_a_real_gap():
    """A pre-augmentation dict is rendered correctly, and a gap it cannot
    explain is named rather than absorbed.

    The weight set is selected by ``model_used``, which assessments written
    before the augmentation do not carry -- so the renderer silently dropped the
    0.30 deviation component and came up more than a tier short. Its deviation
    score is stored either way (0.0 on the no-history branch), so a non-zero one
    is positive proof the known-hotspot weights were used.
    """
    legacy = {
        "frp_score": 39.14,
        "india_calibrated_frp_score": 14.24,
        "historical_deviation_score": 17.12,
        "ai_source_severity_score": 38.6,
        "gis_context_score": 15.0,
        "p95_ratio": 0.86,
        "is_routine_flare": True,
    }
    rows = _weighted_risk_factors(legacy, published_score=20.1)
    labels = [r["factor"] for r in rows]
    assert "Historical Deviation" in labels, (
        f"the deviation component was dropped again: {labels}"
    )
    assert "Indian-calibrated FRP" in labels
    # These factors reconstruct the published score exactly, so there is nothing
    # to flag -- the record is stale, but it is not inconsistent.
    assert _sum_tenths(rows) == 201
    assert UNRECONCILED_FACTOR_LABEL not in labels

    # A stale record whose factors *cannot* reach its published score is the one
    # that must be labelled, so the export's warning has something to key on.
    inconsistent = {
        "frp_score": 50.0,
        "india_calibrated_frp_score": 30.0,
        "historical_deviation_score": 0.0,
        "ai_source_severity_score": 50.0,
        "gis_context_score": 0.0,
        "is_routine_flare": False,
    }
    rows = _weighted_risk_factors(inconsistent, published_score=35.0)
    flagged = _row(rows, UNRECONCILED_FACTOR_LABEL)
    assert flagged["score"] == -5.0, rows
    assert "predates the current scoring model" in flagged["detail"]
    assert _sum_tenths(rows) == 350


def test_no_factor_row_ever_exceeds_its_own_ceiling():
    """Rounding must not push a row past the maximum printed beside it.

    Rows are apportioned to make the sum exact, which means handing a tenth to
    one of them, and a row sitting on its ceiling must never be the one that
    takes it -- the breakdown would print 50.1 of 50. The tenths go to rows with
    a fractional part whenever there are any, and such a row always has headroom,
    so the caps refusal in ``_apportion_tenths`` decides anything only when
    *every* row is already on its ceiling and the target still wants more. That
    takes two things at once: all components rated exactly 100.0 (anything less
    leaves a fractional part for the tenth to go to instead), and a recorded
    ``base_score`` above the 100.0 those components can account for -- a stale
    record, written by a scoring model whose weights are not the current ones.
    The fixture below is that record: base_score 100.06 over components that
    reach 100.00.

    An honest fixture pins nothing here, which is what the shipped version of
    this test was: with ``base_score`` derived from the components the target
    lands exactly on their sum, no tenth is left over, and deleting the refusal
    changes no row. Measured on this fixture, without the refusal the breakdown
    publishes "Fire Radiative Power 50.1" against a ceiling of 50.0.
    """
    def stale_rows(base_score, severity, with_history):
        factors = _assessment(
            frp=100.0, calib=100.0, dev=100.0, ai=100.0, gis=100.0,
            with_history=with_history,
        )
        factors["base_score"] = base_score
        factors["severity_score"] = severity
        return _weighted_risk_factors(factors)

    # The reachable case, in both weight sets: every component pinned at 100.0
    # and a stale base one tenth above what they can account for.
    for with_history in (True, False):
        rows = stale_rows(100.06, 100.1, with_history)
        over = [r for r in rows if r["score"] > float(r["max"]) + 1e-9]
        assert not over, over
        # The tenth is still accounted for -- by the reconciliation row, not by
        # a component row that had no room for it.
        assert _sum_tenths(rows) == 1001, rows

    # And the property holds across the ordinary rating space, where the
    # flooring alone is what guarantees it.
    for rating in (0.0, 0.1, 3.3, 33.3, 49.95, 50.0, 66.6, 99.9, 100.0):
        for with_history in (True, False):
            factors = _assessment(
                frp=rating, calib=rating, dev=rating, ai=rating, gis=rating,
                with_history=with_history,
            )
            over = [
                row for row in _weighted_risk_factors(factors)
                if row["score"] > float(row["max"]) + 1e-9
            ]
            assert not over, (rating, with_history, over)


def test_rounding_never_hands_a_tenth_to_a_row_already_on_its_ceiling():
    """The caps refusal's contract, stated at the level it is defined.

    The test above reaches the refusal through a stale assessment; this one pins
    it with no model arithmetic in the way. ``caps`` is an argument of
    ``_apportion_tenths``, so the contract is exercised directly: two rows pinned
    at 10.0 of 10.0 and a target one tenth above what they can sum to. The tenth
    is left unallocated rather than spent on a row that has no room for it, and
    reconciling the shortfall stays the caller's job (``_reconcile_to``).
    """
    tenths = _apportion_tenths([10.0, 10.0], 201, [10.0, 10.0])
    assert tenths == [100, 100], tenths
    assert sum(tenths) == 200, "the shortfall is the caller's to reconcile"
    for got, cap in zip(tenths, [10.0, 10.0]):
        assert got / 10.0 <= cap + 1e-9, (tenths, cap)

    # A ceiling is not consulted when a row with headroom can take the tenth
    # instead -- the refusal must not cost the sum its exactness.
    tenths = _apportion_tenths([3.5, 10.0], 136, [35.0, 10.0])
    assert tenths == [36, 100], tenths
    assert sum(tenths) == 136


def test_a_breakdown_never_hides_a_gap_it_cannot_explain():
    """Every difference is either attributed to its cause or named as unknown."""
    # An override with no reasons on record is still attributable to an
    # override; the row says so instead of citing a clause it does not have.
    overridden = _assessment(frp=30.0, dev=20.0, ai=50.0, gis=10.0, severity=55.0)
    rows = _weighted_risk_factors(overridden, published_score=55.0)
    escalation = _row(rows, "Operational Escalation")
    assert escalation["score"] == 27.0, rows
    assert escalation["detail"] == "Deterministic override raised the tier floor"
    assert _sum_tenths(rows) == 550

    # A score that fell with no clamp behind it is the case that must be flagged
    # rather than quietly reconciled: nothing in the assessment explains it.
    fallen = _assessment(frp=60.0, dev=40.0, ai=50.0, gis=20.0, severity=30.0)
    rows = _weighted_risk_factors(fallen, published_score=30.0)
    flagged = _row(rows, UNRECONCILED_FACTOR_LABEL)
    assert flagged["score"] == -16.0, rows
    assert "no override or INV-4 clamp" in flagged["detail"]
    assert _sum_tenths(rows) == 300
