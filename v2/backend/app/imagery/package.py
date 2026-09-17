"""
FIREX v2 Deterministic Investigation Package Builder
Implements Blueprint Stage 5 'Done when' criteria:
Produces a unified investigation package containing:
- Incident Data
- GIS Context
- Historical Features
- Visual Context
- Provenance Metadata
"""
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.storage.models import Incident, IndustrialAsset
from app.selection.engine import evaluate_incident_selection
from app.behavior.baseline import get_or_create_location_baseline, get_or_create_facility_baseline
from app.imagery.service import get_or_create_incident_imagery
from app.gis.mining_basins import get_mining_basin_metadata

def build_investigation_package(
    incident_id: str,
    db: Session,
    custom_radius_meters: Optional[float] = None,
    zoom_level: Optional[int] = None,
    force_refresh_imagery: bool = False
) -> Dict[str, Any]:
    """
    Assembles the complete deterministic investigation package for an incident.
    Prepares all intelligence inputs needed for Stage 6 Multimodal AI analysis.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return {"error": "Incident not found", "incident_id": incident_id}

    # 1. Incident Data
    is_pers = (incident.status == "PERSISTENT")
    incident_data = {
        "id": incident.id,
        "incident_code": incident.incident_code or incident.id,
        "status": incident.status,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "max_frp_mw": incident.current_max_frp,
        "current_mean_frp_mw": incident.current_mean_frp,
        "observation_count": incident.observation_count,
        "is_persistent": is_pers,
        "first_seen_at": incident.first_detected_at.isoformat() if incident.first_detected_at else None,
        "last_seen_at": incident.last_detected_at.isoformat() if incident.last_detected_at else None
    }

    # 2. GIS Context
    facility_dist_m = round(incident.distance_to_asset_km * 1000.0, 1) if incident.distance_to_asset_km is not None else None
    gis_context: Dict[str, Any] = {
        "facility_id": incident.nearest_asset_id,
        "facility_name": None,
        "facility_distance_m": facility_dist_m,
        "facility_type": None,
        "industry": None,
        "hazard_category": None
    }
    if incident.nearest_asset_id:
        facility = db.query(IndustrialAsset).filter(IndustrialAsset.id == incident.nearest_asset_id).first()
        if facility:
            gis_context.update({
                "facility_name": facility.name,
                "facility_type": facility.facility_type,
                "industry": facility.industry,
                "hazard_category": facility.hazard_category,
                "state": facility.state,
                "district": facility.district
            })

    mining_info = get_mining_basin_metadata(incident.latitude, incident.longitude)
    if mining_info:
        gis_context["mining_basin"] = mining_info

    # 3. Historical Features
    if incident.nearest_asset_id:
        hist_baseline = get_or_create_facility_baseline(incident.nearest_asset_id, db, window_days=90)
    else:
        hist_baseline = get_or_create_location_baseline(incident.latitude, incident.longitude, db, window_days=90)

    # 4. Selection Priority Context
    selection_eval = evaluate_incident_selection(incident.id, db)

    # 5. Visual Context
    visual_context = get_or_create_incident_imagery(
        incident_id=incident.id,
        db=db,
        custom_radius_meters=custom_radius_meters,
        zoom_level=zoom_level,
        force_refresh=force_refresh_imagery
    )

    # Compute surge multiplier over local median
    hist_median = hist_baseline.get("median_frp", 0.0) or 1.0
    surge_mult = round(float(incident.current_max_frp or 0.0) / max(1.0, float(hist_median)), 2)

    is_routine_flare_val = False if mining_info else hist_baseline.get("is_routine_flare", False)
    site_hint_val = "COAL_MINING_BASIN" if mining_info else hist_baseline.get("site_classification_hint", "EPISODIC_THERMAL")

    # 6. Assemble Full Investigation Package
    package = {
        "incident": incident_data,
        "gis_context": gis_context,
        "historical_features": {
            "observation_count_90d": hist_baseline.get("observation_count", 0),
            "active_days_365d": hist_baseline.get("active_days_365d", hist_baseline.get("active_days", 0)),
            "median_frp_mw": hist_baseline.get("median_frp", 0.0),
            "p90_frp_mw": hist_baseline.get("p90_frp", 0.0),
            "p95_frp_mw": hist_baseline.get("p95_frp", 0.0),
            "max_frp_mw": hist_baseline.get("max_frp", 0.0),
            "night_ratio": hist_baseline.get("night_ratio", 0.0),
            "surge_multiplier": surge_mult,
            "is_routine_flare": is_routine_flare_val,
            "site_classification_hint": site_hint_val,
            "is_mining_basin": bool(mining_info),
            "history_reliability_label": hist_baseline.get("history_reliability_label", "NONE"),
            "is_persistent": hist_baseline.get("is_persistent", False)
        },
        "selection_context": {
            "investigation_priority": selection_eval.get("selection_priority", 0.0),
            "should_investigate": selection_eval.get("should_investigate", False),
            "is_override_triggered": selection_eval.get("priority_details", {}).get("is_override_triggered", False),
            "override_reasons": selection_eval.get("priority_details", {}).get("override_reasons", [])
        },
        "visual_context": {
            "provider": visual_context.get("provider"),
            "zoom_level": visual_context.get("zoom_level"),
            "radius_meters": visual_context.get("radius_meters"),
            "scale_label": visual_context.get("scale_label"),
            "is_custom_radius": visual_context.get("is_custom_radius", False),
            "bounding_box": visual_context.get("bounding_box"),
            "dimensions": visual_context.get("dimensions"),
            "image_valid": visual_context.get("image_valid", False),
            "raw_image_url": visual_context.get("raw_image_url"),
            "annotated_image_url": visual_context.get("annotated_image_url")
        },
        "provenance_metadata": {
            "pipeline_stage": "STAGE_5_SELECTION_AND_VISUAL_CONTEXT",
            "version": "2.0.0",
            "generated_at": datetime.utcnow().isoformat(),
            "status": "READY_FOR_AI_INVESTIGATION"
        }
    }

    return package
