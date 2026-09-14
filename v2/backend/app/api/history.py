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
    profile = get_or_create_facility_profile(facility_id, db, window_days=window_days)
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
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
    baseline = get_or_create_facility_baseline(facility_id, db, window_days=window_days)
    if "error" in baseline:
        raise HTTPException(status_code=404, detail=baseline["error"])
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
