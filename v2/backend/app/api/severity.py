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


@router.get("/incident/{incident_id}", summary="Compute or retrieve multi-factor severity assessment")
def get_or_evaluate_severity(
    incident_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    F-056: the spec's route table (V2_LOGIC_SPECIFICATION.md:474) documents
    GET /api/severity/incident/{id} as "compute or retrieve"; only the retrieve-only
    /severity/{id} and the evaluate-only POST existed, so the documented URL 404'd.
    Retrieval is tried first and only a miss triggers evaluation, because
    evaluate_incident_severity persists an assessment and emits alerts as a side effect --
    recomputing on every poll would stack duplicate rows and re-fire alerts.

    Both branches answer in the persisted-assessment shape the sibling GET /severity/{id}
    returns, so a client reads the same keys whichever branch served it; the richer
    evaluation payload (alert detail, override reasons) stays on POST /severity/evaluate/{id}.
    """
    history = get_incident_severity_history(incident_id, db)
    if not history:
        try:
            evaluate_incident_severity(incident_id, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Severity evaluation failed: {str(e)}")
        history = get_incident_severity_history(incident_id, db)
    return history[0]


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
            detail=f"No severity assessment found for incident {incident_id}. Trigger GET /api/severity/incident/{incident_id} to compute one."
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
