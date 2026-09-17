"""
FIREX v2 Stage 7 Comprehensive Test Suite: Severity Engine & Alert System
Tests deterministic scoring, dual models, operational overrides, severity confidence,
re-investigation safety trigger, alert deduplication/escalation, and operator lifecycle actions.
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.storage.database import Base, get_db
from app.storage.models import Incident, IndustrialAsset, AIInvestigation, SeverityAssessment, AlertRecord, IncidentEvent
from app.severity.scoring import (
    calculate_frp_severity,
    calculate_historical_deviation,
    calculate_ai_source_severity,
    calculate_gis_context_severity,
    evaluate_severity_overrides,
    calculate_severity_confidence,
    compute_incident_severity,
    score_to_level
)
from app.severity.state_machine import determine_lifecycle_state
from app.severity.service import evaluate_incident_severity, get_incident_severity_history
from app.alerts.engine import (
    evaluate_and_emit_alert,
    acknowledge_alert,
    resolve_alert,
    dismiss_alert,
    get_active_alerts,
    AlertNotFound,
    InvalidAlertTransition,
)
from app.main import app

from sqlalchemy.pool import StaticPool

@pytest.fixture
def db_session():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    yield session
    session.close()

# ---------------------------------------------------------------------------
# 1. DETERMINISTIC SCORING & DUAL MODEL TESTS
# ---------------------------------------------------------------------------
def test_frp_severity_curve():
    assert calculate_frp_severity(0.0) == 0.0
    assert calculate_frp_severity(1.0) == 25.0
    assert calculate_frp_severity(3.0) == 50.0
    assert calculate_frp_severity(7.0) == 75.0
    assert calculate_frp_severity(15.0) == 100.0
    assert calculate_frp_severity(100.0) == 100.0


def test_dual_model_known_hotspot_vs_new_hotspot():
    # Known hotspot (with history)
    res_known = compute_incident_severity(
        frp_mw=10.0,
        firms_confidence=80.0,
        classification="gas_flare",
        ai_confidence=80.0,
        median_frp=3.0,
        p95_frp=10.0,
        history_reliability=0.8,
        facility_distance_m=100.0,
        is_inside_facility=False
    )
    assert res_known["model_used"] == "KNOWN_HOTSPOT_WITH_HISTORY"
    assert "historical_deviation_score" in res_known["factors"]
    assert res_known["factors"]["historical_deviation_score"] > 0.0

    # New hotspot (no history)
    res_new = compute_incident_severity(
        frp_mw=10.0,
        firms_confidence=80.0,
        classification="gas_flare",
        ai_confidence=80.0,
        median_frp=0.0,
        p95_frp=0.0,
        history_reliability=0.0,
        facility_distance_m=100.0,
        is_inside_facility=False
    )
    assert res_new["model_used"] == "NEW_HOTSPOT_NO_HISTORY"
    assert res_new["factors"]["historical_deviation_score"] == 0.0


def test_deterministic_same_input_same_output():
    args = dict(
        frp_mw=25.0,
        firms_confidence=85.0,
        classification="industrial_fire",
        ai_confidence=85.0,
        median_frp=4.0,
        p95_frp=12.0,
        history_reliability=0.8,
        facility_distance_m=0.0,
        is_inside_facility=True
    )
    run1 = compute_incident_severity(**args)
    run2 = compute_incident_severity(**args)
    assert run1["severity_score"] == run2["severity_score"]
    assert run1["severity_level"] == run2["severity_level"]
    assert run1["severity_confidence"] == run2["severity_confidence"]

# ---------------------------------------------------------------------------
# 2. OPERATIONAL ESCALATION OVERRIDE TESTS
# ---------------------------------------------------------------------------
def test_extreme_frp_override():
    # FRP > 150 MW with high confidence -> minimum HIGH / CRITICAL
    res = compute_incident_severity(
        frp_mw=180.0,
        firms_confidence=95.0,
        classification="wildfire",
        ai_confidence=70.0,
        facility_distance_m=5000.0,
        is_inside_facility=False
    )
    assert res["severity_level"] in ["HIGH", "CRITICAL"]
    assert res["has_override"] is True
    assert any("EXTREME_FRP_OVERRIDE" in r for r in res["override_reasons"])


def test_industrial_fire_inside_facility_override():
    # industrial_fire + inside facility -> CRITICAL
    res = compute_incident_severity(
        frp_mw=20.0,
        firms_confidence=85.0,
        classification="industrial_fire",
        ai_confidence=90.0,
        facility_distance_m=0.0,
        facility_type="refinery",
        is_inside_facility=True
    )
    assert res["severity_level"] == "CRITICAL"
    assert res["severity_score"] >= 75.0
    assert any("INDUSTRIAL_CATASTROPHE_OVERRIDE" in r for r in res["override_reasons"])


def test_abnormal_activity_spike_override():
    # 5x spike over P95 normal ceiling -> ABNORMAL_ACTIVITY_SPIKE
    res = compute_incident_severity(
        frp_mw=50.0,
        firms_confidence=80.0,
        classification="gas_flare",
        ai_confidence=80.0,
        median_frp=2.0,
        p95_frp=10.0,  # 50.0 / 10.0 = 5.0x
        history_reliability=0.9,
        facility_distance_m=200.0,
        is_inside_facility=False
    )
    assert res["has_override"] is True
    assert any("ABNORMAL_ACTIVITY_SPIKE" in r for r in res["override_reasons"])
    assert res["severity_level"] in ["HIGH", "CRITICAL"]

# ---------------------------------------------------------------------------
# 3. SEVERITY CONFIDENCE & RE-INVESTIGATION SAFETY TRIGGER
# ---------------------------------------------------------------------------
def test_high_severity_low_confidence_triggers_reinvestigation():
    # High severity (CRITICAL) but low confidence (<60)
    res = compute_incident_severity(
        frp_mw=160.0,
        firms_confidence=40.0,  # very low FIRMS confidence
        classification="industrial_fire",
        ai_confidence=45.0,     # low AI confidence
        history_reliability=0.1,
        facility_distance_m=2500.0
    )
    assert res["severity_level"] in ["HIGH", "CRITICAL"]
    assert res["severity_confidence"] < 60.0
    assert res["needs_reinvestigation"] is True


def test_high_severity_high_confidence_no_reinvestigation():
    res = compute_incident_severity(
        frp_mw=160.0,
        firms_confidence=95.0,
        classification="industrial_fire",
        ai_confidence=92.0,
        history_reliability=0.9,
        facility_distance_m=50.0
    )
    assert res["severity_level"] == "CRITICAL"
    assert res["severity_confidence"] >= 60.0
    assert res["needs_reinvestigation"] is False

# ---------------------------------------------------------------------------
# 4. ALERT ENGINE: EMISSION, DEDUPLICATION, AND ESCALATION
# ---------------------------------------------------------------------------
def test_alert_emission_thresholds(db_session):
    incident_low = Incident(
        id="inc-low-01",
        incident_code="INC-LOW-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow()
    )
    db_session.add(incident_low)
    db_session.commit()

    # LOW severity -> NO alert emitted
    alert_low = evaluate_and_emit_alert(
        incident_low,
        {"severity_level": "LOW", "severity_score": 15.0},
        db_session
    )
    assert alert_low is None
    assert db_session.query(AlertRecord).count() == 0

    # HIGH severity -> Alert emitted
    incident_high = Incident(
        id="inc-high-01",
        incident_code="INC-HIGH-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=45.0,
        classification="industrial_fire"
    )
    db_session.add(incident_high)
    db_session.commit()

    alert_high = evaluate_and_emit_alert(
        incident_high,
        {"severity_level": "HIGH", "severity_score": 68.0, "severity_confidence": 85.0},
        db_session
    )
    assert alert_high is not None
    assert alert_high.severity_level == "HIGH"
    assert db_session.query(AlertRecord).count() == 1


def test_alert_exactly_once_deduplication(db_session):
    incident = Incident(
        id="inc-dedup-01",
        incident_code="INC-DEDUP-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=50.0,
        classification="industrial_fire"
    )
    db_session.add(incident)
    db_session.commit()

    # First emission
    alert1 = evaluate_and_emit_alert(
        incident,
        {"severity_level": "HIGH", "severity_score": 65.0},
        db_session
    )
    assert alert1 is not None
    assert db_session.query(AlertRecord).count() == 1

    # Second evaluation at same severity -> DEDUPLICATED (returns existing, does NOT create new)
    alert2 = evaluate_and_emit_alert(
        incident,
        {"severity_level": "HIGH", "severity_score": 67.0},
        db_session
    )
    assert alert2.id == alert1.id
    assert db_session.query(AlertRecord).count() == 1


def test_alert_escalation_from_high_to_critical(db_session):
    incident = Incident(
        id="inc-esc-01",
        incident_code="INC-ESC-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=50.0,
        classification="industrial_fire"
    )
    db_session.add(incident)
    db_session.commit()

    # Initial alert at HIGH
    alert_high = evaluate_and_emit_alert(
        incident,
        {"severity_level": "HIGH", "severity_score": 60.0},
        db_session
    )
    assert alert_high.severity_level == "HIGH"

    # Escalation to CRITICAL -> Emits new ESCALATED alert
    alert_crit = evaluate_and_emit_alert(
        incident,
        {"severity_level": "CRITICAL", "severity_score": 90.0, "override_reasons": ["INDUSTRIAL_CATASTROPHE_OVERRIDE"]},
        db_session
    )
    assert alert_crit.id != alert_high.id
    assert alert_crit.severity_level == "CRITICAL"
    assert db_session.query(AlertRecord).count() == 2

    # Section 8's exactly-once rule is about the alert an operator can act on,
    # so the escalation supersedes rather than joins. Leaving the HIGH row open
    # meant two NEW alerts coexisted for one incident, and once the CRITICAL row
    # was closed the stale HIGH row became active again -- at which point
    # `CRITICAL > HIGH` held a second time and the same escalation was emitted
    # again. Asserting only `count() == 2` is satisfied by both behaviours, so
    # the original version of this test could not tell them apart.
    db_session.refresh(alert_high)
    assert alert_high.status == "RESOLVED"
    assert alert_high.superseded_by == alert_crit.id
    assert alert_high.resolved_at is not None

    active = db_session.query(AlertRecord).filter(
        AlertRecord.incident_id == incident.id,
        AlertRecord.status.in_(["NEW", "ACKNOWLEDGED"])
    ).all()
    assert len(active) == 1
    assert active[0].id == alert_crit.id

    # Re-evaluating at the escalated severity changes nothing.
    again = evaluate_and_emit_alert(
        incident,
        {"severity_level": "CRITICAL", "severity_score": 91.0},
        db_session
    )
    assert again.id == alert_crit.id
    assert db_session.query(AlertRecord).count() == 2

    # And closing the CRITICAL alert does not resurrect the superseded HIGH one.
    resolve_alert(alert_crit.id, db_session)
    assert db_session.query(AlertRecord).filter(
        AlertRecord.incident_id == incident.id,
        AlertRecord.status.in_(["NEW", "ACKNOWLEDGED"])
    ).count() == 0

    # A later CRITICAL assessment raises a *fresh* alert (no active alert
    # remains); it must not be an escalation of a closed row.
    reopened = evaluate_and_emit_alert(
        incident,
        {"severity_level": "CRITICAL", "severity_score": 93.0},
        db_session
    )
    assert reopened.status == "NEW"
    assert reopened.title.startswith("[CRITICAL]")
    assert not reopened.title.startswith("[ESCALATED]")
    assert db_session.query(AlertRecord).count() == 3


def test_alert_emission_is_distinguishable_from_deduplication(db_session):
    """The dedup path and the emission path both return a record; `is_new` tells them apart.

    Without it, `severity/service.py` reported `alert_emitted: True` on every
    HIGH/CRITICAL re-evaluation, so the audit trail could not answer whether an
    assessment raised an alert or was suppressed by one already open.
    """
    incident = Incident(
        id="inc-dedup-01",
        incident_code="INC-DEDUP-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=50.0,
    )
    db_session.add(incident)
    db_session.commit()

    emitted = evaluate_and_emit_alert(
        incident, {"severity_level": "HIGH", "severity_score": 60.0}, db_session
    )
    assert emitted.is_new is True

    deduplicated = evaluate_and_emit_alert(
        incident, {"severity_level": "HIGH", "severity_score": 61.0}, db_session
    )
    assert deduplicated.is_new is False
    assert deduplicated.id == emitted.id

    # Below the alerting threshold there is no record at all.
    assert evaluate_and_emit_alert(
        incident, {"severity_level": "MEDIUM", "severity_score": 40.0}, db_session
    ) is None


def test_alert_transition_table_is_enforced(db_session):
    """Closed alerts cannot be driven back onto the operator's board."""
    incident = Incident(
        id="inc-fsm-01",
        incident_code="INC-FSM-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow(),
        current_max_frp=50.0,
    )
    db_session.add(incident)
    db_session.commit()

    alert = evaluate_and_emit_alert(
        incident, {"severity_level": "HIGH", "severity_score": 60.0}, db_session
    )

    # NEW -> ACKNOWLEDGED is legal, and repeating it is an idempotent no-op.
    assert acknowledge_alert(alert.id, db_session).status == "ACKNOWLEDGED"
    events_before = db_session.query(IncidentEvent).count()
    assert acknowledge_alert(alert.id, db_session).status == "ACKNOWLEDGED"
    assert db_session.query(IncidentEvent).count() == events_before

    # ACKNOWLEDGED -> RESOLVED is legal; both terminal states then refuse.
    assert resolve_alert(alert.id, db_session).status == "RESOLVED"
    with pytest.raises(InvalidAlertTransition):
        acknowledge_alert(alert.id, db_session)
    with pytest.raises(InvalidAlertTransition):
        dismiss_alert(alert.id, db_session)

    # DISMISSED is terminal too.
    second = evaluate_and_emit_alert(
        incident, {"severity_level": "CRITICAL", "severity_score": 90.0}, db_session
    )
    assert dismiss_alert(second.id, db_session).status == "DISMISSED"
    with pytest.raises(InvalidAlertTransition):
        acknowledge_alert(second.id, db_session)

    # An unknown id is a different failure and must stay distinguishable, so the
    # API can answer 404 rather than 409.
    with pytest.raises(AlertNotFound):
        acknowledge_alert("no-such-alert", db_session)

# ---------------------------------------------------------------------------
# 5. ALERT OPERATOR LIFECYCLE TESTS
# ---------------------------------------------------------------------------
def test_alert_operator_lifecycle(db_session):
    incident = Incident(
        id="inc-life-01",
        incident_code="INC-LIFE-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow()
    )
    db_session.add(incident)
    db_session.commit()

    alert = evaluate_and_emit_alert(
        incident,
        {"severity_level": "CRITICAL", "severity_score": 85.0},
        db_session
    )
    assert alert.status == "NEW"

    # Acknowledge
    ack = acknowledge_alert(alert.id, db_session, notes="Dispatching emergency brigade.")
    assert ack.status == "ACKNOWLEDGED"

    # Resolve
    res = resolve_alert(alert.id, db_session, notes="Fire contained.")
    assert res.status == "RESOLVED"

    # Active alerts query does not return RESOLVED
    active = get_active_alerts(db_session)
    assert len(active) == 0


def test_alert_dismiss(db_session):
    incident = Incident(
        id="inc-dis-01",
        incident_code="INC-DIS-01",
        status="ACTIVE",
        latitude=20.0,
        longitude=80.0,
        first_detected_at=datetime.utcnow(),
        last_detected_at=datetime.utcnow()
    )
    db_session.add(incident)
    db_session.commit()

    alert = evaluate_and_emit_alert(
        incident,
        {"severity_level": "HIGH", "severity_score": 70.0},
        db_session
    )
    dismissed = dismiss_alert(alert.id, db_session, reason="Authorized flare testing")
    assert dismissed.status == "DISMISSED"

# ---------------------------------------------------------------------------
# 6. INCIDENT STATE MACHINE TRANSITION TESTS
# ---------------------------------------------------------------------------
def test_state_machine_transitions():
    # Active incident becomes ESCALATED on CRITICAL severity
    assert determine_lifecycle_state("ACTIVE", "CRITICAL", is_persistent=False) == "ESCALATED"

    # Active incident becomes PERSISTENT when flagged
    assert determine_lifecycle_state("ACTIVE", "LOW", is_persistent=True) == "PERSISTENT"

    # Incident with no detections for 24h becomes SUBSIDING
    assert determine_lifecycle_state("ACTIVE", "MEDIUM", is_persistent=False, hours_since_last_seen=25.0) == "SUBSIDING"

    # Incident with no detections for 48h becomes RESOLVED
    assert determine_lifecycle_state("ACTIVE", "MEDIUM", is_persistent=False, hours_since_last_seen=50.0) == "RESOLVED"

# ---------------------------------------------------------------------------
# 7. SEVERITY ORCHESTRATION SERVICE & FASTAPI API TESTS
# ---------------------------------------------------------------------------
def test_severity_service_and_api_endpoints(db_session):
    asset = IndustrialAsset(
        id="asset-sev-01",
        name="Paradip Petrochemical Complex",
        facility_type="petrochemical",
        industry="Chemicals",
        category="RED",
        latitude=20.3,
        longitude=86.6
    )
    db_session.add(asset)

    incident = Incident(
        id="inc-sev-01",
        incident_code="INC-SEV-01",
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
    db_session.add(incident)
    db_session.commit()

    # Run service
    res = evaluate_incident_severity("inc-sev-01", db_session)
    assert res["severity_level"] == "CRITICAL"
    assert res["severity_score"] >= 75.0
    assert res["alert"] is not None
    assert res["alert"]["status"] == "NEW"

    # Verify SeverityAssessment row in DB
    history = get_incident_severity_history("inc-sev-01", db_session)
    assert len(history) == 1
    assert history[0]["level"] == "CRITICAL"

    # Verify FastAPI endpoints with dependency override
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp_get = client.get("/api/alerts")
        assert resp_get.status_code == 200
        assert isinstance(resp_get.json(), list)
        assert len(resp_get.json()) >= 1

        alert_id = resp_get.json()[0]["id"]
        resp_ack = client.post(f"/api/alerts/{alert_id}/acknowledge", json={"notes": "Roger that."})
        assert resp_ack.status_code == 200
        assert resp_ack.json()["status"] == "ACKNOWLEDGED"
    finally:
        app.dependency_overrides.clear()
