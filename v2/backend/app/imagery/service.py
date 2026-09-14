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

    # 2. Check Disk Cache (unless custom radius changed or force_refresh requested)
    if not force_refresh and os.path.exists(raw_path) and os.path.exists(annotated_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                cached_meta = json.load(f)
            # If custom radius matches or wasn't specified, use cache
            if custom_radius_meters is None or abs(cached_meta.get("radius_meters", 0) - custom_radius_meters) < 50:
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
