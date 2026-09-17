"""
FIREX v2 Data Reference Clock

FIREX reasons about *recency* in two different senses, and conflating them is
not cosmetic -- it decides whether the console board is populated at all.

* **Audit time.** When a row was written, when an assessment happened, when a
  log line was emitted. This is wall clock (`datetime.utcnow()`), and it is
  correct.

* **Fire time.** How long ago a thermal detection was seen. Section 20's
  lifecycle rule is a threshold on this -- SUBSIDING at 24 hours since last
  detection, RESOLVED at 48 -- and so is the SUBSIDING/ACTIVE distinction the
  console board is built on.

The two coincide only when the observation archive is being ingested live. When
FIREX runs against a *stored* archive -- the reviewed FIRMS corpus, a demo
replay, a backfill -- they diverge by the whole age of the archive. Every
incident's `last_detected_at` then sits weeks behind `utcnow()`, so a
wall-clock recency test declares the entire queue RESOLVED on the first pass.

That is not hypothetical. Measured on the shipped database on 2026-09-17:

    max(observations.acquired_at)    = 2026-09-13 19:57:00
    max(incidents.last_detected_at)  = 2026-09-13 21:45:45
    wall clock                       = 2026-09-17 00:07:50   (74+ hours later)

    sweep with wall clock    -> RESOLVED 332, ACTIVE 0    (board emptied)
    sweep with archive clock -> ACTIVE 122, SUBSIDING 110,
                                RESOLVED 97, PERSISTENT 3

So fire recency is measured against the archive's own newest detection, which
is what "now" means for the data being reasoned about. `data_reference_time`
is the single definition of that instant; callers must not re-derive it.
"""
import logging
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.storage.models import Incident, Observation

logger = logging.getLogger(__name__)

# Memo key on `Session.info`. A 332-incident severity sweep asks for the
# reference time once per incident; the answer cannot change mid-sweep, and
# caching it on the Session keeps the value scoped to that unit of work rather
# than to a module global that would go stale across runs.
_SESSION_CACHE_KEY = "firex_data_reference_time"


def data_reference_time(db: Session, use_cache: bool = True) -> datetime:
    """The instant the observation archive currently ends at.

    Returns the later of the newest observation `acquired_at` and the newest
    incident `last_detected_at`. Both are consulted because the two are written
    by different stages and a backfill can leave one ahead of the other; taking
    the later one guarantees no incident is ever "seen in the future", which
    would clamp to zero and read as brand new.

    Falls back to wall clock when the archive is empty (a fresh database, or a
    test session with no fixtures). That fallback is deliberately silent and
    non-fatal: an empty archive has no stale incidents for the distinction to
    matter to, and raising here would make every caller handle a case that
    cannot produce a wrong answer.

    Memoised on the Session. Pass `use_cache=False` to force a re-read after
    ingesting observations within the same session.
    """
    if use_cache:
        cached = db.info.get(_SESSION_CACHE_KEY)
        if cached is not None:
            return cached

    reference: Optional[datetime] = None
    for model, column in ((Observation, Observation.acquired_at),
                          (Incident, Incident.last_detected_at)):
        try:
            value = db.query(sa.func.max(column)).scalar()
        except Exception as exc:  # table absent -- an unmigrated or empty database
            logger.debug("[Clock] %s unavailable (%s); skipping.", model.__tablename__, exc)
            continue
        if value is not None and (reference is None or value > reference):
            reference = value

    if reference is None:
        reference = datetime.utcnow()
        logger.debug("[Clock] Archive empty; falling back to wall clock %s.", reference)

    db.info[_SESSION_CACHE_KEY] = reference
    return reference


def hours_since(then: Optional[datetime], reference: Optional[datetime] = None,
                db: Optional[Session] = None) -> float:
    """Hours from `then` to the reference instant, never negative.

    Convenience wrapper for the common call shape. Clamping at zero keeps an
    incident whose detection is stamped marginally ahead of the archive
    reference from reporting a negative age, which the lifecycle state machine
    would otherwise treat as "just seen" only by luck.
    """
    if then is None:
        return 0.0
    if reference is None:
        reference = data_reference_time(db) if db is not None else datetime.utcnow()
    return max(0.0, (reference - then).total_seconds() / 3600.0)
