"""
Incidents REST API Router
Endpoints specified in Section 32 of Blueprint:
- GET  /incidents: List/filter incidents (by status, severity, facility, state)
- GET  /incidents/{id}: Retrieve detailed incident record with linked observations and events
- POST /incidents/cluster-sync: Run clustering and association over unassigned observations
- POST /incidents/{id}/state: Transition incident state (ACTIVE, SUBSIDING, RESOLVED)
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from app.storage.database import get_db
from app.storage.models import Incident, Observation, IncidentObservation, IncidentEvent
from app.incidents.clustering import cluster_observations
from app.incidents.association import sync_clusters_to_incidents
from app.incidents.state import transition_incident_state

router = APIRouter(prefix="/incidents", tags=["Incidents"])

class LinkedObservationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    latitude: float
    longitude: float
    frp_mw: float
    confidence_score: Optional[float] = None
    acquired_at: datetime
    satellite: Optional[str] = None
    sensor: Optional[str] = None

class IncidentEventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    payload: Optional[Dict[str, Any]] = None
    occurred_at: datetime

class IncidentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_code: str
    status: str
    latitude: float
    longitude: float
    footprint_radius_meters: float
    first_detected_at: datetime
    last_detected_at: datetime
    observation_count: int
    current_max_frp: float
    current_mean_frp: float
    severity_level: str
    severity_score: float
    investigation_priority: float
    classification: str
    is_inside_facility: bool
    distance_to_asset_km: Optional[float] = None
    nearest_asset_id: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class IncidentFullResponse(IncidentDetailResponse):
    observations: List[LinkedObservationSummary] = []
    events: List[IncidentEventSummary] = []

class StateTransitionRequest(BaseModel):
    new_state: str
    reason: Optional[str] = "Manual operator update"

@router.get("", response_model=List[IncidentDetailResponse])
def get_incidents(
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
    severity_level: Optional[str] = Query(default=None),
    is_inside_facility: Optional[bool] = Query(default=None),
    state: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """
    List incidents with operational filtering.
    """
    query = db.query(Incident)

    if status:
        query = query.filter(Incident.status == status.upper())
    if severity_level:
        query = query.filter(Incident.severity_level == severity_level.upper())
    if is_inside_facility is not None:
        query = query.filter(Incident.is_inside_facility == is_inside_facility)
    if state:
        query = query.filter(Incident.state.ilike(f"%{state}%"))

    return query.order_by(Incident.last_detected_at.desc()).offset(offset).limit(limit).all()

@router.get("/{incident_id}", response_model=IncidentFullResponse)
def get_incident_by_id(incident_id: str, db: Session = Depends(get_db)):
    """
    Retrieve single incident with its complete chain of evidence (linked observations & timeline events).
    """
    incident = (
        db.query(Incident)
        .filter((Incident.id == incident_id) | (Incident.incident_code == incident_id))
        .first()
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    # Fetch linked observations
    linked_obs = (
        db.query(Observation)
        .join(IncidentObservation, IncidentObservation.observation_id == Observation.id)
        .filter(IncidentObservation.incident_id == incident.id)
        .order_by(Observation.acquired_at.desc())
        .all()
    )

    # Fetch audit events
    events = (
        db.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.occurred_at.asc())
        .all()
    )

    resp_dict = IncidentDetailResponse.model_validate(incident).model_dump()
    resp_dict["observations"] = [LinkedObservationSummary.model_validate(o) for o in linked_obs]
    resp_dict["events"] = [IncidentEventSummary.model_validate(e) for e in events]
    return resp_dict

@router.post("/cluster-sync")
def trigger_cluster_sync(
    spatial_eps_meters: float = 2000.0,
    time_window_hours: float = 24.0,
    db: Session = Depends(get_db)
):
    """
    Clusters stored observations and associates them into persistent Incident objects.
    """
    # Grab all stored observations
    observations = db.query(Observation).all()
    if not observations:
        return {"status": "no_data", "message": "No observations available to cluster"}

    clusters = cluster_observations(
        observations,
        spatial_eps_meters=spatial_eps_meters,
        time_window_hours=time_window_hours
    )
    incidents = sync_clusters_to_incidents(db, clusters)

    return {
        "status": "success",
        "total_observations": len(observations),
        "candidate_clusters": len(clusters),
        "incidents_affected": len(incidents),
        "incidents": [
            {
                "id": inc.id,
                "incident_code": inc.incident_code,
                "status": inc.status,
                "observation_count": inc.observation_count,
                "max_frp": inc.current_max_frp,
                "mean_frp": inc.current_mean_frp,
                "is_inside_facility": inc.is_inside_facility
            }
            for inc in incidents
        ]
    }

@router.post("/{incident_id}/state")
def update_incident_state(
    incident_id: str,
    payload: StateTransitionRequest,
    db: Session = Depends(get_db)
):
    """
    Transition incident lifecycle state (ACTIVE, SUBSIDING, RESOLVED).
    """
    incident = (
        db.query(Incident)
        .filter((Incident.id == incident_id) | (Incident.incident_code == incident_id))
        .first()
    )
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    updated = transition_incident_state(
        db,
        incident=incident,
        new_state=payload.new_state,
        reason=payload.reason or "Manual state update"
    )
    return {
        "status": "success",
        "incident_code": updated.incident_code,
        "new_state": updated.status
    }
