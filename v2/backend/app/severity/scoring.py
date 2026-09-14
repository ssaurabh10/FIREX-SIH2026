"""
FIREX v2 Severity Scoring Engine
Implements Section 18 & 19 of FIREX-SIH2026 Blueprint:
- Known-Hotspot Model (35% FRP + 30% Historical Deviation + 20% AI + 15% GIS)
- New-Hotspot Model (50% FRP + 30% AI + 20% GIS)
- Deterministic Operational Escalation Overrides
- Independent Severity Confidence & Re-Investigation Trigger
"""
import math
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

# Canonical severity tiers
SEVERITY_LEVELS = [
    (0.0, 24.9, "LOW"),
    (25.0, 49.9, "MEDIUM"),
    (50.0, 74.9, "HIGH"),
    (75.0, 100.0, "CRITICAL")
]

def score_to_level(score: float) -> str:
    """Maps a 0-100 severity score to canonical level."""
    s = max(0.0, min(100.0, score))
    if s >= 75.0:
        return "CRITICAL"
    elif s >= 50.0:
        return "HIGH"
    elif s >= 25.0:
        return "MEDIUM"
    return "LOW"


# Sovereign Indian FIRMS FRP Distribution Constants (Measured across 2,896,415 Indian Observations)
INDIA_FRP_P50_MEDIAN = 4.05   # MW (National Median)
INDIA_FRP_P90 = 13.32         # MW (Top 10% thermal intensity)
INDIA_FRP_P95 = 20.81         # MW (Top 5% thermal intensity)
INDIA_FRP_P99 = 64.49         # MW (Top 1% extreme wildfire/explosion incidents)


def calculate_frp_severity(frp_mw: float) -> float:
    """
    Logarithmic normalization of Fire Radiative Power (FRP) on 0-100 scale:
    min(100, 25 * log2(FRP + 1))
    """
    if frp_mw <= 0:
        return 0.0
    return min(100.0, round(25.0 * math.log2(frp_mw + 1.0), 2))


def calculate_calibrated_frp_severity(frp_mw: float) -> float:
    """
    Empirical log-percentile calibration anchored directly to sovereign Indian FIRMS ground truth:
    - P50 (4.05 MW) -> 25.0 (Low-to-Medium boundary)
    - P90 (13.32 MW) -> 52.5 (High threshold)
    - P95 (20.81 MW) -> 65.4 (High tier)
    - P99 (64.49 MW) -> 100.0 (Critical disaster tier)
    """
    if frp_mw <= 0:
        return 0.0
    return min(100.0, round(25.0 * math.log2((frp_mw / INDIA_FRP_P50_MEDIAN) + 1.0), 2))


def calculate_historical_deviation(
    frp_mw: float,
    median_frp: float,
    p95_frp: float,
    is_routine_flare: bool = False
) -> float:
    """
    Evaluates current thermal energy relative to the facility's 365-day empirical baseline.
    Compares against P95 flare ceiling and median.
    If is_routine_flare=True and current FRP <= P95, clamps score to <= 20.0
    to prevent routine continuous flares from generating false high-severity alerts.
    """
    if p95_frp <= 0.0 and median_frp <= 0.0:
        return 0.0

    ref_ceiling = p95_frp if p95_frp > 0.0 else (median_frp * 2.0)
    ratio = frp_mw / ref_ceiling if ref_ceiling > 0 else 1.0

    if ratio >= 3.0:
        return 100.0
    elif ratio >= 2.0:
        return round(80.0 + (ratio - 2.0) * 20.0, 2)
    elif ratio >= 1.0:
        return round(50.0 + (ratio - 1.0) * 30.0, 2)
    else:
        # Below normal P95 ceiling
        base_dev = round(50.0 * ratio, 2)
        if is_routine_flare:
            # Routine flare suppression: normal flaring within historical envelope stays green (< 20)
            return min(20.0, max(5.0, round(base_dev * 0.4, 2)))
        return max(10.0, base_dev)


def calculate_ai_source_severity(classification: str, confidence: float) -> float:
    """
    Translates AI classification and confidence into source risk contribution (0-100).
    """
    base_scores = {
        "industrial_fire": 92.0,
        "wildfire": 75.0,
        "mining_related": 60.0,
        "uncertain": 50.0,
        "gas_flare": 38.0,
        "agricultural_burning": 32.0
    }
    base = base_scores.get(classification.lower(), 50.0)
    conf_factor = max(0.0, min(1.0, confidence / 100.0))
    # Blend base with confidence
    return round(base * conf_factor + (1.0 - conf_factor) * 50.0, 2)


def calculate_gis_context_severity(
    distance_m: Optional[float],
    facility_type: Optional[str] = None,
    hazard_category: Optional[str] = None,
    is_inside: bool = False,
    is_protected_area: bool = False
) -> float:
    """
    Evaluates spatial risk, infrastructure vulnerability, and environmental proximity (0-100).
    """
    high_hazard_types = {"refinery", "petrochemical", "lng_terminal", "steel_plant", "chemical"}
    f_type = (facility_type or "").lower()

    if is_inside:
        if any(h in f_type for h in high_hazard_types) or hazard_category == "MAJOR_ACCIDENT_HAZARD":
            return 95.0
        return 75.0

    if is_protected_area:
        return 85.0

    if distance_m is not None:
        if distance_m <= 500.0:
            return 65.0
        elif distance_m <= 1500.0:
            return 45.0
        elif distance_m <= 3000.0:
            return 30.0

    return 15.0


def evaluate_severity_overrides(
    frp_mw: float,
    firms_confidence: float,
    classification: str,
    ai_confidence: float,
    is_inside_facility: bool,
    p95_ratio: Optional[float],
    is_protected_area: bool = False,
    is_routine_flare: bool = False
) -> Tuple[Optional[str], List[str]]:
    """
    Evaluates explicit operational rules outside of the weighted linear model.
    """
    triggers = []
    forced_level = None

    # Override 1: Extreme FRP + high FIRMS confidence -> minimum HIGH / CRITICAL
    # Routine flares under 100 MW with known envelope are not automatically forced to CRITICAL
    extreme_threshold = 180.0 if is_routine_flare else 150.0
    if frp_mw >= extreme_threshold and firms_confidence >= 80.0:
        forced_level = "CRITICAL" if frp_mw >= 250.0 or firms_confidence >= 90.0 else "HIGH"
        triggers.append(f"EXTREME_FRP_OVERRIDE ({frp_mw:.1f} MW, conf {firms_confidence:.0f}%) -> {forced_level}")

    # Override 2: Industrial Fire confirmed inside facility boundary -> CRITICAL
    if classification == "industrial_fire" and ai_confidence >= 80.0 and is_inside_facility:
        forced_level = "CRITICAL"
        triggers.append("INDUSTRIAL_CATASTROPHE_OVERRIDE (industrial_fire in facility boundary) -> CRITICAL")

    # Override 3: Abnormal activity spike far above historical baseline (>= 3x P95 flare ceiling)
    if p95_ratio is not None and p95_ratio >= 3.0:
        triggers.append(f"ABNORMAL_ACTIVITY_SPIKE ({p95_ratio:.1f}x of P95 flare ceiling)")
        if forced_level is None or forced_level in ["LOW", "MEDIUM"]:
            forced_level = "HIGH"

    # Override 4: Wildfire inside protected forest
    if classification == "wildfire" and is_protected_area:
        triggers.append("PROTECTED_FOREST_WILDFIRE_ESCALATION")
        if forced_level is None or forced_level == "LOW":
            forced_level = "MEDIUM"

    return forced_level, triggers


def calculate_severity_confidence(
    firms_confidence: float,
    ai_confidence: float,
    history_reliability: float,
    distance_m: Optional[float]
) -> float:
    """
    Calculates independent certainty in the severity assessment (0-100).
    """
    # Distance certainty: closer means higher spatial precision
    if distance_m is not None:
        dist_certainty = max(40.0, 100.0 - (distance_m / 50.0))
    else:
        dist_certainty = 60.0

    conf = (
        0.25 * firms_confidence +
        0.35 * ai_confidence +
        0.20 * dist_certainty +
        0.20 * (history_reliability * 100.0 if history_reliability <= 1.0 else history_reliability)
    )
    return max(10.0, min(100.0, round(conf, 1)))


def compute_incident_severity(
    frp_mw: float,
    firms_confidence: float,
    classification: str,
    ai_confidence: float,
    median_frp: float = 0.0,
    p95_frp: float = 0.0,
    history_reliability: float = 0.0,
    facility_distance_m: Optional[float] = None,
    facility_type: Optional[str] = None,
    hazard_category: Optional[str] = None,
    is_inside_facility: bool = False,
    is_protected_area: bool = False,
    is_routine_flare: bool = False
) -> Dict[str, Any]:
    """
    Full deterministic severity evaluation returning score, level, factors, and confidence.
    Supports empirical Indian climatology calibration and routine flare suppression.
    """
    frp_score = calculate_frp_severity(frp_mw)
    india_calibrated_frp = calculate_calibrated_frp_severity(frp_mw)
    ai_score = calculate_ai_source_severity(classification, ai_confidence)
    gis_score = calculate_gis_context_severity(
        distance_m=facility_distance_m,
        facility_type=facility_type,
        hazard_category=hazard_category,
        is_inside=is_inside_facility,
        is_protected_area=is_protected_area
    )

    has_history = (p95_frp > 0.0 or median_frp > 0.0) and history_reliability >= 0.4
    p95_ratio = (frp_mw / p95_frp) if p95_frp > 0.0 else None

    # For routine persistent flares, use empirical Indian FIRMS calibrated FRP
    # so normal flaring within baseline does not artificially inflate FRP contribution
    effective_frp_score = india_calibrated_frp if is_routine_flare else frp_score

    if has_history:
        model_name = "KNOWN_HOTSPOT_WITH_HISTORY"
        dev_score = calculate_historical_deviation(frp_mw, median_frp, p95_frp, is_routine_flare=is_routine_flare)
        raw_score = (
            0.35 * effective_frp_score +
            0.30 * dev_score +
            0.20 * ai_score +
            0.15 * gis_score
        )
    else:
        model_name = "NEW_HOTSPOT_NO_HISTORY"
        dev_score = 0.0
        raw_score = (
            0.50 * effective_frp_score +
            0.30 * ai_score +
            0.20 * gis_score
        )

    base_score = max(0.0, min(100.0, round(raw_score, 2)))
    base_level = score_to_level(base_score)

    # Check operational overrides
    forced_level, override_reasons = evaluate_severity_overrides(
        frp_mw=frp_mw,
        firms_confidence=firms_confidence,
        classification=classification,
        ai_confidence=ai_confidence,
        is_inside_facility=is_inside_facility,
        p95_ratio=p95_ratio,
        is_protected_area=is_protected_area,
        is_routine_flare=is_routine_flare
    )

    final_level = forced_level or base_level
    # Adjust score if level was forced upward
    tier_min_scores = {"LOW": 10.0, "MEDIUM": 35.0, "HIGH": 65.0, "CRITICAL": 85.0}
    final_score = max(base_score, tier_min_scores[final_level]) if forced_level else base_score

    # Compute independent severity confidence
    sev_confidence = calculate_severity_confidence(
        firms_confidence=firms_confidence,
        ai_confidence=ai_confidence,
        history_reliability=history_reliability,
        distance_m=facility_distance_m
    )

    # Re-investigation safety trigger: High severity + Low confidence
    needs_reinvestigation = (final_level in ["HIGH", "CRITICAL"] and sev_confidence < 60.0)

    return {
        "severity_score": round(final_score, 1),
        "severity_level": final_level,
        "severity_confidence": sev_confidence,
        "model_used": model_name,
        "base_score": base_score,
        "base_level": base_level,
        "has_override": len(override_reasons) > 0,
        "override_reasons": override_reasons,
        "needs_reinvestigation": needs_reinvestigation,
        "factors": {
            "frp_score": frp_score,
            "india_calibrated_frp_score": india_calibrated_frp,
            "historical_deviation_score": dev_score,
            "ai_source_severity_score": ai_score,
            "gis_context_score": gis_score,
            "p95_ratio": round(p95_ratio, 2) if p95_ratio else None,
            "is_routine_flare": is_routine_flare
        }
    }
