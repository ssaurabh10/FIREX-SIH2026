"""
Automated Test Suite for Stage 5: Selection Engine & Visual Context
Tests:
1. Normalized FRP scoring curve (4 MW -> ~58, 8 MW -> ~79, 15+ MW -> 100).
2. FIRMS confidence mapping (MODIS, VIIRS, continuous percentage).
3. Selection override rules (Extreme FRP >150MW, High persistence >85, Anomaly >3x).
4. Dual-mode investigation priority formula (with history vs without history - Rule 6).
5. Dynamic cluster viewport scaling (500m to 2000m) and custom radius overrides.
6. Slippy map tile math (deg2num / num2deg) and image stitching.
7. Tactical thermal reticle rendering and image validity checks.
8. Deterministic Investigation Package generation.
9. Selection & Imagery REST API router endpoints.
"""
import os
import math
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.storage.database import SessionLocal, Base, engine
from app.storage.models import Incident, IndustrialAsset, ImageryRecord
from app.selection.scoring import (
    calculate_frp_score,
    map_firms_confidence,
    evaluate_selection_overrides,
    compute_investigation_priority
)
from app.selection.engine import evaluate_incident_selection, select_investigation_candidates
from app.imagery.viewport import (
    calculate_incident_viewport,
    determine_zoom_for_radius,
    get_meters_per_pixel,
    ViewportSpec
)
from app.imagery.provider import (
    deg2num,
    num2deg,
    fetch_tile,
    get_stitched_crop,
    verify_image_validity
)
from app.imagery.reticle import draw_tactical_reticle
from app.imagery.service import get_or_create_incident_imagery
from app.imagery.package import build_investigation_package

client = TestClient(app)

def test_frp_scoring_log2_curve():
    """Blueprint 14.1: FRP score mapping 0-100."""
    assert calculate_frp_score(0.0) == 0.0
    # 4 MW -> 25 * log2(5) ~= 58.0
    score_4 = calculate_frp_score(4.0)
    assert 57.0 <= score_4 <= 59.0

    # 8 MW -> 25 * log2(9) ~= 79.2
    score_8 = calculate_frp_score(8.0)
    assert 78.0 <= score_8 <= 80.5

    # 15 MW -> 25 * log2(16) = 100.0
    score_15 = calculate_frp_score(15.0)
    assert score_15 == 100.0

    # 200 MW -> capped at 100.0
    assert calculate_frp_score(200.0) == 100.0

def test_confidence_mapping():
    """Blueprint 14.2: MODIS and VIIRS confidence mapping."""
    # MODIS
    assert map_firms_confidence("low", "MODIS") == 25.0
    assert map_firms_confidence("nominal", "MODIS") == 65.0
    assert map_firms_confidence("high", "MODIS") == 95.0

    # VIIRS
    assert map_firms_confidence("l", "VIIRS") == 35.0
    assert map_firms_confidence("n", "VIIRS") == 70.0
    assert map_firms_confidence("h", "VIIRS") == 95.0

    # Continuous score
    assert map_firms_confidence(confidence_score=0.85) == 85.0

def test_selection_overrides():
    """Blueprint 14.3: Mandatory selection overrides."""
    # Extreme FRP: >150 MW and >= 80 confidence
    ov1, r1 = evaluate_selection_overrides(frp_mw=180.0, confidence=85.0, persistence_score=20.0)
    assert ov1 is True
    assert any("EXTREME_FRP" in r for r in r1)

    # High Persistence: >= 85
    ov2, r2 = evaluate_selection_overrides(frp_mw=10.0, confidence=50.0, persistence_score=90.0)
    assert ov2 is True
    assert any("HIGH_PERSISTENCE" in r for r in r2)

    # Strong Historical Anomaly: frp_ratio >= 3.0
    ov3, r3 = evaluate_selection_overrides(frp_mw=30.0, confidence=70.0, persistence_score=40.0, frp_ratio=3.5)
    assert ov3 is True
    assert any("STRONG_HISTORICAL_ANOMALY" in r for r in r3)

    # Normal activity -> no override
    ov_none, r_none = evaluate_selection_overrides(frp_mw=12.0, confidence=60.0, persistence_score=30.0, frp_ratio=1.1)
    assert ov_none is False
    assert len(r_none) == 0

def test_dual_mode_investigation_priority():
    """
    Blueprint Section 14:
    With history: 40% FRP + 30% Persistence + 20% Confidence + 10% Anomaly
    Without history: 45% FRP + 30% Persistence + 25% Confidence (Rule 6 compliant)
    """
    # 1. With history
    res_hist = compute_investigation_priority(
        frp_mw=15.0, # 100 FRP score
        confidence_score=80.0,
        persistence_score=60.0,
        anomaly_score=50.0,
        has_history=True,
        historical_median_frp=5.0 # ratio = 3.0 -> triggers override!
    )
    assert res_hist["is_override_triggered"] is True
    assert res_hist["investigation_priority"] >= 90.0

    # 2. Without history (Rule 6)
    res_no_hist = compute_investigation_priority(
        frp_mw=8.0, # ~79.2 score
        confidence_score=70.0,
        persistence_score=40.0,
        has_history=False
    )
    assert res_no_hist["scoring_mode"] == "NEW_INCIDENT_NO_HISTORY"
    assert res_no_hist["components"]["anomaly_score"] is None
    # 0.45 * 79.2 + 0.30 * 40.0 + 0.25 * 70.0 = 35.64 + 12 + 17.5 = 65.14
    assert 64.0 <= res_no_hist["investigation_priority"] <= 66.5

def test_dynamic_and_custom_viewport_radius():
    """Blueprint Stage 5: Dynamic incident viewport / radius and custom overrides."""
    lat, lon = 22.025, 88.058

    # Isolated event -> 500m, Zoom 17
    vp_iso = calculate_incident_viewport(lat, lon, observation_count=1)
    assert vp_iso.radius_meters == 500.0
    assert vp_iso.zoom_level == 17
    assert vp_iso.is_custom_radius is False

    # Small cluster -> 750m, Zoom 16
    vp_small = calculate_incident_viewport(lat, lon, observation_count=3)
    assert vp_small.radius_meters == 750.0
    assert vp_small.zoom_level == 16

    # Medium cluster -> 1000m, Zoom 16
    vp_med = calculate_incident_viewport(lat, lon, observation_count=6)
    assert vp_med.radius_meters == 1000.0
    assert vp_med.zoom_level == 16

    # Large cluster -> up to 2000m, Zoom 15
    vp_large = calculate_incident_viewport(lat, lon, observation_count=15, cluster_radius_meters=1200.0)
    assert vp_large.radius_meters >= 1200.0
    assert vp_large.zoom_level == 15

    # Custom radius override
    vp_custom = calculate_incident_viewport(lat, lon, custom_radius_meters=1800.0)
    assert vp_custom.radius_meters == 1800.0
    assert vp_custom.zoom_level == 15
    assert vp_custom.is_custom_radius is True

    # Viewport bounding box sanity
    bbox = vp_custom.bounding_box
    assert bbox[0] < bbox[2] # min_lat < max_lat
    assert bbox[1] < bbox[3] # min_lon < max_lon

def test_slippy_tile_math_and_provider():
    """Tests Web Mercator tile conversion math and tile generation."""
    lat, lon, zoom = 22.025, 88.058, 16
    xtile, ytile = deg2num(lat, lon, zoom)
    lat_back, lon_back = num2deg(xtile, ytile, zoom)

    assert abs(lat - lat_back) < 0.001
    assert abs(lon - lon_back) < 0.001

    # Fetch 3x3 stitched crop
    crop, prov = get_stitched_crop(lat, lon, zoom=16, crop_size=640)
    assert crop.size == (640, 640)
    assert verify_image_validity(crop) is True
    assert prov in ["Google Satellite", "Esri World Imagery", "Synthetic Tactical Map"]

def test_tactical_reticle_overlay():
    """Tests reticle annotation with range rings and telemetry HUD."""
    base_img = Image.new("RGB", (640, 640), color=(30, 35, 40))
    reticle_img = draw_tactical_reticle(
        img=base_img,
        lat=22.025,
        lon=88.058,
        incident_id="INC-TEST-RETICLE-01",
        frp_mw=25.4,
        radius_meters=750.0,
        provider="Google Satellite",
        meters_per_pixel=1.2
    )

    assert reticle_img.size == (640, 640)
    assert verify_image_validity(reticle_img) is True
    # The reticle draws red crosshairs, so red channel should have peaks
    extrema = reticle_img.getextrema()
    assert extrema[0][1] > 200 # Red channel max should be bright red/white

def test_investigation_package_and_imagery_service():
    """End-to-end integration test for Imagery Service and Investigation Package."""
    db = SessionLocal()
    test_inc_id = f"inc_test_stage5_{int(datetime.utcnow().timestamp())}"
    try:
        # Create an isolated test incident
        inc = Incident(
            id=test_inc_id,
            incident_code=f"FIREX-2026-{test_inc_id[-6:]}",
            status="ACTIVE",
            latitude=22.456,
            longitude=88.789,
            current_max_frp=32.5,
            current_mean_frp=28.0,
            observation_count=4,
            first_detected_at=datetime.utcnow() - timedelta(days=2),
            last_detected_at=datetime.utcnow()
        )
        db.add(inc)
        db.commit()

        # 1. Generate Imagery via Service
        img_meta = get_or_create_incident_imagery(
            incident_id=inc.id,
            db=db,
            custom_radius_meters=800.0,
            force_refresh=True
        )
        assert img_meta["incident_id"] == inc.id
        assert img_meta["image_valid"] is True
        assert os.path.exists(img_meta["raw_image_path"])
        assert os.path.exists(img_meta["annotated_image_path"])
        assert img_meta["radius_meters"] == 800.0
        assert img_meta["is_custom_radius"] is True

        # Check DB record in imagery_records
        db_rec = db.query(ImageryRecord).filter(ImageryRecord.incident_id == inc.id).first()
        assert db_rec is not None
        assert db_rec.zoom_level == img_meta["zoom_level"]

        # 2. Build Investigation Package
        pkg = build_investigation_package(inc.id, db, custom_radius_meters=800.0)
        assert pkg["incident"]["id"] == inc.id
        assert pkg["incident"]["max_frp_mw"] == 32.5
        assert "gis_context" in pkg
        assert "historical_features" in pkg
        assert "selection_context" in pkg
        assert pkg["selection_context"]["investigation_priority"] > 0
        assert "visual_context" in pkg
        assert pkg["visual_context"]["image_valid"] is True
        assert pkg["provenance_metadata"]["pipeline_stage"] == "STAGE_5_SELECTION_AND_VISUAL_CONTEXT"
        assert pkg["provenance_metadata"]["status"] == "READY_FOR_AI_INVESTIGATION"

    finally:
        # Clean up database records
        db.query(ImageryRecord).filter(ImageryRecord.incident_id == test_inc_id).delete(synchronize_session=False)
        db.query(Incident).filter(Incident.id == test_inc_id).delete(synchronize_session=False)
        db.commit()
        db.close()

def test_selection_and_imagery_api_endpoints():
    """Tests REST API endpoints for Selection Engine and Imagery."""
    # 1. Interactive score endpoint
    score_resp = client.post("/api/selection/score", json={
        "frp_mw": 18.0,
        "confidence_score": 80.0,
        "persistence_score": 60.0,
        "has_history": True,
        "historical_median_frp": 12.0
    })
    assert score_resp.status_code == 200
    score_data = score_resp.json()
    assert "investigation_priority" in score_data
    assert score_data["investigation_priority"] > 50.0

    # 2. Get candidates endpoint
    cand_resp = client.get("/api/selection/candidates?min_priority=10.0&limit=5")
    assert cand_resp.status_code == 200
    candidates = cand_resp.json()
    assert isinstance(candidates, list)
