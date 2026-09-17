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
import json
import shutil
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
    crop_coverage_radius_meters,
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
from app.imagery.reticle import draw_tactical_reticle, plan_reticle_geometry, RING_FACTORS
from app.imagery.service import get_or_create_incident_imagery
# Imported as a module, not by value: conftest.py rebinds service.CACHE_DIR into a throwaway
# directory before any test module runs, and the renderer version is read from the same module.
from app.imagery import service as imagery_service
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

    # Isolated event -> ~500m target, Zoom 17
    vp_iso = calculate_incident_viewport(lat, lon, observation_count=1)
    assert vp_iso.zoom_level == 17
    assert 300.0 < vp_iso.radius_meters < 500.0  # F-009: declared = real crop coverage, not the 500m target
    assert vp_iso.is_custom_radius is False

    # Small cluster -> ~750m target, Zoom 16
    vp_small = calculate_incident_viewport(lat, lon, observation_count=3)
    assert vp_small.zoom_level == 16
    assert 600.0 < vp_small.radius_meters < 750.0

    # Medium cluster -> ~1000m target, Zoom 16
    vp_med = calculate_incident_viewport(lat, lon, observation_count=6)
    assert vp_med.zoom_level == 16
    assert 600.0 < vp_med.radius_meters < 1000.0

    # Large cluster -> up to 2000m, Zoom 15
    vp_large = calculate_incident_viewport(lat, lon, observation_count=15, cluster_radius_meters=1200.0)
    assert vp_large.radius_meters >= 1200.0
    assert vp_large.zoom_level == 15

    # Custom radius override (Zoom 15 cannot hold 1800m at this latitude, so the declared
    # radius is the 1417m the crop really covers)
    vp_custom = calculate_incident_viewport(lat, lon, custom_radius_meters=1800.0)
    assert vp_custom.zoom_level == 15
    assert abs(vp_custom.radius_meters - 1417.2) < 1.0
    assert vp_custom.is_custom_radius is True

    # Viewport bounding box sanity
    bbox = vp_custom.bounding_box
    assert bbox[0] < bbox[2] # min_lat < max_lat
    assert bbox[1] < bbox[3] # min_lon < max_lon

def test_viewport_declared_radius_matches_crop_coverage():
    """F-009: radius_meters and the bounding box must describe the 640px crop's real ground coverage."""
    # The zoom chooser must know the latitude: a Zoom-17 crop covers only ~336-378m of ground in
    # India, so the ~500m tier needs Zoom 16 further north; and no latitude reaches the 3.125 m/px
    # the old table assumed at Zoom 16 (that would need cos(lat) > 1).
    assert determine_zoom_for_radius(500.0, 22.025) == 17
    assert determine_zoom_for_radius(500.0, 28.6) == 17
    assert determine_zoom_for_radius(500.0, 40.0) == 16
    assert determine_zoom_for_radius(1000.0, 22.025) == 16
    assert get_meters_per_pixel(22.025, 16) > 2.0  # not the 1.2 m/px the old reticle default assumed

    for lat in (22.025, 28.6):
        for obs, cluster_r in ((1, 0.0), (3, 0.0), (6, 0.0), (15, 1200.0)):
            vp = calculate_incident_viewport(lat, 88.058, observation_count=obs, cluster_radius_meters=cluster_r)
            coverage = (vp.crop_size_px / 2.0) * vp.meters_per_pixel
            assert abs(vp.radius_meters - coverage) < 0.5
            assert vp.radius_meters == round(crop_coverage_radius_meters(lat, vp.zoom_level, vp.crop_size_px), 1)
            # The bbox must span the same ground radius as the pixels, not a larger one
            half_lat_m = (vp.bounding_box[2] - vp.bounding_box[0]) / 2.0 * 111320.0
            assert abs(half_lat_m - vp.radius_meters) < 5.0

        custom = calculate_incident_viewport(lat, 88.058, custom_radius_meters=1800.0)
        assert custom.radius_meters <= 1800.0  # never claim more ground than was fetched
        assert abs(custom.radius_meters - (custom.crop_size_px / 2.0) * custom.meters_per_pixel) < 0.5

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
        meters_per_pixel=2.214
    )

    assert reticle_img.size == (640, 640)
    assert verify_image_validity(reticle_img) is True
    # The reticle draws red crosshairs, so red channel should have peaks
    extrema = reticle_img.getextrema()
    assert extrema[0][1] > 200 # Red channel max should be bright red/white

def test_reticle_rings_drawn_for_every_declared_factor():
    """F-008: every declared ring factor must reach the frame on a 640px crop.

    Covers the tiers the report reproduced the loss on -- isolated event (zoom 17), medium
    cluster (zoom 16) -- and the large cluster (zoom 15) that happened to keep both rings.
    """
    for lat in (22.025, 28.6):
        for obs, cluster_r in ((1, 0.0), (6, 0.0), (15, 1200.0)):
            vp = calculate_incident_viewport(lat, 88.058, observation_count=obs, cluster_radius_meters=cluster_r)
            geom = plan_reticle_geometry(640, 640, vp.radius_meters, vp.meters_per_pixel)
            assert geom["skipped_rings"] == []
            assert [ring["factor"] for ring in geom["rings"]] == list(RING_FACTORS)

            base_img = Image.new("RGB", (640, 640), color=(30, 35, 40))
            out = draw_tactical_reticle(
                img=base_img, lat=lat, lon=88.058, incident_id="INC-TEST-RING",
                frp_mw=12.0, radius_meters=vp.radius_meters, meters_per_pixel=vp.meters_per_pixel
            )
            for ring in geom["rings"]:
                # rings scale with the frame: 40%/80% of the 320px frame radius
                assert ring["radius_px"] == int(round(ring["factor"] * 320))
                for px in ((320 + ring["radius_px"], 320), (320, 320 - ring["radius_px"])):
                    assert out.getpixel(px) != (30, 35, 40)  # a drawn ring pixel, not background
                # the ring's own label states its real ground distance, and 40/80% of the
                # declared viewport radius is exactly what the frame holds
                assert abs(ring["ground_meters"] - ring["radius_px"] * vp.meters_per_pixel) < 1e-9
                assert abs(ring["ground_meters"] - ring["factor"] * vp.radius_meters) <= vp.meters_per_pixel
            # the outermost ring must not be dropped -- it is the one the old guard discarded
            assert geom["rings"][-1]["radius_px"] == 256

def test_reticle_scale_bar_present_and_truthful():
    """F-010: the scale bar must render at Indian latitudes instead of vanishing silently."""
    for lat in (22.025, 28.6):
        # Medium tier (200m bar) and large tier (500m bar) -- the medium tier lost its bar entirely
        for obs, cluster_r in ((6, 0.0), (15, 1200.0)):
            vp = calculate_incident_viewport(lat, 88.058, observation_count=obs, cluster_radius_meters=cluster_r)
            geom = plan_reticle_geometry(640, 640, vp.radius_meters, vp.meters_per_pixel)
            bar = geom["scale_bar"]
            assert bar is not None
            # the labelled distance is what the drawn bar really spans on the ground (within one pixel)
            assert abs(bar["distance_meters"] - bar["length_px"] * vp.meters_per_pixel) <= vp.meters_per_pixel

            base_img = Image.new("RGB", (640, 640), color=(30, 35, 40))
            out = draw_tactical_reticle(
                img=base_img, lat=lat, lon=88.058, incident_id="INC-TEST-SCALE",
                frp_mw=12.0, radius_meters=vp.radius_meters, meters_per_pixel=vp.meters_per_pixel
            )
            drawn = [
                x for x in range(14, 14 + bar["length_px"])
                if out.getpixel((x, 628))[0] > 200 and out.getpixel((x, 628))[1] > 200
            ]
            assert len(drawn) >= bar["length_px"] - 4
            assert 14 + bar["length_px"] + 8 < 640 - 180  # label stays clear of the provider block

    # F-010 reproduction: radius 1000 at 2.214 m/px wants a 225px bar, which the old w//3 = 213
    # guard rejected -- the bar and its label were both dropped.
    repro = plan_reticle_geometry(640, 640, 1000.0, 2.214)
    assert repro["scale_bar"] is not None
    assert repro["scale_bar"]["distance_meters"] == 500.0

    # A frame too fine for the nominal distance shrinks the bar to the largest round distance
    # that fits, rather than dropping it.
    tight = plan_reticle_geometry(640, 640, 354.2, 0.2768)
    assert tight["scale_bar"] is not None
    assert tight["scale_bar"]["shrunk"] is True
    assert tight["scale_bar"]["distance_meters"] == 100.0
    assert tight["scale_bar"]["length_px"] <= 640 - 180 - 14 - 48

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
        assert img_meta["radius_meters"] <= 800.0  # F-009: the declared radius is the crop's real coverage
        assert img_meta["radius_meters"] == calculate_incident_viewport(
            inc.latitude, inc.longitude, observation_count=4, custom_radius_meters=800.0
        ).radius_meters
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

def _seed_imagery_incident(db, incident_id, **overrides):
    """Insert one throwaway incident for an imagery-service test.

    Mirrors the inline fixture in test_investigation_package_and_imagery_service, with overrides
    so the cluster tier -- and therefore the derived zoom -- can be pinned per test.
    """
    fields = dict(
        incident_code=f"FIREX-2026-{incident_id[-6:]}",
        status="ACTIVE",
        latitude=22.456,
        longitude=88.789,
        current_max_frp=32.5,
        current_mean_frp=28.0,
        observation_count=4,
        first_detected_at=datetime.utcnow() - timedelta(days=2),
        last_detected_at=datetime.utcnow()
    )
    fields.update(overrides)
    inc = Incident(id=incident_id, **fields)
    db.add(inc)
    db.commit()
    return inc

def _drop_imagery_incident(db, incident_id):
    """Remove the test incident and its ImageryRecord, as the existing test's cleanup does."""
    db.query(ImageryRecord).filter(ImageryRecord.incident_id == incident_id).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.id == incident_id).delete(synchronize_session=False)
    db.commit()

def _assert_cache_dir_is_isolated(cache_dir):
    """Fail rather than write renders into the served cache if conftest's redirection is off.

    conftest.py redirects imagery_service.CACHE_DIR into a throwaway directory (F-106). A test
    that hand-writes cache entries is exactly the test that must not be the one to discover that
    the redirection stopped working, so this pins it before anything is written.
    """
    source_cache_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "backend", "data", "imagery_cache")
    )
    assert os.path.abspath(cache_dir) != source_cache_dir, (
        f"imagery_service.CACHE_DIR is still the source-tree cache at {source_cache_dir!r}; "
        "this test would write into the served cache"
    )

def test_custom_radius_cache_is_reused_from_disk():
    """F-103: a second request at the same custom radius must be served from the cached render.

    Pre-fix this always missed and re-rendered: the reuse test was
    "custom_radius_meters is None or abs(metadata['radius_meters'] - custom_radius_meters) < 50",
    comparing the request (800 m) against the *derived* coverage stored in metadata -- 706.4 m at
    this latitude and zoom 16, a 93.6 m gap -- so the tolerance was false, the tiles were
    re-fetched from the provider and the crop was redrawn on every call. Asserted on the metadata
    the service really returns, and on the mtimes of the files it did or did not rewrite, not on
    a mock.
    """
    db = SessionLocal()
    inc_id = f"inc_test_cache_reuse_{int(datetime.utcnow().timestamp() * 1000)}"
    try:
        # observation_count=1: this incident's default (no custom radius) request derives a
        # different zoom from the 800 m one, which the third call below relies on.
        inc = _seed_imagery_incident(db, inc_id, observation_count=1)

        first = get_or_create_incident_imagery(
            incident_id=inc.id, db=db, custom_radius_meters=800.0, force_refresh=True
        )
        assert first["cached"] is False
        # The reported radius is the derived coverage, not the 800 m request -- which is exactly
        # the number the pre-fix reuse test compared the request against.
        assert first["radius_meters"] == calculate_incident_viewport(
            inc.latitude, inc.longitude, observation_count=1, custom_radius_meters=800.0
        ).radius_meters

        raw_mtime = os.path.getmtime(first["raw_image_path"])
        annotated_mtime = os.path.getmtime(first["annotated_image_path"])

        second = get_or_create_incident_imagery(incident_id=inc.id, db=db, custom_radius_meters=800.0)
        # The reuse the pre-fix check never granted: it compared this same 800 m request against
        # the derived 706.4 m coverage in metadata, a 93.6 m gap, and re-rendered every time.
        assert second["cached"] is True
        assert second["requested_radius_meters"] == 800.0
        assert abs(first["radius_meters"] - first["requested_radius_meters"]) >= 50.0
        # Nothing was re-rendered: same capture, same files, same reported viewport.
        assert second["captured_at"] == first["captured_at"]
        assert {k: v for k, v in second.items() if k != "cached"} == {
            k: v for k, v in first.items() if k != "cached"
        }
        assert os.path.getmtime(second["raw_image_path"]) == raw_mtime
        assert os.path.getmtime(second["annotated_image_path"]) == annotated_mtime

        # The cache is keyed on the request, so a *different* request must not be handed this
        # render -- pre-fix, asking for no custom radius at all accepted any cached entry.
        third = get_or_create_incident_imagery(incident_id=inc.id, db=db)
        assert third["cached"] is False
        assert third["requested_radius_meters"] is None
        assert third["zoom_level"] != second["zoom_level"]
        assert third["radius_meters"] != second["radius_meters"]
    finally:
        _drop_imagery_incident(db, inc_id)
        db.close()

def test_stale_renderer_version_is_a_cache_miss():
    """F-105: a cached render stamped with an old renderer version must be re-rendered.

    Pre-fix the cache check looked at file existence and radius only, so a render written by
    earlier reticle/annotation code stayed valid forever -- the renders in the served cache were
    all produced before the current drawing code and would be served as if current. The metadata
    here is hand-written into this test's isolated cache directory (never the served one): first
    stamped with the current version as a control, then with a deliberately old one, so the
    version is the only thing that differs between the hit and the miss.
    """
    db = SessionLocal()
    inc_id = f"inc_test_renderer_version_{int(datetime.utcnow().timestamp() * 1000)}"
    inc_cache_dir = None
    try:
        _assert_cache_dir_is_isolated(imagery_service.CACHE_DIR)
        inc = _seed_imagery_incident(db, inc_id)

        viewport = calculate_incident_viewport(
            inc.latitude,
            inc.longitude,
            observation_count=inc.observation_count,
            custom_radius_meters=800.0
        )
        inc_cache_dir = os.path.join(imagery_service.CACHE_DIR, inc.id)
        os.makedirs(inc_cache_dir, exist_ok=True)
        raw_path = os.path.join(inc_cache_dir, "raw.jpg")
        annotated_path = os.path.join(inc_cache_dir, "annotated.jpg")
        meta_path = os.path.join(inc_cache_dir, "metadata.json")
        Image.new("RGB", (640, 640), color=(28, 33, 40)).save(raw_path, "JPEG")

        def write_entry(renderer_version):
            """Write a cache entry valid for everything except its stamped renderer version."""
            Image.new("RGB", (640, 640), color=(30, 35, 40)).save(annotated_path, "JPEG")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "incident_id": inc.id,
                    "renderer_version": renderer_version,
                    "requested_radius_meters": viewport.requested_radius_meters,
                    "crop_size_px": viewport.crop_size_px,
                    "provider": "Test Stub",
                    "zoom_level": viewport.zoom_level,
                    "radius_meters": viewport.radius_meters,
                    "annotated_image_url": f"/api/imagery/cache/{inc.id}/annotated.jpg",
                    "captured_at": "2026-01-01T00:00:00",
                    "cached": False
                }, f, indent=2)

        # Control: stamped with the current version this entry IS reusable, so the files, the
        # radius and the zoom on their own cannot explain the miss that follows.
        write_entry(imagery_service.RENDERER_VERSION)
        control = get_or_create_incident_imagery(incident_id=inc.id, db=db, custom_radius_meters=800.0)
        assert control["cached"] is True

        # Deliberately old version -> the entry is stale and must be re-rendered.
        write_entry("0.0.0-pre-fix")
        stale = get_or_create_incident_imagery(incident_id=inc.id, db=db, custom_radius_meters=800.0)
        assert stale["cached"] is False
        assert stale["captured_at"] != "2026-01-01T00:00:00"  # a new render, not the stale file
        assert stale["renderer_version"] == imagery_service.RENDERER_VERSION
        with open(meta_path, "r", encoding="utf-8") as f:
            rewritten = json.load(f)
        assert rewritten["renderer_version"] == imagery_service.RENDERER_VERSION
        assert rewritten["captured_at"] == stale["captured_at"]

        # ...and what it wrote back is reusable again, so the cache heals on read.
        healed = get_or_create_incident_imagery(incident_id=inc.id, db=db, custom_radius_meters=800.0)
        assert healed["cached"] is True
        assert healed["captured_at"] == stale["captured_at"]
    finally:
        _drop_imagery_incident(db, inc_id)
        db.close()
        if inc_cache_dir:
            shutil.rmtree(inc_cache_dir, ignore_errors=True)

def test_requested_radius_clamp_and_declared_coverage_are_coherent():
    """F-104: the clamp bounds the REQUEST, while the declared radius is the crop's real coverage.

    The docstring used to claim that the returned radius "tracks the target but is never larger",
    which is false: a 5000 m request derives 5668.7 m, because a zoom level quantises the ground
    radius -- the same 640px crop covers exactly twice as much ground per zoom step down -- so the
    request can only be met by the nearest point of a geometric grid. The property the corrected
    docstring now states, and the one tested here, is that the declared radius is the (clamped)
    request snapped to that grid: within a factor 2/3..4/3 of it, and in every case exactly the
    ground the fetched crop covers. Understating that number would be the safety-relevant lie --
    it is the ground radius an operator is shown -- so it is never clamped to the request, while
    the clamp itself is applied to the request. Requests on both sides of the 250..5000 m clamp
    are covered, including the 5000 m one that used to escape it.
    """
    lat, lon = 22.025, 88.058

    for request, clamped_request in (
        (100.0, 250.0),    # below the clamp floor -> the request is raised to the floor
        (250.0, 250.0),    # the floor itself
        (800.0, 800.0),
        (3000.0, 3000.0),
        (5000.0, 5000.0),  # the ceiling itself, and the case the old docstring got wrong
        (25000.0, 5000.0)  # above the ceiling -> the request is lowered to the ceiling
    ):
        vp = calculate_incident_viewport(lat, lon, custom_radius_meters=request)
        assert vp.is_custom_radius is True
        # The clamp bounds the request, and the honoured request is reported alongside it.
        assert vp.requested_radius_meters == clamped_request
        # The declared radius is the coverage of the fetched crop, at every request.
        coverage = crop_coverage_radius_meters(lat, vp.zoom_level, vp.crop_size_px)
        assert abs(vp.radius_meters - coverage) < 0.5
        # ...and it is that clamped request snapped to the tile grid, so it stays within one
        # zoom step of it -- larger or smaller, neither direction being clamped away.
        assert (2.0 / 3.0) * vp.requested_radius_meters <= vp.radius_meters <= (4.0 / 3.0) * vp.requested_radius_meters

    # The 5000 m case the old docstring denied: the declared radius EXCEEDS the request, because
    # the nearest grid point above it is the whole zoom-13 crop.
    vp_ceiling = calculate_incident_viewport(lat, lon, custom_radius_meters=5000.0)
    assert vp_ceiling.radius_meters > vp_ceiling.requested_radius_meters == 5000.0
    assert vp_ceiling.zoom_level == 13
    assert abs(vp_ceiling.radius_meters - crop_coverage_radius_meters(lat, 13, vp_ceiling.crop_size_px)) < 0.5

    # The floor end: 250 m is the smallest request a caller can make, and the grid point nearest
    # it is finer still, so the declared radius sits below the clamp -- an honest 177.1 m of scene
    # rather than a promise of 250 m the pixels do not hold.
    vp_floor = calculate_incident_viewport(lat, lon, custom_radius_meters=100.0)
    assert vp_floor.requested_radius_meters == 250.0
    assert vp_floor.radius_meters < vp_floor.requested_radius_meters
    assert abs(vp_floor.radius_meters - crop_coverage_radius_meters(lat, vp_floor.zoom_level, vp_floor.crop_size_px)) < 0.5

    # A second call at the floor request reports the same clamp and the same grid point.
    vp_floor_again = calculate_incident_viewport(lat, lon, custom_radius_meters=250.0)
    assert vp_floor_again.requested_radius_meters == vp_floor.requested_radius_meters
    assert vp_floor_again.radius_meters == vp_floor.radius_meters
    assert vp_floor_again.zoom_level == vp_floor.zoom_level
