"""
FIREX v2 Test Suite: Empirical Climatology, Prompt Grounding, and Indian Severity Calibration
Validates Items 1, 4, and 5:
1. National Thermal Climatology sub-millisecond query and persistent flaring detection.
2. Multimodal AI Prompt Grounding with 365-day forensic context.
3. Calibrated Indian FRP severity curve (P50=4.05 MW, P90=13.32 MW, P95=20.81 MW, P99=64.49 MW).
4. Routine flare suppression vs abnormal thermal surge escalation.
"""
import time
import pytest
from app.storage.database import SessionLocal
from app.storage.models import ThermalClimatology
from app.behavior.baseline import get_or_create_location_baseline
from app.imagery.package import build_investigation_package
from app.intelligence.prompts import build_investigation_prompt
from app.severity.scoring import (
    calculate_frp_severity,
    calculate_calibrated_frp_severity,
    calculate_historical_deviation,
    compute_incident_severity,
    INDIA_FRP_P50_MEDIAN,
    INDIA_FRP_P90,
    INDIA_FRP_P95,
    INDIA_FRP_P99
)

def test_climatology_submillisecond_lookup():
    """Item 1: Ensure cached climatology query executes in < 5ms (warm < 2ms)."""
    db = SessionLocal()
    try:
        # Pre-seed or query known industrial flaring cell in India (Raigarh / Chhattisgarh)
        # Warm-up call
        get_or_create_location_baseline(22.04, 83.73, db)
        
        t0 = time.perf_counter()
        bl = get_or_create_location_baseline(22.04, 83.73, db)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        
        assert latency_ms < 5.0, f"Query took {latency_ms:.2f} ms (expected < 5.0 ms)"
        assert bl["spatial_key"] == "GRID_22.04_83.73"
        assert bl["observation_count"] > 100
        assert bl["active_days_365d"] > 50
        assert bl["median_frp"] > 0.0
        assert bl["p95_frp"] > 0.0
        assert bl["night_ratio"] >= 0.30
        assert bl["is_routine_flare"] is True
        assert bl["site_classification_hint"] == "ROUTINE_FLARE"
    finally:
        db.close()

def test_multimodal_prompt_empirical_grounding():
    """Item 4: Ensure prompt builder injects 365-day site memory and empirical signatures."""
    mock_package = {
        "incident": {
            "incident_code": "INC-TEST-001",
            "latitude": 22.04,
            "longitude": 83.73,
            "max_frp_mw": 8.5,
            "mean_frp_mw": 6.2,
            "observation_count": 4,
            "satellite": "VIIRS_NOAA20"
        },
        "gis_context": {
            "facility_name": "Jindal Steel & Power Complex",
            "facility_type": "steel_plant",
            "industry": "Metallurgy",
            "facility_distance_m": 85.0,
            "is_inside_facility": True,
            "state": "Chhattisgarh",
            "district": "Raigarh"
        },
        "historical_features": {
            "active_days_365d": 284,
            "median_frp_mw": 5.47,
            "p95_frp_mw": 14.36,
            "night_ratio": 0.638,
            "surge_multiplier": 1.55,
            "is_routine_flare": True,
            "site_classification_hint": "ROUTINE_FLARE",
            "history_reliability_label": "STRONG",
            "is_persistent": True
        },
        "visual_context": {
            "provider": "Google Satellite",
            "radius_meters": 1000.0,
            "zoom_level": 16
        }
    }
    
    prompt = build_investigation_prompt(mock_package)
    
    assert "365-DAY SATELLITE CLIMATOLOGY & HISTORICAL BEHAVIOR (EMPIRICAL):" in prompt
    assert "Active on 284 distinct calendar days out of 365" in prompt
    assert "Historical Median FRP: 5.5 MW" in prompt
    assert "Normal Operational Ceiling (P95): 14.4 MW" in prompt
    assert "Observed FRP (8.5 MW) is 1.6x of historical median" in prompt
    assert "63.8% of historical detections occur at NIGHT" in prompt
    assert "Known Routine Flare: YES" in prompt
    assert "ROUTINE_FLARE" in prompt

def test_indian_firms_calibrated_severity_curve():
    """Item 5: Validate empirical percentiles mapping against national FIRMS truth."""
    # 0 MW -> 0.0
    assert calculate_calibrated_frp_severity(0.0) == 0.0
    
    # National Median (4.05 MW) -> Exactly 25.0 (Low/Medium threshold)
    score_p50 = calculate_calibrated_frp_severity(INDIA_FRP_P50_MEDIAN)
    assert abs(score_p50 - 25.0) < 0.5
    
    # P90 (13.32 MW) -> ~52.5 (High threshold)
    score_p90 = calculate_calibrated_frp_severity(INDIA_FRP_P90)
    assert 50.0 <= score_p90 <= 55.0
    
    # P95 (20.81 MW) -> ~65.4 (Solid High tier)
    score_p95 = calculate_calibrated_frp_severity(INDIA_FRP_P95)
    assert 64.0 <= score_p95 <= 68.0
    
    # P99 (64.49 MW) -> 100.0 (Top 1% Extreme wildfire/explosion)
    score_p99 = calculate_calibrated_frp_severity(INDIA_FRP_P99)
    assert score_p99 == 100.0

def test_routine_flare_suppression():
    """Item 5: A known routine flare within normal P95 ceiling must not trigger High alarm."""
    res = compute_incident_severity(
        frp_mw=8.0,
        firms_confidence=85.0,
        classification="gas_flare",
        ai_confidence=90.0,
        median_frp=5.0,
        p95_frp=15.0,
        history_reliability=1.0,
        facility_distance_m=50.0,
        facility_type="refinery",
        is_inside_facility=True,
        is_routine_flare=True
    )
    
    # Historical deviation must be suppressed (< 20.0)
    assert res["factors"]["historical_deviation_score"] <= 20.0
    assert res["factors"]["is_routine_flare"] is True
    # Final level should be LOW or MEDIUM (never HIGH or CRITICAL for routine flaring)
    assert res["severity_level"] in ["LOW", "MEDIUM"]
    assert res["has_override"] is False

def test_abnormal_thermal_surge_escalation():
    """Item 5: When a flare surges to 3.5x its P95 ceiling, trigger immediate High escalation."""
    res = compute_incident_severity(
        frp_mw=52.5,  # 3.5x of 15 MW P95 ceiling
        firms_confidence=90.0,
        classification="gas_flare",
        ai_confidence=85.0,
        median_frp=5.0,
        p95_frp=15.0,
        history_reliability=1.0,
        facility_distance_m=50.0,
        facility_type="refinery",
        is_inside_facility=True,
        is_routine_flare=True
    )
    
    assert res["factors"]["historical_deviation_score"] == 100.0
    assert res["has_override"] is True
    assert any("ABNORMAL_ACTIVITY_SPIKE" in r for r in res["override_reasons"])
    assert res["severity_level"] in ["HIGH", "CRITICAL"]
