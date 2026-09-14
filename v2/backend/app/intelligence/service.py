"""
FIREX v2 AI Investigation Orchestrator Service
Integrates Stage 5 visual packages with Stage 6 multimodal AI intelligence and DB persistence.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.storage.models import Incident, AIInvestigation, IncidentEvent
from app.imagery.package import build_investigation_package
from app.intelligence.vision import analyze_incident_scene
from app.intelligence.provider import BaseAIProvider
from app.intelligence.schemas import AIInvestigationReport

logger = logging.getLogger(__name__)

def run_incident_investigation(
    incident_id: str,
    db: Session,
    custom_radius_meters: Optional[float] = None,
    force_reinvestigate: bool = False,
    provider: Optional[BaseAIProvider] = None
) -> Dict[str, Any]:
    """
    Executes an end-to-end multimodal AI investigation for a candidate incident.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError(f"Incident {incident_id} not found in database.")

    # 1. Check existing investigation if not forced
    if not force_reinvestigate:
        existing = db.query(AIInvestigation).filter(
            AIInvestigation.incident_id == incident_id
        ).order_by(AIInvestigation.created_at.desc()).first()
        if existing:
            logger.info(f"[Service] Returning existing AI investigation for incident {incident_id}")
            return {
                "incident_id": incident_id,
                "incident_code": incident.incident_code,
                "investigation_id": existing.id,
                "status": "CACHED",
                "classification": existing.classification,
                "confidence": existing.confidence,
                "uncertainty": existing.uncertainty,
                "reasoning_summary": existing.reasoning,
                "evidence_points": existing.evidence_points or {},
                "model_used": existing.model_name,
                "investigated_at": existing.created_at.isoformat()
            }

    # 2. Build or fetch Stage 5 Investigation Package
    package = build_investigation_package(
        incident_id,
        db,
        custom_radius_meters=custom_radius_meters
    )

    # 3. Analyze scene through configured AI Provider
    report: AIInvestigationReport = analyze_incident_scene(package, provider=provider)

    # 4. Map uncertainty tier
    if report.confidence >= 80.0:
        uncertainty_level = "LOW"
    elif report.confidence >= 60.0:
        uncertainty_level = "MEDIUM"
    else:
        uncertainty_level = "HIGH"

    evidence_payload = {
        "visual_evidence": report.visual_evidence,
        "contextual_evidence": report.contextual_evidence,
        "uncertainties": report.uncertainties,
        "alternative": report.alternative.model_dump(),
        "image_quality": report.image_quality.model_dump(),
        "needs_reinvestigation": report.needs_reinvestigation,
        "reasoning_details": report.reasoning_details,
        "prompt_version": report.prompt_version,
        "key_used": report.key_used,
        "observation_count": incident.observation_count or 1,
        "max_frp": incident.current_max_frp or 0.0
    }

    # 5. Persist AIInvestigation record
    investigation_row = AIInvestigation(
        incident_id=incident.id,
        model_name=report.model_used or "unknown",
        classification=report.classification,
        confidence=report.confidence,
        uncertainty=uncertainty_level,
        reasoning=report.reasoning_summary,
        evidence_points=evidence_payload,
        created_at=datetime.utcnow()
    )
    db.add(investigation_row)

    # 6. Update Incident state machine
    incident.classification = report.classification
    incident.classification_confidence = report.confidence
    if incident.status in ["NEW", "INVESTIGATING"]:
        incident.status = "ACTIVE"
    incident.updated_at = datetime.utcnow()

    # 7. Audit trail logging
    event = IncidentEvent(
        incident_id=incident.id,
        event_type="INVESTIGATION_COMPLETED",
        payload={
            "description": f"AI classified as '{report.classification}' ({report.confidence:.1f}%) via {report.model_used}",
            "classification": report.classification,
            "confidence": report.confidence,
            "uncertainty": uncertainty_level,
            "alternative": report.alternative.classification,
            "model": report.model_used
        },
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(investigation_row)

    logger.info(
        f"[Service] Investigation completed for {incident.incident_code}: "
        f"{report.classification} ({report.confidence:.1f}%)"
    )

    return {
        "incident_id": incident.id,
        "incident_code": incident.incident_code,
        "investigation_id": investigation_row.id,
        "status": "COMPLETED",
        "classification": investigation_row.classification,
        "confidence": investigation_row.confidence,
        "uncertainty": investigation_row.uncertainty,
        "reasoning_summary": investigation_row.reasoning,
        "evidence_points": investigation_row.evidence_points,
        "model_used": investigation_row.model_name,
        "investigated_at": investigation_row.created_at.isoformat()
    }


def get_incident_investigations(incident_id: str, db: Session) -> List[Dict[str, Any]]:
    """
    Retrieves full chronological investigation history for an incident.
    """
    rows = db.query(AIInvestigation).filter(
        AIInvestigation.incident_id == incident_id
    ).order_by(AIInvestigation.created_at.desc()).all()

    return [
        {
            "investigation_id": row.id,
            "incident_id": row.incident_id,
            "model_name": row.model_name,
            "classification": row.classification,
            "confidence": row.confidence,
            "uncertainty": row.uncertainty,
            "reasoning_summary": row.reasoning,
            "evidence_points": row.evidence_points or {},
            "investigated_at": row.created_at.isoformat()
        }
        for row in rows
    ]
