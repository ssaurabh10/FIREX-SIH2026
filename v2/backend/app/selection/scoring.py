"""
FIREX v2 Candidate Prioritization Scoring Engine
Implements Section 14 of Blueprint:
1. Log2-normalized FRP scoring.
2. FIRMS confidence mapping (0-100).
3. Mandatory selection overrides (Extreme FRP, High Persistence, Strong Anomaly).
4. Dual-mode investigation priority model (with history vs without history - Rule 6).
"""
import math
from typing import Dict, Any, List, Tuple, Optional

def calculate_frp_score(frp_mw: float) -> float:
    """
    Blueprint 14.1:
    FRP_Score = min(100.0, 25.0 * log2(frp_mw + 1.0))
    Maps 0 MW -> 0, 4 MW -> ~58, 8 MW -> ~79, 15+ MW -> 100.
    """
    if not frp_mw or frp_mw <= 0.0:
        return 0.0
    val = 25.0 * math.log2(frp_mw + 1.0)
    return round(min(100.0, max(0.0, val)), 1)

def map_firms_confidence(
    confidence_raw: Optional[str] = None,
    instrument: Optional[str] = None,
    confidence_score: Optional[float] = None
) -> float:
    """
    Blueprint 14.2:
    Maps raw confidence to a standard 0-100 score.
    - MODIS: low -> 25, nominal -> 65, high -> 95
    - VIIRS: l -> 35, n -> 70, h -> 95
    - Numeric (0-100 or 0-1 float): appropriately scaled
    """
    if confidence_score is not None:
        if 0.0 <= confidence_score <= 1.0:
            return round(confidence_score * 100.0, 1)
        return round(min(100.0, max(0.0, confidence_score)), 1)

    if not confidence_raw:
        return 50.0

    raw_lower = str(confidence_raw).strip().lower()
    inst_lower = str(instrument or "").strip().lower()

    if "modis" in inst_lower:
        if raw_lower in ["l", "low"]:
            return 25.0
        elif raw_lower in ["n", "nominal"]:
            return 65.0
        elif raw_lower in ["h", "high"]:
            return 95.0

    if "viirs" in inst_lower or raw_lower in ["l", "n", "h", "low", "nominal", "high"]:
        if raw_lower in ["l", "low"]:
            return 35.0
        elif raw_lower in ["n", "nominal"]:
            return 70.0
        elif raw_lower in ["h", "high"]:
            return 95.0

    try:
        val = float(raw_lower)
        if 0.0 <= val <= 1.0:
            return round(val * 100.0, 1)
        return round(min(100.0, max(0.0, val)), 1)
    except ValueError:
        return 50.0

def evaluate_selection_overrides(
    frp_mw: float,
    confidence: float,
    persistence_score: float,
    frp_ratio: float = 1.0
) -> Tuple[bool, List[str]]:
    """
    Blueprint 14.3:
    Mandatory Selection Override Thresholds:
    1. Extreme FRP: FRP > 150 MW and Confidence >= 80.0
    2. High Persistence: Persistence Score >= 85.0
    3. Strong Historical Anomaly: Current FRP >= 3.0 * Historical Median FRP (frp_ratio >= 3.0)
    """
    reasons: List[str] = []

    if frp_mw >= 150.0 and confidence >= 80.0:
        reasons.append(f"EXTREME_FRP: {frp_mw:.1f} MW exceeds 150 MW threshold at {confidence:.0f}% confidence")

    if persistence_score >= 85.0:
        reasons.append(f"HIGH_PERSISTENCE: Score {persistence_score:.1f} indicates multi-day persistent thermal activity")

    if frp_ratio >= 3.0:
        reasons.append(f"STRONG_HISTORICAL_ANOMALY: Thermal output is {frp_ratio:.1f}x higher than historical baseline median")

    override_triggered = len(reasons) > 0
    return override_triggered, reasons

def compute_investigation_priority(
    frp_mw: float,
    confidence_raw: Optional[str] = None,
    instrument: Optional[str] = "VIIRS",
    confidence_score: Optional[float] = None,
    persistence_score: float = 0.0,
    anomaly_score: float = 0.0,
    has_history: bool = True,
    historical_median_frp: Optional[float] = None
) -> Dict[str, Any]:
    """
    Blueprint Section 14:
    Calculates weighted Investigation Priority (0-100).
    Dual-mode:
    - When history exists:
      Priority = 0.40 * FRP_Score + 0.30 * Persistence_Score + 0.20 * Confidence + 0.10 * Anomaly_Score
    - When history does NOT exist (Rule 6: Never penalize new incidents):
      Priority = 0.45 * FRP_Score + 0.30 * Persistence_Score + 0.25 * Confidence
    """
    frp_score = calculate_frp_score(frp_mw)
    conf_norm = map_firms_confidence(confidence_raw, instrument, confidence_score)

    frp_ratio = 1.0
    if has_history and historical_median_frp and historical_median_frp > 0.0:
        frp_ratio = round(frp_mw / historical_median_frp, 2)

    override_triggered, override_reasons = evaluate_selection_overrides(
        frp_mw=frp_mw,
        confidence=conf_norm,
        persistence_score=persistence_score,
        frp_ratio=frp_ratio
    )

    if has_history:
        base_priority = (
            0.40 * frp_score +
            0.30 * persistence_score +
            0.20 * conf_norm +
            0.10 * anomaly_score
        )
        mode = "WITH_HISTORICAL_BASELINE"
    else:
        base_priority = (
            0.45 * frp_score +
            0.30 * persistence_score +
            0.25 * conf_norm
        )
        mode = "NEW_INCIDENT_NO_HISTORY"

    # If an override was triggered, elevate priority to at least 90.0
    final_priority = max(base_priority, 90.0) if override_triggered else base_priority
    final_priority = round(min(100.0, max(0.0, final_priority)), 1)

    return {
        "investigation_priority": final_priority,
        "base_priority": round(base_priority, 1),
        "scoring_mode": mode,
        "is_override_triggered": override_triggered,
        "override_reasons": override_reasons,
        "components": {
            "frp_mw": frp_mw,
            "frp_score": frp_score,
            "persistence_score": round(persistence_score, 1),
            "confidence_score": conf_norm,
            "anomaly_score": round(anomaly_score, 1) if has_history else None,
            "frp_ratio": frp_ratio if has_history else None
        }
    }
