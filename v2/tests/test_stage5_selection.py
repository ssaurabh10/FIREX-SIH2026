"""
Automated Test Suite for Stage 5: Selection Engine (priority scoring & candidate pool)

Regression tests for the Section 14 candidate-selection defects:

1. F-048 / F-062: C_firms is the incident's real FIRMS confidence aggregate
   (0-100, app/incidents/aggregation.py), not a hard-coded 80.0 -- so the
   Section 14.3 extreme-FRP override is a two-condition test again.
2. F-049: has_history is `baseline p95 > 0` (Section 11 line 565), not
   `observation_count > 0`, so both branches of the dual-mode model are reachable.
3. F-063: R_frp = FRP_current / max(1.0, Median_FRP), so a sub-median detection
   cannot manufacture a STRONG_HISTORICAL_ANOMALY override.
4. F-064: S_anom is consumed on the Section 4.4 0-100 anomaly-table scale, with
   no rescaling in either direction.
5. F-065: S_pers is the Section 4.4 formula on 0-100, so the >= 85.0
   HIGH_PERSISTENCE override is reachable for a genuinely persistent incident.
6. F-066: a bound candidate pool is logged, never silently truncated.
"""
import logging
import uuid
from datetime import datetime, timedelta

import pytest

from app.storage.database import SessionLocal
from app.storage.models import HistoricalBaseline, Incident, IncidentObservation, Observation
from app.selection import engine as selection_engine
from app.selection.engine import (
    CANDIDATE_POOL_LIMIT,
    compute_spec_persistence_score,
    evaluate_incident_selection,
    select_investigation_candidates,
)
from app.selection.scoring import compute_investigation_priority, evaluate_selection_overrides

# Coordinates deliberately outside the fixture climatology grid (tests/fixtures/
# reference_data.json is India-only), one pair per test, so no test can inherit
# another's materialized baseline cell.
SPATIAL_KEYS = [
    "GRID_0.50_0.50",
    "GRID_0.60_0.60",
    "GRID_0.75_0.75",
    "GRID_0.85_0.85",
    "GRID_0.95_0.95",
]


@pytest.fixture()
def db():
    """A session on the throwaway test database, with this module's rows removed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.query(IncidentObservation).filter(
            IncidentObservation.incident_id.like("inc_test_sel_%")
        ).delete(synchronize_session=False)
        session.query(Observation).filter(
            Observation.external_id.like("test-sel-%")
        ).delete(synchronize_session=False)
        session.query(Incident).filter(
            Incident.id.like("inc_test_sel_%")
        ).delete(synchronize_session=False)
        session.query(HistoricalBaseline).filter(
            HistoricalBaseline.spatial_key.in_(SPATIAL_KEYS)
        ).delete(synchronize_session=False)
        session.commit()
        session.close()


def _new_incident(db, **overrides) -> Incident:
    inc_id = f"inc_test_sel_{uuid.uuid4().hex[:10]}"
    now = datetime.utcnow()
    fields = dict(
        id=inc_id,
        incident_code=f"FIREX-TEST-{inc_id[-6:]}",
        status="ACTIVE",
        latitude=0.5,
        longitude=0.5,
        current_max_frp=8.0,
        current_mean_frp=6.0,
        observation_count=1,
        first_detected_at=now - timedelta(hours=6),
        last_detected_at=now,
    )
    fields.update(overrides)
    inc = Incident(**fields)
    db.add(inc)
    db.commit()
    return inc


def _add_members(db, incident, confidence_scores, frp_mw: float) -> None:
    """Link member observations carrying real FIRMS confidence (0.0-1.0 scale)."""
    for idx, score in enumerate(confidence_scores):
        obs = Observation(
            id=f"obs_test_sel_{uuid.uuid4().hex[:10]}",
            external_id=f"test-sel-{uuid.uuid4().hex[:12]}",
            latitude=incident.latitude,
            longitude=incident.longitude,
            frp_mw=frp_mw,
            confidence_raw="n",
            confidence_score=score,
            satellite="VIIRS",
            daynight="NIGHT",
            acquired_at=incident.last_detected_at - timedelta(minutes=5 * idx),
        )
        db.add(obs)
        db.add(IncidentObservation(
            incident_id=incident.id,
            observation_id=obs.id,
            is_primary=(idx == 0),
        ))
    db.commit()


def test_spec_persistence_score_matches_section_4_4():
    """F-065: S_pers is Section 4.4's formula (line 153), expressed 0-100."""
    # 45/45 * 0.7 + 100/100 * 0.3 = 1.0 -> 100.0
    assert compute_spec_persistence_score(45, 100) == 100.0
    assert compute_spec_persistence_score(0, 0) == 0.0
    # 20/45 * 0.7 + 40/100 * 0.3 = 0.3111 + 0.12 = 0.4311 -> 43.1
    assert compute_spec_persistence_score(20, 40) == 43.1
    # The outer min(1.0, ...) saturates rather than overflowing past 100.
    assert compute_spec_persistence_score(400, 4000) == 100.0

def test_high_persistence_override_reachable_from_spec_score():
    """F-065: the 85.0 override must be reachable from the spec's own S_pers."""
    s_pers = compute_spec_persistence_score(45, 100)
    assert s_pers >= 85.0

    triggered, reasons = evaluate_selection_overrides(
        frp_mw=10.0, confidence=70.0, persistence_score=s_pers
    )
    assert triggered is True
    assert any("HIGH_PERSISTENCE" in r for r in reasons)

def test_frp_ratio_is_floored_at_one():
    """F-063: R_frp = FRP_current / max(1.0, Median_FRP) -- Section 4.5 line 165."""
    # Median 0.5 MW, current 1.6 MW -> max(1.0, 0.5) -> 1.6x, NOT 3.2x.
    res_low = compute_investigation_priority(
        frp_mw=1.6,
        confidence_score=0.70,
        persistence_score=0.0,
        anomaly_score=0.0,
        has_history=True,
        historical_median_frp=0.5,
    )
    assert res_low["components"]["frp_ratio"] == 1.6
    assert res_low["is_override_triggered"] is False

    # A genuine 3x excursion over a >= 1.0 MW median still overrides.
    res_high = compute_investigation_priority(
        frp_mw=12.0,
        confidence_score=0.70,
        persistence_score=0.0,
        has_history=True,
        historical_median_frp=4.0,
    )
    assert res_high["components"]["frp_ratio"] == 3.0
    assert any("STRONG_HISTORICAL_ANOMALY" in r for r in res_high["override_reasons"])
    assert res_high["investigation_priority"] >= 90.0

def test_selection_uses_real_firms_confidence(db):
    """F-048 / F-062: C_firms is the member aggregate, so the extreme-FRP
    override is no longer satisfied by a constant."""
    low_conf = _new_incident(db, latitude=0.5, longitude=0.5, current_max_frp=160.0, observation_count=2)
    _add_members(db, low_conf, [0.35, 0.95], frp_mw=160.0)  # mean 0.65 -> 65.0 %
    res_low = evaluate_incident_selection(low_conf.id, db)
    assert res_low["firms_confidence"] == 65.0
    assert res_low["priority_details"]["components"]["confidence_score"] == 65.0
    # FRP >= 150 MW at 65 % confidence fails the C_firms >= 80.0 % half of the rule.
    assert res_low["priority_details"]["is_override_triggered"] is False
    assert res_low["priority_details"]["override_reasons"] == []

    high_conf = _new_incident(db, latitude=0.6, longitude=0.6, current_max_frp=160.0, observation_count=2)
    _add_members(db, high_conf, [0.95, 0.95], frp_mw=160.0)  # mean 0.95 -> 95.0 %
    res_high = evaluate_incident_selection(high_conf.id, db)
    assert res_high["firms_confidence"] == 95.0
    assert res_high["priority_details"]["is_override_triggered"] is True
    assert any("EXTREME_FRP" in r for r in res_high["priority_details"]["override_reasons"])

def test_has_history_requires_positive_baseline_p95(db):
    """F-049 / Section 11 line 565: has_history=(baseline p95 > 0).

    Both branches of the dual-mode model must be reachable from the same cell:
    a cell with detections but no empirical p95 is a NEW_INCIDENT_NO_HISTORY,
    and the same cell once a p95 exists takes the with-history weights.
    """
    baseline = HistoricalBaseline(
        spatial_key="GRID_0.75_0.75",
        window_start=datetime.utcnow() - timedelta(days=90),
        window_end=datetime.utcnow(),
        detection_count_90d=12,
        median_frp=0.0,
        p90_frp=0.0,
        p95_frp=0.0,
        mean_frp=0.0,
        history_reliability=0.5,
        is_persistent=True,
        last_updated_at=datetime.utcnow(),
    )
    db.add(baseline)
    db.commit()

    incident = _new_incident(db, latitude=0.75, longitude=0.75, observation_count=12)

    # observation_count is 12 > 0, but there is no empirical p95 -> no history.
    res_no_hist = evaluate_incident_selection(incident.id, db)
    assert res_no_hist["priority_details"]["scoring_mode"] == "NEW_INCIDENT_NO_HISTORY"
    assert res_no_hist["historical_context"]["has_history"] is False
    assert res_no_hist["historical_context"]["historical_p95_frp"] == 0.0

    baseline.p95_frp = 20.0
    baseline.median_frp = 4.0
    baseline.p90_frp = 15.0
    baseline.mean_frp = 4.0
    db.commit()

    res_hist = evaluate_incident_selection(incident.id, db)
    assert res_hist["priority_details"]["scoring_mode"] == "WITH_HISTORICAL_BASELINE"
    assert res_hist["historical_context"]["has_history"] is True
    assert res_hist["historical_context"]["historical_p95_frp"] == 20.0

def test_anomaly_score_consumed_on_0_100_scale(db):
    """F-064: S_anom is the Section 4.4 table score (0-100), unscaled."""
    db.add(HistoricalBaseline(
        spatial_key="GRID_0.95_0.95",
        detection_count_90d=5,
        median_frp=4.0,
        p90_frp=8.0,
        p95_frp=9.0,
        mean_frp=4.0,
        history_reliability=0.5,
        is_persistent=False,
        last_updated_at=datetime.utcnow(),
    ))
    db.commit()

    incident = _new_incident(db, latitude=0.95, longitude=0.95, current_max_frp=8.0, observation_count=5)
    res = evaluate_incident_selection(incident.id, db)

    # R_frp = 8 / max(1.0, 4.0) = 2.0 -> Section 4.4 table score 40, on 0-100.
    components = res["priority_details"]["components"]
    assert components["frp_ratio"] == 2.0
    assert components["anomaly_score"] == 40.0

    # End-to-end scale check: S_anom enters the sum as 0.10 * 40.0 = 4.0, not
    # 0.10 * 0.40 = 0.04. Recompute the weighted sum from the reported components
    # so the assertion does not depend on the wall clock.
    expected = round(
        0.40 * components["frp_score"]
        + 0.30 * components["persistence_score"]
        + 0.20 * components["confidence_score"]
        + 0.10 * components["anomaly_score"],
        1,
    )
    assert res["priority_details"]["base_priority"] == expected
    assert expected >= 50.0, "a 0-1 anomaly term would land near 47"

    # The site is not persistent: 5 detections over the incident's own active days.
    assert components["persistence_score"] == compute_spec_persistence_score(
        res["historical_context"]["active_days"], 5
    )

def test_engine_persistence_score_reaches_high_persistence_override(db):
    """F-065 end-to-end: a 46-day, 120-detection site clears S_pers >= 85.0.

    The previous `75.0 if status == PERSISTENT else min(100.0, obs * 15.0)` gave
    this incident 75.0 and could never fire the override.
    """
    db.add(HistoricalBaseline(
        spatial_key="GRID_0.85_0.85",
        detection_count_90d=120,
        median_frp=4.0,
        p90_frp=40.0,
        p95_frp=60.0,
        mean_frp=5.0,
        history_reliability=1.0,
        is_persistent=True,
        last_updated_at=datetime.utcnow(),
    ))
    db.commit()

    now = datetime.utcnow()
    incident = _new_incident(
        db,
        latitude=0.85,
        longitude=0.85,
        current_max_frp=6.0,
        observation_count=120,
        first_detected_at=now - timedelta(days=46),
        last_detected_at=now,
    )
    res = evaluate_incident_selection(incident.id, db)

    assert res["historical_context"]["active_days"] == 47
    assert res["priority_details"]["components"]["persistence_score"] == 100.0
    assert any("HIGH_PERSISTENCE" in r for r in res["priority_details"]["override_reasons"])
    assert res["selection_priority"] >= 90.0

def test_candidate_pool_truncation_is_logged(db, caplog, monkeypatch):
    """F-066: the scored pool is bounded, and binding the bound is reported."""
    monkeypatch.setattr(selection_engine, "CANDIDATE_POOL_LIMIT", 1)
    _new_incident(db, latitude=0.5, longitude=0.5, current_max_frp=8.0)
    _new_incident(db, latitude=0.6, longitude=0.6, current_max_frp=8.0)

    with caplog.at_level(logging.WARNING):
        candidates = select_investigation_candidates(db, min_priority=0.0, limit=10, status="ACTIVE")

    messages = [record.getMessage() for record in caplog.records]
    assert any("Selection candidate pool truncated" in m for m in messages), messages
    # Only the capped pool was scored, so at most one candidate can come back.
    assert len(candidates) <= 1

def test_candidate_pool_limit_is_a_documented_constant():
    """F-066: the cap is a named constant, not a bare `.limit(100)` literal."""
    assert isinstance(CANDIDATE_POOL_LIMIT, int)
    assert CANDIDATE_POOL_LIMIT >= 100
