"""
FIREX v2 Severity Evaluation Orchestration Service
Coordinates data ingestion from Stages 1-6, executes dual-model severity scoring,
updates incident lifecycle state, persists SeverityAssessment records, and triggers alerts.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.storage.models import Incident, IndustrialAsset, AIInvestigation, SeverityAssessment, IncidentEvent
from app.behavior.baseline import get_or_create_facility_baseline, get_or_create_location_baseline
from app.severity.scoring import compute_incident_severity
from app.severity.state_machine import determine_lifecycle_state
from app.alerts.engine import evaluate_and_emit_alert

logger = logging.getLogger(__name__)

def evaluate_incident_severity(incident_id: str, db: Session) -> Dict[str, Any]:
    """
    Evaluates comprehensive operational severity for an incident after AI investigation.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError(f"Incident {incident_id} not found.")

    # 1. Fetch latest AI investigation
    latest_inv = db.query(AIInvestigation).filter(
        AIInvestigation.incident_id == incident.id
    ).order_by(AIInvestigation.created_at.desc()).first()

    classification = latest_inv.classification if latest_inv else (incident.classification or "uncertain")
    ai_confidence = latest_inv.confidence if latest_inv else (incident.classification_confidence or 50.0)

    # 2. Fetch nearest asset details
    asset = None
    if incident.nearest_asset_id:
        asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == incident.nearest_asset_id).first()

    facility_type = asset.facility_type if asset else None
    hazard_cat = asset.hazard_category if asset else None
    distance_m = round(incident.distance_to_asset_km * 1000.0, 1) if incident.distance_to_asset_km is not None else None

    # 3. Fetch 365-day historical baseline
    if incident.nearest_asset_id:
        base_dict = get_or_create_facility_baseline(incident.nearest_asset_id, db)
    else:
        base_dict = get_or_create_location_baseline(incident.latitude, incident.longitude, db)

    median_frp = base_dict.get("median_frp", 0.0)
    p95_frp = base_dict.get("p95_frp", 0.0)
    history_rel = base_dict.get("history_reliability", 0.0)
    is_persistent = base_dict.get("is_persistent", False)
    is_routine_flare = base_dict.get("is_routine_flare", False)

    # 4. Compute severity and confidence
    firms_confidence = incident.severity_confidence or 75.0  # default reasonable FIRMS confidence
    assessment = compute_incident_severity(
        frp_mw=incident.current_max_frp,
        firms_confidence=firms_confidence,
        classification=classification,
        ai_confidence=ai_confidence,
        median_frp=median_frp,
        p95_frp=p95_frp,
        history_reliability=history_rel,
        facility_distance_m=distance_m,
        facility_type=facility_type,
        hazard_category=hazard_cat,
        is_inside_facility=incident.is_inside_facility,
        is_protected_area=False,
        is_routine_flare=is_routine_flare
    )

    # 5. Evaluate state machine transition
    hours_since_last = 0.0
    if incident.last_detected_at:
        hours_since_last = max(0.0, (datetime.utcnow() - incident.last_detected_at).total_seconds() / 3600.0)

    next_status = determine_lifecycle_state(
        current_status=incident.status,
        severity_level=assessment["severity_level"],
        is_persistent=is_persistent,
        hours_since_last_seen=hours_since_last
    )

    # 6. Update Incident in DB
    incident.severity_score = assessment["severity_score"]
    incident.severity_level = assessment["severity_level"]
    incident.severity_confidence = assessment["severity_confidence"]
    incident.status = next_status
    incident.updated_at = datetime.utcnow()

    # 7. Persist SeverityAssessment record
    assessment_row = SeverityAssessment(
        incident_id=incident.id,
        score=assessment["severity_score"],
        level=assessment["severity_level"],
        confidence=assessment["severity_confidence"],
        factors=assessment["factors"],
        created_at=datetime.utcnow()
    )
    db.add(assessment_row)

    # 8. Trigger Alert Engine
    alert_record = evaluate_and_emit_alert(incident, assessment, db)

    # 9. Audit event
    event = IncidentEvent(
        incident_id=incident.id,
        event_type="SEVERITY_ASSESSED",
        payload={
            "score": assessment["severity_score"],
            "level": assessment["severity_level"],
            "confidence": assessment["severity_confidence"],
            "model_used": assessment["model_used"],
            "alert_emitted": alert_record is not None,
            "overrides": assessment["override_reasons"]
        },
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(assessment_row)

    logger.info(
        f"[Severity] Assessment complete for {incident.incident_code}: "
        f"{assessment['severity_level']} ({assessment['severity_score']}/100, "
        f"Conf: {assessment['severity_confidence']}%)"
    )

    return {
        "incident_id": incident.id,
        "incident_code": incident.incident_code,
        "assessment_id": assessment_row.id,
        "severity_score": assessment["severity_score"],
        "severity_level": assessment["severity_level"],
        "severity_confidence": assessment["severity_confidence"],
        "lifecycle_status": next_status,
        "model_used": assessment["model_used"],
        "factors": assessment["factors"],
        "override_reasons": assessment["override_reasons"],
        "needs_reinvestigation": assessment["needs_reinvestigation"],
        "alert": {
            "alert_id": alert_record.id,
            "status": alert_record.status,
            "title": alert_record.title
        } if alert_record else None,
        "assessed_at": assessment_row.created_at.isoformat()
    }


def get_incident_severity_history(incident_id: str, db: Session) -> List[Dict[str, Any]]:
    """Retrieves all past severity assessments for an incident."""
    rows = db.query(SeverityAssessment).filter(
        SeverityAssessment.incident_id == incident_id
    ).order_by(SeverityAssessment.created_at.desc()).all()

    return [
        {
            "assessment_id": r.id,
            "incident_id": r.incident_id,
            "score": r.score,
            "level": r.level,
            "confidence": r.confidence,
            "factors": r.factors or {},
            "assessed_at": r.created_at.isoformat()
        }
        for r in rows
    ]
