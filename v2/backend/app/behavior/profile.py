"""
FIREX v2 Historical Behavior Profile Engine
Builds and materializes:
1. Location History Profiles
2. Facility History Profiles
3. Multi-window summaries (30d / 90d / 365d)
4. Daily summaries
5. Incremental feature refresh & cache
"""
import math
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import (
    Observation, IndustrialAsset, Incident,
    BehaviorProfile, BehaviorDailySummary, HistoricalBaseline
)
from app.gis.spatial import haversine_distance_km
from app.behavior.baseline import (
    compute_percentiles,
    calculate_history_reliability,
    classify_history_reliability,
    generate_spatial_key
)
from app.behavior.persistence import calculate_persistence_score
from app.behavior.trends import compute_historical_trend
from app.core.logging import logger

def compute_multi_window_metrics(
    observations: List[Observation],
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Computes distinct metrics for 30-day, 90-day, and 365-day windows.
    """
    if now is None:
        now = datetime.utcnow()

    obs_30d = [o for o in observations if o.acquired_at and o.acquired_at >= now - timedelta(days=30)]
    obs_90d = [o for o in observations if o.acquired_at and o.acquired_at >= now - timedelta(days=90)]
    obs_365d = [o for o in observations if o.acquired_at and o.acquired_at >= now - timedelta(days=365)]

    def summarize_obs(subset: List[Observation], days: int) -> Dict[str, Any]:
        frps = [float(o.frp_mw or 0.0) for o in subset]
        stats = compute_percentiles(frps)
        dates = {o.acquired_at.strftime("%Y-%m-%d") for o in subset if o.acquired_at}
        active_days = len(dates)
        det_freq = round(active_days / max(1, days), 4)
        reliability = calculate_history_reliability(len(subset), active_days, days)
        return {
            "window_days": days,
            "observation_count": len(subset),
            "active_days": active_days,
            "detection_frequency": det_freq,
            "median_frp": stats["median"],
            "mean_frp": stats["mean"],
            "p90_frp": stats["p90"],
            "p95_frp": stats["p95"],
            "min_frp": stats["min"],
            "max_frp": stats["max"],
            "history_reliability": reliability,
            "history_reliability_label": classify_history_reliability(len(subset))
        }

    return {
        "window_30d": summarize_obs(obs_30d, 30),
        "window_90d": summarize_obs(obs_90d, 90),
        "window_365d": summarize_obs(obs_365d, 365)
    }

def build_daily_summaries(
    profile_id: str,
    observations: List[Observation],
    db: Session
) -> List[Dict[str, Any]]:
    """
    Groups observations by day, records BehaviorDailySummary entities,
    and returns a clean JSON summary list.
    """
    daily_groups: Dict[str, List[float]] = {}
    for o in observations:
        if not o.acquired_at:
            continue
        d_str = o.acquired_at.strftime("%Y-%m-%d")
        if d_str not in daily_groups:
            daily_groups[d_str] = []
        daily_groups[d_str].append(float(o.frp_mw or 0.0))

    summaries = []
    # Remove existing daily summaries for this profile
    db.query(BehaviorDailySummary).filter(BehaviorDailySummary.profile_id == profile_id).delete()

    for date_str in sorted(daily_groups.keys()):
        frps = daily_groups[date_str]
        count = len(frps)
        mean_frp = round(sum(frps) / count, 2)
        max_frp = round(max(frps), 2)
        sorted_f = sorted(frps)
        if count % 2 == 1:
            median_frp = sorted_f[count // 2]
        else:
            median_frp = round((sorted_f[count // 2 - 1] + sorted_f[count // 2]) / 2.0, 2)

        record = BehaviorDailySummary(
            profile_id=profile_id,
            date=date_str,
            observation_count=count,
            max_frp=max_frp,
            mean_frp=mean_frp,
            median_frp=median_frp,
            active=True
        )
        db.add(record)
        summaries.append({
            "date": date_str,
            "observation_count": count,
            "mean_frp": mean_frp,
            "median_frp": median_frp,
            "max_frp": max_frp
        })

    db.commit()
    return summaries

def get_or_create_location_profile(
    lat: float,
    lon: float,
    db: Session,
    window_days: int = 365,
    search_radius_km: float = 3.0,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Generates or retrieves a materialized location history profile.
    Answers:
    - What is normal here?
    - How often does activity recur?
    - Is the source persistent?
    - How reliable is the historical evidence?

    `window_days` defaults to the specification's 365-day Stage-4 window
    (spec line 150); the 90-day default this used to carry made every
    "365-day baseline" quarter-length (defect F-018 / C2). Callers that want a
    shorter horizon -- the REST layer, which exposes it as a query parameter --
    can still pass one.
    """
    spatial_key = generate_spatial_key(lat, lon)
    now = datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    # 1. Check existing cached profile
    profile = (
        db.query(BehaviorProfile)
        .filter(
            BehaviorProfile.profile_type == "location",
            BehaviorProfile.spatial_reference == spatial_key
        )
        .first()
    )

    if not force_refresh and profile and profile.updated_at and (now - profile.updated_at).total_seconds() < 86400:
        # Load daily summaries
        daily_records = (
            db.query(BehaviorDailySummary)
            .filter(BehaviorDailySummary.profile_id == profile.id)
            .order_by(BehaviorDailySummary.date.asc())
            .all()
        )
        daily_summaries = [
            {
                "date": d.date,
                "observation_count": d.observation_count,
                "mean_frp": d.mean_frp,
                "median_frp": d.median_frp,
                "max_frp": d.max_frp
            }
            for d in daily_records
        ]
        return {
            "profile_id": profile.id,
            "profile_type": "location",
            "spatial_reference": spatial_key,
            "window_days": window_days,
            "observation_count": profile.observation_count,
            "active_days": profile.active_days,
            "median_frp": profile.median_frp,
            "mean_frp": profile.mean_frp,
            "p90_frp": profile.p90_frp,
            "p95_frp": profile.p95_frp,
            "min_frp": profile.min_frp,
            "max_frp": profile.max_frp,
            "normal_activity_range": [profile.min_frp, profile.p95_frp],
            "detection_frequency": profile.detection_frequency,
            "persistence_score": profile.persistence_score,
            "history_reliability": profile.history_reliability,
            "history_reliability_label": classify_history_reliability(profile.observation_count or 0),
            "day_passes_count": profile.day_passes_count or 0,
            "night_passes_count": profile.night_passes_count or 0,
            "is_continuous_24h": bool(profile.is_continuous_24h),
            "daily_summaries": daily_summaries,
            "answers": {
                "what_is_normal_here": f"Typical median FRP is {profile.median_frp} MW (P95 upper limit: {profile.p95_frp} MW).",
                "how_often_does_activity_recur": f"Detected on {profile.active_days} distinct days over {window_days} days (frequency: {round((profile.detection_frequency or 0.0) * 100, 1)}%).",
                "is_source_persistent": f"Persistence score is {profile.persistence_score} ({'Persistent' if (profile.persistence_score or 0) >= 0.50 else 'Intermittent/New'}).",
                "how_reliable_is_history": f"{classify_history_reliability(profile.observation_count or 0)} ({profile.observation_count} observations)."
            }
        }

    # 2. Query observations within search radius over 365 days to support all windows
    max_window_start = now - timedelta(days=365)
    lat_delta = search_radius_km / 111.0
    lon_delta = search_radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))

    candidates = (
        db.query(Observation)
        .filter(
            Observation.latitude >= lat - lat_delta,
            Observation.latitude <= lat + lat_delta,
            Observation.longitude >= lon - lon_delta,
            Observation.longitude <= lon + lon_delta,
            Observation.acquired_at >= max_window_start
        )
        .all()
    )

    matching_365d = [
        o for o in candidates
        if haversine_distance_km(lat, lon, o.latitude, o.longitude) <= search_radius_km
    ]
    matching_window = [o for o in matching_365d if o.acquired_at and o.acquired_at >= window_start]

    frp_values = [float(o.frp_mw or 0.0) for o in matching_window]
    stats = compute_percentiles(frp_values)
    dates = {o.acquired_at.strftime("%Y-%m-%d") for o in matching_window if o.acquired_at}
    active_days = len(dates)
    det_freq = round(active_days / max(1, window_days), 4)

    persistence_info = calculate_persistence_score(matching_window, window_days)
    persistence_score = persistence_info["persistence_score"]

    reliability = calculate_history_reliability(len(matching_window), active_days, window_days)
    reliability_label = classify_history_reliability(len(matching_window))

    # 3. Materialize profile record
    # window_days / day_passes_count / night_passes_count / is_continuous_24h
    # are live columns on behavior_profiles that the profiler used to leave at
    # their defaults, so a rebuilt-from-ORM profile could not reproduce the
    # running table's content (defect F-061). They are written from the
    # persistence evaluation below, which is what computes them.
    if not profile:
        profile = BehaviorProfile(
            profile_type="location",
            spatial_reference=spatial_key,
            window_start=window_start,
            window_end=now,
            window_days=window_days,
            observation_count=len(matching_window),
            active_days=active_days,
            day_passes_count=persistence_info["day_pass_count"],
            night_passes_count=persistence_info["night_pass_count"],
            is_continuous_24h=persistence_info["day_night_continuous"],
            median_frp=stats["median"],
            mean_frp=stats["mean"],
            p90_frp=stats["p90"],
            p95_frp=stats["p95"],
            min_frp=stats["min"],
            max_frp=stats["max"],
            detection_frequency=det_freq,
            persistence_score=persistence_score,
            history_reliability=reliability,
            updated_at=now
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    else:
        profile.window_start = window_start
        profile.window_end = now
        profile.window_days = window_days
        profile.observation_count = len(matching_window)
        profile.active_days = active_days
        profile.day_passes_count = persistence_info["day_pass_count"]
        profile.night_passes_count = persistence_info["night_pass_count"]
        profile.is_continuous_24h = persistence_info["day_night_continuous"]
        profile.median_frp = stats["median"]
        profile.mean_frp = stats["mean"]
        profile.p90_frp = stats["p90"]
        profile.p95_frp = stats["p95"]
        profile.min_frp = stats["min"]
        profile.max_frp = stats["max"]
        profile.detection_frequency = det_freq
        profile.persistence_score = persistence_score
        profile.history_reliability = reliability
        profile.updated_at = now
        db.commit()

    daily_summaries = build_daily_summaries(profile.id, matching_window, db)
    multi_window = compute_multi_window_metrics(matching_365d, now)

    return {
        "profile_id": profile.id,
        "profile_type": "location",
        "spatial_reference": spatial_key,
        "window_days": window_days,
        "observation_count": len(matching_window),
        "active_days": active_days,
        "day_passes_count": persistence_info["day_pass_count"],
        "night_passes_count": persistence_info["night_pass_count"],
        "is_continuous_24h": persistence_info["day_night_continuous"],
        "median_frp": stats["median"],
        "mean_frp": stats["mean"],
        "p90_frp": stats["p90"],
        "p95_frp": stats["p95"],
        "min_frp": stats["min"],
        "max_frp": stats["max"],
        "normal_activity_range": [stats["min"], stats["p95"]],
        "detection_frequency": det_freq,
        "persistence_score": persistence_score,
        "persistence_classification": persistence_info["persistence_classification"],
        "history_reliability": reliability,
        "history_reliability_label": reliability_label,
        "windows": multi_window,
        "daily_summaries": daily_summaries,
        "answers": {
            "what_is_normal_here": f"Typical median FRP is {stats['median']} MW (P95 upper limit: {stats['p95']} MW).",
            "how_often_does_activity_recur": f"Detected on {active_days} distinct days over {window_days} days (frequency: {round(det_freq * 100, 1)}%).",
            "is_source_persistent": f"Persistence score is {persistence_score} ({persistence_info['persistence_classification']}).",
            "how_reliable_is_history": f"{reliability_label} ({len(matching_window)} observations)."
        }
    }

def get_or_create_facility_profile(
    facility_id: str,
    db: Session,
    window_days: int = 365,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Generates or retrieves a materialized facility history profile for an industrial facility.
    Includes:
    - Industrial asset metadata
    - Historical incident count
    - Abnormal event count
    - Normal activity range [min, p95]
    - Multi-window summaries (30d / 90d / 365d)
    - Daily summaries

    `window_days` defaults to the specification's 365-day Stage-4 window
    (spec line 150); see get_or_create_location_profile.
    """
    asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == facility_id).first()
    if not asset:
        return {
            "facility_id": facility_id,
            "error": "Facility not found",
            "observation_count": 0,
            "history_reliability_label": "NONE"
        }

    search_radius_km = (asset.buffer_radius_meters or 1500.0) / 1000.0
    now = datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    # 1. Check existing cached profile
    profile = (
        db.query(BehaviorProfile)
        .filter(
            BehaviorProfile.profile_type == "facility",
            BehaviorProfile.facility_id == facility_id
        )
        .first()
    )

    # Query historical incident count for this facility
    incident_count = (
        db.query(Incident)
        .filter(Incident.nearest_asset_id == facility_id)
        .count()
    )

    if not force_refresh and profile and profile.updated_at and (now - profile.updated_at).total_seconds() < 86400:
        daily_records = (
            db.query(BehaviorDailySummary)
            .filter(BehaviorDailySummary.profile_id == profile.id)
            .order_by(BehaviorDailySummary.date.asc())
            .all()
        )
        daily_summaries = [
            {
                "date": d.date,
                "observation_count": d.observation_count,
                "mean_frp": d.mean_frp,
                "median_frp": d.median_frp,
                "max_frp": d.max_frp
            }
            for d in daily_records
        ]
        return {
            "profile_id": profile.id,
            "facility_id": facility_id,
            "facility_name": asset.name,
            "facility_type": asset.facility_type,
            "operator": asset.operator,
            "industry": asset.industry,
            "profile_type": "facility",
            "spatial_reference": f"FACILITY_{facility_id}",
            "window_days": window_days,
            "observation_count": profile.observation_count,
            "active_days": profile.active_days,
            "median_frp": profile.median_frp,
            "mean_frp": profile.mean_frp,
            "p90_frp": profile.p90_frp,
            "p95_frp": profile.p95_frp,
            "min_frp": profile.min_frp,
            "max_frp": profile.max_frp,
            "normal_activity_range": [profile.min_frp, profile.p95_frp],
            "historical_incident_count": incident_count,
            "abnormal_event_count": len([d for d in daily_summaries if d["max_frp"] > (profile.p95_frp or 0.0)]),
            "detection_frequency": profile.detection_frequency,
            "persistence_score": profile.persistence_score,
            "history_reliability": profile.history_reliability,
            "history_reliability_label": classify_history_reliability(profile.observation_count or 0),
            "day_passes_count": profile.day_passes_count or 0,
            "night_passes_count": profile.night_passes_count or 0,
            "is_continuous_24h": bool(profile.is_continuous_24h),
            "daily_summaries": daily_summaries
        }

    # 2. Compute from observations
    max_window_start = now - timedelta(days=365)
    lat_delta = search_radius_km / 111.0
    lon_delta = search_radius_km / (111.0 * max(0.1, math.cos(math.radians(asset.latitude))))

    candidates = (
        db.query(Observation)
        .filter(
            Observation.latitude >= asset.latitude - lat_delta,
            Observation.latitude <= asset.latitude + lat_delta,
            Observation.longitude >= asset.longitude - lon_delta,
            Observation.longitude <= asset.longitude + lon_delta,
            Observation.acquired_at >= max_window_start
        )
        .all()
    )

    matching_365d = [
        o for o in candidates
        if haversine_distance_km(asset.latitude, asset.longitude, o.latitude, o.longitude) <= search_radius_km
    ]
    matching_window = [o for o in matching_365d if o.acquired_at and o.acquired_at >= window_start]

    frp_values = [float(o.frp_mw or 0.0) for o in matching_window]
    stats = compute_percentiles(frp_values)
    dates = {o.acquired_at.strftime("%Y-%m-%d") for o in matching_window if o.acquired_at}
    active_days = len(dates)
    det_freq = round(active_days / max(1, window_days), 4)

    persistence_info = calculate_persistence_score(matching_window, window_days)
    persistence_score = persistence_info["persistence_score"]

    reliability = calculate_history_reliability(len(matching_window), active_days, window_days)
    reliability_label = classify_history_reliability(len(matching_window))

    # 3. Materialize profile
    # Same F-061 columns as the location branch above: window_days,
    # day_passes_count, night_passes_count and is_continuous_24h are written
    # from the persistence evaluation instead of being left at their defaults.
    if not profile:
        profile = BehaviorProfile(
            profile_type="facility",
            facility_id=facility_id,
            spatial_reference=f"FACILITY_{facility_id}",
            window_start=window_start,
            window_end=now,
            window_days=window_days,
            observation_count=len(matching_window),
            active_days=active_days,
            day_passes_count=persistence_info["day_pass_count"],
            night_passes_count=persistence_info["night_pass_count"],
            is_continuous_24h=persistence_info["day_night_continuous"],
            median_frp=stats["median"],
            mean_frp=stats["mean"],
            p90_frp=stats["p90"],
            p95_frp=stats["p95"],
            min_frp=stats["min"],
            max_frp=stats["max"],
            detection_frequency=det_freq,
            persistence_score=persistence_score,
            history_reliability=reliability,
            updated_at=now
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    else:
        profile.window_start = window_start
        profile.window_end = now
        profile.window_days = window_days
        profile.observation_count = len(matching_window)
        profile.active_days = active_days
        profile.day_passes_count = persistence_info["day_pass_count"]
        profile.night_passes_count = persistence_info["night_pass_count"]
        profile.is_continuous_24h = persistence_info["day_night_continuous"]
        profile.median_frp = stats["median"]
        profile.mean_frp = stats["mean"]
        profile.p90_frp = stats["p90"]
        profile.p95_frp = stats["p95"]
        profile.min_frp = stats["min"]
        profile.max_frp = stats["max"]
        profile.detection_frequency = det_freq
        profile.persistence_score = persistence_score
        profile.history_reliability = reliability
        profile.updated_at = now
        db.commit()

    daily_summaries = build_daily_summaries(profile.id, matching_window, db)
    multi_window = compute_multi_window_metrics(matching_365d, now)
    abnormal_count = len([d for d in daily_summaries if d["max_frp"] > stats["p95"]])

    return {
        "profile_id": profile.id,
        "facility_id": facility_id,
        "facility_name": asset.name,
        "facility_type": asset.facility_type,
        "operator": asset.operator,
        "industry": asset.industry,
        "profile_type": "facility",
        "spatial_reference": f"FACILITY_{facility_id}",
        "window_days": window_days,
        "observation_count": len(matching_window),
        "active_days": active_days,
        "day_passes_count": persistence_info["day_pass_count"],
        "night_passes_count": persistence_info["night_pass_count"],
        "is_continuous_24h": persistence_info["day_night_continuous"],
        "median_frp": stats["median"],
        "mean_frp": stats["mean"],
        "p90_frp": stats["p90"],
        "p95_frp": stats["p95"],
        "min_frp": stats["min"],
        "max_frp": stats["max"],
        "normal_activity_range": [stats["min"], stats["p95"]],
        "historical_incident_count": incident_count,
        "abnormal_event_count": abnormal_count,
        "detection_frequency": det_freq,
        "persistence_score": persistence_score,
        "persistence_classification": persistence_info["persistence_classification"],
        "history_reliability": reliability,
        "history_reliability_label": reliability_label,
        "windows": multi_window,
        "daily_summaries": daily_summaries
    }

def refresh_behavior_features(db: Session) -> Dict[str, Any]:
    """
    Performs incremental feature refresh across all industrial assets
    and recent incident locations to keep materialized behavior caches current.
    """
    assets = db.query(IndustrialAsset).all()
    refreshed_facilities = 0
    for asset in assets:
        try:
            # 365 days: Stage 4 is a 365-day rolling window (spec line 150). The
            # 90-day value this call used to pass was defect F-018/C2.
            get_or_create_facility_profile(asset.id, db, window_days=365, force_refresh=True)
            refreshed_facilities += 1
        except Exception as e:
            logger.warning(f"Error refreshing facility profile for {asset.id}: {e}")

    # Also refresh recent active incidents
    recent_incidents = (
        db.query(Incident)
        .order_by(Incident.updated_at.desc())
        .limit(50)
        .all()
    )
    refreshed_locations = 0
    for inc in recent_incidents:
        try:
            get_or_create_location_profile(inc.latitude, inc.longitude, db, window_days=365, force_refresh=True)
            refreshed_locations += 1
        except Exception as e:
            logger.warning(f"Error refreshing location profile for incident {inc.id}: {e}")

    return {
        "status": "SUCCESS",
        "refreshed_facilities_count": refreshed_facilities,
        "refreshed_locations_count": refreshed_locations,
        "timestamp": datetime.utcnow().isoformat()
    }
