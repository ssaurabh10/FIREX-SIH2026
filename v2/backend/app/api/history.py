"""
FIREX v2 Historical Intelligence & Behavior REST API Router
Endpoints:
- GET /incidents/{id}/history
- GET /incidents/{id}/baseline
- GET /incidents/{id}/anomaly
- GET /incidents/{id}/trend
- GET /industries/{id}/history
- GET /industries/{id}/baseline
- GET /industries/{id}/trends
- POST /history/refresh
"""
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.storage.database import get_db
from app.storage.models import Incident, IndustrialAsset, Observation
from app.behavior.baseline import (
    get_or_create_location_baseline,
    get_or_create_facility_baseline
)
from app.behavior.anomaly import evaluate_historical_anomaly
from app.behavior.trends import compute_historical_trend
from app.behavior.profile import (
    get_or_create_location_profile,
    get_or_create_facility_profile,
    refresh_behavior_features
)
from app.gis.spatial import haversine_distance_km
from app.gis.boundaries import INDIAN_STATE_REGIONS, resolve_admin_boundary
from app.gis.assets import find_nearest_asset
import math
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/incidents/{incident_id}/history", response_model=Dict[str, Any])
def get_incident_history_profile(
    incident_id: str,
    window_days: int = Query(90, description="Historical window in days (e.g. 30, 90, 365)"),
    db: Session = Depends(get_db)
):
    """
    Retrieves the authoritative Location History Profile for the spatial area of this incident.
    Answers:
    - What is normal here?
    - How often does activity recur?
    - Is the source persistent?
    - How reliable is the historical evidence?
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    profile = get_or_create_location_profile(
        lat=incident.latitude,
        lon=incident.longitude,
        db=db,
        window_days=window_days
    )
    profile["incident_id"] = incident_id
    profile["incident_max_frp"] = incident.current_max_frp
    return profile

@router.get("/incidents/{incident_id}/baseline", response_model=Dict[str, Any])
def get_incident_baseline(
    incident_id: str,
    window_days: int = Query(90, description="Historical window in days"),
    db: Session = Depends(get_db)
):
    """
    Returns the statistical baseline (Median, P90, P95, Mean, Min, Max FRP)
    and history reliability for this incident's coordinates.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    baseline = get_or_create_location_baseline(
        lat=incident.latitude,
        lon=incident.longitude,
        db=db,
        window_days=window_days
    )
    baseline["incident_id"] = incident_id
    return baseline

@router.get("/incidents/{incident_id}/anomaly", response_model=Dict[str, Any])
def get_incident_anomaly_assessment(
    incident_id: str,
    db: Session = Depends(get_db)
):
    """
    Compares the current incident's FRP against the historical median and P95.
    Evaluates whether the event is:
    - Persistent / Normal
    - Persistent / Abnormal
    - New / Abnormal
    - New / Normal
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Retrieve location profile for persistence score
    loc_profile = get_or_create_location_profile(incident.latitude, incident.longitude, db)
    persistence_score = loc_profile.get("persistence_score", 0.0)

    anomaly = evaluate_historical_anomaly(
        current_frp=incident.current_max_frp,
        lat=incident.latitude,
        lon=incident.longitude,
        incident_id=incident_id,
        db=db,
        persistence_score=persistence_score
    )
    anomaly["facility_id"] = incident.nearest_asset_id
    anomaly["facility_name"] = incident.asset.name if incident.asset else None
    return anomaly

@router.get("/incidents/{incident_id}/trend", response_model=Dict[str, Any])
def get_incident_trend(
    incident_id: str,
    db: Session = Depends(get_db)
):
    """
    Calculates the historical emission trend (INCREASING, STABLE, DECREASING),
    emission velocity, and daily histogram for the incident location.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    search_radius_km = 3.0
    now = datetime.utcnow()
    window_start = now - timedelta(days=90)
    lat_delta = search_radius_km / 111.0
    lon_delta = search_radius_km / (111.0 * max(0.1, math.cos(math.radians(incident.latitude))))

    obs_records = (
        db.query(Observation)
        .filter(
            Observation.latitude >= incident.latitude - lat_delta,
            Observation.latitude <= incident.latitude + lat_delta,
            Observation.longitude >= incident.longitude - lon_delta,
            Observation.longitude <= incident.longitude + lon_delta,
            Observation.acquired_at >= window_start
        )
        .all()
    )

    matching_obs = [
        o for o in obs_records
        if haversine_distance_km(incident.latitude, incident.longitude, o.latitude, o.longitude) <= search_radius_km
    ]

    trend = compute_historical_trend(matching_obs)
    trend["incident_id"] = incident_id
    return trend

from app.core.cache import cache

@router.get("/industries/{facility_id}/history", response_model=Dict[str, Any])
def get_facility_history(
    facility_id: str,
    window_days: int = Query(90, description="Historical window in days"),
    db: Session = Depends(get_db)
):
    """
    Retrieves the full Facility History Profile for an industrial site.
    Includes 30d/90d/365d breakdowns, daily summaries, and abnormal event count.
    """
    cache_key = f"facility:history:{facility_id}:{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    profile = get_or_create_facility_profile(facility_id, db, window_days=window_days)
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
    cache.set(cache_key, profile, ttl=120)
    return profile

@router.get("/industries/{facility_id}/baseline", response_model=Dict[str, Any])
def get_facility_baseline(
    facility_id: str,
    window_days: int = Query(90, description="Historical window in days"),
    db: Session = Depends(get_db)
):
    """
    Returns the statistical baseline (Median, P90, P95, Mean, Min, Max FRP)
    for a specific industrial facility.
    """
    cache_key = f"facility:baseline:{facility_id}:{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    baseline = get_or_create_facility_baseline(facility_id, db, window_days=window_days)
    if "error" in baseline:
        raise HTTPException(status_code=404, detail=baseline["error"])
    cache.set(cache_key, baseline, ttl=120)
    return baseline

@router.get("/industries/{facility_id}/trends", response_model=Dict[str, Any])
def get_facility_trends(
    facility_id: str,
    db: Session = Depends(get_db)
):
    """
    Calculates emission trajectory, velocity, and daily histogram for an industrial facility.
    """
    asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == facility_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Facility not found")

    search_radius_km = (asset.buffer_radius_meters or 1500.0) / 1000.0
    now = datetime.utcnow()
    window_start = now - timedelta(days=90)
    lat_delta = search_radius_km / 111.0
    lon_delta = search_radius_km / (111.0 * max(0.1, math.cos(math.radians(asset.latitude))))

    obs_records = (
        db.query(Observation)
        .filter(
            Observation.latitude >= asset.latitude - lat_delta,
            Observation.latitude <= asset.latitude + lat_delta,
            Observation.longitude >= asset.longitude - lon_delta,
            Observation.longitude <= asset.longitude + lon_delta,
            Observation.acquired_at >= window_start
        )
        .all()
    )

    matching_obs = [
        o for o in obs_records
        if haversine_distance_km(asset.latitude, asset.longitude, o.latitude, o.longitude) <= search_radius_km
    ]

    trend = compute_historical_trend(matching_obs)
    trend["facility_id"] = facility_id
    trend["facility_name"] = asset.name
    return trend

@router.post("/history/refresh", response_model=Dict[str, Any])
def trigger_history_refresh(
    db: Session = Depends(get_db)
):
    """
    Executes an incremental feature refresh across all industrial facilities
    and recent incidents to update behavior profiles and baseline caches.
    """
    return refresh_behavior_features(db)

@router.get("/history/search", response_model=Dict[str, Any])
def search_historical_observations(
    query: Optional[str] = Query(None, description="Search state, district, or facility"),
    state: Optional[str] = Query(None, description="Filter by Indian State"),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    min_frp: float = Query(2.0, ge=0.0, description="Minimum FRP in MW"),
    max_frp: Optional[float] = Query(None, description="Maximum FRP in MW"),
    satellite: Optional[str] = Query(None, description="Satellite or sensor filter (VIIRS/MODIS)"),
    limit: int = Query(50, ge=1, le=200, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db)
):
    """
    Interactive Search across 2.89M historical satellite observations.
    Filters by Date Range, Sovereign State/District, and Min FRP.
    Enriches results with administrative resolution and nearest industrial facility.
    """
    filters = [Observation.frp_mw >= min_frp]

    if max_frp is not None:
        filters.append(Observation.frp_mw <= max_frp)

    # 1. Date range filters
    if start_date:
        try:
            s_dt = datetime.fromisoformat(start_date)
            filters.append(Observation.acquired_at >= s_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format, use YYYY-MM-DD")

    if end_date:
        try:
            e_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
            filters.append(Observation.acquired_at <= e_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format, use YYYY-MM-DD")

    # 2. State bounding box resolution
    target_state = state or query
    state_bbox = None
    if target_state:
        target_clean = target_state.strip().lower()
        for s_name, bbox in INDIAN_STATE_REGIONS.items():
            if target_clean in s_name.lower():
                state_bbox = bbox
                break

    if state_bbox:
        min_lat, max_lat, min_lon, max_lon, _ = state_bbox
        filters.append(Observation.latitude >= min_lat)
        filters.append(Observation.latitude <= max_lat)
        filters.append(Observation.longitude >= min_lon)
        filters.append(Observation.longitude <= max_lon)

    # 3. Satellite filter
    if satellite and satellite.upper() != "ALL":
        sat_clean = f"%{satellite.strip()}%"
        filters.append(
            (Observation.satellite.ilike(sat_clean)) | (Observation.sensor.ilike(sat_clean))
        )

    # Query matching records
    q = db.query(Observation).filter(*filters).order_by(Observation.acquired_at.desc())
    total_matches = q.count()
    rows = q.offset(offset).limit(limit).all()

    # Calculate summary metrics
    max_val = 0.0
    sum_val = 0.0
    results = []

    for r in rows:
        f_val = float(r.frp_mw or 0.0)
        max_val = max(max_val, f_val)
        sum_val += f_val

        # Sovereign administrative resolution
        admin = resolve_admin_boundary(r.latitude, r.longitude)
        nearest = find_nearest_asset(r.latitude, r.longitude, db)

        results.append({
            "id": r.id,
            "latitude": round(r.latitude, 4),
            "longitude": round(r.longitude, 4),
            "frp_mw": round(f_val, 2),
            "acquired_at": r.acquired_at.isoformat() if r.acquired_at else None,
            "satellite": r.satellite or "VIIRS",
            "sensor": r.sensor or "VIIRS",
            "confidence": r.confidence_raw or "nominal",
            "daynight": r.daynight or "N",
            "state": admin.get("state") or "India",
            "district": admin.get("district") or "Unknown",
            "nearest_facility": nearest.get("facility_name"),
            "distance_km": nearest.get("distance_km")
        })

    mean_val = round(sum_val / len(rows), 2) if rows else 0.0

    return {
        "total_matches": total_matches,
        "returned": len(results),
        "limit": limit,
        "offset": offset,
        "summary": {
            "max_frp": round(max_val, 2),
            "mean_frp": mean_val,
            "min_frp": min_frp,
            "state_filter": target_state if state_bbox else None
        },
        "results": results
    }

