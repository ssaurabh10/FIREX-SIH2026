"""
FIREX v2 Selection Engine
Evaluates and ranks incident candidates for investigation.
Combines Incident state, GIS context, Stage 4 behavior features, and priority scoring.
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.storage.models import Incident, IndustrialAsset
from app.selection.scoring import compute_investigation_priority
from app.behavior.baseline import get_or_create_location_baseline, get_or_create_facility_baseline
from app.behavior.persistence import calculate_persistence_score
from app.behavior.anomaly import evaluate_historical_anomaly
from app.core.logging import logger

def evaluate_incident_selection(incident_id: str, db: Session) -> Dict[str, Any]:
    """
    Evaluates selection priority for a single incident.
    Fetches its historical baseline, persistence, and confidence to calculate investigation priority.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return {"error": "Incident not found", "incident_id": incident_id}

    # 1. FRP intensity
    frp_val = float(incident.current_max_frp or incident.current_mean_frp or 0.0)

    # 2. Historical baseline lookup (Facility-level if associated, else Location-level)
    baseline_data: Optional[Dict[str, Any]] = None
    has_history = False
    hist_median = 0.0

    if incident.nearest_asset_id:
        baseline_data = get_or_create_facility_baseline(incident.nearest_asset_id, db, window_days=90)
    else:
        baseline_data = get_or_create_location_baseline(incident.latitude, incident.longitude, db, window_days=90)

    if baseline_data and baseline_data.get("observation_count", 0) > 0:
        has_history = True
        hist_median = float(baseline_data.get("median_frp", 0.0) or 0.0)

    # 3. Persistence score
    obs_count = incident.observation_count or 1
    is_pers = (incident.status == "PERSISTENT")
    persistence_score = 75.0 if is_pers else min(100.0, obs_count * 15.0)

    # 4. Historical anomaly score
    anomaly_score = 0.0
    if has_history:
        eval_res = evaluate_historical_anomaly(frp_val, hist_median, persistence_score)
        anomaly_score = float(eval_res.get("anomaly_score", 0.0))

    # 5. FIRMS confidence approximation (default 80 if aggregate)
    confidence_val = 80.0

    priority_result = compute_investigation_priority(
        frp_mw=frp_val,
        confidence_score=confidence_val,
        persistence_score=persistence_score,
        anomaly_score=anomaly_score,
        has_history=has_history,
        historical_median_frp=hist_median
    )

    # Determine selection recommendation
    priority = priority_result["investigation_priority"]
    should_investigate = priority >= 40.0 or priority_result["is_override_triggered"]

    # Update incident investigation_priority field in DB
    incident.investigation_priority = priority
    db.commit()

    facility_name = None
    dist_m = None
    if incident.nearest_asset_id:
        asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == incident.nearest_asset_id).first()
        if asset:
            facility_name = asset.name
        if incident.distance_to_asset_km is not None:
            dist_m = round(incident.distance_to_asset_km * 1000.0, 1)

    return {
        "incident_id": incident.id,
        "incident_code": incident.incident_code or incident.id,
        "status": incident.status,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "primary_facility_name": facility_name,
        "primary_facility_distance_m": dist_m,
        "selection_priority": priority,
        "should_investigate": should_investigate,
        "priority_details": priority_result,
        "historical_context": {
            "has_history": has_history,
            "historical_median_frp": hist_median,
            "baseline_label": baseline_data.get("history_reliability_label", "NONE") if baseline_data else "NONE"
        }
    }

def select_investigation_candidates(
    db: Session,
    min_priority: float = 35.0,
    limit: int = 25,
    status: Optional[str] = "ACTIVE"
) -> List[Dict[str, Any]]:
    """
    Ranks and returns incident candidates for deep AI investigation.
    Prioritizes highest investigation_priority score and override triggers.
    """
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    else:
        query = query.filter(Incident.status != "RESOLVED")

    incidents = query.order_by(Incident.updated_at.desc()).limit(100).all()

    candidates: List[Dict[str, Any]] = []
    for inc in incidents:
        eval_res = evaluate_incident_selection(inc.id, db)
        if "error" in eval_res:
            continue

        priority = eval_res["selection_priority"]
        is_override = eval_res["priority_details"]["is_override_triggered"]

        if priority >= min_priority or is_override:
            candidates.append(eval_res)

    # Sort descending by selection priority
    candidates.sort(key=lambda x: x["selection_priority"], reverse=True)
    return candidates[:limit]
