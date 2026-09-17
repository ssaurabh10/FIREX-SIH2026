"""
Observations REST API Router
Endpoints:
- GET /observations: List/filter normalized observations with spatial bounding box and FRP limits
- GET /observations/{id}: Retrieve single observation by ID
- POST /observations/ingest: Trigger live or fixture FIRMS ingestion
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
import math

from app.storage.database import get_db
from app.storage.models import Observation
from app.ingestion.firms import FIRMSClient
from app.core.config import settings
from app.gis.spatial import haversine_distance_km

router = APIRouter(prefix="/observations", tags=["Observations"])

class ObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    external_id: Optional[str] = None
    latitude: float
    longitude: float
    frp_mw: float
    confidence_raw: Optional[str] = None
    confidence_score: Optional[float] = None
    satellite: Optional[str] = None
    sensor: Optional[str] = None
    product: Optional[str] = None
    daynight: Optional[str] = None
    acquired_at: datetime

class IngestionRequest(BaseModel):
    product: Optional[str] = "VIIRS_NOAA20_NRT"
    days: Optional[int] = 1
    file_path: Optional[str] = None

@router.get("", response_model=List[ObservationResponse])
def get_observations(
    limit: int = Query(default=100, le=2000),
    offset: int = Query(default=0, ge=0),
    min_frp: Optional[float] = Query(default=None),
    satellite: Optional[str] = Query(default=None),
    daynight: Optional[str] = Query(default=None),
    # Bounding Box: min_lat, max_lat, min_lon, max_lon
    min_lat: Optional[float] = Query(default=None),
    max_lat: Optional[float] = Query(default=None),
    min_lon: Optional[float] = Query(default=None),
    max_lon: Optional[float] = Query(default=None),
    # Radial spatial query: center_lat, center_lon, radius_km
    center_lat: Optional[float] = Query(default=None),
    center_lon: Optional[float] = Query(default=None),
    radius_km: Optional[float] = Query(default=None),
    db: Session = Depends(get_db)
):
    """
    Query normalized observations. Supports bounding box filtering and radial distance queries.
    """
    query = db.query(Observation)

    if min_frp is not None:
        query = query.filter(Observation.frp_mw >= min_frp)
    if satellite:
        query = query.filter(Observation.satellite.ilike(f"%{satellite}%"))
    if daynight:
        query = query.filter(Observation.daynight == daynight.upper())

    # Spatial Bounding Box Filter
    if min_lat is not None:
        query = query.filter(Observation.latitude >= min_lat)
    if max_lat is not None:
        query = query.filter(Observation.latitude <= max_lat)
    if min_lon is not None:
        query = query.filter(Observation.longitude >= min_lon)
    if max_lon is not None:
        query = query.filter(Observation.longitude <= max_lon)

    # Radial Proximity Filter (degree-space bounding box prefilter + exact
    # distance post-filter)
    if center_lat is not None and center_lon is not None and radius_km is not None:
        # Coarse prefilter only: 1 deg latitude ~ 111 km, longitude scaled by
        # cos(lat). It needs to be a superset of the true 1500 m-scale disc, and
        # the exact test below is what actually decides membership.
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * max(0.1, math.cos(math.radians(center_lat))))

        query = query.filter(
            Observation.latitude >= center_lat - lat_delta,
            Observation.latitude <= center_lat + lat_delta,
            Observation.longitude >= center_lon - lon_delta,
            Observation.longitude <= center_lon + lon_delta
        )

    observations = query.order_by(Observation.acquired_at.desc()).offset(offset).limit(limit).all()

    # Exact great-circle filter if radius_km requested.
    #
    # This used to carry a verbatim inline copy of the haversine
    # (`2 * R * atan2(sqrt(a), sqrt(1 - a))`, R = 6371.0). Besides duplicating
    # the geodesy, that copy omitted the Section 4.1 `min(1.0, sqrt(a))` clamp,
    # so for near-antipodal input `a` can exceed 1.0 by an ulp and
    # `math.sqrt(1 - a)` raises ValueError('expected a nonnegative input'),
    # turning a valid radius query into a 500. There is one definition of the
    # haversine in this codebase; call it.
    if center_lat is not None and center_lon is not None and radius_km is not None:
        observations = [
            obs for obs in observations
            if haversine_distance_km(center_lat, center_lon, obs.latitude, obs.longitude) <= radius_km
        ]

    return observations

@router.get("/{observation_id}", response_model=ObservationResponse)
def get_observation_by_id(observation_id: str, db: Session = Depends(get_db)):
    """
    Retrieve single observation by internal ID or external_id.
    """
    obs = (
        db.query(Observation)
        .filter((Observation.id == observation_id) | (Observation.external_id == observation_id))
        .first()
    )
    if not obs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return obs

@router.post("/ingest")
def trigger_ingestion(payload: IngestionRequest, db: Session = Depends(get_db)):
    """
    Triggers FIRMS ingestion. If file_path is provided, loads from local CSV fixture.
    Otherwise queries NASA FIRMS live API.
    """
    client = FIRMSClient()
    if payload.file_path:
        stats = client.ingest_from_file(db, payload.file_path, product=payload.product or settings.FIRMS_DEFAULT_PRODUCTS[0])
        return {
            "status": "success",
            "mode": "fixture_file",
            "file": payload.file_path,
            "stats": stats
        }
    
    csv_text = client.fetch_live_csv(product=payload.product or "VIIRS_NOAA20_NRT", days=payload.days or 1)
    if not csv_text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch data from NASA FIRMS API"
        )

    records = client.parse_csv(csv_text, product=payload.product or "VIIRS_NOAA20_NRT")
    stats = client.save_to_db(db, records)
    return {
        "status": "success",
        "mode": "live_api",
        "product": payload.product,
        "stats": stats
    }
