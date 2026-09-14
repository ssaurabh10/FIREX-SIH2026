"""
FIREX v2 Historical Anomaly & Spike Detector
Evaluates:
- Ratio of current FRP against historical Median FRP (frp_ratio).
- Checks whether current FRP exceeds historical P95 threshold (above_p95).
- Detects whether an event is:
    1. Persistent / Normal: High persistence + normal historical range
    2. Persistent / Abnormal: High persistence + strong historical deviation (> P95)
    3. New / Abnormal: Low persistence + strong historical deviation
    4. New / Normal: Low persistence + normal range
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
    Blueprint Stage 4 & 13.9:
    high persistence + normal historical range     -> persistent / normal
    high persistence + strong historical deviation -> persistent / abnormal
    low persistence + strong historical deviation  -> new / abnormal
    low persistence + normal historical range      -> new / normal
    """
    is_high_persistence = persistence_score >= 0.50
    is_strong_deviation = above_p95 or (frp_ratio > 2.0)

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

    # If insufficient history (< 3 observations), handle gracefully without penalizing
    if obs_count < 3 or median_frp <= 0.0:
        synthesis = classify_behavior_synthesis(persistence_score, False, 1.0)
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
            "synthesis": synthesis,
            "explanation": "Insufficient historical observations in this spatial grid to establish a baseline."
        }

    # Calculate FRP ratio
    ratio = round(current_frp / max(1.0, median_frp), 2)
    is_above_p95 = current_frp > p95_frp
    ratio_score_100 = calculate_frp_ratio_score(ratio)
    anomaly_score = round(ratio_score_100 / 100.0, 2)

    # Blueprint test check: current FRP vs baseline (e.g. 12 -> normal, 40 -> abnormal)
    if is_above_p95:
        anomaly_status = "ABNORMAL_HISTORICAL_SPIKE"
        explanation = f"Current FRP ({current_frp} MW) exceeds historical P95 ({p95_frp} MW) by {ratio}x median."
    elif ratio > 1.5:
        anomaly_status = "ELEVATED_EMISSION"
        explanation = f"Current FRP ({current_frp} MW) is {ratio}x historical median ({median_frp} MW)."
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
                frp_ratio=ratio,
                anomaly_score=anomaly_score,
                above_p95=is_above_p95
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
        "frp_ratio": ratio,
        "ratio_score_100": ratio_score_100,
        "anomaly_score": anomaly_score,
        "above_p95": is_above_p95,
        "status": anomaly_status,
        "synthesis": synthesis,
        "explanation": explanation
    }
