"""
FIREX v2 Historical Anomaly & Spike Detector
Evaluates:
- Ratio of current FRP against historical Median FRP (frp_ratio).
- Checks whether current FRP exceeds historical P95 threshold (above_p95).
- Detects whether an event is (Section 4.4 Behavior Synthesis Matrix, which
  crosses persistence >= 0.5 with the 0-100 anomaly score >= 50):
    1. Persistent / Normal: High persistence + normal anomaly score
    2. Persistent / Abnormal: High persistence + strong historical deviation
    3. New / Abnormal: Low persistence + strong historical deviation
    4. New / Normal: Low persistence + normal anomaly score
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.storage.models import HistoricalAnomaly, Incident
from app.behavior.baseline import get_or_create_location_baseline
from app.core.logging import logger

_RATIO_TABLE = (
    (1.0, 0.0),
    (1.25, 10.0),
    (1.5, 20.0),
    (2.0, 40.0),
    (3.0, 60.0),
    (4.0, 75.0),
    (5.0, 90.0),
)

def calculate_frp_ratio_score(ratio: float) -> float:
    """
    Blueprint 13.10 engineering starting table:
    <= 1.0x       -> 0
    > 1.0 - 1.25x -> 10
    > 1.25 - 1.5x -> 20
    > 1.5 - 2x    -> 40
    > 2 - 3x      -> 60
    > 3 - 4x      -> 75
    > 4 - 5x      -> 90
    > 5x          -> 100
    """
    for threshold, score in _RATIO_TABLE:
        if ratio <= threshold:
            return score
    return 100.0

def classify_behavior_synthesis(
    persistence_score: float,
    above_p95: bool,
    frp_ratio: float
) -> str:
    """
    Blueprint Stage 4 & 13.9 / Specification 4.4 Behavior Synthesis Matrix
    (spec lines 178-190):
    high persistence + normal anomaly score        -> persistent / normal
    high persistence + strong historical deviation -> persistent / abnormal
    low persistence + strong historical deviation  -> new / abnormal
    low persistence + normal anomaly score         -> new / normal

    The matrix crosses persistence (>= 0.5) with the ANOMALY SCORE (>= 50) --
    what the spec's own row/column labels say -- rather than with P95
    membership. `above_p95` is still accepted because callers pass it, but it
    is deliberately NOT part of the predicate: the ratio table below already
    encodes the spec's 50-point boundary (the table steps from 40 at <= 2.0x to
    60 above it), and keying on `above_p95` instead labelled every ordinary
    P95 exceedance whose ratio still sat in (p95/median, 2.0x] as abnormal
    while the table -- the spec's own authority for that boundary -- scored it
    normal. That extra disjunct is defect F-023.
    """
    is_high_persistence = persistence_score >= 0.50
    is_strong_deviation = calculate_frp_ratio_score(frp_ratio) >= 50.0

    if is_high_persistence and not is_strong_deviation:
        return "persistent / normal"
    elif is_high_persistence and is_strong_deviation:
        return "persistent / abnormal"
    elif not is_high_persistence and is_strong_deviation:
        return "new / abnormal"
    else:
        return "new / normal"

def evaluate_historical_anomaly(
    current_frp: float,
    lat: float,
    lon: float,
    incident_id: Optional[str] = None,
    db: Optional[Session] = None,
    persistence_score: float = 0.0,
    baseline_override: Optional[Dict[str, Any]] = None,
    save_record: bool = True
) -> Dict[str, Any]:
    """
    Compares current FRP against localized historical baseline.
    Returns anomaly diagnosis and optionally persists audit record in historical_anomalies.
    """
    if baseline_override:
        baseline = baseline_override
    elif db is not None:
        baseline = get_or_create_location_baseline(lat, lon, db)
    else:
        baseline = {
            "median_frp": 0.0,
            "p95_frp": 0.0,
            "observation_count": 0
        }

    median_frp = baseline.get("median_frp", 0.0)
    p95_frp = baseline.get("p95_frp", 0.0)
    obs_count = baseline.get("observation_count", 0)

    # Specification 4.4 defines a LOW reliability tier at 1-4 observations and a
    # MODERATE tier at 5-9 (spec lines 156-162), and applies the historical
    # anomaly table to whatever location/facility baseline exists -- there is no
    # minimum-observation carve-out (spec lines 164-176). Only a cell with no
    # baseline at all (no observations, or a zero median) is INSUFFICIENT_HISTORY,
    # and that status is returned explicitly with an unassessed synthesis, so a
    # sparse cell can neither be scored off a table it never reached nor read
    # back as a benign "normal" quadrant (defect F-021 / C5).
    if obs_count <= 0 or median_frp <= 0.0:
        return {
            "incident_id": incident_id,
            "current_frp": current_frp,
            "historical_median_frp": 0.0,
            "historical_p95_frp": 0.0,
            "frp_ratio": 1.0,
            "ratio_score_100": 0.0,
            "anomaly_score": 0.0,
            "above_p95": False,
            "status": "INSUFFICIENT_HISTORY",
            # None, not a quadrant label: the synthesis matrix is not assessable
            # without a baseline, and "new / normal" would claim it was.
            "synthesis": None,
            "explanation": "Insufficient historical observations in this spatial grid to establish a baseline."
        }

    # Specification 4.4: R_frp = FRP_current / max(1.0, Median_FRP), a ratio
    # against the empirical median, used as an exact quotient against the table.
    # Rounding it to 2 decimals *before* the lookup made the classification
    # depend on presentation rounding: 1.254 collapsed to 1.25 and scored 10
    # where the spec's "> 1.25 - 1.5x" row gives 20; 2.004 collapsed to 2.0 and
    # scored 40 where the spec gives 60; 1.004 collapsed to 1.0 and scored 0
    # where the spec gives 10 (defect F-020). Round only the reported value.
    ratio = current_frp / max(1.0, median_frp)
    ratio_display = round(ratio, 2)
    is_above_p95 = current_frp > p95_frp
    ratio_score_100 = calculate_frp_ratio_score(ratio)
    # 0-100 everywhere (Section 4.4's table scale). This is the same scale as
    # Incident.anomaly_score, Selection's 0.10 * S_anom term and the stored
    # HistoricalAnomaly.anomaly_score column; the old `ratio_score_100 / 100.0`
    # made it a 0-1 fraction on a 0-100 path and underweighted the selection
    # composite by 100x -- a ceiling of 0.1 priority points instead of 10.0
    # (defects F-022 / F-064).
    anomaly_score = ratio_score_100

    # Blueprint test check: current FRP vs baseline (e.g. 12 -> normal, 40 -> abnormal)
    if is_above_p95:
        anomaly_status = "ABNORMAL_HISTORICAL_SPIKE"
        explanation = f"Current FRP ({current_frp} MW) exceeds historical P95 ({p95_frp} MW) by {ratio_display}x median."
    elif ratio > 1.5:
        anomaly_status = "ELEVATED_EMISSION"
        explanation = f"Current FRP ({current_frp} MW) is {ratio_display}x historical median ({median_frp} MW)."
    else:
        anomaly_status = "NORMAL_OPERATIONAL_RANGE"
        explanation = f"Current FRP ({current_frp} MW) is within normal baseline range (Median: {median_frp} MW)."

    synthesis = classify_behavior_synthesis(persistence_score, is_above_p95, ratio)

    # Record anomaly evaluation in historical_anomalies if DB and incident_id are present
    if save_record and db is not None and incident_id:
        try:
            record = HistoricalAnomaly(
                incident_id=incident_id,
                current_frp=current_frp,
                historical_median=median_frp,
                historical_p95=p95_frp,
                frp_ratio=ratio_display,
                anomaly_score=anomaly_score,
                above_p95=is_above_p95,
                # The persisted counterpart of the status string below. The
                # column exists in the live schema; nothing wrote it (F-061).
                anomaly_status=anomaly_status
            )
            db.add(record)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to record historical anomaly: {e}")
            db.rollback()

    return {
        "incident_id": incident_id,
        "current_frp": current_frp,
        "historical_median_frp": median_frp,
        "historical_p95_frp": p95_frp,
        "frp_ratio": ratio_display,
        # Retained as an alias of anomaly_score for existing callers; both are
        # the Section 4.4 table score on its native 0-100 scale.
        "ratio_score_100": ratio_score_100,
        "anomaly_score": anomaly_score,
        "above_p95": is_above_p95,
        "status": anomaly_status,
        "synthesis": synthesis,
        "explanation": explanation
    }
