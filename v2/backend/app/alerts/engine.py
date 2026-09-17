"""
FIREX v2 Alert Engine with Exactly-Once Deduplication
Implements Section 21 of FIREX-SIH2026 Blueprint:
- Emits alerts only on HIGH and CRITICAL severity
- Exactly-once deduplication prevents alert spamming
- Manages operator lifecycle: NEW -> ACKNOWLEDGED -> RESOLVED / DISMISSED
"""
import logging
from typing import Optional, List, Dict, Any, Set
from datetime import datetime
from sqlalchemy.orm import Session

from app.storage.models import AlertRecord, Incident, IncidentEvent

logger = logging.getLogger(__name__)

ALERT_ELIGIBLE_LEVELS = {"HIGH", "CRITICAL"}
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# The statuses an alert can actually occupy. `RESOLVED` is included because
# Section 8's lifecycle and `resolve_alert` below both use it, and because
# `get_active_alerts` excludes it from the active set -- its absence from the
# Section 9 data dictionary was a documentation gap, not a code one (F-015).
ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "RESOLVED", "DISMISSED")

# Section 8's operator lifecycle, enforced rather than assumed. The previous
# code assigned `alert.status` after only a not-found check, so a client could
# drive NEW -> RESOLVED, DISMISSED -> ACKNOWLEDGED or RESOLVED -> ACKNOWLEDGED.
# The last two are the damaging pair: `get_active_alerts` filters on
# `status in (NEW, ACKNOWLEDGED)`, so re-acknowledging a closed alert put it
# back on the operator's board (F-011).
#
# Both terminal states are terminal. Re-opening a closed alert is deliberately
# not offered: a re-detection at the same site is a new alert against the same
# incident, which is what the emission path already produces.
ALERT_TRANSITIONS: Dict[str, Set[str]] = {
    "NEW": {"ACKNOWLEDGED", "RESOLVED", "DISMISSED"},
    "ACKNOWLEDGED": {"RESOLVED", "DISMISSED"},
    "RESOLVED": set(),
    "DISMISSED": set(),
}


class AlertNotFound(ValueError):
    """No alert carries the given id."""


class InvalidAlertTransition(ValueError):
    """The requested status change is not permitted from the alert's current status."""

    def __init__(self, current: str, target: str, alert_id: str):
        self.current = current
        self.target = target
        self.alert_id = alert_id
        super().__init__(
            f"Alert {alert_id} cannot move {current or 'UNSET'} -> {target}; "
            f"permitted from {current or 'UNSET'}: "
            f"{sorted(ALERT_TRANSITIONS.get(current or '', set())) or 'nothing (terminal)'}."
        )


def evaluate_and_emit_alert(
    incident: Incident,
    assessment: Dict[str, Any],
    db: Session
) -> Optional[AlertRecord]:
    """
    Evaluates severity assessment and emits an alert with exactly-once deduplication.

    The returned record carries a transient `is_new` flag. Both the fresh-emission
    and the escalation path return a record the caller has never seen; the
    deduplication path returns the *existing* record. All three are non-None, so
    without the flag a caller cannot tell a dispatch from a suppression -- which
    is what made `alert_emitted` in the severity audit payload true on every
    HIGH/CRITICAL re-evaluation (F-013). `is_new` is deliberately not a column:
    it describes this evaluation, and a persisted copy would be stale the moment
    the next one ran.
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
        # Compare against the *highest* active severity, not merely the newest
        # row. Section 8's exactly-once rule is a statement about the alert an
        # operator can currently see, so a legacy pair of open alerts must not
        # let a third escalation through just because the newest is the weaker
        # one (F-012).
        latest = max(active_alerts, key=lambda a: SEVERITY_RANK.get(a.severity_level, 0))

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

            # Close the alert being superseded. Without this the two coexist as
            # NEW, and the moment the CRITICAL row leaves the active set the
            # stale HIGH row is active again -- `4 > 3` then holds once more and
            # the same escalation is emitted a second time (F-012).
            db.flush()  # assign escalated_alert.id for the back-reference
            latest.status = "RESOLVED"
            latest.resolved_at = datetime.utcnow()
            latest.superseded_by = escalated_alert.id

            event = IncidentEvent(
                incident_id=incident.id,
                event_type="ALERT_ESCALATED",
                payload={
                    "previous_severity": latest.severity_level,
                    "new_severity": severity_level,
                    "score": assessment.get("severity_score"),
                    "overrides": assessment.get("override_reasons", []),
                    "superseded_alert_id": latest.id,
                    "escalated_alert_id": escalated_alert.id,
                },
                occurred_at=datetime.utcnow()
            )
            db.add(event)
            db.commit()
            db.refresh(escalated_alert)
            escalated_alert.is_new = True
            return escalated_alert

        # Deduplication: active alert already exists at same or higher severity
        logger.debug(
            f"[AlertEngine] Deduplication: Active {latest.severity_level} alert already exists for {incident.incident_code}."
        )
        latest.is_new = False
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
    # Set after `refresh`, which reloads mapped state; a non-mapped attribute
    # written before it would be the one thing the reload could disturb.
    alert.is_new = True
    return alert


def _load_alert(alert_id: str, db: Session) -> AlertRecord:
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        raise AlertNotFound(f"Alert {alert_id} not found.")
    return alert


def _transition_alert(
    alert_id: str,
    db: Session,
    target: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    timestamp_field: Optional[str] = None,
) -> AlertRecord:
    """Apply a Section 8 lifecycle transition, enforcing the transition table.

    A transition to the status the alert already holds is a no-op that returns
    the record unchanged and records no second audit event. Operator consoles
    double-submit; making that an error would surface as a spurious failure for
    an action that had already succeeded.
    """
    alert = _load_alert(alert_id, db)
    current = (alert.status or "NEW").upper()

    if target == current:
        logger.debug("[AlertEngine] Alert %s already %s; no-op.", alert_id, target)
        return alert

    if target not in ALERT_TRANSITIONS.get(current, set()):
        raise InvalidAlertTransition(current, target, alert_id)

    alert.status = target
    if timestamp_field:
        setattr(alert, timestamp_field, datetime.utcnow())

    event = IncidentEvent(
        incident_id=alert.incident_id,
        event_type=event_type,
        payload={"alert_id": alert_id, "from_status": current, "to_status": target, **(payload or {})},
        occurred_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
    db.refresh(alert)
    logger.info("[AlertEngine] Alert %s: %s -> %s", alert_id, current, target)
    return alert


def acknowledge_alert(alert_id: str, db: Session, notes: Optional[str] = None) -> AlertRecord:
    """Transitions an alert to ACKNOWLEDGED."""
    return _transition_alert(
        alert_id, db, "ACKNOWLEDGED", "ALERT_ACKNOWLEDGED",
        payload={"notes": notes}, timestamp_field="acknowledged_at",
    )


def resolve_alert(alert_id: str, db: Session, notes: Optional[str] = None) -> AlertRecord:
    """Transitions an alert to RESOLVED."""
    return _transition_alert(
        alert_id, db, "RESOLVED", "ALERT_RESOLVED",
        payload={"notes": notes}, timestamp_field="resolved_at",
    )


def dismiss_alert(alert_id: str, db: Session, reason: str = "False alarm or planned maintenance") -> AlertRecord:
    """Transitions an alert to DISMISSED."""
    return _transition_alert(
        alert_id, db, "DISMISSED", "ALERT_DISMISSED",
        payload={"reason": reason},
    )


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
