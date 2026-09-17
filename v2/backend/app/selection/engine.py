"""
FIREX v2 Selection Engine
Evaluates and ranks incident candidates for investigation.
Combines Incident state, GIS context, Stage 4 behavior features, and priority scoring.
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.storage.models import Incident, IndustrialAsset
from app.incidents.aggregation import resolve_firms_confidence
from app.selection.scoring import compute_investigation_priority
from app.behavior.baseline import get_or_create_location_baseline, get_or_create_facility_baseline
from app.behavior.anomaly import evaluate_historical_anomaly
from app.core.logging import logger

# Section 11's pseudocode (V2_LOGIC_SPECIFICATION.md:559-572) scores the whole
# incident queue before `top_candidates = candidates[:5]`, and the spec names no
# pool cap. This bound exists only to keep the per-incident baseline work in
# `select_investigation_candidates` finite; that function logs whenever it binds,
# so the truncation is never silent. It replaced a bare `.limit(100)` literal that
# cut the queue without a trace, making the response read as "the whole queue was
# ranked" when it had not been (defect F-066).
CANDIDATE_POOL_LIMIT = 500

def compute_spec_persistence_score(active_days: int, observation_count: int) -> float:
    """
    Section 4.4's persistence_score, expressed on the 0-100 scale Section 14 uses.

    V2_LOGIC_SPECIFICATION.md:153 defines
        persistence_score = min(1.0, active_days/45.0 * 0.7 + min(1.0, obs_count/100.0) * 0.3)
    and Section 14's second mandatory override (line 207, "High Persistence:
    S_pers >= 85.0") consumes S_pers alongside the other 0-100 Section 14 terms.

    This replaced `75.0 if status == "PERSISTENT" else min(100.0, obs_count * 15.0)`,
    which had no active-day term at all and so could never reach the 85.0 override
    for a PERSISTENT incident -- the override was unreachable by construction
    (defect F-065).
    """
    active_term = (max(0, active_days) / 45.0) * 0.7
    volume_term = min(1.0, max(0, observation_count) / 100.0) * 0.3
    return round(100.0 * min(1.0, active_term + volume_term), 1)

def _incident_active_days(incident: Incident) -> int:
    """
    Active calendar days attributable to the incident itself.

    Used only when the baseline carries no day count: the materialized
    HistoricalBaseline cache path in behavior/baseline.py stores detection counts
    but not distinct-day counts, whereas the freshly computed path and the thermal
    climatology path both expose one.
    """
    if incident.first_detected_at is None or incident.last_detected_at is None:
        return 1
    return max(1, (incident.last_detected_at.date() - incident.first_detected_at.date()).days + 1)

def _anomaly_table_score(eval_res: Dict[str, Any]) -> float:
    """
    Section 4.4's historical anomaly score, 0-100.

    Section 14 weights S_anom at 0.10 next to 0-100 peers, so the engine has to
    feed it the anomaly table's own value. behavior/anomaly.py computes that table
    score as `ratio_score_100` (0/10/20/40/60/75/90/100) and also re-exposes it
    divided down to `anomaly_score`; read the 0-100 field directly so no scale
    assumption (and no rescaling in either direction) is needed here. This is what
    the old `* 100.0` patch on this path got wrong (defect F-064).
    """
    value = eval_res.get("ratio_score_100")
    if value is None:
        value = eval_res.get("anomaly_score", 0.0)
    return float(value or 0.0)

def evaluate_incident_selection(incident_id: str, db: Session) -> Dict[str, Any]:
    """
    Evaluates selection priority for a single incident.
    Fetches its historical baseline, persistence, and confidence to calculate investigation priority.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return {"error": "Incident not found", "incident_id": incident_id}

    # 1. FRP intensity
    frp_val = float(incident.current_max_frp or incident.current_mean_frp or 0.0)

    # 2. Historical baseline lookup (Facility-level if associated, else Location-level)
    baseline_data: Optional[Dict[str, Any]] = None
    has_history = False
    hist_median = 0.0
    baseline_p95 = 0.0

    if incident.nearest_asset_id:
        baseline_data = get_or_create_facility_baseline(incident.nearest_asset_id, db, window_days=90)
    else:
        baseline_data = get_or_create_location_baseline(incident.latitude, incident.longitude, db, window_days=90)

    if baseline_data:
        baseline_p95 = float(baseline_data.get("p95_frp", 0.0) or 0.0)
        hist_median = float(baseline_data.get("median_frp", 0.0) or 0.0)
        # Section 11 line 565 defines history as an available baseline:
        # `has_history=(inc.baseline_p95 > 0)`. Deriving it from
        # `observation_count > 0` marked nearly every incident as having history
        # and routed them into the with-history weights with a zero anomaly term,
        # penalising them ~9 points against the no-history model (defect F-049).
        # Section 4.4's reliability label NONE (obs == 0) implies p95 == 0, so
        # using the empirical p95 subsumes the reliability gate.
        has_history = baseline_p95 > 0.0

    # 3. Persistence score (Section 4.4 / Section 14 S_pers, 0-100)
    active_days = 0
    baseline_obs_count = 0
    if baseline_data:
        active_days = int(baseline_data.get("active_days") or baseline_data.get("active_days_365d") or 0)
        baseline_obs_count = int(baseline_data.get("observation_count") or 0)
    if active_days <= 0:
        active_days = _incident_active_days(incident)
    # Section 4.4 measures obs_count for the site's window, which is what the
    # baseline reports; the incident's own member count is the fallback when the
    # grid cell carries no history.
    obs_count = baseline_obs_count if baseline_obs_count > 0 else (incident.observation_count or 1)
    persistence_score = compute_spec_persistence_score(active_days, obs_count)

    # 4. Historical anomaly score (Section 4.4 table, 0-100)
    anomaly_score = 0.0
    if has_history:
        # Note on the persistence argument: behavior/anomaly.py gates its
        # synthesis matrix at `persistence_score >= 0.50` (the 0-1 behaviour
        # scale), so it reads as satisfied for every value this caller can pass.
        # The engine consumes only `anomaly_score`, so prioritisation is
        # unaffected; the argument is passed through unchanged rather than
        # silently re-scaled, since both scales are per-call-site by design.
        eval_res = evaluate_historical_anomaly(
            current_frp=frp_val,
            lat=incident.latitude,
            lon=incident.longitude,
            persistence_score=persistence_score,
            baseline_override=baseline_data
        )
        anomaly_score = _anomaly_table_score(eval_res)

    # 5. FIRMS confidence (Section 4.5 C_firms, 0-100)
    # This used to be the literal `confidence_val = 80.0` ("FIRMS confidence
    # approximation (default 80 if aggregate)"), which pinned every incident's
    # 0.20/0.25 C_firms term and made the Section 14.3 extreme-FRP override
    # (FRP >= 150 MW *and* C_firms >= 80.0%) degenerate into an FRP-only test,
    # since a constant 80.0 always satisfies the confidence half of the condition
    # (defects F-048 / F-062). incidents/aggregation.resolve_firms_confidence is
    # the single source of the real aggregate and never returns None.
    firms_confidence_pct = resolve_firms_confidence(incident, db)

    priority_result = compute_investigation_priority(
        frp_mw=frp_val,
        # map_firms_confidence accepts either scale under `confidence_score`;
        # pass the fraction explicitly so the 0-100 aggregate cannot be
        # mistaken for the 0-1 form at the call site.
        confidence_score=firms_confidence_pct / 100.0,
        persistence_score=persistence_score,
        anomaly_score=anomaly_score,
        has_history=has_history,
        historical_median_frp=hist_median
    )

    # Determine selection recommendation
    priority = priority_result["investigation_priority"]
    should_investigate = priority >= 40.0 or priority_result["is_override_triggered"]

    # Update incident investigation_priority field in DB
    incident.investigation_priority = priority
    db.commit()

    facility_name = None
    dist_m = None
    if incident.nearest_asset_id:
        asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == incident.nearest_asset_id).first()
        if asset:
            facility_name = asset.name
        if incident.distance_to_asset_km is not None:
            dist_m = round(incident.distance_to_asset_km * 1000.0, 1)

    return {
        "incident_id": incident.id,
        "incident_code": incident.incident_code or incident.id,
        "status": incident.status,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "primary_facility_name": facility_name,
        "primary_facility_distance_m": dist_m,
        "selection_priority": priority,
        "should_investigate": should_investigate,
        "firms_confidence": firms_confidence_pct,
        "priority_details": priority_result,
        "historical_context": {
            "has_history": has_history,
            "historical_median_frp": hist_median,
            "historical_p95_frp": baseline_p95,
            "active_days": active_days,
            "baseline_label": baseline_data.get("history_reliability_label", "NONE") if baseline_data else "NONE"
        }
    }

def select_investigation_candidates(
    db: Session,
    min_priority: float = 35.0,
    limit: int = 25,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Ranks and returns incident candidates for deep AI investigation.
    Prioritizes highest investigation_priority score and override triggers.
    """
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    else:
        query = query.filter(Incident.status != "RESOLVED")

    # Count the queue before capping it so a bound pool is reported rather than
    # implying the whole queue was ranked (defect F-066).
    total_open = query.count()
    incidents = query.order_by(Incident.updated_at.desc()).limit(CANDIDATE_POOL_LIMIT).all()
    if total_open > len(incidents):
        logger.warning(
            "Selection candidate pool truncated: scored %d of %d open incidents "
            "(CANDIDATE_POOL_LIMIT=%d); the remainder were not evaluated for this pass.",
            len(incidents), total_open, CANDIDATE_POOL_LIMIT
        )

    candidates: List[Dict[str, Any]] = []
    for inc in incidents:
        eval_res = evaluate_incident_selection(inc.id, db)
        if "error" in eval_res:
            continue

        priority = eval_res["selection_priority"]
        is_override = eval_res["priority_details"]["is_override_triggered"]

        if priority >= min_priority or is_override:
            candidates.append(eval_res)

    # Sort descending by selection priority
    candidates.sort(key=lambda x: x["selection_priority"], reverse=True)
    return candidates[:limit]
