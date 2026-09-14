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
    window_days: int = 90
) -> Dict[str, Any]:
    """
    Evaluates thermal persistence characteristics:
    - detection_count
    - active_days
    - day_pass_count vs night_pass_count
    - day_night_continuous: True if detected during BOTH Day and Night passes
    - persistence_score: 0.0 (Isolated / New) to 1.0 (Confirmed 24h Continuous Industrial)
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

    # Calculate score components
    # Frequency component: active days out of 30 expected
    freq_score = min(1.0, active_days / 15.0)
    # Density component
    density_score = min(1.0, total_obs / 25.0)
    # Day/Night bonus: continuous 24h emission adds 0.35 weight
    continuous_bonus = 0.35 if has_day_and_night else 0.0

    raw_score = (0.35 * freq_score) + (0.30 * density_score) + continuous_bonus
    score = round(min(1.0, raw_score), 2)

    # Classify pattern
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
