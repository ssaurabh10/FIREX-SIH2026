"""
FIRMS Observation Normalizer
Translates raw parsed CSV rows into standardized NormalizedObservation objects.
Handles:
1. VIIRS vs MODIS confidence scoring (categorical l/n/h vs 0-100% integer).
2. ISO Acquisition timestamp synthesis (YYYY-MM-DD + HHMM integer).
3. Deterministic external_id generation for deduplication.
"""
import hashlib
from datetime import datetime
from typing import Dict, Any
from app.ingestion.validator import RawFIRMSObservation, NormalizedObservation

def parse_acquisition_datetime(acq_date_str: str, acq_time_str: str) -> datetime:
    """
    Parses 'YYYY-MM-DD' and 'HHMM' (or 'HH:MM') into a Python datetime object.
    Example: 2026-09-02, 750 -> 2026-09-02 07:50:00
    """
    cleaned_time = str(acq_time_str).replace(":", "").strip()
    try:
        time_int = int(cleaned_time)
        hour = time_int // 100
        minute = time_int % 100
    except ValueError:
        hour, minute = 0, 0
    
    date_parts = [int(p) for p in acq_date_str.strip().split("-")]
    return datetime(date_parts[0], date_parts[1], date_parts[2], hour, minute)

def normalize_confidence(confidence_raw: str, instrument: str) -> float:
    """
    Normalizes confidence to a 0.0 - 1.0 continuous score:
    - VIIRS: 'l' (low) -> 0.35, 'n' (nominal) -> 0.70, 'h' (high) -> 0.95
    - MODIS: '0'-'100' -> numeric / 100.0
    """
    if not confidence_raw:
        return 0.5

    c_clean = str(confidence_raw).strip().lower()
    inst_clean = str(instrument).strip().lower()

    if "viirs" in inst_clean or c_clean in ["l", "n", "h", "low", "nominal", "high"]:
        if c_clean in ["l", "low"]:
            return 0.35
        elif c_clean in ["n", "nominal"]:
            return 0.70
        elif c_clean in ["h", "high"]:
            return 0.95
        return 0.50

    try:
        val = float(c_clean)
        return max(0.0, min(1.0, val / 100.0))
    except ValueError:
        return 0.50

def generate_observation_external_id(
    satellite: str,
    instrument: str,
    lat: float,
    lon: float,
    acquired_at: datetime
) -> str:
    """
    Generates a deterministic unique ID for an observation pass.
    Allows deduplication if the same observation is ingested across overlapping 24h/48h runs.
    """
    # Round coordinates to 4 decimal places (~11 meters) to guard floating point variance
    key = f"{satellite.upper()}_{instrument.upper()}_{lat:.4f}_{lon:.4f}_{acquired_at.strftime('%Y%m%d%H%M')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

def normalize_raw_firms(raw: RawFIRMSObservation, product: str = "VIIRS_NRT") -> NormalizedObservation:
    """
    Transforms RawFIRMSObservation into NormalizedObservation.
    """
    acq_dt = parse_acquisition_datetime(raw.acq_date, raw.acq_time)
    conf_score = normalize_confidence(raw.confidence, raw.instrument or "VIIRS")
    ext_id = generate_observation_external_id(
        satellite=raw.satellite,
        instrument=raw.instrument or "VIIRS",
        lat=raw.latitude,
        lon=raw.longitude,
        acquired_at=acq_dt
    )

    daynight_code = "NIGHT" if str(raw.daynight).strip().upper() == "N" else "DAY"

    return NormalizedObservation(
        source="NASA_FIRMS",
        external_id=ext_id,
        latitude=raw.latitude,
        longitude=raw.longitude,
        frp_mw=float(raw.frp or 0.0),
        confidence_raw=str(raw.confidence or "nominal"),
        confidence_score=conf_score,
        satellite=raw.satellite,
        sensor=raw.instrument or "VIIRS",
        product=product,
        daynight=daynight_code,
        acquired_at=acq_dt,
        raw_payload=raw.model_dump()
    )
