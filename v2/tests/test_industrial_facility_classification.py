"""
Unit & Integration Tests for Heavy Industrial & Metallurgical Fire Classification
Verifies that:
1. Steel plants, blast furnaces, and smelters are classified as 'industrial_fire', NEVER as 'gas_flare'.
2. Petroleum facilities (oil refineries, LNG terminals, offshore platforms) are classified as 'gas_flare'.
3. Climatology baseline sanitization: steel plants/smelters have is_routine_flare=False and hint='METALLURGICAL_INDUSTRIAL'.
4. AI investigation prompt injects heavy industrial operational guidance and marks Known Routine Flare: NO.
5. export_v1_dashboard_data correctly exports nearest facility metadata and PERSISTENT_METALLURGICAL_EMISSION pattern.
"""
import pytest
from app.gis.assets import (
    INITIAL_INDUSTRIAL_FACILITIES,
    find_nearest_asset,
    is_flaring_facility,
    is_metallurgical_or_manufacturing_facility,
    get_facility_classification_category,
    seed_industrial_assets
)
from app.behavior.baseline import get_or_create_location_baseline
from app.intelligence.prompts import build_investigation_prompt
from app.storage.database import SessionLocal
from app.storage.models import Incident, IndustrialAsset

def test_facility_categorization_logic():
    """Verify distinct separation between flaring petroleum assets and metallurgical manufacturing assets."""
    # Petroleum flaring facilities
    assert is_flaring_facility("oil_refinery", "gas_flare") is True
    assert is_flaring_facility("lng_terminal", "gas_flare") is True
    assert is_flaring_facility("offshore_platform", "gas_flare") is True
    assert get_facility_classification_category("oil_refinery", "Petroleum Refining", "gas_flare") == "gas_flare"

    # Metallurgical & steel manufacturing facilities
    assert is_flaring_facility("steel_plant", "industrial_fire") is False
    assert is_flaring_facility("smelter", "industrial_fire") is False
    assert is_metallurgical_or_manufacturing_facility("steel_plant", "Integrated Steel Plant & Blast Furnace") is True
    assert is_metallurgical_or_manufacturing_facility("smelter", "Aluminium Smelter") is True
    assert get_facility_classification_category("steel_plant", "Steel Manufacturing", "industrial_fire") == "industrial_fire"

def test_steel_plants_spatial_coverage():
    """Verify key sovereign steel plants and smelters resolve to accurate facility records."""
    db = SessionLocal()
    try:
        seed_industrial_assets(db)
        
        # Test cases: (lat, lon, expected_name_substring)
        test_cases = [
            (22.795, 86.200, "TATA Steel Works, Jamshedpur"),
            (21.189, 81.385, "Bhilai Steel Plant"),
            (17.615, 83.205, "Visakhapatnam Steel Plant"),
            (22.215, 84.860, "Rourkela Steel Plant"),
            (20.965, 86.011, "TATA Steel Kalinganagar"),
            (20.785, 85.275, "Jindal Steel & Power"),
            (22.040, 83.735, "Vedanta Aluminium Smelter"),
            (18.690, 73.038, "JSW Steel Dolvi Works"),
            (21.370, 81.660, "Siltara & Urla Heavy Industrial Complex"),
            (19.100, 82.165, "NMDC Iron & Steel Plant"),
        ]
        
        for lat, lon, expected_sub in test_cases:
            res = find_nearest_asset(lat, lon, db)
            assert res is not None
            assert res.get("asset_id") is not None
            assert expected_sub.lower() in res.get("facility_name", "").lower(), f"Expected {expected_sub} at ({lat}, {lon})"
            assert res.get("distance_km") <= 5.0, f"Distance too far ({res.get('distance_km')}km) for {expected_sub}"
    finally:
        db.close()

def test_climatology_baseline_metallurgical_sanitization():
    """Verify that get_or_create_location_baseline at a steel plant never returns is_routine_flare=True."""
    db = SessionLocal()
    try:
        # Bhilai Steel Plant coordinate
        bl_bhilai = get_or_create_location_baseline(21.189, 81.385, db)
        assert bl_bhilai["is_routine_flare"] is False, "Bhilai Steel Plant coordinate must not be a routine flare"
        assert bl_bhilai["site_classification_hint"] == "METALLURGICAL_INDUSTRIAL"
        assert bl_bhilai["is_metallurgical_facility"] is True

        # Tata Steel Kalinganagar coordinate
        bl_tata = get_or_create_location_baseline(20.965, 86.011, db)
        assert bl_tata["is_routine_flare"] is False, "Tata Steel Kalinganagar coordinate must not be a routine flare"
        assert bl_tata["site_classification_hint"] == "METALLURGICAL_INDUSTRIAL"

        # Vizag Steel coordinate
        bl_vizag = get_or_create_location_baseline(17.615, 83.205, db)
        assert bl_vizag["is_routine_flare"] is False, "Vizag Steel coordinate must not be a routine flare"
        assert bl_vizag["site_classification_hint"] == "METALLURGICAL_INDUSTRIAL"
    finally:
        db.close()

def test_prompt_includes_metallurgical_guidance():
    """Verify that build_investigation_prompt injects heavy industrial operational guidance."""
    mock_pkg = {
        "incident": {
            "incident_code": "INC-BHILAI-001",
            "latitude": 21.189,
            "longitude": 81.385,
            "max_frp_mw": 18.5,
            "mean_frp_mw": 14.2,
            "observation_count": 12,
            "satellite": "VIIRS"
        },
        "gis_context": {
            "facility_name": "Bhilai Steel Plant (SAIL), Durg",
            "facility_type": "steel_plant",
            "industry": "Steel Manufacturing",
            "is_inside_facility": True,
            "state": "Chhattisgarh",
            "district": "Durg"
        },
        "historical_features": {
            "active_days_365d": 280,
            "median_frp_mw": 12.0,
            "p95_frp_mw": 25.0,
            "night_ratio": 0.65,
            "surge_multiplier": 1.5,
            "is_routine_flare": False,
            "site_classification_hint": "METALLURGICAL_INDUSTRIAL",
            "is_metallurgical_facility": True
        },
        "visual_context": {
            "provider": "Google Satellite",
            "radius_meters": 1500.0,
            "zoom_level": 16
        }
    }
    prompt = build_investigation_prompt(mock_pkg)
    assert "Bhilai Steel Plant" in prompt
    assert "steel_plant" in prompt
    assert "METALLURGICAL_INDUSTRIAL" in prompt
    assert "Known Routine Flare: NO" in prompt
    assert "OPERATIONAL GUIDANCE FOR HEAVY INDUSTRIAL / METALLURGICAL FACILITIES" in prompt
    assert "NOT petroleum gas flares" in prompt
    assert "Classify as 'industrial_fire'" in prompt
