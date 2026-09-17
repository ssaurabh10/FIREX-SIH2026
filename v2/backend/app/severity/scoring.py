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


# Ordering of the canonical levels, for the one comparison the model needs:
# whether an operational override raises the level or is already satisfied by
# it. `score_to_level`'s boundaries (25/50/75) and the tier floors below (30/55/80)
# are deliberately different -- a forced level sets a score comfortably inside
# its band rather than exactly on the boundary.
LEVEL_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


# Sovereign Indian FIRMS FRP Distribution Constants
# Measured across the 2,895,064 Indian observations held in the national
# archive. That figure is the row count of the `observations` table, not an
# estimate -- the percentile constants below are only meaningful as a
# description of the corpus they were measured over, so if the archive is
# rebuilt from a different FIRMS window they must be re-measured, not reused.
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
    elif ratio > 1.0:
        return round(50.0 + (ratio - 1.0) * 30.0, 2)
    else:
        # ratio <= 1.0, i.e. at or below the historical P95 ceiling.
        #
        # The boundary is deliberately `ratio > 1.0` above rather than `>=`, so
        # r == 1.0 lands here. Section 4.6.2 and INV-4 apply routine-flare
        # suppression for r <= 1.0 ("within their empirical 365-day P95
        # baseline envelope", ceiling included); with `>=` the code returned
        # 50.0 at exactly r == 1.0 and the suppression branch was unreachable
        # there.
        base_dev = round(50.0 * ratio, 2)
        if is_routine_flare:
            # Routine flare suppression: normal flaring within historical
            # envelope stays green (< 20).
            return min(20.0, max(5.0, round(base_dev * 0.4, 2)))
        # Section 4.6 defines this branch as exactly 50.0 x r with no floor.
        # An undocumented max(10.0, ...) used to sit here.
        return base_dev


def calculate_ai_source_severity(classification: str, confidence: float) -> float:
    """
    Translates AI classification and confidence into source risk contribution (0-100).
    """
    base_scores = {
        "uncontrolled_industrial_fire": 98.0,
        "industrial_fire": 92.0,
        "wildfire": 75.0,
        "mining_or_other_thermal_source": 65.0,
        # Alias of the above. The specification calls this class
        # `mining_or_other_thermal_source`; the multimodal provider emits
        # `mining_related`. Both must rate 65.0 -- the alias previously carried
        # its own 60.0, under-scoring any mining detection that reached this
        # function with the provider's label (severity/service.py reads the
        # stored label verbatim, so the pipeline's local remap never applied).
        "mining_related": 65.0,
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

    Section 4.6 names exactly five high-hazard facility types for the 95.0
    branch. An extra `hazard_category == "MAJOR_ACCIDENT_HAZARD"` disjunct used
    to widen it, and because IndustrialAsset.hazard_category **defaults** to
    that value (storage/models.py), every asset persisted without an explicit
    category took the branch -- outside high-hazard types included.
    """
    high_hazard_types = {"refinery", "petrochemical", "lng_terminal", "steel_plant", "chemical"}
    f_type = (facility_type or "").lower()

    if is_inside:
        if any(h in f_type for h in high_hazard_types):
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
    # Routine flares under 100 MW with known envelope are not automatically forced to CRITICAL.
    # Section 4.6's table carries exactly one escalation clause here:
    # "HIGH (FRP >= 250MW => CRITICAL)" at a forced minimum of 55.0. An extra
    # `or firms_confidence >= 90.0` disjunct used to promote 150-249 MW
    # detections at 90-100% FIRMS confidence to CRITICAL/80.0 instead of
    # HIGH/55.0; no such rule appears in the specification.
    extreme_threshold = 180.0 if is_routine_flare else 150.0
    if frp_mw >= extreme_threshold and firms_confidence >= 80.0:
        forced_level = "CRITICAL" if frp_mw >= 250.0 else "HIGH"
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

    Section 4.6 specifies the four-term weighted sum and
    C_dist = max(40.0, 100.0 - dist_meters/50.0), nothing else. Two undocumented
    behaviours used to sit here:

    * an unknown distance returned 60.0 -- 20 points above the 40.0 the formula
      implies for an unknown/far facility, worth +4.0 C_sev at weight 0.20. An
      unknown distance is now treated as the worst case the formula already
      defines, i.e. the 40.0 floor.
    * an outer `max(10.0, ...)` floor, where the formula's own minimum is 8.0,
      so 8.0 was reported as 10.0. The composite cannot fall below the
      reinvestigation trigger either way.
    """
    # Distance certainty: closer means higher spatial precision
    if distance_m is not None:
        dist_certainty = max(40.0, 100.0 - (distance_m / 50.0))
    else:
        dist_certainty = 40.0

    conf = (
        0.25 * firms_confidence +
        0.35 * ai_confidence +
        0.20 * dist_certainty +
        0.20 * (history_reliability * 100.0 if history_reliability <= 1.0 else history_reliability)
    )
    return min(100.0, round(conf, 1))


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

    # Operational overrides raise the level, they never lower it.
    #
    # Section 4.6 states each override clause as a forced *minimum* -- "HIGH
    # (FRP >= 250MW => CRITICAL)" at a forced minimum of 55.0 -- and two of the
    # four clauses in `evaluate_severity_overrides` are already written that way
    # (`if forced_level is None or forced_level in ["LOW", "MEDIUM"]`). Applying
    # the returned level as a replacement instead let a clause whose stated
    # purpose is escalation *demote* an incident. Concretely, 160 MW at 95%
    # FIRMS confidence with 92% AI confidence scores S_ai 88.6 and a weighted
    # base of 89.59 -- CRITICAL -- and the EXTREME_FRP clause then returned
    # HIGH, publishing "HIGH" beside a score of 89.6.
    #
    # LEVEL_RANK exists only to compare the two; the tier floors are what make a
    # forced level meaningful on the score axis.
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

    tier_min_scores = {"LOW": 10.0, "MEDIUM": 30.0, "HIGH": 55.0, "CRITICAL": 80.0}
    if forced_level and LEVEL_RANK.get(forced_level, -1) > LEVEL_RANK.get(base_level, 99):
        final_level = forced_level
        final_score = max(base_score, tier_min_scores[forced_level])
    else:
        final_level = base_level
        final_score = base_score

    # INV-4 -- Routine continuous flaring inside the facility's own empirical
    # 365-day P95 envelope is suppressed to a low score. Section 4.6.2 clamps
    # only S_dev, which is not sufficient on its own: with S_dev held at its own
    # 20.0 ceiling the KNOWN_HOTSPOT model still returns
    #   0.35*S_frp + 0.30*20.0 + 0.20*S_ai + 0.15*S_gis,
    # so a large but entirely routine flare (say 5,000 MW against a 6,000 MW P95
    # ceiling, AI `gas_flare` at 90%) reached the mid-70s -- CRITICAL -- while
    # INV-4's headline promises such a detection is "clamped to low severity
    # scores (<= 20.0)". The invariant is the contract; clamp the composite.
    routine_suppressed = is_routine_flare and p95_frp > 0.0 and frp_mw <= p95_frp
    if routine_suppressed:
        if final_score > 20.0:
            trigger_note = f"ROUTINE_FLARE_SUPPRESSION (composite {final_score:.1f} -> 20.0)"
        else:
            trigger_note = None
        final_score = min(20.0, final_score)
        final_level = score_to_level(final_score)
        forced_level = None
        if trigger_note:
            override_reasons.append(trigger_note)

    # The level is banded from the score that is actually published, not from the
    # unrounded one. `severity_score` is rounded to one decimal on the way out,
    # and rounding can cross a band boundary: a base of 74.96 was banded HIGH and
    # then published as 75.0, which every consumer -- the console's checkTiers
    # (data.js:110-119), the feed's `risk_tier`, the alert tier -- reads as
    # CRITICAL. Two decimals of headroom is not worth a record that contradicts
    # itself. The tier floors are chosen so this cannot undo an override: a
    # forced floor of 55.0/80.0 bands back to HIGH/CRITICAL exactly.
    final_level = score_to_level(round(final_score, 1))

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
