"""
FIREX v2 Incident Aggregate Derivation

Derives incident-level aggregates from the incident's member observations.

Both the severity engine (Section 4.5/4.6, C_firms) and the selection engine
(Section 4.5 line 206, "C_firms >= 80.0%", and Section 14.2) need the aggregate
NASA FIRMS confidence of an incident's detections. Until now neither had it:

* ``selection/engine.py`` hard-coded ``confidence_val = 80.0`` with the comment
  "FIRMS confidence approximation (default 80 if aggregate)", which made the
  Section 14.3 extreme-FRP override degenerate into an FRP-only test -- an
  aggregate of 80.0 is indistinguishable from the constant.
* ``severity/service.py`` fed ``incident.severity_confidence`` (the incident's
  *own* previously computed severity certainty, overwritten a few lines later)
  in as ``firms_confidence``, closing a self-referential loop.

The real quantity is the mean of the member observations' ``confidence_score``
(``storage/models.py``, normalized to 0.0-1.0 by
``ingestion/normalizer.normalize_confidence``: VIIRS l/n/h -> 0.35/0.70/0.95,
MODIS 0-100 -> n/100). This module is the single place that computes it, so the
two engines cannot drift apart again.

The mean is used rather than the maximum because C_firms is a property of the
*detection set*: a cluster whose members are mostly nominal-confidence should not
report the certainty of its single most confident pixel.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.storage.models import Incident, IncidentObservation, Observation

logger = logging.getLogger(__name__)

# Fallback when an incident has no usable observation confidence at all -- for
# example a legacy row whose members predate confidence_score, or a unit test
# that constructs an Incident directly. This is deliberately the *nominal* VIIRS
# value rather than an optimistic 80, and callers that must distinguish "no
# data" from "nominal" should inspect the None return of
# ``compute_incident_firms_confidence`` instead.
DEFAULT_FIRMS_CONFIDENCE_PCT = 70.0

# A single detection far outside the incident's own time envelope is not a
# representative member. Bounding the aggregate to the incident window keeps a
# long-lived PERSISTENT incident from averaging in observations from a different
# episode.
CONFIDENCE_WINDOW_PADDING_HOURS = 24.0


def compute_incident_firms_confidence(
    incident: Incident,
    db: Session
) -> Optional[float]:
    """Mean NASA FIRMS confidence of an incident's member observations, 0-100.

    Returns ``None`` when the incident has no member observation carrying a
    ``confidence_score``; callers decide what a missing aggregate means for
    them (the severity engine substitutes the nominal default, the selection
    engine passes ``None`` through so ``map_firms_confidence`` can apply its own
    raw-string fallback).
    """
    if incident is None or incident.id is None:
        return None

    window_start = incident.first_detected_at
    window_end = incident.last_detected_at
    query = (
        db.query(func.avg(Observation.confidence_score))
        .join(IncidentObservation, IncidentObservation.observation_id == Observation.id)
        .filter(IncidentObservation.incident_id == incident.id)
        .filter(Observation.confidence_score.isnot(None))
    )
    if window_start is not None:
        query = query.filter(
            Observation.acquired_at >= window_start - timedelta(hours=CONFIDENCE_WINDOW_PADDING_HOURS)
        )
    if window_end is not None:
        query = query.filter(
            Observation.acquired_at <= window_end + timedelta(hours=CONFIDENCE_WINDOW_PADDING_HOURS)
        )

    avg_score = query.scalar()
    if avg_score is None:
        return None

    # confidence_score is stored on the 0.0-1.0 scale (models.py, normalizer.py).
    # Defensive: a row written by an older revision on the 0-100 scale would be
    # read back as a fraction, so scale only what is actually fractional.
    pct = float(avg_score) * 100.0 if float(avg_score) <= 1.0 else float(avg_score)
    return round(max(0.0, min(100.0, pct)), 1)


def refresh_incident_firms_confidence(
    incident: Incident,
    db: Session,
    commit: bool = False
) -> Optional[float]:
    """Recompute and persist ``Incident.firms_confidence`` for one incident.

    Persisting matters beyond caching: the stored column is what the console
    reads for its ``confidence`` label, and it is what the documentation's
    "aggregate FIRMS confidence" refers to. Returns the value written, or None
    when no member confidence was available (the existing column value is then
    left untouched rather than being nulled out).
    """
    value = compute_incident_firms_confidence(incident, db)
    if value is None:
        return incident.firms_confidence
    if incident.firms_confidence != value:
        incident.firms_confidence = value
        incident.updated_at = datetime.utcnow()
        if commit:
            db.commit()
    return value


def resolve_firms_confidence(
    incident: Incident,
    db: Session
) -> float:
    """The aggregate for scoring, with the nominal default applied.

    Order of preference: the stored column (kept fresh by the pipeline), then a
    live computation over the member observations, then the nominal default.
    Never falls back to ``severity_confidence`` -- that is a different quantity
    and reusing it is what made the severity engine self-referential.
    """
    if incident is None:
        return DEFAULT_FIRMS_CONFIDENCE_PCT
    if incident.firms_confidence is not None:
        return float(incident.firms_confidence)
    computed = compute_incident_firms_confidence(incident, db)
    if computed is None:
        return DEFAULT_FIRMS_CONFIDENCE_PCT
    incident.firms_confidence = computed
    return computed
