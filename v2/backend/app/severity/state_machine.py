"""
FIREX v2 Incident State Machine
Implements Section 20 of Blueprint:
Transitions incidents cleanly through lifecycle states:
NEW -> INVESTIGATING -> ACTIVE -> ESCALATED / PERSISTENT -> SUBSIDING -> RESOLVED
"""
import logging
from app.incidents.state import VALID_STATES

logger = logging.getLogger(__name__)

def determine_lifecycle_state(
    current_status: str,
    severity_level: str,
    is_persistent: bool = False,
    hours_since_last_seen: float = 0.0
) -> str:
    """
    Evaluates incident temporal recency, severity, and persistence to determine the next lifecycle state.
    Strictly keeps state separate from severity level.
    """
    # 1. Temporal resolution transitions
    if hours_since_last_seen >= 48.0:
        return "RESOLVED"
    elif hours_since_last_seen >= 24.0:
        return "SUBSIDING"

    # 2. Escalation transitions
    if severity_level == "CRITICAL":
        return "ESCALATED"

    # 3. Persistent thermal source
    if is_persistent:
        return "PERSISTENT"

    # 4. Standard active incident
    if current_status in ["NEW", "INVESTIGATING"]:
        return "ACTIVE"

    return current_status if current_status in VALID_STATES else "ACTIVE"
