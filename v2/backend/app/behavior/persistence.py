"""
FIREX v2 Thermal Persistence Engine
Distinguishes:
1. 24h Continuous Industrial Flaring (Day + Night presence)
2. Recurrent Industrial Smelters / Kilns (regular active days)
3. One-off new thermal ignitions (Wildfires / Ag-burning with zero prior detection)
Generates a continuous persistence score (0.0 to 1.0).
"""
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import Observation
from app.gis.spatial import haversine_distance_km

def calculate_persistence_score(
    observations: List[Observation],
    window_days: int = 365
) -> Dict[str, Any]:
    """
    Evaluates thermal persistence characteristics:
    - detection_count
    - active_days
    - day_pass_count vs night_pass_count
    - day_night_continuous: True if detected during BOTH Day and Night passes
    - persistence_score: 0.0 (Isolated / New) to 1.0 (Confirmed 24h Continuous Industrial)

    `window_days` is the rolling window the caller already scoped `observations`
    to, and defaults to Specification 4.4's 365-day Stage-4 window. The spec's
    persistence formula itself is window-independent -- it consumes the two
    counts the window produced -- so the parameter is carried for call-site
    compatibility and reporting only.
    """
    if not observations:
        return {
            "persistence_score": 0.0,
            "detection_count": 0,
            "active_days": 0,
            "day_pass_count": 0,
            "night_pass_count": 0,
            "day_night_continuous": False,
            "persistence_classification": "NEW_UNOBSERVED"
        }

    total_obs = len(observations)
    dates = {o.acquired_at.strftime("%Y-%m-%d") for o in observations if o.acquired_at}
    active_days = len(dates)

    day_count = len([o for o in observations if (o.daynight or "DAY").upper() == "DAY"])
    night_count = len([o for o in observations if (o.daynight or "DAY").upper() == "NIGHT"])

    # Check 24h continuous flaring signature (present in daytime AND nighttime)
    has_day_and_night = (day_count > 0 and night_count > 0)

    # Specification 4.4, spec line 153:
    #   persistence_score = min(1.0, (active_days/45.0)*0.7 + min(1.0, obs_count/100.0)*0.3)
    # Returns the spec's 0.0-1.0 scale, which behavior/anomaly.py compares
    # against >= 0.50 when it crosses the synthesis matrix.
    #
    # The previous formula was freq = min(1.0, active_days/15.0), density =
    # min(1.0, total_obs/25.0) and an undocumented 0.35 day/night bonus with
    # weights 0.35/0.30. 15 active days with >= 25 observations therefore scored
    # 0.35 + 0.30 + 0.35 = 1.00, where the spec's formula gives
    # 0.7*(15/45) + 0.3*(25/100) = 0.308. That ~3x inflation fired the matrix's
    # >= 0.50 persistence test far earlier than the spec intends (defect F-016).
    score = round(
        min(1.0, (active_days / 45.0) * 0.7 + min(1.0, total_obs / 100.0) * 0.3),
        2
    )

    # Pattern labels are code-local: the specification defines no persistence
    # classification vocabulary, so these thresholds are anchored to the spec
    # formula's own range rather than to the retired inflated one. Under the
    # spec formula a continuously flaring industrial source clears 0.70 at
    # ~26 active days (with obs_count >= 100), which is the intended bar.
    if score >= 0.70 and has_day_and_night:
        pattern = "CONFIRMED_CONTINUOUS_24H_INDUSTRIAL"
    elif score >= 0.40:
        pattern = "RECURRING_INTERMITTENT_THERMAL"
    elif total_obs <= 2:
        pattern = "NEW_UNOBSERVED_IGNITION"
    else:
        pattern = "EPISODIC_ACTIVITY"

    return {
        "persistence_score": score,
        "detection_count": total_obs,
        "active_days": active_days,
        "day_pass_count": day_count,
        "night_pass_count": night_count,
        "day_night_continuous": has_day_and_night,
        "persistence_classification": pattern
    }
