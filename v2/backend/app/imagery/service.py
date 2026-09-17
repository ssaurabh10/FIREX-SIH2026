"""
FIREX v2 Imagery Service
Orchestrates optical satellite tile retrieval, tactical reticle rendering, disk caching, and database persistence.
"""
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.storage.models import Incident, ImageryRecord
from app.imagery.viewport import calculate_incident_viewport, ViewportSpec
from app.imagery.provider import get_stitched_crop, verify_image_validity
from app.imagery.reticle import draw_tactical_reticle
from app.core.logging import logger

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "imagery_cache"))

# F-105: version of the renderer that produced a cached annotated.jpg. Bump it whenever the
# pixels of an existing render would change -- the reticle/annotation drawing, the geometry fed
# into it, or the cached file format. The cache key below already compares the rendering INPUTS a
# caller can vary (requested radius, zoom, crop size), but no input can reveal that the renderer
# itself changed between two calls that asked for the same thing: a render written by the previous
# drawing code is indistinguishable from a current one on the input key alone, so all 631 renders
# in the served cache -- every one of them written before the reticle and radius fixes -- would
# stay valid forever. The version is the one thing that has to be stamped at write time and
# compared at read time, which makes the read side self-healing: a stale entry is a miss and the
# next request re-renders it. Nothing walks or deletes the cache.
RENDERER_VERSION = 2

# F-103: how close two *requests* must be to name the same cache entry, in metres. The comparison
# is request-to-request now; it used to be request-to-derived-render, which is why the old 50 m
# window was both necessary and useless (see _cache_entry_is_reusable). Half a metre only absorbs
# float round-tripping through JSON -- far below the tile grid, which quantises the render to
# steps of hundreds of metres, so two requests this close cannot produce different pixels.
REQUEST_MATCH_TOLERANCE_M = 0.5

def _cache_entry_is_reusable(cached_meta: Dict[str, Any], viewport: ViewportSpec) -> bool:
    """
    Is this cached entry the render the current request would produce? (F-103, F-105)

    The cache is keyed on the REQUEST, not on the rendering the request derives. The old check
    compared the requested radius against metadata["radius_meters"], which holds the *derived*
    coverage from calculate_incident_viewport: an 800 m request derives 706.4 m at lat 22.456 /
    zoom 16, a 93.6 m gap, so `abs(derived - requested) < 50` was false and the incident was
    re-fetched from the tile provider on every single call. The identity that decides reuse is:
      * renderer version (F-105) -- same request, different drawing code;
      * zoom level -- a request that derives another zoom is another crop, even when the radius
        request is identical (an explicit zoom override changes this without changing radius);
      * the requested radius (ViewportSpec.requested_radius_meters: the clamped custom radius,
        or None when the caller asked for none) -- None matches None only, so a default view is
        never served a custom-radiused render, or the reverse;
      * crop size in pixels.
    A missing key (a pre-F-105 entry) reads as None and never equals the current version, so such
    an entry is a miss rather than something that has to be migrated.

    One rendering input is deliberately not part of the key: the incident's FRP, which the reticle
    prints into its HUD. It changes on every ingestion, so folding it in would re-fetch tiles and
    redraw on each observation rather than per request; the version above is what covers a change
    in how that figure is drawn.
    """
    if cached_meta.get("renderer_version") != RENDERER_VERSION:
        return False
    if cached_meta.get("zoom_level") != viewport.zoom_level:
        return False
    if cached_meta.get("crop_size_px") != viewport.crop_size_px:
        return False

    cached_request = cached_meta.get("requested_radius_meters")
    requested = viewport.requested_radius_meters
    if cached_request is None or requested is None:
        return cached_request is None and requested is None
    return abs(float(cached_request) - float(requested)) < REQUEST_MATCH_TOLERANCE_M

def get_or_create_incident_imagery(
    incident_id: str,
    db: Session,
    custom_radius_meters: Optional[float] = None,
    zoom_level: Optional[int] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Retrieves or generates high-resolution optical satellite context for an incident.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return {"error": "Incident not found", "incident_id": incident_id}

    # Ensure cache directory exists
    inc_cache_dir = os.path.join(CACHE_DIR, incident.id)
    os.makedirs(inc_cache_dir, exist_ok=True)

    raw_path = os.path.join(inc_cache_dir, "raw.jpg")
    annotated_path = os.path.join(inc_cache_dir, "annotated.jpg")
    meta_path = os.path.join(inc_cache_dir, "metadata.json")

    # 1. Calculate Viewport & Ground Radius
    viewport: ViewportSpec = calculate_incident_viewport(
        lat=incident.latitude,
        lon=incident.longitude,
        observation_count=incident.observation_count or 1,
        custom_radius_meters=custom_radius_meters,
        zoom_level=zoom_level
    )

    # 2. Check Disk Cache (unless force_refresh requested). An entry is reusable only when it was
    # rendered for this exact request by the current renderer (F-103/F-105); anything else is a
    # miss and falls through to the tile provider, which also re-stamps the entry below.
    if not force_refresh and os.path.exists(raw_path) and os.path.exists(annotated_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                cached_meta = json.load(f)
            if _cache_entry_is_reusable(cached_meta, viewport):
                cached_meta["cached"] = True
                return cached_meta
        except Exception:
            pass

    # 3. Fetch Stitched Optical Scene
    raw_img, provider_name = get_stitched_crop(
        lat=incident.latitude,
        lon=incident.longitude,
        zoom=viewport.zoom_level,
        crop_size=viewport.crop_size_px
    )

    # 4. Draw Tactical Hotspot Reticle
    frp_mw = float(incident.current_max_frp or incident.current_mean_frp or 0.0)
    annotated_img = draw_tactical_reticle(
        img=raw_img,
        lat=incident.latitude,
        lon=incident.longitude,
        incident_id=incident.id,
        frp_mw=frp_mw,
        radius_meters=viewport.radius_meters,
        provider=provider_name,
        meters_per_pixel=viewport.meters_per_pixel
    )

    # 5. Verify image validity
    is_valid = verify_image_validity(raw_img)

    # 6. Save Crops to Disk
    raw_img.save(raw_path, "JPEG", quality=90)
    annotated_img.save(annotated_path, "JPEG", quality=92)

    raw_rel_url = f"/api/imagery/cache/{incident.id}/raw.jpg"
    annotated_rel_url = f"/api/imagery/cache/{incident.id}/annotated.jpg"

    metadata = {
        "incident_id": incident.id,
        # F-103/F-105: the request identity and the renderer that produced this file -- these are
        # what a later call compares against, so an entry is reusable only for the same request
        # and is never served once the drawing code behind it has changed.
        "renderer_version": RENDERER_VERSION,
        "requested_radius_meters": viewport.requested_radius_meters,
        "crop_size_px": viewport.crop_size_px,
        "provider": provider_name,
        "zoom_level": viewport.zoom_level,
        "radius_meters": viewport.radius_meters,
        "scale_label": viewport.scale_label,
        "is_custom_radius": viewport.is_custom_radius,
        "center_coordinates": {"lat": viewport.center_lat, "lon": viewport.center_lon},
        "bounding_box": viewport.bounding_box,
        "dimensions": [viewport.crop_size_px, viewport.crop_size_px],
        "image_valid": is_valid,
        "raw_image_url": raw_rel_url,
        "annotated_image_url": annotated_rel_url,
        "raw_image_path": raw_path,
        "annotated_image_path": annotated_path,
        "captured_at": datetime.utcnow().isoformat(),
        "cached": False
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # 7. Persist or Update ImageryRecord in Database
    existing_rec = db.query(ImageryRecord).filter(ImageryRecord.incident_id == incident.id).first()
    if not existing_rec:
        new_rec = ImageryRecord(
            incident_id=incident.id,
            provider=provider_name,
            zoom_level=viewport.zoom_level,
            image_raw_url=raw_rel_url,
            image_annotated_url=annotated_rel_url
        )
        db.add(new_rec)
    else:
        existing_rec.provider = provider_name
        existing_rec.zoom_level = viewport.zoom_level
        existing_rec.image_raw_url = raw_rel_url
        existing_rec.image_annotated_url = annotated_rel_url

    db.commit()

    return metadata
