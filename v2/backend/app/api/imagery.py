"""
FIREX v2 Imagery API Router
Endpoints for satellite visual context, tactical reticles, cache serving, and investigation packages.
"""
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.storage.database import get_db
from app.imagery.service import get_or_create_incident_imagery, CACHE_DIR
from app.imagery.package import build_investigation_package

router = APIRouter(prefix="/imagery", tags=["Visual Context & Imagery"])

@router.get("/incident/{incident_id}", summary="Get or render optical satellite crop with tactical reticle")
def get_incident_imagery_endpoint(
    incident_id: str,
    radius: Optional[float] = Query(None, description="Custom ground radius in meters (250 - 5000)"),
    zoom: Optional[int] = Query(None, description="Custom zoom level (12 - 19)"),
    force_refresh: bool = Query(False, description="Bypass disk cache and re-fetch tiles"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    res = get_or_create_incident_imagery(
        incident_id=incident_id,
        db=db,
        custom_radius_meters=radius,
        zoom_level=zoom,
        force_refresh=force_refresh
    )
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@router.get("/incident/{incident_id}/package", summary="Build complete deterministic Investigation Package")
def get_incident_package_endpoint(
    incident_id: str,
    radius: Optional[float] = Query(None, description="Custom ground radius in meters"),
    zoom: Optional[int] = Query(None, description="Custom zoom level"),
    force_refresh: bool = Query(False, description="Re-generate imagery"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    res = build_investigation_package(
        incident_id=incident_id,
        db=db,
        custom_radius_meters=radius,
        zoom_level=zoom,
        force_refresh_imagery=force_refresh
    )
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res

@router.get("/cache/{incident_id}/{filename}", summary="Serve cached satellite images")
def serve_cached_image(incident_id: str, filename: str):
    file_path = os.path.abspath(os.path.join(CACHE_DIR, incident_id, filename))
    # Security path check
    if not file_path.startswith(CACHE_DIR) or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")

    media_type = "image/jpeg"
    if filename.endswith(".json"):
        media_type = "application/json"
    return FileResponse(file_path, media_type=media_type)
