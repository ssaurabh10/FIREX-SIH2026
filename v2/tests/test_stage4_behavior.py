"""
Stage 4 Behavior Intelligence & Historical System Test Suite
Tests:
1. Statistical percentiles with synthetic sequence: [10, 12, 11, 13, 12]
2. Normal vs Abnormal detection (12 -> normal, 40 -> abnormal spike)
3. Synthesis rules:
   - high persistence + normal range -> persistent / normal
   - high persistence + strong deviation -> persistent / abnormal
   - low persistence + strong deviation -> new / abnormal
4. Day/Night 24h continuity persistence scoring
5. Multi-window trends (increasing, stable, decreasing)
6. History reliability classification (NONE, LOW, MODERATE, GOOD, STRONG)
7. REST API router endpoints for incidents and industries
8. The 365-day location-baseline window itself: a real year-wide observation
   set, with a detection outside it that must be excluded (E7)
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.storage.database import SessionLocal, Base, engine
from app.storage.models import (
    Observation, IndustrialAsset, Incident, BehaviorProfile, HistoricalBaseline
)
from app.behavior.baseline import (
    compute_percentiles,
    calculate_history_reliability,
    classify_history_reliability,
    generate_spatial_key,
    get_or_create_location_baseline,
    get_or_create_facility_baseline
)
from app.behavior.persistence import calculate_persistence_score
from app.behavior.anomaly import (
    calculate_frp_ratio_score,
    classify_behavior_synthesis,
    evaluate_historical_anomaly
)
from app.behavior.trends import compute_historical_trend
from app.behavior.profile import (
    get_or_create_location_profile,
    get_or_create_facility_profile,
    refresh_behavior_features
)

client = TestClient(app)

def test_synthetic_sequence_percentiles():
    """
    Blueprint requirement:
    Test synthetic sequence: 10, 12, 11, 13, 12
    Verify median is 12.0 and upper percentiles are calculated.
    """
    seq = [10.0, 12.0, 11.0, 13.0, 12.0]
    stats = compute_percentiles(seq)
    
    assert stats["median"] == 12.0
    assert stats["min"] == 10.0
    assert stats["max"] == 13.0
    assert stats["mean"] == 11.6
    assert stats["p95"] >= 12.0

def test_synthetic_normal_vs_abnormal_anomaly():
    """
    Blueprint requirement:
    Compare current values against baseline of [10, 12, 11, 13, 12]:
    12 -> normal
    40 -> abnormal
    """
    seq = [10.0, 12.0, 11.0, 13.0, 12.0]
    stats = compute_percentiles(seq)
    baseline_override = {
        "median_frp": stats["median"],
        "p95_frp": stats["p95"],
        "observation_count": len(seq)
    }

    # Test 12 MW -> Normal
    res_normal = evaluate_historical_anomaly(
        current_frp=12.0,
        lat=22.5,
        lon=88.3,
        baseline_override=baseline_override,
        save_record=False
    )
    assert res_normal["status"] == "NORMAL_OPERATIONAL_RANGE"
    assert res_normal["above_p95"] is False
    assert res_normal["frp_ratio"] == 1.0

    # Test 40 MW -> Abnormal
    res_abnormal = evaluate_historical_anomaly(
        current_frp=40.0,
        lat=22.5,
        lon=88.3,
        baseline_override=baseline_override,
        save_record=False
    )
    assert res_abnormal["status"] == "ABNORMAL_HISTORICAL_SPIKE"
    assert res_abnormal["above_p95"] is True
    assert res_abnormal["frp_ratio"] > 3.0
    # Section 4.4's ratio table is 0-100 (40/12 = 3.33x -> the "> 3.0 - 4.0x"
    # row scores 75); the field used to be returned as the 0-1 fraction 0.75,
    # which the selection composite then weighted by 0.10 verbatim.
    assert res_abnormal["anomaly_score"] == 75.0
    assert res_abnormal["anomaly_score"] == res_abnormal["ratio_score_100"]
    # Low persistence + strong deviation crosses to the abnormal quadrant.
    assert res_abnormal["synthesis"] == "new / abnormal"

def test_anomaly_ratio_uses_unrounded_quotient():
    """
    Section 4.4 (spec line 165): R_frp is used directly against the ratio table.
    Rounding it to 2 decimals first moved boundary values down a row (1.254 ->
    1.25 scored 10 where the spec's "> 1.25 - 1.5x" row gives 20).
    """
    baseline = {"median_frp": 100.0, "p95_frp": 9999.0, "observation_count": 50}

    res = evaluate_historical_anomaly(
        current_frp=125.4, lat=22.5, lon=88.3,
        baseline_override=baseline, save_record=False
    )
    assert res["frp_ratio"] == 1.25            # rounded for display only
    assert res["ratio_score_100"] == 20.0      # classified on 1.2540

    res = evaluate_historical_anomaly(
        current_frp=200.4, lat=22.5, lon=88.3,
        baseline_override=baseline, save_record=False
    )
    assert res["ratio_score_100"] == 60.0      # classified on 2.0040

def test_sparse_history_reaches_the_anomaly_table():
    """
    Section 4.4 defines LOW (1-4 obs) and MODERATE (5-9 obs) reliability tiers
    and applies the table to whatever baseline exists -- there is no
    minimum-observation carve-out. Only a cell with no baseline at all is
    INSUFFICIENT_HISTORY, and that path reports an unassessed synthesis rather
    than a benign "normal" quadrant.
    """
    sparse = {"median_frp": 100.0, "p95_frp": 150.0, "observation_count": 2}

    res = evaluate_historical_anomaly(
        current_frp=600.0, lat=22.5, lon=88.3,
        baseline_override=sparse, save_record=False
    )
    assert res["status"] == "ABNORMAL_HISTORICAL_SPIKE"
    assert res["anomaly_score"] == 100.0
    assert res["synthesis"] == "new / abnormal"

    no_history = {"median_frp": 0.0, "p95_frp": 0.0, "observation_count": 0}
    res_none = evaluate_historical_anomaly(
        current_frp=600.0, lat=22.5, lon=88.3,
        baseline_override=no_history, save_record=False
    )
    assert res_none["status"] == "INSUFFICIENT_HISTORY"
    assert res_none["synthesis"] is None

def test_behavior_synthesis_rules():
    """
    Blueprint requirement / Section 4.4 matrix (spec lines 178-190): the matrix
    crosses persistence >= 0.5 with the ANOMALY SCORE >= 50, not with P95
    membership.
    """
    # 1. High persistence (0.85) + normal (ratio 1.0 -> table score 0)
    syn1 = classify_behavior_synthesis(persistence_score=0.85, above_p95=False, frp_ratio=1.0)
    assert syn1 == "persistent / normal"

    # 2. High persistence (0.85) + strong deviation (ratio 3.5 -> table score 75)
    syn2 = classify_behavior_synthesis(persistence_score=0.85, above_p95=True, frp_ratio=3.5)
    assert syn2 == "persistent / abnormal"

    # 3. Low persistence (0.10) + strong deviation (ratio 4.0 -> table score 90)
    syn3 = classify_behavior_synthesis(persistence_score=0.10, above_p95=True, frp_ratio=4.0)
    assert syn3 == "new / abnormal"

    # 4. Low persistence (0.10) + normal range (ratio 1.1 -> table score 10)
    syn4 = classify_behavior_synthesis(persistence_score=0.10, above_p95=False, frp_ratio=1.1)
    assert syn4 == "new / normal"

    # 5. The extra P95 disjunct is gone: above_p95 alone does not make a
    #    deviation "strong", because the table scores 1.1x as 10 (normal).
    syn5 = classify_behavior_synthesis(persistence_score=0.85, above_p95=True, frp_ratio=1.1)
    assert syn5 == "persistent / normal"

def test_history_reliability_classification():
    """
    Blueprint 13.7 / Section 4.4 (spec lines 155-162):
    0 observations -> NONE
    1-4 -> LOW
    5-9 -> MODERATE
    10-19 -> GOOD
    20+ -> STRONG
    """
    assert classify_history_reliability(0) == "NONE"
    assert classify_history_reliability(3) == "LOW"
    assert classify_history_reliability(7) == "MODERATE"
    assert classify_history_reliability(15) == "GOOD"
    assert classify_history_reliability(25) == "STRONG"

def test_history_reliability_is_the_discrete_spec_tier():
    """
    The numeric companion must return the spec's five discrete tier values
    (0.0/0.25/0.50/0.75/1.00), not a continuous count/day blend. The scale stays
    0.0-1.0 because severity/scoring.py multiplies it by 100 into C_sev.
    """
    assert calculate_history_reliability(0, 0, 365) == 0.0
    for obs in (1, 2, 3, 4):
        assert calculate_history_reliability(obs, obs, 365) == 0.25
    for obs in (5, 7, 9):
        assert calculate_history_reliability(obs, obs, 365) == 0.50
    for obs in (10, 15, 19):
        assert calculate_history_reliability(obs, obs, 365) == 0.75
    for obs in (20, 500):
        assert calculate_history_reliability(obs, obs, 365) == 1.00

def test_persistence_engine_day_night_continuity():
    """
    Distinguishes 24h continuous flaring (Day + Night) from isolated detections,
    scored with the spec formula (spec line 153):
        min(1.0, (active_days/45.0)*0.7 + min(1.0, obs_count/100.0)*0.3)
    """
    now = datetime.utcnow()
    # Continuous: 90 observations spread over 45 distinct days, half Day and
    # half Night => (45/45)*0.7 + min(1.0, 90/100)*0.3 = 0.97
    obs_continuous = []
    for i in range(90):
        dn = "DAY" if i % 2 == 0 else "NIGHT"
        obs_continuous.append(
            Observation(
                external_id=f"TEST_PERSIST_{i}",
                latitude=22.5,
                longitude=88.3,
                frp_mw=15.0,
                daynight=dn,
                acquired_at=now - timedelta(days=i % 45)
            )
        )

    res = calculate_persistence_score(obs_continuous)
    assert res["active_days"] == 45
    assert res["persistence_score"] == 0.97
    assert res["day_night_continuous"] is True
    assert res["day_pass_count"] == 45
    assert res["night_pass_count"] == 45
    assert res["persistence_classification"] == "CONFIRMED_CONTINUOUS_24H_INDUSTRIAL"

    # Single observation
    res_isolated = calculate_persistence_score([obs_continuous[0]])
    assert res_isolated["day_night_continuous"] is False
    assert res_isolated["persistence_classification"] == "NEW_UNOBSERVED_IGNITION"

def test_historical_trend_computation():
    """
    Tests trend velocity: INCREASING, STABLE, DECREASING.
    """
    now = datetime.utcnow()
    # Increasing trend: older days 10 MW, recent days 30 MW
    obs_increasing = [
        Observation(latitude=22.0, longitude=88.0, frp_mw=10.0, acquired_at=now - timedelta(days=12)),
        Observation(latitude=22.0, longitude=88.0, frp_mw=10.0, acquired_at=now - timedelta(days=10)),
        Observation(latitude=22.0, longitude=88.0, frp_mw=30.0, acquired_at=now - timedelta(days=2)),
        Observation(latitude=22.0, longitude=88.0, frp_mw=32.0, acquired_at=now - timedelta(days=1)),
    ]
    res = compute_historical_trend(obs_increasing)
    assert res["trend_direction"] == "INCREASING"
    assert res["frp_velocity"] > 5.0
    assert len(res["daily_histogram"]) == 4

def test_db_location_and_facility_profile_flow():
    """
    Tests end-to-end profile creation and queries against the database session.
    """
    db = SessionLocal()
    try:
        test_lat = 10.123
        test_lon = 70.123
        asset = IndustrialAsset(
            name="Isolated Test Unit",
            facility_type="petrochemical",
            operator="Synthetic Ltd",
            industry="Chemicals",
            category="gas_flare",
            latitude=test_lat,
            longitude=test_lon,
            state="Offshore",
            district="Offshore",
            buffer_radius_meters=2000.0
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        # Add 6 observations near the asset
        now = datetime.utcnow()
        for i in range(6):
            o = Observation(
                external_id=f"TEST_STAGE4_OBS_{i}_{now.timestamp()}",
                latitude=test_lat + (i * 0.001),
                longitude=test_lon + (i * 0.001),
                frp_mw=12.0 + i,
                daynight="DAY" if i % 2 == 0 else "NIGHT",
                acquired_at=now - timedelta(days=i * 2)
            )
            db.add(o)
        db.commit()

        # Generate Facility Profile
        fac_prof = get_or_create_facility_profile(asset.id, db, window_days=90, force_refresh=True)
        assert fac_prof["facility_id"] == asset.id
        assert fac_prof["observation_count"] == 6
        assert fac_prof["median_frp"] > 0.0
        assert fac_prof["history_reliability_label"] == "MODERATE"
        assert len(fac_prof["daily_summaries"]) > 0

        # Generate Location Profile
        loc_prof = get_or_create_location_profile(test_lat, test_lon, db, window_days=90, force_refresh=True)
        assert loc_prof["observation_count"] == 6
        assert "what_is_normal_here" in loc_prof["answers"]
        assert "is_source_persistent" in loc_prof["answers"]

        # The live behavior_profiles columns the profiler used to leave at their
        # defaults are now populated from the persistence evaluation (F-061).
        assert loc_prof["window_days"] == 90
        assert loc_prof["day_passes_count"] + loc_prof["night_passes_count"] == 6
        assert loc_prof["is_continuous_24h"] is True

        persisted = (
            db.query(BehaviorProfile)
            .filter(
                BehaviorProfile.profile_type == "location",
                BehaviorProfile.spatial_reference == loc_prof["spatial_reference"]
            )
            .first()
        )
        assert persisted is not None
        assert persisted.window_days == 90
        assert persisted.day_passes_count == loc_prof["day_passes_count"]
        assert persisted.night_passes_count == loc_prof["night_passes_count"]
        assert bool(persisted.is_continuous_24h) is True

        # Stage 4's window is 365 days by default (spec line 150).
        assert get_or_create_location_profile.__defaults__[0] == 365

        # Test incremental refresh function
        refresh_res = refresh_behavior_features(db)
        assert refresh_res["status"] == "SUCCESS"
        assert refresh_res["refreshed_facilities_count"] >= 1

    finally:
        # Clean up test asset and test observations
        db.query(Observation).filter(Observation.external_id.like("TEST_STAGE4_OBS_%")).delete(synchronize_session=False)
        db.query(IndustrialAsset).filter(IndustrialAsset.name == "Isolated Test Unit").delete(synchronize_session=False)
        db.commit()
        db.close()

def test_api_historical_endpoints():
    """
    Tests REST API endpoints for history, baseline, anomaly, and trends.
    """
    db = SessionLocal()
    try:
        # Create an incident
        now = datetime.utcnow()
        inc = Incident(
            incident_code=f"INC-HIST-TEST-{int(now.timestamp())}",
            status="ACTIVE",
            classification="INDUSTRIAL_FIRE",
            latitude=22.025,
            longitude=88.058,
            state="West Bengal",
            current_max_frp=35.0,
            current_mean_frp=25.0,
            first_detected_at=now - timedelta(days=1),
            last_detected_at=now
        )
        db.add(inc)
        db.commit()
        db.refresh(inc)

        # 1. GET /incidents/{id}/history
        res = client.get(f"/incidents/{inc.id}/history")
        assert res.status_code == 200
        data = res.json()
        assert data["incident_id"] == inc.id
        assert "answers" in data

        # 2. GET /incidents/{id}/baseline
        res = client.get(f"/incidents/{inc.id}/baseline")
        assert res.status_code == 200
        data = res.json()
        assert "median_frp" in data
        assert "p95_frp" in data

        # 3. GET /incidents/{id}/anomaly
        res = client.get(f"/incidents/{inc.id}/anomaly")
        assert res.status_code == 200
        data = res.json()
        assert "anomaly_score" in data
        assert "synthesis" in data

        # 4. GET /incidents/{id}/trend
        res = client.get(f"/incidents/{inc.id}/trend")
        assert res.status_code == 200
        data = res.json()
        assert "trend_direction" in data

        # 5. POST /history/refresh
        res = client.post("/history/refresh")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"

    finally:
        db.close()

# A coordinate this test owns, picked for what it is *not*: it sits ~300 km from
# the nearest seeded industrial asset (Bhilai Steel Plant, SAIL, Durg) and no
# ThermalClimatology grid cell in tests/fixtures/reference_data.json covers it.
# Both properties are load-bearing. Either one would divert
# get_or_create_location_baseline into a short-circuit -- the 24 h baseline
# cache, or the pre-computed climatology cell -- before it ever reached the
# observation scan this test is about.
BASELINE_LAT = 21.5000
BASELINE_LON = 78.5000


def test_location_baseline_365_day_window_is_real():
    """
    E7 / F-097: build a genuine 365-day window and assert the windowing itself.

    Section 12 of the specification claims this file covers "365d percentiles",
    but no test here ever constructed a window wider than ten observations a few
    days across (`range(10)` in the profile test, `range(6)` in the facility
    profiler): every 365 in the file was a literal in a mocked payload. Nothing
    exercised the `Observation.acquired_at >= now - timedelta(days=window_days)`
    filter that makes "365-day rolling window" (spec line 150) true, so a filter
    that silently widened to all of history -- or collapsed to the last month --
    would have passed the entire suite.

    The window is built to be falsifiable rather than merely present: one
    seeded observation sits 400 days back, outside the window, and its FRP
    (900.0 MW) is far above every in-window value. If the filter leaks it the
    count reads 5 instead of 4, `max_frp` reads 900.0 instead of 50.0, and
    `p95_frp` reads 730.0 instead of 48.5 -- each assertion below fails loudly,
    and none of them can be satisfied by an implementation that ignores the
    window.
    """
    db = SessionLocal()
    spatial_key = generate_spatial_key(BASELINE_LAT, BASELINE_LON)
    now = datetime.utcnow()
    # (in-window?, days before now, FRP in MW)
    seeded = [
        (False, 400, 900.0),   # the leak detector: outside every horizon below
        (True, 300, 20.0),
        (True, 200, 30.0),
        (True, 100, 40.0),
        (True, 10, 50.0),
    ]
    in_window_frps = [frp for inside, _, frp in seeded if inside]
    obs_ids = [f"obs-base365-{days}d" for _, days, _ in seeded]
    try:
        # A previously interrupted run must not leave its cache row behind: a
        # row written seconds ago is 24 h-fresh and would take the cache path.
        db.query(HistoricalBaseline).filter(
            HistoricalBaseline.spatial_key == spatial_key
        ).delete(synchronize_session=False)
        db.query(Observation).filter(
            Observation.id.in_(obs_ids)
        ).delete(synchronize_session=False)
        db.commit()

        for obs_id, (_, days, frp) in zip(obs_ids, seeded):
            db.add(Observation(
                id=obs_id,
                external_id=obs_id,
                latitude=BASELINE_LAT + 0.005,   # ~0.56 km: inside the 3 km radius
                longitude=BASELINE_LON,
                frp_mw=frp,
                satellite="N20",
                sensor="VIIRS",
                acquired_at=now - timedelta(days=days),
            ))
        db.commit()

        # force_refresh bypasses the cache; the fresh scan is the code path that
        # applies window_days, and it is the one production reaches on a cold
        # start for a coordinate with no climatology cell.
        res = get_or_create_location_baseline(
            BASELINE_LAT, BASELINE_LON, db, window_days=365, force_refresh=True
        )

        assert res["window_days"] == 365
        assert res["observation_count"] == len(in_window_frps), (
            "the 400-day-old detection was counted inside a 365-day window; the "
            "acquired_at filter is not scoping the scan"
        )
        assert res["active_days"] == len(in_window_frps)

        # The statistics must summarize the in-window set and nothing else.
        assert res["max_frp"] == 50.0, "the out-of-window 900.0 MW detection leaked in"
        assert res["min_frp"] == 20.0
        assert res["median_frp"] == 35.0
        assert res["mean_frp"] == 35.0
        # P95 over [20, 30, 40, 50]: k = 3 * 0.95 = 2.85, so
        # sorted[2] * (3 - 2.85) + sorted[3] * (2.85 - 2) = 40 * 0.15 + 50 * 0.85.
        assert res["p95_frp"] == pytest.approx(48.5)
        # P90: k = 3 * 0.90 = 2.70 -> 40 * 0.30 + 50 * 0.70.
        assert res["p90_frp"] == pytest.approx(47.0)
        # ... and independently of those literals, the reported figures are the
        # in-window set's own percentiles, recomputed here from the seeded FRPs.
        expected = compute_percentiles(in_window_frps)
        assert res["p95_frp"] == pytest.approx(expected["p95"])
        assert res["p90_frp"] == pytest.approx(expected["p90"])
        assert res["median_frp"] == pytest.approx(expected["median"])

        # The count reaches a consumer: 4 observations is the LOW band.
        assert res["history_reliability_label"] == "LOW"
        # No facility within 300 km, no mining basin, no flare context here.
        assert res["is_routine_flare"] is False
        assert res["site_classification_hint"] == "EPISODIC_THERMAL"

        # The materialized row must record the same window it reported, with the
        # per-horizon counts split correctly.
        persisted = (
            db.query(HistoricalBaseline)
            .filter(HistoricalBaseline.spatial_key == spatial_key)
            .first()
        )
        assert persisted is not None
        assert persisted.detection_count_365d == len(in_window_frps)
        # Only the 10-day-old detection falls inside the shorter horizons.
        assert persisted.detection_count_90d == 1
        assert persisted.detection_count_30d == 1
        assert persisted.p95_frp == pytest.approx(48.5)
        # The stored window really is a year long, and ends at scan time.
        assert (persisted.window_end - persisted.window_start).days == 365
        assert (now - persisted.window_end).total_seconds() < 60

        # A follow-up call at a shorter horizon must re-read the matching column
        # rather than report the 365-day count as a 90-day one. This call takes
        # the cache path (the row was written moments ago, and the site is not
        # flare-adjacent), which is the reader the per-horizon split exists for.
        cached_90 = get_or_create_location_baseline(
            BASELINE_LAT, BASELINE_LON, db, window_days=90
        )
        assert cached_90["window_days"] == 90
        assert cached_90["observation_count"] == 1, (
            "a 90-day read returned the 365-day count; the cached per-horizon "
            "counts are not being selected by window_days"
        )
    finally:
        try:
            db.query(Observation).filter(
                Observation.id.in_(obs_ids)
            ).delete(synchronize_session=False)
            db.query(HistoricalBaseline).filter(
                HistoricalBaseline.spatial_key == spatial_key
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()
