"""
FIREX v2 Test Suite: Sovereign Indian Mining Basin Verification & Anti-False-Flare Protection
Tests:
1. Spatial containment across Korba, Jharia, Bokaro, Singrauli, Talcher, Ib Valley, Ballari, etc.
2. Climatology calibration: mining basins must NOT be classified as routine gas flares.
3. Landcover & GIS enrichment correctly detects open_cast_mine and mining concessions.
4. Investigation package & AI prompt inject mining operational guidance.
5. Orchestration pipeline exports mining_or_other_thermal_source instead of gas_flare.
"""
import pytest
from app.gis.mining_basins import is_in_major_mining_basin, get_mining_basin_metadata, MAJOR_INDIAN_MINING_BASINS
from app.gis.landcover import resolve_landcover
from app.gis.enrichment import enrich_coordinate_gis_context
from app.behavior.baseline import get_or_create_location_baseline
from app.storage.database import SessionLocal
from app.imagery.package import build_investigation_package
from app.intelligence.prompts import build_investigation_prompt
from app.storage.models import Incident, IndustrialAsset

def test_major_mining_basins_spatial_coverage():
    """Verify key sovereign mining coordinates fall inside registered basins."""
    test_cases = [
        (22.324, 82.592, "KORBA_COALFIELD"),            # Korba Open-Cast Mine
        (23.769, 86.389, "JHARIA_BOKARO_COALFIELD"),     # Jharia Coalfield
        (24.181, 82.659, "SINGRAULI_COALFIELD"),        # Singrauli NCL
        (20.957, 85.012, "TALCHER_COALFIELD"),          # Talcher Coalfield
        (21.857, 83.966, "IB_VALLEY_COALFIELD"),        # Ib Valley Coalfield
        (23.663, 87.156, "RANIGANJ_COALFIELD"),         # Raniganj Coalfield
        (23.695, 85.289, "KARANPURA_COALFIELD"),        # North Karanpura Coalfield
        (15.174, 76.785, "BALLARI_HOSPET_IRON_ORE_BASIN"), # Ballari-Sandur Iron Ore
        (22.054, 85.465, "KEONJHAR_BARBIL_IRON_ORE_BELT"), # Keonjhar-Barbil Iron Ore
    ]
    for lat, lon, expected_id in test_cases:
        is_inside, basin = is_in_major_mining_basin(lat, lon)
        assert is_inside is True, f"Failed to identify mining basin for ({lat}, {lon})"
        assert basin["id"] == expected_id

def test_mining_landcover_resolution():
    """Verify resolve_landcover identifies open_cast_mine inside basins."""
    # Korba Coalfield
    res = resolve_landcover(22.324, 82.592, nearest_asset_distance_km=30.0)
    assert res["primary_landcover"] == "open_cast_mine"
    assert "Mining Basin" in res["mining_context"]
    assert "SECL" in res["mining_context"]

    # Ballari Iron Ore
    res_b = resolve_landcover(15.174, 76.785, nearest_asset_distance_km=25.0)
    assert res_b["primary_landcover"] == "open_cast_mine"
    assert "Ballari" in res_b["mining_context"]

def test_climatology_baseline_mining_sanitization():
    """Verify that get_or_create_location_baseline in a mining basin never returns is_routine_flare=True."""
    db = SessionLocal()
    try:
        # Korba coordinate
        bl = get_or_create_location_baseline(22.324, 82.592, db)
        assert bl["is_routine_flare"] is False, "Mining basin coordinate must not be a routine flare"
        assert bl["site_classification_hint"] == "COAL_MINING_BASIN"
        assert bl["is_mining_basin"] is True

        # Jharia coordinate
        bl_j = get_or_create_location_baseline(23.769, 86.389, db)
        assert bl_j["is_routine_flare"] is False
        assert bl_j["site_classification_hint"] == "COAL_MINING_BASIN"
    finally:
        db.close()

def test_prompt_includes_mining_guidance():
    """Verify that build_investigation_prompt injects mining operational guidance."""
    mock_pkg = {
        "incident": {
            "incident_code": "INC-KORBA-001",
            "latitude": 22.324,
            "longitude": 82.592,
            "max_frp_mw": 3.5,
            "mean_frp_mw": 2.8,
            "observation_count": 8,
            "satellite": "VIIRS"
        },
        "gis_context": {
            "facility_name": "None in immediate vicinity",
            "state": "Chhattisgarh",
            "district": "Korba",
            "mining_basin": {
                "basin_name": "Korba Open-Cast Coal Basin (Gevra, Kusmunda, Dipka, Korba)",
                "operator": "South Eastern Coalfields Limited (SECL)"
            }
        },
        "historical_features": {
            "active_days_365d": 89,
            "median_frp_mw": 1.9,
            "p95_frp_mw": 4.9,
            "night_ratio": 0.85,
            "surge_multiplier": 1.4,
            "is_routine_flare": False,
            "site_classification_hint": "COAL_MINING_BASIN",
            "is_mining_basin": True
        },
        "visual_context": {
            "provider": "Google Satellite",
            "radius_meters": 1200.0,
            "zoom_level": 15
        }
    }
    prompt = build_investigation_prompt(mock_pkg)
    assert "Sovereign Mining Basin: Korba Open-Cast Coal Basin" in prompt
    assert "South Eastern Coalfields Limited (SECL)" in prompt
    assert "COAL_MINING_BASIN" in prompt
    assert "Known Routine Flare: NO" in prompt
    assert "OPERATIONAL GUIDANCE FOR MINING BASINS" in prompt
    assert "NOT petroleum gas flares" in prompt
    assert "Prefer 'mining_related'" in prompt
