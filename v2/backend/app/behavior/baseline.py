"""
FIREX v2 Historical Baseline Engine
Computes:
1. A 365-day rolling baseline per Specification 4.4 (30/90-day sub-counts are
   persisted alongside it for the multi-window summaries).
2. Statistical Percentiles: Median FRP, P90 FRP, P95 FRP, Mean FRP, Min/Max.
3. History Reliability: the specification's five discrete observation-count
   tiers (Section 4.4, spec lines 155-162), reported on a 0.0 - 1.0 scale.
"""
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import Observation, HistoricalBaseline, BehaviorProfile, IndustrialAsset, ThermalClimatology
from app.gis.spatial import haversine_distance_km
from app.gis.mining_basins import is_in_major_mining_basin
from app.gis.assets import find_nearest_asset, is_flaring_facility, is_metallurgical_or_manufacturing_facility
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
    Returns how trustworthy the historical baseline is, using the
    specification's five discrete tiers (Section 4.4, spec lines 155-162):

        obs = 0      -> 0.00 ('NONE')
        1 <= obs <= 4  -> 0.25 ('LOW')
        5 <= obs <= 9  -> 0.50 ('MODERATE')
        10 <= obs <= 19 -> 0.75 ('GOOD')
        obs >= 20    -> 1.00 ('STRONG')

    The scale stays 0.0 - 1.0 because severity/scoring.py multiplies it by 100
    into C_sev. The previous implementation blended
    0.6*min(1.0, obs/20.0) + 0.4*min(1.0, active_days/max(1, min(15, window//3)))
    into a continuous value clamped to [0.1, 1.0], which is not the documented
    function at all: at a 90-day window it returned 0.10 for 1 observation,
    0.28 for 5 and 0.97 for 19, where the spec's tiers are 0.25, 0.50 and 0.75
    (defect F-019 / C3).

    `active_days` and `window_days` are retained because every call site passes
    them, but the spec's tiers key on the observation count alone.
    """
    if observation_count <= 0:
        return 0.0
    elif observation_count <= 4:
        return 0.25
    elif observation_count <= 9:
        return 0.50
    elif observation_count <= 19:
        return 0.75
    else:
        return 1.00

def _is_routine_flare_by_inv4(active_days: int, p95_frp: float) -> bool:
    """
    INV-4 (spec line 32): "Persistent flares with >= 10 active days/year
    operating within their empirical 365-day 95th-percentile (P95) baseline
    envelope are marked as ROUTINE_FLARE."

    So the flag here is exactly `active_days >= 10` AND the site's own P95
    envelope is known (`p95_frp > 0`). Facility-type gating still applies on
    top (§5: mining basins and metallurgical plants are never routine flares).

    This is NOT the predicate the climatology producer applies, and the two
    disagree -- which is F-046, not a closed defect. The producer writes its own
    `is_routine_flare` bit from `is_routine_flare_cell`
    (scripts/build_thermal_climatology.py:90), which adds a third conjunct this
    reader does not carry: `night_ratio >= 0.25`. A persistent cell whose
    detections are all daytime is therefore ROUTINE_FLARE to this module and not
    in `thermal_climatology`, and a severity consumer that reads the stored bit
    gets the producer's answer instead. Measured divergence at the time of
    writing: 589 cells. An earlier version of this docstring claimed the two
    predicates agreed; they do not.

    The divergence is inert today -- no live incident, severity row or served
    record is decided by it -- and whether INV-4 admits a nocturnality term at
    all is unresolved (the producer's own comment at its :80-82 calls that term
    "not part of INV-4"), so the reconciliation is a product decision rather
    than a bug fix and is deliberately left open here.
    """
    return bool(active_days >= 10 and (p95_frp or 0.0) > 0.0)

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
    window_days: int = 365,
    search_radius_km: float = 3.0,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Extracts or computes historical baseline for a location within search_radius_km.
    Queries all observations in database over the past window_days.

    `window_days` defaults to 365 because Stage 4 is defined as a "365-day
    rolling window" (spec line 150). The 90-day default here was the defect:
    every production caller either passed 90 explicitly or inherited it, so the
    "365-day baselines" the Stage-4 output promises were quarter-length
    (defect F-018 / C2). Callers that genuinely want a shorter horizon still can
    -- api/history.py exposes it as a query parameter.
    """
    spatial_key = generate_spatial_key(lat, lon)
    now = datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    # Check sovereign Indian mining basin containment
    is_mining, basin = is_in_major_mining_basin(lat, lon)

    # Check industrial facility context
    asset_info = find_nearest_asset(lat, lon, db)
    dist_km = asset_info.get("distance_km") or 999.0
    is_near_facility = asset_info.get("is_inside_facility") or (dist_km <= 5.0)
    is_metal_fac = is_near_facility and (
        is_metallurgical_or_manufacturing_facility(asset_info.get("facility_type"), asset_info.get("industry"))
        or asset_info.get("category") == "industrial_fire"
    )
    is_flare_fac = is_near_facility and is_flaring_facility(asset_info.get("facility_type"), asset_info.get("category"))

    # 1. Check existing baseline cache.
    existing_bl = (
        db.query(HistoricalBaseline)
        .filter(HistoricalBaseline.spatial_key == spatial_key)
        .first()
    )
    # A flare-adjacent site never takes this shortcut: the cached row stores no
    # active-day count, so INV-4's routine-flare predicate (spec line 32) cannot
    # be evaluated from it. Such sites resolve through the climatology cell or
    # the fresh observation scan below, both of which know active_days. This is
    # one of the two F-046 sites -- the cache path used to inherit
    # `is_persistent`'s (obs >= 5 and active_days >= 3) test, i.e. three active
    # days against the invariant's ten.
    if (not force_refresh and existing_bl and existing_bl.last_updated_at
            and (now - existing_bl.last_updated_at).total_seconds() < 86400
            and not is_flare_fac):
        # detection_count_* are stored per horizon; read the one matching the
        # requested window so a 90-day count is never reported as a 365-day one.
        if window_days <= 30:
            count = existing_bl.detection_count_30d or 0
        elif window_days <= 90:
            count = existing_bl.detection_count_90d or 0
        else:
            count = existing_bl.detection_count_365d or 0
        if is_mining:
            is_routine = False
            hint = "COAL_MINING_BASIN"
        elif is_metal_fac:
            is_routine = False
            hint = "METALLURGICAL_INDUSTRIAL"
        else:
            # No facility context: episodic. (A flare-adjacent site is excluded
            # from this branch by the cache guard above.)
            is_routine = False
            hint = "EPISODIC_THERMAL"
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
            "is_persistent": existing_bl.is_persistent,
            "is_routine_flare": is_routine,
            "site_classification_hint": hint,
            "is_mining_basin": is_mining,
            "is_metallurgical_facility": is_metal_fac,
            "nearest_asset": asset_info if is_near_facility else None
        }

    # 1b. Check National Thermal Climatology (pre-computed 0.02° grid across 2.89M Indian observations)
    clim = (
        db.query(ThermalClimatology)
        .filter(ThermalClimatology.spatial_key == spatial_key)
        .first()
    )
    if not force_refresh and clim:
        count = clim.observation_count or 0
        active_days = clim.active_days or 0
        reliability = calculate_history_reliability(count, active_days, window_days)
        if is_mining:
            is_routine = False
            hint = "COAL_MINING_BASIN"
        elif is_metal_fac:
            is_routine = False
            hint = "METALLURGICAL_INDUSTRIAL"
        # Sovereign offshore petroleum flaring sector (Bombay High: 18.0-20.5°N, 70.5-72.5°E)
        elif is_flare_fac or (18.0 <= lat <= 20.5 and 70.5 <= lon <= 72.5):
            # INV-4 (spec line 32). The cell carries both of the invariant's
            # inputs -- its 365-day active_days and its P95 envelope -- so the
            # flag is derived from the same predicate the climatology generator
            # applies (see _is_routine_flare_by_inv4) rather than read back from
            # the generator's own pre-computed bit. Defect F-046: producer and
            # consumer previously keyed on different thresholds.
            is_routine = _is_routine_flare_by_inv4(active_days, clim.p95_frp)
            hint = "ROUTINE_FLARE" if is_routine else (clim.site_classification_hint or "EPISODIC_THERMAL")
        else:
            is_routine = False
            hint = "PERSISTENT_INDUSTRIAL" if bool(clim.is_routine_flare) else (clim.site_classification_hint or "EPISODIC_THERMAL")

        is_persistent = bool(is_routine or (count >= 5 and active_days >= 3) or is_mining or is_metal_fac)
        return {
            "spatial_key": spatial_key,
            "window_days": window_days,
            "observation_count": count,
            "active_days_365d": active_days,
            "median_frp": clim.median_frp or 0.0,
            "p90_frp": clim.p90_frp or 0.0,
            "p95_frp": clim.p95_frp or 0.0,
            "mean_frp": clim.median_frp or 0.0,
            "min_frp": 0.0,
            "max_frp": clim.max_frp or 0.0,
            "night_ratio": clim.night_ratio or 0.0,
            "is_routine_flare": is_routine,
            "site_classification_hint": hint,
            "is_mining_basin": is_mining,
            "is_metallurgical_facility": is_metal_fac,
            "nearest_asset": asset_info if is_near_facility else None,
            "history_reliability": reliability,
            "history_reliability_label": classify_history_reliability(count),
            "is_persistent": is_persistent
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

    # INV-4 (spec line 32): ROUTINE_FLARE is a flare-adjacent site with >= 10
    # active days/year inside its own empirical 365-day P95 envelope. The fresh
    # path previously hard-coded False here, so a persistent refinery flare at a
    # coordinate with no ThermalClimatology cell was never suppressible -- the
    # second half of defect F-046.
    is_routine_flare = bool(is_flare_fac and _is_routine_flare_by_inv4(active_days, stats["p95"]))
    if is_mining:
        site_hint = "COAL_MINING_BASIN"
    elif is_metal_fac:
        site_hint = "METALLURGICAL_INDUSTRIAL"
    elif is_flare_fac:
        site_hint = "ROUTINE_FLARE" if is_routine_flare else "EPISODIC_THERMAL"
    else:
        site_hint = "EPISODIC_THERMAL"

    # Per-horizon detection counts. matching_obs is already scoped to
    # window_days, so the 30/90-day figures are exact and the third slot holds
    # the count over the requested window -- 365 by default, which is what the
    # cached-baseline reader above selects on.
    count_30d = len([o for o in matching_obs if o.acquired_at and o.acquired_at >= now - timedelta(days=30)])
    count_90d = len([o for o in matching_obs if o.acquired_at and o.acquired_at >= now - timedelta(days=90)])
    count_window = len(matching_obs)

    # 3. Store / update materialized baseline
    if not existing_bl:
        existing_bl = HistoricalBaseline(
            spatial_key=spatial_key,
            window_start=window_start,
            window_end=now,
            detection_count_30d=count_30d,
            detection_count_90d=count_90d,
            detection_count_365d=count_window,
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
        existing_bl.window_start = window_start
        existing_bl.window_end = now
        existing_bl.detection_count_30d = count_30d
        existing_bl.detection_count_90d = count_90d
        existing_bl.detection_count_365d = count_window
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
        "is_persistent": is_persistent,
        "is_routine_flare": is_routine_flare,
        "site_classification_hint": site_hint,
        "is_mining_basin": is_mining,
        "is_metallurgical_facility": is_metal_fac,
        "nearest_asset": asset_info if is_near_facility else None
    }

def get_or_create_facility_baseline(
    facility_id: str,
    db: Session,
    window_days: int = 365,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Computes statistical baseline for a specific industrial asset / facility.

    `window_days` defaults to the specification's 365-day Stage-4 window; see
    get_or_create_location_baseline for why.
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
