"""
FIREX v2 Storage Models (SQLAlchemy Declarative Base)
Full Schema based on Section 10 of Blueprint:
- Observation
- Incident
- IncidentObservation
- IndustrialAsset
- ImageryRecord
- AIInvestigation
- HistoricalBaseline
- SeverityAssessment
- AlertRecord
- IncidentEvent
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship
from app.storage.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Observation(Base):
    __tablename__ = "observations"

    id = Column(String, primary_key=True, default=generate_uuid)
    source = Column(String, default="NASA_FIRMS", index=True)
    external_id = Column(String, nullable=True, index=True)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    frp_mw = Column(Float, nullable=False, default=0.0)
    confidence_raw = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    satellite = Column(String, nullable=True, index=True)
    sensor = Column(String, nullable=True)
    product = Column(String, nullable=True)
    daynight = Column(String, nullable=True)
    acquired_at = Column(DateTime, nullable=False, index=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    raw_payload = Column(JSON, nullable=True)

    incident_links = relationship("IncidentObservation", back_populates="observation")

    __table_args__ = (
        Index("ix_obs_lat_lon", "latitude", "longitude"),
        Index("ix_obs_acquired_frp", "acquired_at", "frp_mw"),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_code = Column(String, unique=True, index=True)
    status = Column(String, default="NEW", index=True)  # NEW, INVESTIGATING, ACTIVE, PERSISTENT, ESCALATED, SUBSIDING, RESOLVED, REOPENED -- see incidents/state.py:VALID_STATES
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    footprint_radius_meters = Column(Float, default=500.0)
    footprint_geojson = Column(JSON, nullable=True)
    first_detected_at = Column(DateTime, nullable=False)
    last_detected_at = Column(DateTime, nullable=False)
    observation_count = Column(Integer, default=1)
    current_max_frp = Column(Float, default=0.0)
    current_mean_frp = Column(Float, default=0.0)
    
    # Priority & Severity
    investigation_priority = Column(Float, default=0.0)
    severity_score = Column(Float, default=0.0)
    severity_level = Column(String, default="LOW")  # LOW, MEDIUM, HIGH, CRITICAL
    severity_confidence = Column(Float, default=0.0)
    
    # Classification
    classification = Column(String, default="uncertain")
    classification_confidence = Column(Float, default=0.0)

    # Aggregate NASA FIRMS confidence of the incident's member observations,
    # on the 0-100 scale produced by ingestion.normalizer.normalize_confidence.
    # This is a property of the *detections*, not of any AI or severity verdict,
    # and it is what Section 4.5 / 4.6 mean by C_firms. It used to be absent, so
    # the selection engine hard-coded 80.0 and the severity engine fed the
    # incident's own previous severity_confidence back into itself.
    firms_confidence = Column(Float, nullable=True)

    # GIS and Asset Association
    nearest_asset_id = Column(String, ForeignKey("industrial_assets.id"), nullable=True)
    distance_to_asset_km = Column(Float, nullable=True)
    is_inside_facility = Column(Boolean, default=False)
    state = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    observations = relationship("IncidentObservation", back_populates="incident")
    imagery = relationship("ImageryRecord", back_populates="incident")
    investigations = relationship("AIInvestigation", back_populates="incident")
    severity_assessments = relationship("SeverityAssessment", back_populates="incident")
    alerts = relationship("AlertRecord", back_populates="incident")
    events = relationship("IncidentEvent", back_populates="incident")
    asset = relationship("IndustrialAsset")

    __table_args__ = (
        Index("ix_incidents_lat_lon", "latitude", "longitude"),
        Index("ix_incidents_status_priority", "status", "investigation_priority"),
        Index("ix_incidents_status_severity", "status", "severity_score"),
        Index("ix_incidents_last_detected", "last_detected_at"),
    )


class IncidentObservation(Base):
    __tablename__ = "incident_observations"

    incident_id = Column(String, ForeignKey("incidents.id"), primary_key=True)
    observation_id = Column(String, ForeignKey("observations.id"), primary_key=True)
    is_primary = Column(Boolean, default=False)
    association_method = Column(String, default="SPATIAL_TEMPORAL_DBSCAN")  # SPATIAL_TEMPORAL_DBSCAN, FOOTPRINT_OVERLAP, FACILITY_CONTAINMENT
    association_score = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="observations")
    observation = relationship("Observation", back_populates="incident_links")


class IndustrialAsset(Base):
    __tablename__ = "industrial_assets"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    facility_type = Column(String, nullable=False, default="petrochemical", index=True)  # refinery, petrochemical, steel, mining, thermal_power
    operator = Column(String, nullable=True)
    industry = Column(String, nullable=False, default="Energy & Chemicals", index=True)
    category = Column(String, nullable=False, index=True)  # gas_flare, industrial_fire, mining_or_other_thermal_source
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    state = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True)
    display_address = Column(String, nullable=True)
    hazard_category = Column(String, default="MAJOR_ACCIDENT_HAZARD")
    buffer_radius_meters = Column(Float, default=1500.0)
    polygon_geojson = Column(JSON, nullable=True)  # Polygon geometry for point-in-polygon containment
    source = Column(String, default="NATIONAL_INDUSTRIAL_REGISTRY")
    created_at = Column(DateTime, default=datetime.utcnow)



class ImageryRecord(Base):
    __tablename__ = "imagery_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    provider = Column(String, default="Google Satellite")
    zoom_level = Column(Integer, default=16)
    image_raw_url = Column(String, nullable=True)
    image_annotated_url = Column(String, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="imagery")


class AIInvestigation(Base):
    __tablename__ = "ai_investigations"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    model_name = Column(String, nullable=False)
    classification = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    uncertainty = Column(String, default="medium")
    reasoning = Column(Text, nullable=True)
    evidence_points = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="investigations")


class SeverityAssessment(Base):
    __tablename__ = "severity_assessments"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    score = Column(Float, nullable=False)
    level = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    factors = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="severity_assessments")


class BehaviorProfile(Base):
    __tablename__ = "behavior_profiles"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_type = Column(String, nullable=False, index=True)  # facility, location
    facility_id = Column(String, ForeignKey("industrial_assets.id"), nullable=True, index=True)
    spatial_reference = Column(String, nullable=False, index=True)  # rounded coordinate grid or geohash
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    observation_count = Column(Integer, default=0)
    active_days = Column(Integer, default=0)
    median_frp = Column(Float, default=0.0)
    mean_frp = Column(Float, default=0.0)
    p90_frp = Column(Float, default=0.0)
    p95_frp = Column(Float, default=0.0)
    min_frp = Column(Float, default=0.0)
    max_frp = Column(Float, default=0.0)
    detection_frequency = Column(Float, default=0.0)  # active_days / total_days
    persistence_score = Column(Float, default=0.0)    # 0.0 to 1.0 continuous persistence
    history_reliability = Column(Float, default=0.0)  # confidence in baseline
    # Columns the live database carries but this model used to omit, so a
    # rebuild from the ORM could not reproduce the running schema. See
    # Section 10 of the specification.
    window_days = Column(Integer, default=365)        # rolling window the profile was built over
    day_passes_count = Column(Integer, default=0)     # daytime overpass count in window
    night_passes_count = Column(Integer, default=0)   # night-time overpass count in window
    is_continuous_24h = Column(Boolean, default=False)  # both day and night passes present
    updated_at = Column(DateTime, default=datetime.utcnow)


class BehaviorDailySummary(Base):
    __tablename__ = "behavior_daily_summaries"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_id = Column(String, ForeignKey("behavior_profiles.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    observation_count = Column(Integer, default=0)
    max_frp = Column(Float, default=0.0)
    mean_frp = Column(Float, default=0.0)
    median_frp = Column(Float, default=0.0)
    active = Column(Boolean, default=True)


class HistoricalBaseline(Base):
    __tablename__ = "historical_baselines"

    id = Column(String, primary_key=True, default=generate_uuid)
    spatial_key = Column(String, index=True)  # geohash or rounded grid cell
    profile_id = Column(String, ForeignKey("behavior_profiles.id"), nullable=True)
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    detection_count_30d = Column(Integer, default=0)
    detection_count_90d = Column(Integer, default=0)
    detection_count_365d = Column(Integer, default=0)
    median_frp = Column(Float, default=0.0)
    p90_frp = Column(Float, default=0.0)
    p95_frp = Column(Float, default=0.0)
    mean_frp = Column(Float, default=0.0)
    history_reliability = Column(Float, default=0.0)
    is_persistent = Column(Boolean, default=False)
    last_updated_at = Column(DateTime, default=datetime.utcnow)


class ThermalClimatology(Base):
    __tablename__ = "thermal_climatology"

    spatial_key = Column(String, primary_key=True, index=True)  # e.g. GRID_21.16_72.68 (0.02 deg ~2.2km)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    observation_count = Column(Integer, default=0)
    active_days = Column(Integer, default=0)
    median_frp = Column(Float, default=0.0)
    p90_frp = Column(Float, default=0.0)
    p95_frp = Column(Float, default=0.0)
    max_frp = Column(Float, default=0.0)
    night_ratio = Column(Float, default=0.0)  # 0.0 - 1.0 night-time detection fraction
    is_routine_flare = Column(Boolean, default=False, index=True)
    site_classification_hint = Column(String, default="EPISODIC_VEGETATION")
    last_updated_at = Column(DateTime, default=datetime.utcnow)


class HistoricalAnomaly(Base):
    __tablename__ = "historical_anomalies"

    id = Column(String, primary_key=True, default=generate_uuid)
    profile_id = Column(String, ForeignKey("behavior_profiles.id"), nullable=True)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=True, index=True)
    current_frp = Column(Float, nullable=False)
    historical_median = Column(Float, default=0.0)
    historical_p95 = Column(Float, default=0.0)
    frp_ratio = Column(Float, default=1.0)
    anomaly_score = Column(Float, default=0.0)  # 0-100, matching the Section 4.4 ratio table
    above_p95 = Column(Boolean, default=False)
    # Persisted counterpart of the status string returned by
    # behavior.anomaly.evaluate_historical_anomaly (NORMAL_OPERATIONAL_RANGE,
    # ELEVATED_EMISSION, ABNORMAL_HISTORICAL_SPIKE, INSUFFICIENT_HISTORY).
    anomaly_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    severity_level = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="NEW")  # NEW, ACKNOWLEDGED, RESOLVED, DISMISSED
    # An alert superseded by an escalation is closed, not left open alongside
    # its replacement. See app/alerts/engine.py.
    superseded_by = Column(String, ForeignKey("alert_records.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="alerts")


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    event_type = Column(String, nullable=False, index=True)  # incident.created, investigation.completed, etc.
    payload = Column(JSON, nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="events")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    status = Column(String, default="RUNNING", index=True)  # RUNNING, COMPLETED, FAILED
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    observations_count = Column(Integer, default=0)
    new_observations_count = Column(Integer, default=0)
    incidents_updated_count = Column(Integer, default=0)
    new_incidents_count = Column(Integer, default=0)
    investigations_count = Column(Integer, default=0)
    alerts_count = Column(Integer, default=0)
    summary_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
