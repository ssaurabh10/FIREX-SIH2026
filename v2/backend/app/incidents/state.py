"""
Incident State Machine & Audit Timeline Engine
Manages transitions:
NEW -> INVESTIGATING -> ACTIVE -> PERSISTENT / ESCALATED -> SUBSIDING -> RESOLVED
Records immutable timeline entries in incident_events.
"""
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.storage.models import Incident, IncidentEvent
from app.core.logging import logger

VALID_TRANSITIONS = {
    "NEW": ["INVESTIGATING", "ACTIVE", "RESOLVED"],
    "INVESTIGATING": ["ACTIVE", "PERSISTENT", "RESOLVED"],
    "ACTIVE": ["INVESTIGATING", "PERSISTENT", "SUBSIDING", "RESOLVED"],
    "PERSISTENT": ["INVESTIGATING", "ACTIVE", "SUBSIDING", "RESOLVED"],
    "SUBSIDING": ["ACTIVE", "RESOLVED"],
    "RESOLVED": ["ACTIVE", "REOPENED"]
}

def record_incident_event(
    db: Session,
    incident_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None
) -> IncidentEvent:
    """
    Appends an immutable timeline event for auditability and explainability.
    Examples: incident.created, incident.updated, severity.changed, state.transitioned
    """
    event = IncidentEvent(
        incident_id=incident_id,
        event_type=event_type,
        payload=payload or {},
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    return event

def transition_incident_state(
    db: Session,
    incident: Incident,
    new_state: str,
    reason: str = ""
) -> Incident:
    """
    Validates and executes an incident state transition.
    Logs transition event to incident_events.
    """
    curr = incident.status or "NEW"
    new_state_upper = new_state.upper()

    allowed = VALID_TRANSITIONS.get(curr, [])
    if new_state_upper not in allowed and new_state_upper != curr:
        logger.warning(
            f"Unusual state transition for {incident.incident_code}: {curr} -> {new_state_upper}. Overriding with audit log."
        )

    old_state = incident.status
    incident.status = new_state_upper
    incident.updated_at = datetime.utcnow()

    record_incident_event(
        db,
        incident_id=incident.id,
        event_type="incident.state_changed",
        payload={
            "from_state": old_state,
            "to_state": new_state_upper,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    db.commit()
    logger.info(f"Incident {incident.incident_code} transitioned: {old_state} -> {new_state_upper} ({reason})")
    return incident
