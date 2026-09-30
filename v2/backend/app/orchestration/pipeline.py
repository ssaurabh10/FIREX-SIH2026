"""
FIREX v2 End-to-End Analysis Pipeline Runner
Implements Section 23 & 25 of Blueprint:
FIRMS
→ validation & deduplication
→ GIS spatial context
→ clustering
→ incident association
→ behavior features & baselines
→ selection & ranking
→ visual context & imagery
→ multimodal AI investigation
→ severity assessment
→ alert evaluation & deduplication
→ database persistence & SSE emission
"""
import os
import json
import math
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.storage.models import (
    Observation, Incident, IndustrialAsset, AIInvestigation,
    SeverityAssessment, AlertRecord, AnalysisRun, ThermalClimatology,
    HistoricalBaseline, IncidentObservation
)
from app.ingestion.firms import FIRMSClient
from app.gis.enrichment import enrich_coordinate_gis_context
from app.gis.boundaries import is_within_indian_sovereign_territory
from app.gis.mining_basins import is_in_major_mining_basin
from app.gis.assets import find_nearest_asset, is_flaring_facility, is_metallurgical_or_manufacturing_facility
from app.gis.landcover import resolve_landcover
from app.gis.spatial import climatology_cell
from app.incidents.clustering import cluster_observations
from app.incidents.association import sync_clusters_to_incidents
from app.behavior.baseline import get_or_create_facility_baseline, get_or_create_location_baseline
from app.selection.engine import select_investigation_candidates
from app.imagery.service import get_or_create_incident_imagery
from app.intelligence.service import run_incident_investigation
from app.intelligence.provider import FALLBACK_CONFIDENCE_CEILING
from app.severity.service import evaluate_incident_severity
from app.severity.scoring import (
    calculate_frp_severity,
    calculate_calibrated_frp_severity,
    score_to_level,
    SEVERITY_LEVELS,
)
from app.orchestration.lock import pipeline_lock, AnalysisAlreadyRunningError
from app.orchestration.events import (
    event_broadcaster,
    EVENT_ANALYSIS_STARTED,
    EVENT_FIRMS_FETCHED,
    EVENT_GIS_COMPLETED,
    EVENT_CLUSTERING_COMPLETED,
    EVENT_SELECTION_COMPLETED,
    EVENT_IMAGERY_STARTED,
    EVENT_AI_STARTED,
    EVENT_AI_COMPLETED,
    EVENT_SEVERITY_COMPLETED,
    EVENT_ALERT_CREATED,
    EVENT_ANALYSIS_COMPLETED,
    EVENT_ANALYSIS_FAILED
)

# Export directories for v2 frontend console and backward-compatible v1 dashboard.
#
# Both are anchored on the repository root, four levels up from this file:
# `v2/backend/app/orchestration` -> `v2/backend/app` -> `v2/backend` -> `v2` -> the root.
# V1_DATA_DIR climbed only three and wrote to a phantom `v2/v1/dashboard/data`,
# while the dashboard the v1 UI actually reads (`v1/dashboard/server.py` serves
# `GIS_DIR/data`; `js/config.js:7` fetches `data/incidents.json`) stayed frozen.
#
# Both are overridable from the environment: the source-tree default means any
# caller that exports overwrites the console's fallback files. A conftest rebind
# covers neither a caller outside v2/tests/ nor a re-exec of this module body,
# which recomputes both names from __file__.
#
# v2 stands alone: `v1/` is an archived prototype that v2 mirrors as a courtesy,
# never a dependency. See `_export_targets`.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
FRONTEND_DATA_DIR = os.environ.get("FIREX_FRONTEND_DATA_DIR") or os.path.join(_REPO_ROOT, "v2", "frontend", "data")
V1_DATA_DIR = os.environ.get("FIREX_V1_DATA_DIR") or os.path.join(_REPO_ROOT, "v1", "dashboard", "data")

# Whether V1_DATA_DIR was set by the environment rather than derived from the
# source tree. An explicit setting is an operator instruction and is honoured
# wherever it points, including at a directory that does not exist yet; the
# source-tree default is only written to when it is already there.
_V1_DATA_DIR_IS_EXPLICIT = "FIREX_V1_DATA_DIR" in os.environ


def _export_targets() -> List[str]:
    """Directories ``export_v1_dashboard_data`` writes the console feed into.

    The console target is unconditional -- it is v2's own data directory and the
    export exists for it. The v1 target is conditional. The export used to
    ``os.makedirs`` both unconditionally, so running v2 on a checkout with no
    ``v1/`` beside it silently created ``../v1/dashboard/data``: a directory tree
    outside v2, belonging to a project that is not installed there, holding files
    nothing reads. Mirroring the feed is worth doing while v1 is present --
    that is what keeps the archived dashboard current -- but conjuring the tree
    is not, and v2 must run without it either way.
    """
    targets = [FRONTEND_DATA_DIR]
    if V1_DATA_DIR and (_V1_DATA_DIR_IS_EXPLICIT or os.path.isdir(V1_DATA_DIR)):
        targets.append(V1_DATA_DIR)
    return targets

# Statuses the console queue displays. SUBSIDING was missing: an incident whose
# thermal output is declining but which is still burning is operationally live,
# and every one of the live CRITICAL/HIGH incidents sat in RESOLVED/SUBSIDING,
# so the queue read as a uniform LOW board while the alert feed fired CRITICAL
# at incidents the queue could not display (J4). RESOLVED stays out of the live
# queue -- it is closed -- and is surfaced separately as a closed-alert roll-up
# so the tier histogram is not silently truncated.
#
# The list is `incidents.state.VALID_STATES` split by whether the incident is
# still burning, and it had drifted from that vocabulary in both directions.
# ESCALATED was dropped when this tuple was rewritten -- the fix replaced the
# shipped inline list instead of extending it -- yet Section 8's lifecycle
# promotes an incident to it precisely *because* a fresh assessment raised its
# level, and `severity/state_machine.py` returns it for every CRITICAL detection.
# Ten live incidents held it, so the highest-urgency records in the database
# were served no queue entry at all: J4 again, on the records J4 is about.
# REOPENED is in the same position from the other side -- a resolved incident
# that new detections reopen -- and nothing sets it today only because no code
# path writes it back, which is not a property worth depending on.
# `test_console_queue_covers_every_lifecycle_status` pins the split.
CONSOLE_ACTIVE_STATUSES = (
    "NEW", "INVESTIGATING", "ACTIVE", "PERSISTENT", "ESCALATED", "SUBSIDING", "REOPENED"
)
CONSOLE_CLOSED_STATUSES = ("RESOLVED", "DISMISSED")

# Severity tiers that warrant operator attention in the closed roll-up.
ATTENTION_TIERS = ("HIGH", "CRITICAL")


def _read_cached_location_baseline(db: Session, lat: float, lon: float) -> Dict[str, Any]:
    """Read-only counterpart of ``get_or_create_location_baseline``.

    Section 9's ``historical_baselines`` and ``thermal_climatology`` tables are
    materialised statistics: they are written by an analysis run, and reading
    them should never write. ``GET /api/console/feed`` is fetched by
    ``frontend/js/data.js`` on every page load, and it used to call the
    get-or-create variant, whose slow path ends in ``db.commit()`` -- so simply
    opening the console inserted a ``HistoricalBaseline`` row for every incident
    that lacked a <24 h cache entry (J6).

    This function consults the two caches only and returns ``{}`` on a miss. A
    miss is expected before the first analysis run and after a queue grows;
    ``run_severity_sweep`` below is what populates them, so a console served
    after a run always finds its rows.
    """
    _, _, spatial_key = climatology_cell(lat, lon)

    clim = (
        db.query(ThermalClimatology)
        .filter(ThermalClimatology.spatial_key == spatial_key)
        .first()
    )
    if clim:
        return {
            "spatial_key": spatial_key,
            "observation_count": clim.observation_count or 0,
            "active_days_365d": clim.active_days or 0,
            "median_frp": clim.median_frp or 0.0,
            "p90_frp": clim.p90_frp or 0.0,
            "p95_frp": clim.p95_frp or 0.0,
            "mean_frp": clim.median_frp or 0.0,
            "max_frp": clim.max_frp or 0.0,
            "night_ratio": clim.night_ratio or 0.0,
            "is_routine_flare": bool(clim.is_routine_flare),
            "site_classification_hint": clim.site_classification_hint or "EPISODIC_THERMAL",
            "is_persistent": False,
            "source": "thermal_climatology",
        }

    cached = (
        db.query(HistoricalBaseline)
        .filter(HistoricalBaseline.spatial_key == spatial_key)
        .first()
    )
    if cached:
        return {
            "spatial_key": spatial_key,
            "observation_count": cached.detection_count_90d or 0,
            "active_days_365d": cached.detection_count_365d or 0,
            "median_frp": cached.median_frp or 0.0,
            "p90_frp": cached.p90_frp or 0.0,
            "p95_frp": cached.p95_frp or 0.0,
            "mean_frp": cached.mean_frp or 0.0,
            "max_frp": cached.p95_frp or 0.0,
            "night_ratio": 0.0,
            "is_routine_flare": bool(cached.is_persistent),
            "site_classification_hint": "PERSISTENT_THERMAL" if cached.is_persistent else "EPISODIC_THERMAL",
            "is_persistent": bool(cached.is_persistent),
            "source": "historical_baselines",
        }

    return {}


# Row label for a score the breakdown cannot attribute to an override or to
# INV-4's clamp. Its presence is the machine-readable signal the export logs a
# warning on: an assessment whose recorded score does not follow from its own
# factors is either stale -- written before the current scoring model -- or
# wrong, and both want a human rather than a quieter breakdown.
UNRECONCILED_FACTOR_LABEL = "Recorded Adjustment"


def _apportion_tenths(
    values: List[float], target_tenths: int, caps: List[float]
) -> List[int]:
    """Round ``values`` to tenths so that they sum to exactly ``target_tenths``.

    Rounding each row on its own is what put the breakdown and the score back at
    odds even after the weights were corrected: four components that truly sum
    to 55.00 display as anything from 54.8 to 55.2 depending on where the halves
    fall, and the operator is reading this as a scoreboard. Largest-remainder
    (Hamilton) apportionment keeps every row within 0.05 of its own value -- each
    row is still the correctly rounded one -- while making the sum exact: the
    whole tenths are floored first, then the leftover tenths go to the rows that
    lost the most in the flooring.

    ``caps`` is each row's own maximum. The ceiling is kept by the flooring above:
    a floored tenth-count of a value within the cap cannot exceed it, and every
    leftover tenth goes to a row with a fractional part, which has headroom. The
    refusal bites only on a stale base_score that outruns the components.
    """
    scaled = [v * 10.0 for v in values]

    # A target the rows cannot reach by rounding is not something to apportion
    # them towards: it means the recorded score does not follow from its own
    # components, and dragging every row to a tenth-count none of them supports
    # would misreport each of them to hide a gap the reconciliation row is
    # already going to name. Show every row at its own value instead.
    if abs(target_tenths - sum(scaled)) > len(values):
        return [int(round(s)) for s in scaled]

    tenths = [int(math.floor(s)) for s in scaled]
    leftover = int(target_tenths) - sum(tenths)

    if leftover <= 0:
        # `round` is half-to-even, so the target can land one tenth *below* the
        # floors' sum. Take that tenth back from the rows that lost the least.
        for i in sorted(range(len(values)), key=lambda i: scaled[i] - tenths[i]):
            if leftover == 0:
                break
            if tenths[i] > 0:
                tenths[i] -= 1
                leftover += 1
        return tenths

    order = sorted(
        range(len(values)), key=lambda i: scaled[i] - tenths[i], reverse=True
    )
    for i in order:
        if leftover == 0:
            break
        cap = caps[i]
        if cap is not None and (tenths[i] + 1) / 10.0 > float(cap) + 1e-9:
            continue
        tenths[i] += 1
        leftover -= 1
    return tenths


def _reconciliation_row(
    factors: Dict[str, Any], score_tenths: int, cause: Optional[str]
) -> Dict[str, Any]:
    """The one row that carries the difference between the weighted factors and
    the recorded score, labelled by what actually caused it.

    A gap with a cause is a fact about the incident -- an override raised the
    floor, or INV-4 clamped a routine flare or a chronic thermal source -- and
    belongs in the breakdown. A gap without one is a fact about the *record*, and
    saying so is the point: the alternative, which shipped, was a "Routine Flare
    Suppression" row worth 0.0 that silently let the operator's breakdown
    overstate the score by whatever the clamp had removed.

    ``cause`` is ``None`` when an override or the clamp accounts for the
    difference, ``"stale"`` for an assessment written by an older scoring model,
    and ``"absent"`` when no assessment was ever persisted, so the rows are the
    fallback breakdown's rather than the engine's.
    """
    score = score_tenths / 10.0
    reasons = [str(r) for r in (factors.get("override_reasons") or [])]

    if score > 0 and cause is None:
        return {
            "factor": "Operational Escalation",
            "score": score,
            "max": 100.0,
            "detail": "; ".join(reasons) if reasons else "Deterministic override raised the tier floor",
        }

    ratio = factors.get("p95_ratio")
    # INV-4 clamps on `is_routine_flare or is_chronic` (scoring.py:449) and
    # records both flags, but this gate read only the first, so a chronic
    # non-flare source -- a steel plant hot on 90+ days -- fell past it to the
    # row below and was told "no override or INV-4 clamp in the assessment
    # accounts for the difference (overrides on record:
    # CHRONIC_SOURCE_SUPPRESSION (...))". The sentence denying the clamp was
    # printed in the same string as the reason it quoted. `generate_console_feed_data`
    # then read that label at :967 and logged a second false claim -- that the
    # assessment "predates the current scoring model" -- for a row written
    # seconds earlier by the current model. Fuzzing the real scoring path over
    # 30,000 cases produced 2,618 of these; every one was chronic-source, none
    # was a routine flare, which is why the flare-only gate looked correct.
    #
    # The two cases are labelled apart rather than sharing "Routine Flare
    # Suppression": scoring.py:437 is explicit that "a steel plant is not a
    # flare", and naming it one is the mislabel this fix exists to remove.
    #
    # `cause is None` is retained so an assessment written by an older scoring
    # model keeps its own, different explanation.
    is_flare_clamp = bool(factors.get("is_routine_flare"))
    is_chronic_clamp = bool(factors.get("is_chronic_source"))
    if score < 0 and cause is None and (is_flare_clamp or is_chronic_clamp):
        envelope = f"P95 {float(ratio):.2f}x ratio" if ratio is not None else "P95 envelope"
        return {
            "factor": "Routine Flare Suppression" if is_flare_clamp else "Chronic Source Suppression",
            "score": score,
            "max": 0.0,
            "detail": (
                f"{'Continuous flare site' if is_flare_clamp else 'Chronic thermal source'} inside "
                f"its own 365-day {envelope}; INV-4 clamps the composite at 20.0, leaving the "
                f"published score {abs(score):.1f} below the pre-override base"
            ),
        }

    direction = "below" if score < 0 else "above"
    if cause == "absent":
        detail = (
            f"Recorded score is {abs(score):.1f} {direction} the fallback breakdown's own "
            f"sum; no persisted assessment can account for the difference"
        )
    else:
        detail = (
            f"Recorded score is {abs(score):.1f} {direction} the weighted factor sum, and no "
            f"override or INV-4 clamp in the assessment accounts for the difference"
        )
    if reasons:
        detail += f" (overrides on record: {'; '.join(reasons)})"
    if cause == "stale":
        detail += (
            "; this assessment predates the current scoring model, so its factors "
            "were written by arithmetic that no longer applies -- re-run the severity "
            "sweep to regenerate it"
        )
    elif cause == "absent":
        detail += (
            "; the severity sweep has never persisted an assessment for this incident, "
            "so the fallback breakdown is what is left to read -- re-run the sweep"
        )
    # The row's own ceiling: an unexplained *rise* is bounded by the scale, an
    # unexplained fall by the score it fell from.
    return {
        "factor": UNRECONCILED_FACTOR_LABEL,
        "score": score,
        "max": 100.0 if score > 0 else 0.0,
        "detail": detail,
    }


def _reconcile_to(
    rows: List[Dict[str, Any]],
    target_score: float,
    factors: Dict[str, Any],
    cause: Optional[str],
) -> List[Dict[str, Any]]:
    """Append ``_reconciliation_row`` to a breakdown that does not reach its own
    score, so that "the rows add up to the score beside them" holds on every
    path that can publish a breakdown -- not only the one that renders a
    persisted assessment.

    The fallback path needs this most: it builds its rows from the incident's
    stored fields with a normalisation the engine does not use for a non-routine
    detection, so its sum is its own opinion of the score rather than the
    engine's, and the two disagree by however much the two models differ. Left
    unnamed, that difference is the same defect the assessment path was fixed
    for -- a breakdown that quietly arrives at a number other than the one the
    operator is looking at.
    """
    leftover = int(round(float(target_score) * 10.0)) - sum(
        int(round(row["score"] * 10.0)) for row in rows
    )
    if leftover:
        rows.append(_reconciliation_row(factors, leftover, cause))
    return rows


def _weighted_risk_factors(
    factors: Dict[str, Any],
    published_score: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Render a persisted severity assessment as weighted factor contributions.

    The published ``risk_factors`` used to be the model's *unweighted* component
    scores carrying invented ``max`` values (30/25/20/15/10), so the breakdown
    the operator saw could not add up to the score beside it, and on the
    fallback path the FRP term was a third normalisation the specification does
    not contain -- a linear ``FRP / 64.49 * 25`` shipped to users in place of
    both documented log2 maps (F-027).

    Here each factor reports ``weight * component`` out of ``weight * 100``, and
    the rows sum to the recorded score *exactly* -- not approximately, and not
    up to a display rounding each row does for itself. Three things were needed
    for that, all of them corrections to what shipped:

    * The FRP term is the one the engine actually used. For a routine flare
      that is the Indian-calibrated map, not the raw log2 one: the renderer read
      ``frp_score`` regardless, so a suppressed flare displayed the
      *uncalibrated* rating as its largest contribution -- and at the no-history
      0.50 weight, since only the augmented dicts carry the model label.
    * The deviation term is included whenever the assessment has one. Its
      weight (0.30) is conditioned on ``model_used``, which only the augmented
      dicts carry, so a legacy assessment silently dropped a 30% component and
      the rows came up short by more than a tier.
    * Suppression *subtracts*. INV-4's clamp lowers the composite; the row that
      records it now carries that reduction as a negative score instead of a
      0.0 with a ceiling of 0.0, which described the clamp and then contributed
      nothing to the arithmetic.

    ``factors`` is the augmented dict persisted by ``severity/service.py``: the
    component scores plus ``model_used``, ``base_score``, ``severity_score`` and
    ``override_reasons``. ``published_score`` is the score the caller is about
    to publish for this incident; it is the fallback target when the dict
    predates the augmentation, so the breakdown still reconciles with the number
    the operator sees even for a stale record.
    """
    model = factors.get("model_used") or ""
    # A dict carrying none of the model's own component keys is not one of this
    # model's assessments -- a v1 row, or one imported from somewhere else. It is
    # not rendered as a set of zero contributions, which would state that the
    # model rated every factor at zero: no rows come back, and the caller falls
    # back to a breakdown built from the incident's own fields, whose difference
    # from the published score it names. A dict missing only *some* keys still
    # renders, because the model genuinely did score the rest.
    if not any(factors.get(key) is not None for key in (
        "frp_score", "india_calibrated_frp_score", "historical_deviation_score",
        "ai_source_severity_score", "gis_context_score",
    )):
        return []
    # A legacy dict has no `model_used`. Its deviation score is stored either
    # way -- 0.0 in the no-history branch -- so a non-zero one is positive proof
    # the known-hotspot weights were used, which is how such a record is now
    # rendered correctly instead of with a component missing.
    with_history = model == "KNOWN_HOTSPOT_WITH_HISTORY" or (
        not model and bool(factors.get("historical_deviation_score"))
    )
    routine = bool(factors.get("is_routine_flare"))

    # Which FRP curve this record was scored on. The engine now measures FRP
    # against the sovereign Indian FIRMS distribution (scoring.py), but a record
    # written earlier used the uncalibrated curve whenever it was not a routine
    # flare -- and the renderer has to reproduce the engine's arithmetic to size
    # its reconciliation row. `frp_curve` is the engine's own marker; a record
    # predating it has no marker, so the earlier rule is reconstructed from
    # `is_routine_flare`, which is what the old selection keyed on.
    if "frp_curve" in factors:
        calibrated = factors.get("frp_curve") == "india_calibrated"
    else:
        calibrated = routine
    frp_key = "india_calibrated_frp_score" if calibrated else "frp_score"
    if factors.get(frp_key) is None:
        frp_key = "frp_score"
    frp_raw = float(factors.get(frp_key) or 0.0)
    frp_label = (
        "Indian-calibrated FRP" if frp_key == "india_calibrated_frp_score"
        else "Fire Radiative Power"
    )
    ai_raw = float(factors.get("ai_source_severity_score") or 0.0)
    gis_raw = float(factors.get("gis_context_score") or 0.0)
    dev_raw = float(factors.get("historical_deviation_score") or 0.0)

    # Section 4.6's two weight sets.
    if with_history:
        components = [
            (frp_label, frp_raw, 0.35),
            ("Historical Deviation", dev_raw, 0.30),
            ("Vision AI Source Severity", ai_raw, 0.20),
            ("GIS Context", gis_raw, 0.15),
        ]
    else:
        components = [
            (frp_label, frp_raw, 0.50),
            ("Vision AI Source Severity", ai_raw, 0.30),
            ("GIS Context", gis_raw, 0.20),
        ]

    # (label, weighted value, ceiling, the component rating, the weight)
    weighted = [
        (label, weight * raw, round(weight * 100.0, 1), raw, weight)
        for label, raw, weight in components
    ]

    # The components are apportioned to the assessment's own pre-override base
    # where it recorded one, so the reconciliation row carries exactly the
    # override or the clamp -- and nothing at all when there was neither.
    #
    # The target is that base *at the precision it is published at*, not the
    # base itself. `base_score` carries two decimals and `severity_score` one,
    # so a base of 32.15 is published as 32.1 -- the half-tenth falls the other
    # way in binary, and `round(x, 2)` then `round(x, 1)` is not `round(x, 1)`
    # directly. Apportioning the rows to the two-decimal base made them sum to
    # 32.2 and produced a -0.1 "Recorded Adjustment" naming no cause at all, on
    # four live incidents. The rows' one job is to add up to the number printed
    # beside them, so they are apportioned to that number; `round(.., 1)` here
    # is the same expression `severity/scoring.py` publishes with, so the two
    # agree by construction and a genuine override or clamp still shows up as a
    # reconciliation row of exactly its own size.
    recorded_base = factors.get("base_score")
    base_value = (
        float(recorded_base) if recorded_base is not None
        else sum(value for _, value, _, _, _ in weighted)
    )
    tenths = _apportion_tenths(
        [value for _, value, _, _, _ in weighted],
        int(round(round(base_value, 1) * 10.0)),
        [cap for _, _, cap, _, _ in weighted],
    )

    rows: List[Dict[str, Any]] = []
    for (label, _, cap, raw, weight), row_tenths in zip(weighted, tenths):
        detail = f"{label} rating {raw:.1f}/100, weighted {weight:.0%}"
        if label == "Historical Deviation" and routine:
            # The engine suppresses this term as well as the composite, and the
            # row is the only place an operator can see that the two are
            # separate caps on the same clause of INV-4.
            detail += "; INV-4 caps this term at 20.0 for a routine flare"
        rows.append({
            "factor": label,
            "score": row_tenths / 10.0,
            "max": cap,
            "detail": detail,
        })

    target = factors.get("severity_score")
    if target is None:
        target = published_score
    if target is not None:
        # Integer tenths on both sides, so "the rows add up to the score" is an
        # equality rather than a tolerance nobody can name.
        leftover = int(round(float(target) * 10.0)) - sum(tenths)
        if leftover:
            rows.append(_reconciliation_row(
                factors, leftover, "stale" if "model_used" not in factors else None
            ))

    return rows


def _fallback_risk_factors(
    inc: Incident,
    ai_conf: float,
    is_inside_fac: bool,
    dist_km: float,
    gis_score: float,
) -> List[Dict[str, Any]]:
    """Section 4.6 factor breakdown for an incident with no persisted assessment.

    Section 4.2 defines exactly two FRP normalisations -- ``S_FRP =
    25*log2(FRP+1)`` and the Indian-calibrated ``S_FRP_calib =
    25*log2(FRP/P50 + 1)``. The previous fallback used a third, linear
    ``FRP / 64.49 * 25`` that appears nowhere in the specification and was the
    dominant shipped form (320 of 323 rows in ``incidents.json``). Both
    documented maps are imported above; the calibrated one is the one Section
    4.2 says to prefer for a site with a known Indian baseline.

    Weights are the no-history model's (0.50 / 0.30 / 0.20), because a fallback
    by definition has no persisted baseline to score a deviation against.

    This signature used to take ``is_routine`` and ``p95_frp`` and read neither.
    They are gone rather than wired up: the export resolves "routine" from the
    *location* baseline, while ``severity/service.py`` prefers the *facility*
    baseline and the export then clears the flag outright for a mining or
    metallurgical site, so the flag available here is not the one the engine was
    scored with. Choosing the calibrated map on a flag that may disagree with
    the engine's would be a second divergence wearing the first one's name. The
    map is fixed instead, and wherever it lands away from the published score the
    caller's reconciliation row says so in as many tenths as it is off.
    """
    frp_raw = calculate_calibrated_frp_severity(inc.current_max_frp or 0.0)
    ai_raw = round(max(0.0, min(1.0, ai_conf)) * 100.0, 1)

    return [
        {
            "factor": "Fire Radiative Power",
            "score": round(0.50 * frp_raw, 1),
            "max": 50.0,
            "detail": (
                f"{inc.current_max_frp:.1f} MW, India-calibrated S_FRP {frp_raw:.1f}/100 "
                f"(P50 {4.05} MW)"
            ),
        },
        {
            "factor": "Vision AI Source Severity",
            "score": round(0.30 * ai_raw, 1),
            "max": 30.0,
            "detail": f"{int(ai_conf * 100)}% model certainty -> source severity {ai_raw:.1f}/100",
        },
        {
            "factor": "GIS Context",
            "score": round(0.20 * gis_score, 1),
            "max": 20.0,
            "detail": (
                "Thermal event inside facility footprint" if is_inside_fac
                else (f"Nearest infrastructure {dist_km:.2f} km away" if dist_km < 900 else "No mapped infrastructure within 5 km")
            ),
        },
    ]

def generate_console_feed_data(db: Session) -> Dict[str, Any]:
    """
    Generates latest active incidents and ambient detections from SQLite database
    in the full unified console structure with climatology and sovereign territorial filtering.

    Pure read. This backs ``GET /api/console/feed``, which the console fetches on
    load, so nothing here may write or commit -- see ``_read_cached_location_baseline``.
    The data it reads is populated by ``run_severity_sweep`` during an analysis
    run, which is why the run must complete before the feed is meaningful.
    """
    incidents = db.query(Incident).filter(
        Incident.status.in_(list(CONSOLE_ACTIVE_STATUSES))
    ).all()

    # Sensor provenance for each incident: the satellite, sensor and FIRMS
    # product of its most recent detection. Prefetched in one pass rather than
    # per incident -- the loop below already queries twice per row, and this
    # reads a 1,278-row association table against a 2.9M-row observation table,
    # so doing it 295 times to answer the same question is pure waste.
    #
    # 93 of the 295 console-active incidents are built from detections spanning
    # more than one product, so there is no single right answer for the whole
    # incident and the choice has to be stated: this is the product of the
    # detection the row is stamped with (`acq_date`/`acq_time`, which come from
    # `inc.last_detected_at`), so the provenance line describes the same pass as
    # the timestamp beside it. `is_primary` is not used for this: it marks the
    # association the clusterer seeded from, which need not be the latest.
    detection_meta: Dict[str, Any] = {}
    if incidents:
        link_rows = (
            db.query(
                IncidentObservation.incident_id,
                Observation.acquired_at,
                Observation.satellite,
                Observation.sensor,
                Observation.product,
            )
            .join(Observation, Observation.id == IncidentObservation.observation_id)
            .filter(IncidentObservation.incident_id.in_([inc.id for inc in incidents]))
            .all()
        )
        for inc_id, acquired_at, sat, sensor, product in link_rows:
            prev = detection_meta.get(inc_id)
            if prev is None or (acquired_at is not None and (prev[0] is None or acquired_at > prev[0])):
                detection_meta[inc_id] = (acquired_at, sat, sensor, product)

    v1_incidents = []
    for inc in incidents:
        # Enforce sovereign airspace boundary (strictly Indian territory)
        if not is_within_indian_sovereign_territory(inc.latitude, inc.longitude):
            continue
        latest_inv = db.query(AIInvestigation).filter(
            AIInvestigation.incident_id == inc.id
        ).order_by(AIInvestigation.created_at.desc()).first()

        # Locate latest severity assessment
        latest_sev = db.query(SeverityAssessment).filter(
            SeverityAssessment.incident_id == inc.id
        ).order_by(SeverityAssessment.created_at.desc()).first()

        # Multi-layer intelligence classification & uncertainty resolution.
        # Read-only: the analysis run materialises these rows.
        base_dict = _read_cached_location_baseline(db, inc.latitude, inc.longitude)
        is_routine = base_dict.get("is_routine_flare", False)
        median_frp = base_dict.get("median_frp", 0.0)
        p95_frp = base_dict.get("p95_frp", 0.0)
        active_days_365 = base_dict.get("active_days_365d") or base_dict.get("active_days", 0)

        # 1. Sovereign mining basin check
        is_in_mining, mining_basin_meta = is_in_major_mining_basin(inc.latitude, inc.longitude)

        # 2. Authoritative industrial asset resolution (geometric containment or proximity buffer)
        asset_info = find_nearest_asset(inc.latitude, inc.longitude, db)
        dist_km = asset_info.get("distance_km") or 999.0
        is_inside_fac = asset_info.get("is_inside_facility", False)
        is_near = is_inside_fac or (dist_km <= 5.0)

        fac_name = asset_info.get("facility_name") if is_near else (inc.asset.name if inc.asset and (inc.distance_to_asset_km or 999) <= 5.0 else None)
        fac_type = asset_info.get("facility_type") if is_near else (inc.asset.facility_type if inc.asset else "")
        fac_industry = asset_info.get("industry") if is_near else (inc.asset.industry if inc.asset else "")
        fac_operator = asset_info.get("operator") if is_near else (inc.asset.operator if inc.asset else "")
        fac_address = asset_info.get("display_address") if is_near else (inc.asset.display_address if inc.asset else "")
        fac_category = asset_info.get("category") if is_near else (inc.asset.category if inc.asset else "")

        is_metal_fac = is_near and (
            is_metallurgical_or_manufacturing_facility(fac_type, fac_industry)
            or fac_category == "industrial_fire"
        )
        is_flare_fac = is_near and is_flaring_facility(fac_type, fac_category)

        # Decouple false routine flare flag for mining basins and metallurgical complexes
        if is_in_mining or is_metal_fac:
            is_routine = False

        # Landcover context for the Section 5 classification rule. The spec
        # (line 294) resolves the open-terrain case spatially: cropland and not
        # protected -> agricultural_burning; inside a national park, sanctuary
        # or montane canopy -> wildfire. The cascade below used an FRP threshold
        # and a state-name membership test instead, so the protected-area clause
        # had no spatial test at all and Punjab/Haryana/UP stood in for a
        # cropland mask (F-036). resolve_landcover is the existing primitive.
        try:
            landcover = resolve_landcover(inc.latitude, inc.longitude, nearest_asset_distance_km=dist_km, nearest_asset_category=fac_category or "")
        except Exception as lc_err:
            logger.warning(f"[Feed] Landcover resolution failed for {inc.id}: {lc_err}")
            landcover = {}
        is_cropland = landcover.get("primary_landcover") == "agricultural_cropland"
        is_protected = bool(landcover.get("is_protected_area", False))

        # INV-1 provenance. A `latest_inv` row is the only evidence that a vision
        # model actually looked at this detection. Everything else in the cascade
        # below -- a stored `inc.classification` written by a geometry script, or
        # a mining-basin / facility inference -- is a spatial prior, not a
        # verification. Once published as `ai_classification`/`ai_confidence` the
        # two are indistinguishable, so the distinction is carried explicitly
        # here and the unverified branches are held at the same ceiling
        # `intelligence/provider.py` applies when the model is unavailable. That
        # cap also keeps an unverified label below the `ai_confidence >= 80`
        # severity override gate in `severity/scoring.py`.
        ai_verified = bool(
            latest_inv and latest_inv.classification and latest_inv.classification != "uncertain"
        )
        unverified_conf = FALLBACK_CONFIDENCE_CEILING / 100.0

        if latest_inv and latest_inv.classification and latest_inv.classification != "uncertain":
            cls_name = latest_inv.classification
            # Geometry can override a vision verdict here, but the override is
            # reported rather than written back. `generate_console_feed_data` is
            # documented as a pure read, and assigning to `latest_inv.reasoning`
            # mutated a mapped object that any later commit on the shared session
            # would flush into the investigation record (D-13) -- overwriting the
            # model's own reasoning with text no model produced.
            rectified_reason = None
            if cls_name == "mining_related":
                cls_name = "mining_or_other_thermal_source"
            elif is_in_mining and cls_name == "gas_flare":
                # Rectify misclassification caused by old routine flare metadata
                cls_name = "mining_or_other_thermal_source"
                rectified_reason = (
                    f"Geometric reclassification to open-cast coal/mineral mining inside "
                    f"{mining_basin_meta['name']} ({mining_basin_meta['operator']}); vision returned gas_flare."
                )
            elif is_metal_fac and cls_name == "gas_flare":
                # Rectify misclassification of steel plant / smelter furnace
                cls_name = "industrial_fire"
                rectified_reason = (
                    f"Geometric reclassification to metallurgical furnace / smelter process at "
                    f"{fac_name} ({fac_operator}); vision returned gas_flare."
                )
            ai_conf = (latest_inv.confidence or 85.0) / 100.0
            ai_unc = "low" if ai_conf >= 0.75 else "medium"
            ai_reason = rectified_reason or latest_inv.reasoning or f"Multimodal AI inspection classified thermal event as {cls_name}."
        elif inc.classification and inc.classification != "uncertain":
            cls_name = inc.classification
            if cls_name == "mining_related":
                cls_name = "mining_or_other_thermal_source"
            elif is_in_mining and cls_name == "gas_flare":
                cls_name = "mining_or_other_thermal_source"
            elif is_metal_fac and cls_name == "gas_flare":
                cls_name = "industrial_fire"
            # This branch is only reached when `latest_inv` is absent, so the
            # stored label is a spatial prior, not a verdict. It is capped
            # rather than trusted: `refresh_*_incidents.py` writes 88.0/90.0 here
            # from pure geometry, and those values previously satisfied the
            # CRITICAL industrial override in `severity/scoring.py` on their own.
            ai_conf = unverified_conf
            ai_unc = "medium"
            ai_reason = (
                "Spatial prior only -- no vision investigation on record. "
                f"Stored classification: {cls_name}."
            )
        elif is_in_mining:
            cls_name = "mining_or_other_thermal_source"
            ai_conf = unverified_conf
            ai_unc = "medium"
            ai_reason = f"Geometric context only: detection inside the mapped {mining_basin_meta['name']} concession ({mining_basin_meta['operator']}). No vision investigation."
        elif is_metal_fac:
            cls_name = "industrial_fire"
            ai_conf = unverified_conf
            ai_unc = "medium"
            ai_reason = f"Geometric context only: detection inside the mapped metallurgical facility {fac_name} ({fac_industry}). No vision investigation."
        elif is_flare_fac:
            cls_name = "gas_flare"
            ai_conf = unverified_conf
            ai_unc = "medium"
            ai_reason = f"Geometric context only: detection at the mapped flaring facility {fac_name} ({fac_operator}). No vision investigation."
        elif is_routine:
            cls_name = "gas_flare"
            ai_conf = unverified_conf
            ai_unc = "medium"
            ai_reason = f"Baseline-only routine flare: {active_days_365} active days against the 365-day baseline (median {median_frp:.1f} MW). No vision investigation."
        # Authoritative industrial classification gate: requires physical containment or <= 1.5 km buffer.
        #
        # This branch used to promote a pure geometry-plus-FRP heuristic to
        # `uncontrolled_industrial_fire` at confidence 0.88 with "low"
        # uncertainty, and the console renders that class as a critical-tier
        # fire (frontend/js/config.js). Nothing about it was verified: it fired
        # whenever a raw FIRMS detection sat inside or within 1.5 km of a mapped
        # facility and peaked above 25 MW, including when the vision model had
        # explicitly returned `uncertain` (the two branches above are both gated
        # on `!= "uncertain"`, so an uncertain verdict falls through to here).
        # `uncontrolled_industrial_fire` is also not one of Section 5/6.2's six
        # canonical classes, so the console was publishing a label the vision
        # model can never produce (F-038/INV-1).
        #
        # Geometry alone cannot distinguish an uncontrolled fire from an
        # ordinary process heat signature, so the honest output is the
        # documented `uncertain`, at a confidence that reflects what is
        # actually known.
        elif is_near and (is_inside_fac or dist_km <= 1.5):
            cls_name = "uncertain"
            ai_conf = 0.45
            ai_unc = "high"
            ai_reason = (
                f"Thermal anomaly ({inc.current_max_frp:.1f} MW) inside the {fac_name} perimeter has not been "
                f"verified by optical inspection; process heat, an operational flare and an uncontrolled fire "
                f"are indistinguishable from radiance alone."
            )
        elif is_protected:
            # Section 5: protected park / sanctuary / montane canopy -> wildfire.
            cls_name = "wildfire"
            ai_conf = 0.80
            ai_unc = "low"
            ai_reason = f"Thermal front inside a protected area ({landcover.get('protected_area_name') or 'notified zone'}) at {inc.latitude:.3f}°N, {inc.longitude:.3f}°E."
        elif is_cropland:
            # Section 5: cropland and not protected -> agricultural_burning.
            cls_name = "agricultural_burning"
            ai_conf = 0.80
            ai_unc = "low"
            ai_reason = f"Biomass combustion inside mapped cropland in {inc.district or inc.state or 'the agricultural belt'}."
        # Open terrain, no landcover evidence. These two branches used to name a
        # cause from radiance alone -- `wildfire`, at 0.84 and 0.78 confidence
        # with "low" uncertainty, for anything at or above 6 MW, reasoned as
        # "Vegetative biomass combustion observed in natural terrain". Nothing
        # was observed. `is_protected` above is the only vegetation test this
        # platform can actually run, and `resolve_landcover`'s final fallback is
        # `mixed_vegetation_and_shrubland`, a catch-all meaning "unclassified"
        # rather than "vegetated". The FRP threshold was F-036's replacement for
        # a cropland mask, and it reproduced that defect's false precision with
        # the sign flipped: from an FRP number it asserted a land cover.
        #
        # The measurements contradicted the label besides. Of the 13 incidents
        # these branches served, four sat in cells with no measurable envelope at
        # all, and four more were at or *below* their own cell's 365-day P95
        # (11.33 MW against 11.7, 7.04 against 6.8) -- a site inside its normal
        # operating range, which is the opposite of a front "spreading across
        # open terrain".
        #
        # INV-1 is why that matters: `ai_unc` gates the console's "optically
        # confirmed" badge, and although the cap below held these at "medium"
        # rather than "low", the class name itself still reached the operator as
        # a wildfire. Radiance cannot separate a vegetation fire from
        # agricultural residue burning, a landfill or a smouldering tip, so the
        # documented output for an unverified open-terrain detection is
        # `uncertain` -- the conclusion the facility branch above already reaches
        # for the same reason.
        #
        # Magnitude is a priority signal, not a class signal, and it is still
        # published as one: `MAJOR_FIRE_SURGE` in `triggers` below and the
        # major-surge wording in `p_expl` both key on FRP. What the platform does
        # know about this detection is carried in the reason and in
        # `historical_anomaly` rather than promoted into the class name. Naming a
        # cause here would need an optical pass, which is what `latest_inv` is.
        else:
            cls_name = "uncertain"
            ai_conf = 0.45
            ai_unc = "medium"
            if p95_frp > 0 and inc.current_max_frp > p95_frp:
                ai_reason = (
                    f"Unverified open-terrain thermal anomaly ({inc.current_max_frp:.1f} MW) at "
                    f"{inc.latitude:.3f}°N, {inc.longitude:.3f}°E, above this cell's 365-day P95 "
                    f"({p95_frp:.1f} MW). No vegetation or landcover evidence on record, so the cause "
                    f"is not visually confirmable."
                )
            elif p95_frp > 0:
                ai_reason = (
                    f"Unverified open-terrain thermal anomaly ({inc.current_max_frp:.1f} MW) at "
                    f"{inc.latitude:.3f}°N, {inc.longitude:.3f}°E, within this cell's 365-day P95 "
                    f"({p95_frp:.1f} MW) over {active_days_365} active days. A recurring source "
                    f"behaving inside its measured envelope; the cause is not visually confirmable."
                )
            else:
                ai_reason = (
                    f"Unverified open-terrain thermal anomaly ({inc.current_max_frp:.1f} MW) at "
                    f"{inc.latitude:.3f}°N, {inc.longitude:.3f}°E. This cell has no measurable 365-day "
                    f"baseline, so neither the anomaly nor the cause can be established (INV-5)."
                )

        # INV-1, applied once for the whole cascade rather than branch by branch.
        # Every branch above that is reached without a `latest_inv` row is an
        # inference -- from a basin polygon, a facility perimeter, a landcover
        # class or an FRP threshold -- however specific its wording. The console
        # derives its "optically confirmed" badge from `ai_unc`
        # (frontend/js/data.js: `confirmed = uncertainty is low|none and FIRMS
        # confidence >= 30`), so an uncapped inference is published to the
        # operator as a confirmed detection. Capping here keeps a geometric guess
        # from ever rendering as one, and keeps it below the `ai_confidence >= 80`
        # override gate.
        if not ai_verified:
            ai_conf = min(ai_conf, unverified_conf)
            ai_unc = "high" if cls_name == "uncertain" else "medium"

        # Note on two removed branches. The cascade used to classify mining by
        # state membership (`inc.state in ["Jharkhand", "Odisha", "Chhattisgarh"]`)
        # and agricultural burning by `inc.state in ["Punjab", "Haryana",
        # "Uttar Pradesh"]`. Section 5 line 292 defines the mining rule
        # geometrically -- coordinates inside a registered mining basin -- and
        # line 294 defines the cropland rule spatially, so a state name is a
        # proxy for a test the platform can actually run. Both are now made
        # against `is_in_mining` (registered basins) and `is_cropland`
        # (landcover), leaving the state name where it belongs: in the label.

        ai_ev = latest_inv.evidence_points if (latest_inv and latest_inv.evidence_points) else []

        # Operational triggers
        triggers = []
        if is_in_mining:
            triggers.append("SOVEREIGN_MINING_CONCESSION")
        if is_near:
            triggers.append("CRITICAL_INFRASTRUCTURE")
        if inc.current_max_frp >= 50.0:
            triggers.append("MAJOR_FIRE_SURGE")
        if inc.status == "PERSISTENT" or is_routine or is_metal_fac:
            triggers.append("24H_TEMPORAL_PERSISTENCE")

        # Priority explanation: Why selected for optical investigation
        if is_in_mining:
            p_expl = f"Active sovereign mining basin ({mining_basin_meta['name']}). Monitored against historical P95 baseline ({p95_frp:.1f} MW)."
        elif is_metal_fac:
            p_expl = f"Heavy industrial / metallurgical infrastructure ({fac_name}). Monitored against historical P95 envelope ({p95_frp:.1f} MW)."
        elif is_routine:
            p_expl = f"Routine industrial flare site ({active_days_365} active days/year). Monitored against historical P95 envelope ({p95_frp:.1f} MW)."
        elif inc.current_max_frp >= 50.0:
            p_expl = f"Major thermal surge ({inc.current_max_frp:.1f} MW) exceeding 99th percentile threshold with elevated spread risk."
        elif is_near:
            p_expl = f"High-value infrastructure proximity: detected inside footprint of {fac_name}."
        elif inc.observation_count and inc.observation_count > 3:
            p_expl = f"Spatial multi-pixel cluster ({inc.observation_count} satellite detections) with elevated total radiative intensity."
        else:
            p_expl = f"Thermal anomaly flagged for optical satellite verification at {inc.latitude:.3f}°N, {inc.longitude:.3f}°E."

        # Historical anomaly evaluation. Classified from the already-resolved
        # routine/mining/metallurgical context rather than a fourth rule, so this
        # label and the classification above cannot disagree about the same site.
        if is_routine:
            hist_anomaly = "ROUTINE_FLARE"
        elif is_in_mining or is_metal_fac:
            hist_anomaly = "ABNORMAL_SURGE" if (p95_frp > 0 and inc.current_max_frp > p95_frp) else "NORMAL_BASELINE"
        elif p95_frp > 0 and inc.current_max_frp > p95_frp:
            hist_anomaly = "ABNORMAL_SURGE"
        elif active_days_365 >= 10:
            hist_anomaly = "NORMAL_BASELINE"
        else:
            hist_anomaly = "NEW_UNEXPECTED"

        # Risk-factor breakdown. Prefer the persisted assessment, whose factors
        # are the model's own component scores, and render them as weighted
        # contributions so the rows sum to the published risk_score. Only when no
        # assessment has been persisted does the fallback build a breakdown, and
        # it uses the specification's own FRP normalisation.
        #
        # The renderer is told the score this record is about to publish, so a
        # breakdown reconciles with the number beside it even for an assessment
        # written before the current scoring model -- which is the only case
        # where it cannot reconstruct the score from the factors alone.
        #
        # A record is published either with a breakdown that sums to its
        # `risk_score` exactly, or with no breakdown at all. There is no third
        # state: a score of zero is nothing to break down, and dragging the
        # fallback's rows down to zero to fill one in would misstate every row.
        published_score = round(float(inc.severity_score or 0.0), 1)
        factors_list: List[Dict[str, Any]] = []
        from_assessment = False
        if published_score > 0.0:
            if latest_sev and latest_sev.factors:
                factors_list = _weighted_risk_factors(
                    latest_sev.factors, published_score=published_score
                )
                from_assessment = bool(factors_list)
            if not factors_list:
                # Either no assessment was ever persisted, or the one that was
                # is not in this model's shape. Either way the fallback scores
                # the incident itself rather than reproducing the engine's
                # arithmetic, so its sum is its own opinion of the score; name
                # the difference instead of publishing it silently.
                factors_list = _reconcile_to(
                    _fallback_risk_factors(
                        inc, ai_conf, is_inside_fac, dist_km, gis_score=15.0
                    ),
                    published_score,
                    {},
                    "stale" if (latest_sev and latest_sev.factors) else "absent",
                )

        # The score this record publishes is the engine's -- the same number that
        # set `severity_level` above and that the alert was raised against.
        #
        # It used to be replaced by the sum of the rendered factors whenever the
        # two differed by more than 0.15, which made the breakdown the authority
        # over the assessment. That inverted the dependency: `risk_tier` is
        # `score_to_level(risk_score)` while `severity_level` and
        # `action_recommendation` come from the engine, so the override published
        # contradictions -- INC-2026-0348 went out as score 70.5 / tier HIGH
        # beside severity_level CRITICAL, and INC-2026-0284, a routine flare,
        # went out at 34.2 when INV-4 puts a hard ceiling of 20.0 on it. The
        # divergence is a fact about the record, not a correction to apply: the
        # renderer reports it as a labelled row, and this logs it.
        risk_score = published_score
        risk_score_from_factors = round(sum(f["score"] for f in factors_list), 1)
        unexplained = [f for f in factors_list if f["factor"] == UNRECONCILED_FACTOR_LABEL]
        reasons_for_warning = []
        if unexplained:
            if from_assessment:
                reasons_for_warning.append(
                    "the breakdown could not attribute the score to its own factors "
                    "(the assessment predates the current scoring model)"
                )
            elif latest_sev and latest_sev.factors:
                reasons_for_warning.append(
                    "the persisted assessment is not in the current scoring model's "
                    "shape, so the breakdown is the fallback model's"
                )
            else:
                reasons_for_warning.append(
                    "no severity assessment is persisted for this incident, so the "
                    "breakdown is the fallback model's rather than the engine's"
                )
        if abs(risk_score - risk_score_from_factors) > 0.05:
            reasons_for_warning.append(
                f"the rows sum to {risk_score_from_factors}, not {risk_score}"
            )
        if latest_sev and abs(round(float(latest_sev.score or 0.0), 1) - risk_score) > 0.05:
            reasons_for_warning.append(
                f"the persisted assessment scores {round(float(latest_sev.score or 0.0), 1)}"
            )
        if reasons_for_warning:
            logger.warning(
                f"[Feed] {inc.incident_code}: {'; '.join(reasons_for_warning)}. The score "
                f"published is the severity engine's -- the one severity_level and the "
                f"alert were raised against -- so it is left as it stands; re-run the "
                f"severity sweep to regenerate the assessment."
            )

        rec_action = (
            "IMMEDIATE EMERGENCY DISPATCH & REGULATORY AUDIT" if (inc.severity_level == "CRITICAL")
            else ("TACTICAL DISPATCH: HIGH PRIORITY ON-SITE HAZARD INVESTIGATION" if inc.severity_level == "HIGH"
            else ("ROUTINE LOGGING: MONITOR FACILITY THERMAL EMISSION ENVELOPE" if inc.severity_level == "MEDIUM"
            else "BACKGROUND MONITORING: NOMINAL LOW-RISK SATELLITE DETECTION"))
        )

        location_label = (
            fac_name if (is_near and fac_name)
            else (f"{mining_basin_meta['name']}" if is_in_mining
            else (f"{inc.district}, {inc.state}" if (inc.district and inc.state)
            else (inc.state or "National Sector")))
        )
        display_label = (
            fac_address if (is_near and fac_address)
            else (f"{mining_basin_meta['district']}, {mining_basin_meta['state']}, India" if is_in_mining
            else (f"{inc.district or 'Site'}, {inc.state or 'India'}"))
        )

        persistence_pat = (
            "PERSISTENT_MINING_THERMAL_SOURCE" if is_in_mining
            else ("PERSISTENT_METALLURGICAL_EMISSION" if is_metal_fac
            else ("RECURRING_INDUSTRIAL_FLARE" if (is_routine or (inc.status == "PERSISTENT" and cls_name == "gas_flare"))
            else ("PERSISTENT_THERMAL_SOURCE" if inc.status == "PERSISTENT"
            else "NEW_DETECTION")))
        )

        det_satellite, det_sensor, det_product = (
            detection_meta.get(inc.id, (None, None, None, None))[1:]
        )

        v1_inc = {
            "id": inc.id,
            "incident_code": inc.incident_code,
            "latitude": inc.latitude,
            "longitude": inc.longitude,
            "facility_distance_km": round(dist_km, 3) if is_near else None,
            "nearest_facility_name": fac_name if is_near else (mining_basin_meta["name"] if is_in_mining else None),
            # The registry key for the facility `nearest_facility_name` names.
            # The name alone is not an identifier: `mining_basin_meta["name"]` is
            # a *basin* label, not an `industrial_assets` row, so four of the
            # seven names the feed published were coal basins standing in for
            # facilities -- and one site appeared twice under two spellings
            # ("Talcher Coalfields & NTPC Super Thermal Corridor (Angul)" from the
            # basin registry and "... Super Thermal Power Complex" from the asset
            # registry), which the console's name-grouping counted as two
            # monitored facilities. `is_near` is the same gate the name uses, so
            # the id and the name always describe the same row or neither is set.
            "nearest_asset_id": asset_info.get("asset_id") if is_near else None,
            "facility_type": fac_type if is_near else ("open_cast_coal_mine" if is_in_mining else None),
            "operator": fac_operator if is_near else (mining_basin_meta["operator"] if is_in_mining else None),
            "frp": inc.current_max_frp,
            # INV-2: FRP is never summed. This key used to be `cluster_total_frp`
            # while carrying the incident maximum, so the one field name in the
            # published payload that asserted a total was the one field that must
            # not be one. No consumer read it (grep of frontend/js and index.html
            # is empty), but it is written to incidents.json where a reader can
            # see it. `frp` above is the same value under the honest name.
            "cluster_max_frp": inc.current_max_frp,
            "cluster_pixel_count": inc.observation_count or 1,
            "operational_triggers": triggers,
            # The satellite's own confidence in the detection (C_firms), which is
            # what the console labels "Satellite confidence" / "Sensor
            # confidence". This used to be `"HIGH" if severity_confidence >= 70
            # else "NOMINAL"` -- the severity engine's certainty about its own
            # verdict, published under the detection's name. `dossier.js` carries
            # an explicit comment that keeping the model's confidence and the
            # satellite's apart "is the point", so a band derived from the wrong
            # quantity defeated the one distinction the panel makes.
            # `parseConfidence` reads a numeric percent directly, so no band has
            # to be invented for a value the satellite did report.
            "confidence": f"{float(inc.firms_confidence):.1f}%" if inc.firms_confidence is not None else "",
            "satellite": det_satellite or "unreported",
            # These two were literals here -- "VIIRS / MODIS" and "VIIRS" -- so
            # every incident in the payload claimed the same provenance: the
            # Aqua and Terra (MODIS) detections in the active set were published
            # as VIIRS, and 93 incidents built from more than one product were
            # published as if there were only one. Both columns are populated on
            # all 2,895,133 observations, so nothing had to be invented.
            #
            # `satellite` is the platform code the FIRMS row carries (SNPP, N20,
            # N21, Aqua, Terra). The instrument is read out of the product id
            # rather than taken from `sensor`, because `sensor` disagrees with
            # itself: on the 894,307 SNPP rows it holds the platform ("SNPP")
            # where the other 2,000,826 rows hold the instrument ("VIIRS" /
            # "MODIS"). The product id is consistently `{INSTRUMENT}_{PLATFORM}_
            # {TYPE}` across all nine combinations in the corpus, so its first
            # token is the instrument on every row. `sensor` is the fallback for
            # a row with no product.
            "instrument": (det_product or "").split("_")[0] or det_sensor or "unreported",
            "product": det_product or "unreported",
            "acq_date": inc.last_detected_at.strftime("%Y-%m-%d") if inc.last_detected_at else "",
            "acq_time": inc.last_detected_at.strftime("%H:%M") if inc.last_detected_at else "",
            "location_name": location_label,
            "display_name": display_label,
            "ai_classification": cls_name,
            "ai_confidence": round(ai_conf, 2),
            "ai_uncertainty": ai_unc,
            # Whether a vision model actually ran on this detection, as opposed
            # to a spatial prior having supplied the label. Published so the
            # console can distinguish the two without inferring it from the
            # confidence value.
            "ai_verified": ai_verified,
            "ai_evidence": ai_ev if isinstance(ai_ev, list) else [str(ai_ev)],
            "ai_reasoning": ai_reason,
            "image_url": f"/crops/{inc.id}/annotated.jpg",
            "raw_image_url": f"/crops/{inc.id}/raw.jpg",
            "persistence_pattern": persistence_pat,
            "persistence_description": f"Historical 365-day baseline tracking ({active_days_365} active days). Baseline P95: {p95_frp:.1f} MW.",
            "persistence_detections": inc.observation_count or 1,
            "days_active": max(1, active_days_365),
            "day_night_status": "DAY + NIGHT (Continuous 24h)" if base_dict.get("night_ratio", 0) > 0.3 else "PRIMARILY DAY OVERPASS",
            "risk_score": round(risk_score, 1),
            "risk_tier": score_to_level(risk_score),
            "investigation_priority": round(inc.investigation_priority or 0.0, 1),
            # `priority_rank` is assigned over the finished queue below, not read
            # off the row: Incident carries no such column, so
            # `getattr(inc, "priority_rank", 1)` returned the literal 1 for every
            # record. All 319 rows in the committed payload shipped rank 1 while
            # their investigation_priority spanned 118 distinct values, and
            # data.js:150 sorts the board by exactly this field -- so the
            # console's queue was never ordered.
            "priority_rank": 0,
            "priority_explanation": p_expl,
            "severity_score": round(float(inc.severity_score or 0.0), 1),
            "severity_level": inc.severity_level or "LOW",
            "severity_confidence": round(float(inc.severity_confidence or 0.0), 1),
            # Aggregate NASA FIRMS confidence of this incident's own detections
            # (C_firms). `confidence` above is the assessment's certainty and is
            # a different quantity -- the console used to show only that one,
            # labelled as if it described the detections.
            "firms_confidence": round(float(inc.firms_confidence), 1) if inc.firms_confidence is not None else None,
            "historical_anomaly": hist_anomaly,
            "baseline_median": round(median_frp, 1),
            "baseline_p90": round(base_dict.get("p90_frp", 0.0), 1),
            "baseline_p95": round(p95_frp, 1),
            "active_days_365d": active_days_365,
            "is_routine_flare": is_routine,
            "action_recommendation": rec_action,
            "risk_factors": factors_list,
            # The state the incident sits in, published so the console's site
            # search can match on it. `index.html:321` advertises the field --
            # "Search facility, operator, state (e.g. IOCL, Jamnagar, Odisha)"
            # -- and `render.js:1347` filters on `s.top.state`, which
            # `normaliseCase` never set because nothing here emitted it, so the
            # third of the three advertised search terms could never match
            # anything. Populated on all 386 incident rows (295 of them
            # console-active) and already used for the location labels above.
            "state": inc.state,
            "status": inc.status
        }
        v1_incidents.append(v1_inc)

    # Ambient points (recent 200 observations within sovereign territory)
    recent_obs = db.query(Observation).order_by(Observation.acquired_at.desc()).limit(300).all()
    ambient = [
        {
            "lat": o.latitude,
            "lon": o.longitude,
            "frp": o.frp_mw,
            "conf": o.confidence_raw or "nominal",
            "sat": o.satellite or "VIIRS",
            "date": o.acquired_at.strftime("%Y-%m-%d") if o.acquired_at else "",
            "time": o.acquired_at.strftime("%H:%M") if o.acquired_at else "",
            "pass_type": o.daynight or "D"
        }
        for o in recent_obs
        if is_within_indian_sovereign_territory(o.latitude, o.longitude)
    ][:200]

    # Rank the finished queue by investigation_priority, highest first, and
    # publish that rank as 1..N. data.js:150 sorts the board by this field, so it
    # has to be a rank rather than a constant; `priority_rank` is otherwise
    # absent from the schema entirely. `sorted` is stable, so equal priorities
    # keep the query's own order (which `order_by` above makes deterministic) and
    # the ranking does not shuffle between runs.
    for rank, row in enumerate(
        sorted(v1_incidents, key=lambda r: r["investigation_priority"], reverse=True),
        start=1,
    ):
        row["priority_rank"] = rank

    # Tier histogram over the pubished queue, so a reader can see what the board
    # actually holds without re-deriving it. This is the number J4 was about:
    # before the severity sweep ran over the whole queue it read `{LOW: 322,
    # MEDIUM: 1}` with zero HIGH and zero CRITICAL while the alert feed held five
    # CRITICAL and five HIGH alerts.
    tier_histogram = {level: 0 for _, _, level in SEVERITY_LEVELS}
    for row in v1_incidents:
        tier_histogram[row["risk_tier"]] = tier_histogram.get(row["risk_tier"], 0) + 1

    # Closed-alert roll-up. RESOLVED and DISMISSED incidents are correctly absent
    # from a live triage queue, but the alerts raised against them are still in
    # `alert_records`, and a console that shows a calm board while its own alert
    # feed holds open CRITICAL alerts is the first thing a reviewer notices.
    # Reporting the closed set separately keeps the queue honest without
    # resurrecting closed incidents into it.
    closed_q = db.query(Incident).filter(
        Incident.status.in_(list(CONSOLE_CLOSED_STATUSES)),
        Incident.severity_level.in_(list(ATTENTION_TIERS)),
    ).order_by(Incident.last_detected_at.desc()).all()

    closed_attention = [
        {
            "id": c.id,
            "incident_code": c.incident_code,
            "latitude": c.latitude,
            "longitude": c.longitude,
            "status": c.status,
            "severity_level": c.severity_level,
            "severity_score": round(float(c.severity_score or 0.0), 1),
            "last_detected_at": c.last_detected_at.isoformat() if c.last_detected_at else None,
            "open_alerts": sum(
                1 for a in db.query(AlertRecord).filter(AlertRecord.incident_id == c.id).all()
                if a.status == "NEW"
            ),
        }
        for c in closed_q
        if is_within_indian_sovereign_territory(c.latitude, c.longitude)
    ]

    return {
        "incidents": v1_incidents,
        "ambient": ambient,
        "queue_summary": {
            "active_count": len(v1_incidents),
            "tier_histogram": tier_histogram,
            "attention_count": tier_histogram.get("HIGH", 0) + tier_histogram.get("CRITICAL", 0),
            "closed_attention_count": len(closed_attention),
            "active_statuses": list(CONSOLE_ACTIVE_STATUSES),
        },
        "closed_attention": closed_attention,
    }


def run_severity_sweep(db: Session, force: bool = False) -> Dict[str, Any]:
    """Run the severity engine over the whole displayable queue.

    R15. ``export_v1_dashboard_data`` writes ``risk_score`` and ``risk_factors``
    straight out of the incident row, but the severity engine only ever ran on
    the handful of incidents the selection stage picked for optical
    investigation -- ``max_ai_targets``, five by default. Everything else kept
    the schema default ``severity_score = 0.0``, so 321 of 341 live incidents
    published ``risk_score: 0`` and a uniform LOW board, while the alert feed
    held CRITICAL alerts against incidents the board could not show. The console
    and the alert engine were reading two different systems.

    ``force=False`` (the default) evaluates only incidents whose assessment is
    missing, so a routine run costs one pass over the queue rather than
    re-deriving baselines for every incident every time. ``force=True``
    re-evaluates everything, which is what the data-repair path uses after the
    scoring rules change.

    Failures are collected and reported rather than raised: one incident with
    malformed telemetry must not abort the export for the other 320.
    """
    query = db.query(Incident).filter(Incident.status.in_(list(CONSOLE_ACTIVE_STATUSES)))
    if not force:
        # An incident is "assessed" once it carries a non-default score and a
        # persisted assessment row. `severity_score = 0.0` cannot be
        # distinguished from a genuine zero-severity verdict, so presence of the
        # assessment row is the reliable signal.
        assessed_ids = {
            row[0] for row in db.query(SeverityAssessment.incident_id).distinct().all()
        }
        query = query.filter(~Incident.id.in_(assessed_ids)) if assessed_ids else query

    targets = query.all()
    evaluated: List[str] = []
    failed: List[Dict[str, str]] = []

    for inc in targets:
        if not is_within_indian_sovereign_territory(inc.latitude, inc.longitude):
            continue
        try:
            result = evaluate_incident_severity(inc.id, db)
            evaluated.append(f"{inc.incident_code}:{result['severity_level']}")
        except Exception as sev_err:
            db.rollback()
            failed.append({"incident_code": inc.incident_code or inc.id, "error": str(sev_err)})
            logger.warning(f"[SeveritySweep] {inc.incident_code or inc.id} failed: {sev_err}")

    logger.info(
        f"[SeveritySweep] Evaluated {len(evaluated)} incidents "
        f"({len(failed)} failed); {len(targets) - len(evaluated) - len(failed)} out of scope."
    )
    return {
        "evaluated": len(evaluated),
        "failed": failed,
        "considered": len(targets),
    }


def _write_json_atomic(path: str, payload: Any) -> None:
    """Write JSON through a temporary file, so no reader sees a half-written one.

    The console falls back to these files when the API is unreachable, so a
    truncated write is not a transient glitch -- it is a console that silently
    loses its board. ``os.replace`` is atomic on both NTFS and POSIX.
    """
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp_path, path)


def export_v1_dashboard_data(db: Session) -> List[str]:
    """
    Exports latest active incidents and ambient detections to the v2 console and,
    where the archived v1 dashboard is present, mirrors them there too.

    Writes a bare array to ``incidents.json`` because that is what
    ``frontend/js/data.js`` expects on its static-fallback path; the queue
    summary and the closed-alert roll-up go to a sibling file so the fallback
    keeps working unchanged.

    Returns the directories actually written. Callers report that rather than a
    fixed claim: ``cli.py`` used to print "frontend/data/ and v1/dashboard/data/"
    whether or not a v1 tree was there to write to, and the caller in
    ``scripts/clean_foreign_and_refresh.py`` already prints this return value.

    Never raises on a write failure -- a console that cannot persist its feed is
    a warning, not a failed analysis run -- so an empty return plus the logged
    warning is how a caller learns nothing was written.
    """
    written: List[str] = []
    try:
        data = generate_console_feed_data(db)
        v1_incidents = data["incidents"]
        ambient = data["ambient"]
        summary = data.get("queue_summary", {})
        closed_attention = data.get("closed_attention", [])

        for target_dir in _export_targets():
            try:
                os.makedirs(target_dir, exist_ok=True)
                inc_path = os.path.join(target_dir, "incidents.json")
                _write_json_atomic(inc_path, v1_incidents)
                amb_path = os.path.join(target_dir, "ambient_firms.json")
                _write_json_atomic(amb_path, ambient)
                sum_path = os.path.join(target_dir, "queue_summary.json")
                _write_json_atomic(
                    sum_path, {**summary, "closed_attention": closed_attention}
                )
                written.append(target_dir)
            except Exception as ex:
                logger.warning(f"[Export] Could not write data to {target_dir}: {ex}")

        logger.info(
            f"[Export] Synchronized {len(v1_incidents)} incidents and {len(ambient)} ambient points "
            f"to {', '.join(written) or 'no target'}. Tiers: {summary.get('tier_histogram')}; "
            f"{len(closed_attention)} closed HIGH/CRITICAL incidents carry open alerts."
        )
    except Exception as e:
        logger.warning(f"[Export] Could not export data to dashboard data dir: {e}")
    return written


def execute_analysis_pipeline(
    db: Session,
    firms_csv: Optional[str] = None,
    file_path: Optional[str] = None,
    force_reinvestigate: bool = False,
    max_ai_targets: int = 5,
    export_to_dashboard: bool = True,
    run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes an end-to-end mission analysis run.
    Guarantees single execution via AnalysisRunLock and emits real-time SSE events.
    """
    if not run_id:
        run_id = f"RUN-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 1. Acquire Run Lock
    # Acquisition stays outside the try below on purpose: AnalysisAlreadyRunningError
    # is a contention outcome, not a run failure, and the API maps it to HTTP 409
    # rather than to a failed run (api/analysis.py). Everything *after* this point
    # must produce a terminal event, because the direct SSE stream blocks on this
    # run and only closes when it sees one (F-102).
    pipeline_lock.acquire(run_id)
    start_time = datetime.utcnow()
    t0 = time.time()
    run_record: Optional[AnalysisRun] = None

    try:
        # Create AnalysisRun audit record
        run_record = AnalysisRun(
            id=run_id,
            status="RUNNING",
            started_at=start_time
        )
        db.add(run_record)
        db.commit()

        event_broadcaster.publish(
            EVENT_ANALYSIS_STARTED,
            {
                "run_id": run_id,
                "started_at": start_time.isoformat(),
                "message": f"Starting FIREX mission analysis run {run_id}"
            },
            run_id=run_id
        )

        # 2. FIRMS Telemetry Fetch & Normalization
        firms_client = FIRMSClient()
        new_obs_count = 0
        skipped_dup = 0
        total_fetched = 0

        try:
            if firms_csv:
                normalized_records = firms_client.parse_csv(firms_csv)
                save_res = firms_client.save_to_db(db, normalized_records)
                new_obs_count = save_res["ingested"]
                skipped_dup = save_res["skipped_duplicate"]
                total_fetched = save_res["total"]
            elif file_path and os.path.exists(file_path):
                save_res = firms_client.ingest_from_file(db, file_path)
                new_obs_count = save_res["ingested"]
                skipped_dup = save_res["skipped_duplicate"]
                total_fetched = save_res["total"]
            else:
                # Attempt live NASA fetch
                # NASA's area/csv API serves products as satellite+latency pairs
                # (VIIRS_NOAA20_NRT, VIIRS_SNPP_NRT, MODIS_NRT ...). The literal that
                # used to stand here, "VIIRS_NRT", is not one of them, so the request
                # asked for a product FIRMS does not serve, fetch_live_csv returned
                # None on every run, and the live branch always fell through to the
                # database. FIRMS_DEFAULT_PRODUCTS is exactly that served list.
                live_product = settings.FIRMS_DEFAULT_PRODUCTS[0]
                live_csv = firms_client.fetch_live_csv(live_product, days=1)
                if live_csv:
                    normalized_records = firms_client.parse_csv(live_csv, product=live_product)
                    save_res = firms_client.save_to_db(db, normalized_records)
                    new_obs_count = save_res["ingested"]
                    skipped_dup = save_res["skipped_duplicate"]
                    total_fetched = save_res["total"]
                else:
                    logger.info("[Pipeline] No live FIRMS payload fetched; proceeding with existing active observations.")
        except Exception as fe:
            logger.warning(f"[Pipeline] FIRMS ingestion warning: {fe}. Proceeding with active database observations.")

        event_broadcaster.publish(
            EVENT_FIRMS_FETCHED,
            {
                "new_observations": new_obs_count,
                "skipped_duplicates": skipped_dup,
                "total_fetched": total_fetched,
                "message": f"FIRMS data ingested: {new_obs_count} new, {skipped_dup} skipped."
            },
            run_id=run_id
        )

        # 3. GIS Enrichment
        # Query active observations in past 72 hours for spatial analysis
        time_cutoff = datetime.utcnow() - timedelta(hours=72)
        active_obs = db.query(Observation).filter(Observation.acquired_at >= time_cutoff).all()

        # If sparse, take recent 50 observations
        if not active_obs:
            active_obs = db.query(Observation).order_by(Observation.acquired_at.desc()).limit(50).all()

        # Enforce sovereign Indian territory filtering
        active_obs = [o for o in active_obs if is_within_indian_sovereign_territory(o.latitude, o.longitude)]

        event_broadcaster.publish(
            EVENT_GIS_COMPLETED,
            {
                "active_observations_in_scope": len(active_obs),
                "message": f"GIS spatial indexing complete across {len(active_obs)} active observations."
            },
            run_id=run_id
        )

        # 4. Spatial-Temporal Clustering & Non-Summing Invariant
        clusters = cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)

        event_broadcaster.publish(
            EVENT_CLUSTERING_COMPLETED,
            {
                "clusters_count": len(clusters),
                "message": f"Clustered observations into {len(clusters)} physical candidate clusters."
            },
            run_id=run_id
        )

        # 5. Incident Association & Lifecycle Promotion
        synced_incidents = sync_clusters_to_incidents(db, clusters)
        new_incidents = [i for i in synced_incidents if (datetime.utcnow() - (i.created_at or i.first_detected_at)).total_seconds() < 120]
        updated_incidents = [i for i in synced_incidents if i not in new_incidents]

        # 6. Refresh Behavior Profiles & 365d Baselines for Affected Assets
        #
        # The window is the 365 days Section 4.4 and INV-4 both name. This used to
        # pass 90, so the baseline INV-4's routine-flare test compares against --
        # "within their empirical 365-day P95 baseline envelope" -- was actually a
        # 90-day one, and `active_days` was a 90-day count tested against a
        # per-year threshold.
        for inc in synced_incidents:
            if inc.nearest_asset_id:
                get_or_create_facility_baseline(inc.nearest_asset_id, db, window_days=365)
            else:
                get_or_create_location_baseline(inc.latitude, inc.longitude, db, window_days=365)

        # 7. Selection & Priority Ranking
        candidates = select_investigation_candidates(db, min_priority=30.0, limit=max_ai_targets, status=None)
        event_broadcaster.publish(
            EVENT_SELECTION_COMPLETED,
            {
                "candidates_count": len(candidates),
                "top_incident": candidates[0]["incident_code"] if candidates else None,
                "message": f"Prioritized {len(candidates)} incidents for deep visual investigation."
            },
            run_id=run_id
        )

        investigations_run = 0
        alerts_emitted = 0
        total_candidates = len(candidates)

        # 8, 9, 10, 11: Visual Context, AI Investigation, Severity, and Alerts
        for idx, candidate in enumerate(candidates, start=1):
            inc_id = candidate["incident_id"]
            incident = db.query(Incident).filter(Incident.id == inc_id).first()
            if not incident:
                continue

            # Incremental check: check if already investigated
            existing_inv = db.query(AIInvestigation).filter(
                AIInvestigation.incident_id == inc_id
            ).order_by(AIInvestigation.created_at.desc()).first()

            needs_ai = force_reinvestigate or (existing_inv is None)
            if existing_inv and not force_reinvestigate:
                ev = existing_inv.evidence_points or {}
                prior_obs_count = ev.get("observation_count")
                prior_max_frp = ev.get("max_frp")

                # If new observations arrived for this incident
                if prior_obs_count is not None and (incident.observation_count or 1) > prior_obs_count:
                    needs_ai = True
                # If FRP spiked significantly (>= 50%)
                elif prior_max_frp is not None and incident.current_max_frp and incident.current_max_frp >= 1.5 * prior_max_frp:
                    needs_ai = True

            # Progress computation within 75% -> 94%
            frac = (idx - 1) / max(1, total_candidates)
            frac_done = idx / max(1, total_candidates)
            img_pct = min(94, 75 + int(frac * 18))
            ai_start_pct = min(94, 75 + int((frac + 0.5 / max(1, total_candidates)) * 18))
            ai_done_pct = min(94, 75 + int(frac_done * 18))

            # Imagery step
            event_broadcaster.publish(
                EVENT_IMAGERY_STARTED,
                {
                    "incident_id": inc_id,
                    "incident_code": incident.incident_code,
                    "candidate_index": idx,
                    "candidates_total": total_candidates,
                    "stage_pct": img_pct,
                    "message": f"Fetching satellite image for Target {idx}/{total_candidates} ({incident.incident_code})"
                },
                run_id=run_id
            )
            get_or_create_incident_imagery(inc_id, db, force_refresh=needs_ai)

            # AI Investigation step
            if needs_ai:
                event_broadcaster.publish(
                    EVENT_AI_STARTED,
                    {
                        "incident_id": inc_id,
                        "incident_code": incident.incident_code,
                        "candidate_index": idx,
                        "candidates_total": total_candidates,
                        "stage_pct": ai_start_pct,
                        "message": f"AI Vision analyzing Target {idx}/{total_candidates} ({incident.incident_code})..."
                    },
                    run_id=run_id
                )
                ai_report = run_incident_investigation(inc_id, db, force_reinvestigate=True)
                investigations_run += 1
                event_broadcaster.publish(
                    EVENT_AI_COMPLETED,
                    {
                        "incident_id": inc_id,
                        "incident_code": incident.incident_code,
                        "candidate_index": idx,
                        "candidates_total": total_candidates,
                        "stage_pct": ai_done_pct,
                        "classification": ai_report["classification"],
                        "confidence": ai_report["confidence"],
                        "message": f"Target {idx}/{total_candidates} verified: {ai_report['classification']} ({ai_report['confidence']}%)"
                    },
                    run_id=run_id
                )
            else:
                logger.info(f"[Pipeline] Reusing recent AI investigation for {incident.incident_code}")

            # Severity Assessment step
            sev_result = evaluate_incident_severity(inc_id, db)
            event_broadcaster.publish(
                EVENT_SEVERITY_COMPLETED,
                {
                    "incident_id": inc_id,
                    "incident_code": incident.incident_code,
                    "severity_score": sev_result["severity_score"],
                    "severity_level": sev_result["severity_level"],
                    "model_used": sev_result["model_used"],
                    "message": f"Assessed {incident.incident_code}: {sev_result['severity_level']} ({sev_result['severity_score']}/100)"
                },
                run_id=run_id
            )

            # Alert step
            #
            # INV-6: an alert is emitted once per incident unless severity
            # strictly escalates. The alert engine returns the *existing* record
            # on the deduplicated path, so a non-None result is not the same as a
            # new alert -- counting both inflated `alerts_emitted`, the
            # ALERT_CREATED stream and `AnalysisRun.alerts_count` on every pass.
            # The engine marks the record it returns; respect the mark.
            if sev_result.get("alert"):
                alert_info = sev_result["alert"]
                if alert_info.get("is_new", True):
                    alerts_emitted += 1
                    event_broadcaster.publish(
                        EVENT_ALERT_CREATED,
                        {
                            "alert_id": alert_info.get("alert_id"),
                            "incident_id": inc_id,
                            "incident_code": incident.incident_code,
                            "severity_level": sev_result["severity_level"],
                            "status": alert_info.get("status", "NEW"),
                            "title": alert_info.get("title", ""),
                            "message": f"Dispatched {sev_result['severity_level']} alert for {incident.incident_code}"
                        },
                        run_id=run_id
                    )
                else:
                    logger.info(
                        f"[Pipeline] Alert for {incident.incident_code} deduplicated "
                        f"(INV-6: already open at {sev_result['severity_level']})."
                    )

        # 12. Finalize & Export
        #
        # R15: the severity engine above only ran on the incidents selection
        # picked for optical investigation -- five by default -- while the export
        # publishes every displayable incident. Sweep the rest before the export
        # so `risk_score` and `risk_factors` describe the whole queue rather than
        # only its top five. This is what makes the console's tier histogram and
        # the alert feed describe the same system.
        sweep = run_severity_sweep(db)
        event_broadcaster.publish(
            EVENT_SEVERITY_COMPLETED,
            {
                "sweep": True,
                "incidents_evaluated": sweep["evaluated"],
                "failures": len(sweep["failed"]),
                "message": (
                    f"Severity sweep over the displayable queue: {sweep['evaluated']} incidents "
                    f"evaluated, {len(sweep['failed'])} failed."
                ),
            },
            run_id=run_id
        )

        elapsed = round(time.time() - t0, 2)
        run_record.status = "COMPLETED"
        run_record.completed_at = datetime.utcnow()
        run_record.duration_seconds = elapsed
        run_record.observations_count = len(active_obs)
        run_record.new_observations_count = new_obs_count
        run_record.incidents_updated_count = len(updated_incidents)
        run_record.new_incidents_count = len(new_incidents)
        run_record.investigations_count = investigations_run
        run_record.alerts_count = alerts_emitted

        summary = {
            "run_id": run_id,
            "status": "COMPLETED",
            "duration_seconds": elapsed,
            "observations_active": len(active_obs),
            "new_observations": new_obs_count,
            "clusters_count": len(clusters),
            "incidents_updated": len(updated_incidents),
            "new_incidents": len(new_incidents),
            "candidates_investigated": investigations_run,
            "alerts_emitted": alerts_emitted,
            "severity_sweep_evaluated": sweep["evaluated"],
            "severity_sweep_failures": sweep["failed"],
            "completed_at": run_record.completed_at.isoformat()
        }
        run_record.summary_json = summary
        db.commit()

        if export_to_dashboard:
            export_v1_dashboard_data(db)

        event_broadcaster.publish(
            EVENT_ANALYSIS_COMPLETED,
            summary,
            run_id=run_id
        )

        logger.info(f"[Pipeline] Analysis run {run_id} completed in {elapsed}s.")
        return summary

    except Exception as e:
        logger.error(f"[Pipeline] Analysis run {run_id} failed: {e}", exc_info=True)
        duration = round(time.time() - t0, 2)

        # F-102: recording the failure is best-effort; publishing it is not. A run
        # can fail *because* the database is unavailable, and this block used to
        # share a fate with the thing it was reporting on -- the commit raised, the
        # publish was never reached, and the direct SSE stream waited on a queue
        # that would never receive a terminal event. Publish unconditionally.
        try:
            if run_record is not None:
                run_record.status = "FAILED"
                run_record.completed_at = datetime.utcnow()
                run_record.duration_seconds = duration
                run_record.error_message = str(e)
            else:
                # The run failed before its audit row existed, so write one now
                # rather than losing the failure from the run history.
                run_record = AnalysisRun(
                    id=run_id,
                    status="FAILED",
                    started_at=start_time,
                    completed_at=datetime.utcnow(),
                    duration_seconds=duration,
                    error_message=str(e)
                )
                db.add(run_record)
            db.commit()
        except Exception as record_error:
            logger.error(
                f"[Pipeline] Could not record failure of run {run_id} "
                f"(publishing the terminal event anyway): {record_error}"
            )
            db.rollback()

        event_broadcaster.publish(
            EVENT_ANALYSIS_FAILED,
            {
                "run_id": run_id,
                "error": str(e),
                "duration_seconds": duration
            },
            run_id=run_id
        )
        raise
    finally:
        # Guarantee lock is released
        pipeline_lock.release(run_id)
