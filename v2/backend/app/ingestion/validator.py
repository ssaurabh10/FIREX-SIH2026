"""
FIRMS Observation Validation & Normalization Models
"""
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, field_validator

class RawFIRMSObservation(BaseModel):
    """
    Validates a raw row incoming from NASA FIRMS CSV.
    Accommodates both VIIRS and MODIS CSV column structures.
    """
    latitude: float
    longitude: float
    acq_date: str
    acq_time: str
    satellite: str
    instrument: Optional[str] = "VIIRS"
    confidence: Optional[str] = "nominal"
    frp: Optional[float] = 0.0
    daynight: Optional[str] = "D"
    brightness: Optional[float] = None
    bright_ti4: Optional[float] = None
    bright_ti5: Optional[float] = None
    scan: Optional[float] = None
    track: Optional[float] = None
    version: Optional[str] = None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError(f"Latitude must be between -90 and 90, got {v}")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError(f"Longitude must be between -180 and 180, got {v}")
        return v


class NormalizedObservation(BaseModel):
    """
    Normalized representation of an active thermal detection,
    ready for database storage and geospatial index queries.
    """
    source: str = "NASA_FIRMS"
    external_id: str
    latitude: float
    longitude: float
    frp_mw: float
    confidence_raw: str
    confidence_score: float  # Normalized 0.0 to 1.0
    satellite: str
    sensor: str
    product: str
    daynight: str
    acquired_at: datetime
    raw_payload: Optional[Dict[str, Any]] = None

    model_config = {
        "from_attributes": True
    }
