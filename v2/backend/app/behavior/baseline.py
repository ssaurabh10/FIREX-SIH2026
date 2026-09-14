"""
FIREX v2 Historical Baseline Engine
Computes:
1. Multi-window baselines: 30 days, 90 days, 365 days.
2. Statistical Percentiles: Median FRP, P90 FRP, P95 FRP, Mean FRP, Min/Max.
3. History Reliability Score: Continuous 0.0 - 1.0 based on observation density and window completeness.
"""
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.storage.models import Observation, HistoricalBaseline, BehaviorProfile, IndustrialAsset
from app.gis.spatial import haversine_distance_km
from app.core.logging import logger

def compute_percentiles(values: List[float]) -> Dict[str, float]:
    """
    Computes statistical percentiles (Median, P90, P95, Mean, Min, Max) for a list of FRP numbers.
    """
    if not values:
        return {
            "median": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0
        }
    
    sorted_v = sorted(values)
    n = len(sorted_v)
    
    def get_p(p: float) -> float:
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_v[int(k)]
        return sorted_v[int(f)] * (c - k) + sorted_v[int(c)] * (k - f)

    return {
        "median": round(get_p(0.50), 2),
        "p90": round(get_p(0.90), 2),
        "p95": round(get_p(0.95), 2),
        "mean": round(sum(sorted_v) / n, 2),
        "min": round(sorted_v[0], 2),
        "max": round(sorted_v[-1], 2)
    }

def classify_history_reliability(observation_count: int) -> str:
    """
    Blueprint 13.7:
    0 observations -> NONE
    1-4            -> LOW
    5-9            -> MODERATE
    10-19          -> GOOD
    20+            -> STRONG
    """
    if observation_count == 0:
        return "NONE"
    elif observation_count <= 4:
        return "LOW"
    elif observation_count <= 9:
        return "MODERATE"
    elif observation_count <= 19:
        return "GOOD"
    else:
        return "STRONG"

def calculate_history_reliability(observation_count: int, active_days: int, window_days: int) -> float:
    """
    Calculates how trustworthy the historical baseline is (0.0 to 1.0).
    - If observation_count < 3: Low reliability (< 0.40)
    - If observation_count >= 15 with consistent days: High reliability (> 0.85)
    """
    if observation_count == 0:
        return 0.0
    
    # Weight based on count (maxes out at 20 observations)
    count_factor = min(1.0, observation_count / 20.0)
    # Weight based on active days spread
    days_factor = min(1.0, active_days / max(1, min(15, window_days // 3)))
    
    reliability = 0.6 * count_factor + 0.4 * days_factor
    return round(max(0.1, min(1.0, reliability)), 2)

def generate_spatial_key(lat: float, lon: float, precision: int = 2) -> str:
    """
    Generates a 0.01 deg (~1.1 km) or 0.05 deg grid cell spatial key.
    """
    grid_lat = round(lat, precision)
    grid_lon = round(lon, precision)
    return f"GRID_{grid_lat:.2f}_{grid_lon:.2f}"

def get_or_create_location_baseline(
    lat: float,
    lon: float,
    db: Session,
    window_days: int = 90,
    search_radius_km: float = 3.0,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Extracts or computes historical baseline for a location within search_radius_km.
    Queries all observations in database over the past window_days.
    """
    spatial_key = generate_spatial_key(lat, lon)
    now = datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    # 1. Check existing baseline cache
    existing_bl = (
        db.query(HistoricalBaseline)
        .filter(HistoricalBaseline.spatial_key == spatial_key)
        .first()
    )
    if not force_refresh and existing_bl and existing_bl.last_updated_at and (now - existing_bl.last_updated_at).total_seconds() < 86400:
        count = existing_bl.detection_count_90d or 0
        return {
            "spatial_key": spatial_key,
            "window_days": window_days,
            "observation_count": count,
            "median_frp": existing_bl.median_frp,
            "p90_frp": existing_bl.p90_frp,
            "p95_frp": existing_bl.p95_frp,
            "mean_frp": existing_bl.mean_frp,
            "min_frp": 0.0,
            "max_frp": existing_bl.p95_frp or 0.0,
            "history_reliability": existing_bl.history_reliability,
            "history_reliability_label": classify_history_reliability(count),
            "is_persistent": existing_bl.is_persistent
        }

    # 2. Query observations within coordinate delta
    # 1 deg lat ~ 111 km
    lat_delta = search_radius_km / 111.0
    lon_delta = search_radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))

    obs_records = (
        db.query(Observation)
        .filter(
            Observation.latitude >= lat - lat_delta,
            Observation.latitude <= lat + lat_delta,
            Observation.longitude >= lon - lon_delta,
            Observation.longitude <= lon + lon_delta,
            Observation.acquired_at >= window_start
        )
        .all()
    )

    # Filter with exact Haversine distance
    matching_obs = [
        o for o in obs_records
        if haversine_distance_km(lat, lon, o.latitude, o.longitude) <= search_radius_km
    ]

    frp_values = [float(o.frp_mw or 0.0) for o in matching_obs]
    stats = compute_percentiles(frp_values)
    
    unique_dates = {o.acquired_at.strftime("%Y-%m-%d") for o in matching_obs if o.acquired_at}
    active_days = len(unique_dates)
    reliability = calculate_history_reliability(len(matching_obs), active_days, window_days)
    is_persistent = (len(matching_obs) >= 5 and active_days >= 3)

    # 3. Store / update materialized baseline
    if not existing_bl:
        existing_bl = HistoricalBaseline(
            spatial_key=spatial_key,
            window_start=window_start,
            window_end=now,
            detection_count_30d=len([o for o in matching_obs if o.acquired_at >= now - timedelta(days=30)]),
            detection_count_90d=len(matching_obs),
            detection_count_365d=len(matching_obs),
            median_frp=stats["median"],
            p90_frp=stats["p90"],
            p95_frp=stats["p95"],
            mean_frp=stats["mean"],
            history_reliability=reliability,
            is_persistent=is_persistent,
            last_updated_at=now
        )
        db.add(existing_bl)
    else:
        existing_bl.detection_count_90d = len(matching_obs)
        existing_bl.median_frp = stats["median"]
        existing_bl.p90_frp = stats["p90"]
        existing_bl.p95_frp = stats["p95"]
        existing_bl.mean_frp = stats["mean"]
        existing_bl.history_reliability = reliability
        existing_bl.is_persistent = is_persistent
        existing_bl.last_updated_at = now

    db.commit()

    return {
        "spatial_key": spatial_key,
        "window_days": window_days,
        "observation_count": len(matching_obs),
        "active_days": active_days,
        "median_frp": stats["median"],
        "p90_frp": stats["p90"],
        "p95_frp": stats["p95"],
        "mean_frp": stats["mean"],
        "min_frp": stats["min"],
        "max_frp": stats["max"],
        "history_reliability": reliability,
        "history_reliability_label": classify_history_reliability(len(matching_obs)),
        "is_persistent": is_persistent
    }

def get_or_create_facility_baseline(
    facility_id: str,
    db: Session,
    window_days: int = 90,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Computes statistical baseline for a specific industrial asset / facility.
    """
    asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == facility_id).first()
    if not asset:
        return {
            "facility_id": facility_id,
            "error": "Facility not found",
            "observation_count": 0,
            "median_frp": 0.0,
            "p90_frp": 0.0,
            "p95_frp": 0.0,
            "mean_frp": 0.0,
            "history_reliability": 0.0,
            "history_reliability_label": "NONE",
            "is_persistent": False
        }

    search_radius_km = (asset.buffer_radius_meters or 1500.0) / 1000.0
    res = get_or_create_location_baseline(
        lat=asset.latitude,
        lon=asset.longitude,
        db=db,
        window_days=window_days,
        search_radius_km=search_radius_km,
        force_refresh=force_refresh
    )
    res["facility_id"] = facility_id
    res["facility_name"] = asset.name
    res["facility_type"] = asset.facility_type
    res["normal_activity_range"] = [res.get("min_frp", 0.0), res.get("p95_frp", 0.0)]
    return res
