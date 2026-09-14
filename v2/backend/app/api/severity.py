"""
FIREX v2 Severity Evaluation API Endpoints (Stage 7)
"""
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.severity.service import evaluate_incident_severity, get_incident_severity_history

router = APIRouter(prefix="/severity", tags=["Severity Engine"])

@router.post("/evaluate/{incident_id}", summary="Evaluate Operational Incident Severity")
def evaluate_severity(
    incident_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Evaluates operational severity score (0-100), level (LOW, MEDIUM, HIGH, CRITICAL),
    and confidence. Evaluates operational overrides and triggers alerts if eligible.
    """
    try:
        return evaluate_incident_severity(incident_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Severity evaluation failed: {str(e)}")


@router.get("/{incident_id}", summary="Get Latest Severity Assessment")
def get_latest_severity(
    incident_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retrieves the most recent severity assessment for the incident.
    """
    history = get_incident_severity_history(incident_id, db)
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No severity assessment found for incident {incident_id}. Trigger POST /api/severity/evaluate/{incident_id} first."
        )
    return history[0]


@router.get("/{incident_id}/history", summary="Get Historical Severity Progression")
def get_severity_history(
    incident_id: str,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Returns full timeline of severity assessments for the incident.
    """
    return get_incident_severity_history(incident_id, db)
