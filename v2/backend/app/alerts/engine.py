"""
FIREX v2 Alert Engine with Exactly-Once Deduplication
Implements Section 21 of FIREX-SIH2026 Blueprint:
- Emits alerts only on HIGH and CRITICAL severity
- Exactly-once deduplication prevents alert spamming
- Manages operator lifecycle: NEW -> ACKNOWLEDGED -> RESOLVED / DISMISSED
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from app.storage.models import AlertRecord, Incident, IncidentEvent

logger = logging.getLogger(__name__)

ALERT_ELIGIBLE_LEVELS = {"HIGH", "CRITICAL"}
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

def evaluate_and_emit_alert(
    incident: Incident,
    assessment: Dict[str, Any],
    db: Session
) -> Optional[AlertRecord]:
    """
    Evaluates severity assessment and emits an alert with exactly-once deduplication.
    """
    severity_level = assessment.get("severity_level", "LOW")
    if severity_level not in ALERT_ELIGIBLE_LEVELS:
        return None

    # Check for active alerts for this incident
    active_alerts = db.query(AlertRecord).filter(
        AlertRecord.incident_id == incident.id,
        AlertRecord.status.in_(["NEW", "ACKNOWLEDGED"])
    ).order_by(AlertRecord.created_at.desc()).all()

    if active_alerts:
        latest = active_alerts[0]
        # Check for escalation (e.g. HIGH -> CRITICAL)
        if SEVERITY_RANK.get(severity_level, 0) > SEVERITY_RANK.get(latest.severity_level, 0):
            logger.info(
                f"[AlertEngine] Escalating alert for {incident.incident_code} "
                f"from {latest.severity_level} -> {severity_level}"
            )
            # Create an escalated alert
            escalated_alert = AlertRecord(
                incident_id=incident.id,
                severity_level=severity_level,
                title=f"[ESCALATED] {severity_level} Threat Alert - {incident.incident_code}",
                description=(
                    f"Incident {incident.incident_code} escalated to {severity_level} "
                    f"(Score: {assessment.get('severity_score'):.1f}). "
                    f"Classification: {incident.classification}. "
                    f"Max FRP: {incident.current_max_frp:.1f} MW."
                ),
                status="NEW",
                created_at=datetime.utcnow()
            )
            db.add(escalated_alert)

            event = IncidentEvent(
                incident_id=incident.id,
                event_type="ALERT_ESCALATED",
                payload={
                    "previous_severity": latest.severity_level,
                    "new_severity": severity_level,
                    "score": assessment.get("severity_score"),
                    "overrides": assessment.get("override_reasons", [])
                },
                occurred_at=datetime.utcnow()
            )
            db.add(event)
            db.commit()
            db.refresh(escalated_alert)
            return escalated_alert

        # Deduplication: active alert already exists at same or higher severity
        logger.debug(
            f"[AlertEngine] Deduplication: Active {latest.severity_level} alert already exists for {incident.incident_code}."
        )
        return latest

    # No active alert exists: create fresh alert
    score = assessment.get("severity_score", 0.0)
    title = f"[{severity_level}] Thermal Anomaly Alert - {incident.incident_code}"
    description = (
        f"Incident {incident.incident_code} reached {severity_level} severity "
        f"(Score: {score:.1f}, Confidence: {assessment.get('severity_confidence', 0.0):.1f}%). "
        f"Classification: {incident.classification}. "
        f"Observed FRP: {incident.current_max_frp:.1f} MW."
    )

    alert = AlertRecord(
        incident_id=incident.id,
        severity_level=severity_level,
        title=title,
        description=description,
        status="NEW",
        created_at=datetime.utcnow()
    )
    db.add(alert)

    event = IncidentEvent(
        incident_id=incident.id,
        event_type="ALERT_EMITTED",
        payload={
            "severity_level": severity_level,
            "score": score,
            "confidence": assessment.get("severity_confidence"),
            "classification": incident.classification
        },
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(alert)

    logger.info(f"[AlertEngine] Emitted {severity_level} alert for incident {incident.incident_code}")
    return alert


def acknowledge_alert(alert_id: str, db: Session, notes: Optional[str] = None) -> AlertRecord:
    """Transitions an alert to ACKNOWLEDGED."""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert {alert_id} not found.")

    alert.status = "ACKNOWLEDGED"
    event = IncidentEvent(
        incident_id=alert.incident_id,
        event_type="ALERT_ACKNOWLEDGED",
        payload={"alert_id": alert_id, "notes": notes},
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(alert)
    return alert


def resolve_alert(alert_id: str, db: Session, notes: Optional[str] = None) -> AlertRecord:
    """Transitions an alert to RESOLVED."""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert {alert_id} not found.")

    alert.status = "RESOLVED"
    event = IncidentEvent(
        incident_id=alert.incident_id,
        event_type="ALERT_RESOLVED",
        payload={"alert_id": alert_id, "notes": notes},
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(alert)
    return alert


def dismiss_alert(alert_id: str, db: Session, reason: str = "False alarm or planned maintenance") -> AlertRecord:
    """Transitions an alert to DISMISSED."""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert {alert_id} not found.")

    alert.status = "DISMISSED"
    event = IncidentEvent(
        incident_id=alert.incident_id,
        event_type="ALERT_DISMISSED",
        payload={"alert_id": alert_id, "reason": reason},
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(alert)
    return alert


def get_active_alerts(
    db: Session,
    severity_level: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
) -> List[AlertRecord]:
    """Retrieves filtered alerts in reverse chronological order."""
    query = db.query(AlertRecord)
    if severity_level:
        query = query.filter(AlertRecord.severity_level == severity_level.upper())
    if status:
        query = query.filter(AlertRecord.status == status.upper())
    else:
        # Default: active alerts (NEW and ACKNOWLEDGED)
        query = query.filter(AlertRecord.status.in_(["NEW", "ACKNOWLEDGED"]))
    
    return query.order_by(AlertRecord.created_at.desc()).limit(limit).all()
