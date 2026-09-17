"""
FIREX v2 Alert Management API Endpoints (Stage 7)
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.alerts.engine import (
    get_active_alerts,
    acknowledge_alert,
    resolve_alert,
    dismiss_alert,
    AlertNotFound,
    InvalidAlertTransition,
)

router = APIRouter(prefix="/alerts", tags=["Alert Engine"])

@router.get("", summary="List Active Operational Alerts")
def list_alerts(
    severity_level: Optional[str] = Query(None, description="Filter by HIGH or CRITICAL"),
    status: Optional[str] = Query(None, description="Filter by NEW, ACKNOWLEDGED, RESOLVED, DISMISSED"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Returns filtered alerts in reverse chronological order. Defaults to active alerts (NEW, ACKNOWLEDGED).
    """
    rows = get_active_alerts(db, severity_level=severity_level, status=status, limit=limit)
    return [
        {
            "id": r.id,
            "incident_id": r.incident_id,
            "severity_level": r.severity_level,
            "title": r.title,
            "description": r.description,
            "status": r.status,
            "created_at": r.created_at.isoformat()
        }
        for r in rows
    ]


def _alert_action_response(updated, message: str) -> Dict[str, Any]:
    return {
        "id": updated.id,
        "incident_id": updated.incident_id,
        "status": updated.status,
        "message": message,
    }


# Section 10's route table names this endpoint `/api/alerts/{id}/ack`. The
# implementation offered only `/acknowledge`, and since no client called either
# (the console has no alert-action wiring) the divergence went unnoticed rather
# than being caught by an integration test (F-014). Both spellings are served
# from one handler so the documented contract and the existing one cannot drift
# apart again.
@router.post("/{alert_id}/acknowledge", summary="Acknowledge Alert")
@router.post("/{alert_id}/ack", summary="Acknowledge Alert (spec alias)")
def ack_alert(
    alert_id: str,
    notes: Optional[str] = Body(None, embed=True, description="Operator confirmation notes"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Operator marks alert as acknowledged/dispatched."""
    try:
        updated = acknowledge_alert(alert_id, db, notes=notes)
        return _alert_action_response(updated, "Alert successfully acknowledged by operator.")
    except AlertNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidAlertTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{alert_id}/resolve", summary="Resolve Alert")
def res_alert(
    alert_id: str,
    notes: Optional[str] = Body(None, embed=True, description="Resolution notes"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Marks alert as resolved."""
    try:
        updated = resolve_alert(alert_id, db, notes=notes)
        return _alert_action_response(updated, "Alert marked as resolved.")
    except AlertNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidAlertTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{alert_id}/dismiss", summary="Dismiss Alert (False Alarm / Controlled Burn)")
def dis_alert(
    alert_id: str,
    reason: str = Body("False alarm or controlled burn", embed=True),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Marks alert as dismissed."""
    try:
        updated = dismiss_alert(alert_id, db, reason=reason)
        return _alert_action_response(updated, "Alert dismissed.")
    except AlertNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidAlertTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
