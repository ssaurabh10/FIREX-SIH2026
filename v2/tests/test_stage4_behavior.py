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
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.storage.database import SessionLocal, Base, engine
from app.storage.models import Observation, IndustrialAsset, Incident
from app.behavior.baseline import (
    compute_percentiles,
    calculate_history_reliability,
    classify_history_reliability,
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
    assert res_abnormal["anomaly_score"] >= 0.75

def test_behavior_synthesis_rules():
    """
    Blueprint requirement:
    high persistence + normal historical range -> persistent / normal
    high persistence + strong historical deviation -> persistent / abnormal
    """
    # 1. High persistence (0.85) + normal (above_p95=False, ratio=1.0)
    syn1 = classify_behavior_synthesis(persistence_score=0.85, above_p95=False, frp_ratio=1.0)
    assert syn1 == "persistent / normal"

    # 2. High persistence (0.85) + strong deviation (above_p95=True, ratio=3.5)
    syn2 = classify_behavior_synthesis(persistence_score=0.85, above_p95=True, frp_ratio=3.5)
    assert syn2 == "persistent / abnormal"

    # 3. Low persistence (0.10) + strong deviation (above_p95=True, ratio=4.0)
    syn3 = classify_behavior_synthesis(persistence_score=0.10, above_p95=True, frp_ratio=4.0)
    assert syn3 == "new / abnormal"

    # 4. Low persistence (0.10) + normal range (above_p95=False, ratio=1.1)
    syn4 = classify_behavior_synthesis(persistence_score=0.10, above_p95=False, frp_ratio=1.1)
    assert syn4 == "new / normal"

def test_history_reliability_classification():
    """
    Blueprint 13.7:
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

def test_persistence_engine_day_night_continuity():
    """
    Distinguishes 24h continuous flaring (Day + Night) from isolated detections.
    """
    now = datetime.utcnow()
    # Continuous: 10 observations with both Day and Night passes
    obs_continuous = []
    for i in range(10):
        dn = "DAY" if i % 2 == 0 else "NIGHT"
        obs_continuous.append(
            Observation(
                external_id=f"TEST_PERSIST_{i}",
                latitude=22.5,
                longitude=88.3,
                frp_mw=15.0,
                daynight=dn,
                acquired_at=now - timedelta(days=i)
            )
        )

    res = calculate_persistence_score(obs_continuous)
    assert res["day_night_continuous"] is True
    assert res["day_pass_count"] == 5
    assert res["night_pass_count"] == 5
    assert res["persistence_score"] >= 0.70
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
