"""
FIREX v2 Historical Trend & Multi-Window Activity Engine
Calculates:
- Temporal trajectory: INCREASING, STABLE, DECREASING
- 30-day, 90-day, and 365-day observation frequency trends
- Historical daily summaries for dashboard charts
"""
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import Observation
from app.gis.spatial import haversine_distance_km

def compute_historical_trend(
    observations: List[Observation]
) -> Dict[str, Any]:
    """
    Computes emission trend direction (INCREASING, STABLE, DECREASING)
    by comparing recent window (last 7 days) against older baseline window (8-30 days).
    """
    if len(observations) < 4:
        return {
            "trend_direction": "INSUFFICIENT_DATA",
            "frp_velocity": 0.0,
            "recent_mean_frp": 0.0,
            "historical_mean_frp": 0.0,
            "daily_histogram": []
        }

    # Group by date
    daily_groups: Dict[str, List[float]] = {}
    for o in observations:
        if not o.acquired_at:
            continue
        d_str = o.acquired_at.strftime("%Y-%m-%d")
        if d_str not in daily_groups:
            daily_groups[d_str] = []
        daily_groups[d_str].append(float(o.frp_mw or 0.0))

    sorted_dates = sorted(daily_groups.keys())
    daily_histogram = [
        {
            "date": d,
            "observation_count": len(daily_groups[d]),
            "mean_frp": round(sum(daily_groups[d]) / len(daily_groups[d]), 2),
            "max_frp": round(max(daily_groups[d]), 2)
        }
        for d in sorted_dates
    ]

    # Split into recent half vs older half
    half = len(sorted_dates) // 2
    older_dates = sorted_dates[:half]
    recent_dates = sorted_dates[half:]

    older_frps = [val for d in older_dates for val in daily_groups[d]]
    recent_frps = [val for d in recent_dates for val in daily_groups[d]]

    older_mean = sum(older_frps) / len(older_frps) if older_frps else 0.0
    recent_mean = sum(recent_frps) / len(recent_frps) if recent_frps else 0.0

    velocity = round(recent_mean - older_mean, 2)

    if velocity > 5.0:
        trend = "INCREASING"
    elif velocity < -5.0:
        trend = "DECREASING"
    else:
        trend = "STABLE"

    return {
        "trend_direction": trend,
        "frp_velocity": velocity,
        "recent_mean_frp": round(recent_mean, 2),
        "historical_mean_frp": round(older_mean, 2),
        "daily_histogram": daily_histogram
    }
