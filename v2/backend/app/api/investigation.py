"""
FIREX v2 AI Investigation API Endpoints (Stage 6)
"""
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.intelligence.service import run_incident_investigation, get_incident_investigations

router = APIRouter(prefix="/investigation", tags=["AI Investigation"])

@router.post("/{incident_id}", summary="Run AI Multimodal Investigation")
def trigger_investigation(
    incident_id: str,
    custom_radius_meters: Optional[float] = Query(None, ge=100.0, le=10000.0, description="Optional custom radius in meters"),
    force: bool = Query(False, description="Force fresh analysis even if previous report exists"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Triggers multimodal AI investigation:
    1. Fetches or builds optical satellite crop + GIS context + historical baseline.
    2. Runs configured multimodal model with reasoning preservation and key failover.
    3. Updates incident classification state and logs audit trail.
    """
    try:
        result = run_incident_investigation(
            incident_id=incident_id,
            db=db,
            custom_radius_meters=custom_radius_meters,
            force_reinvestigate=force
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Investigation failed: {str(e)}")


@router.get("/{incident_id}", summary="Get Latest AI Investigation Report")
def get_latest_investigation(
    incident_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retrieves the most recent AI investigation report and synthesized evidence for an incident.
    """
    history = get_incident_investigations(incident_id, db)
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No investigation report found for incident {incident_id}. Trigger POST /api/investigation/{incident_id} first."
        )
    return history[0]


@router.get("/{incident_id}/history", summary="Get Chronological Investigation History")
def get_investigation_history(
    incident_id: str,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Returns all AI investigation runs for the incident in reverse chronological order.
    """
    return get_incident_investigations(incident_id, db)


@router.post("/{incident_id}/reinvestigate", summary="Force Re-investigation")
def reinvestigate_incident(
    incident_id: str,
    custom_radius_meters: Optional[float] = Query(None, ge=100.0, le=10000.0, description="Optional new viewport radius"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Forces a fresh AI investigation run (e.g. after satellite imagery refresh or operator review).
    """
    try:
        result = run_incident_investigation(
            incident_id=incident_id,
            db=db,
            custom_radius_meters=custom_radius_meters,
            force_reinvestigate=True
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Re-investigation failed: {str(e)}")
