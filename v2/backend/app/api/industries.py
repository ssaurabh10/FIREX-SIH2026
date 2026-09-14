"""
Industry Intelligence & Facility Search REST API Router
Implements Section 32 of Blueprint:
- GET /industries: List/filter industrial infrastructure assets
- GET /industries/search?q=: Full-text search across facility names, operators, districts, and states
- GET /industries/{id}: Retrieve detailed asset record with GeoJSON perimeter
- POST /industries/seed: Force initial seeding of authoritative national facilities
- GET /gis/enrich: On-demand GIS enrichment query for arbitrary coordinates
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, ConfigDict
from app.storage.database import get_db
from app.storage.models import IndustrialAsset
from app.gis.assets import seed_industrial_assets
from app.gis.enrichment import enrich_coordinate_gis_context

router = APIRouter(tags=["Industry Intelligence"])

class IndustrialAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    facility_type: str
    operator: Optional[str] = None
    industry: str
    category: str
    latitude: float
    longitude: float
    state: Optional[str] = None
    district: Optional[str] = None
    display_address: Optional[str] = None
    hazard_category: Optional[str] = None
    buffer_radius_meters: float
    polygon_geojson: Optional[Dict[str, Any]] = None

@router.get("/industries", response_model=List[IndustrialAssetResponse])
def list_industries(
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    facility_type: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """
    List industrial facilities with optional filtering by type, state, or thermal category.
    """
    # Ensure seed data exists
    if db.query(IndustrialAsset).count() == 0:
        seed_industrial_assets(db)

    query = db.query(IndustrialAsset)
    if facility_type:
        query = query.filter(IndustrialAsset.facility_type.ilike(f"%{facility_type}%"))
    if state:
        query = query.filter(IndustrialAsset.state.ilike(f"%{state}%"))
    if category:
        query = query.filter(IndustrialAsset.category == category)

    return query.order_by(IndustrialAsset.name.asc()).offset(offset).limit(limit).all()

@router.get("/industries/search", response_model=List[IndustrialAssetResponse])
def search_industries(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db)
):
    """
    Search industrial facilities across name, operator, state, district, or industry.
    """
    if db.query(IndustrialAsset).count() == 0:
        seed_industrial_assets(db)

    term = f"%{q.strip()}%"
    results = (
        db.query(IndustrialAsset)
        .filter(
            or_(
                IndustrialAsset.name.ilike(term),
                IndustrialAsset.operator.ilike(term),
                IndustrialAsset.state.ilike(term),
                IndustrialAsset.district.ilike(term),
                IndustrialAsset.industry.ilike(term),
                IndustrialAsset.facility_type.ilike(term)
            )
        )
        .limit(limit)
        .all()
    )
    return results

@router.get("/industries/{asset_id}", response_model=IndustrialAssetResponse)
def get_industry_by_id(asset_id: str, db: Session = Depends(get_db)):
    """
    Get detailed facility profile by ID.
    """
    asset = db.query(IndustrialAsset).filter(IndustrialAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Industrial asset not found")
    return asset

@router.post("/industries/seed")
def trigger_seed_industries(db: Session = Depends(get_db)):
    """
    Trigger manual seeding of Indian industrial registry.
    """
    count = seed_industrial_assets(db)
    return {"status": "success", "facilities_count": count}

@router.get("/gis/enrich")
def get_gis_enrichment(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    db: Session = Depends(get_db)
):
    """
    Evaluates spatial GIS context for any coordinate (nearest asset, distance, containment, landcover, state).
    """
    return enrich_coordinate_gis_context(lat, lon, db)
