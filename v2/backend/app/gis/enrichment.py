"""
Master GIS Context Enrichment Engine
Combines:
1. Nearest industrial asset calculation + Point-in-Polygon containment (assets.py)
2. Indian sovereign state and district resolution (boundaries.py)
3. Land cover and protected eco-sensitive reserve detection (landcover.py)
Generates the complete GIS context payload required by Section 10.5 & 11.2 of the Blueprint.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.gis.assets import find_nearest_asset
from app.gis.boundaries import resolve_admin_boundary
from app.gis.landcover import resolve_landcover

def enrich_coordinate_gis_context(lat: float, lon: float, db: Session) -> Dict[str, Any]:
    """
    Computes unified GIS enrichment payload for any spatial coordinate.
    """
    # 1. Proximity & Point-in-Polygon Containment to Industrial Assets
    asset_context = find_nearest_asset(lat, lon, db)

    # 2. Sovereign Administrative Units (State & District)
    admin_context = resolve_admin_boundary(lat, lon)
    state = asset_context.get("state") or admin_context.get("state")
    district = asset_context.get("district") or admin_context.get("district")

    # 3. Land Cover & Protected Area Resolution
    land_context = resolve_landcover(
        lat=lat,
        lon=lon,
        nearest_asset_distance_km=asset_context.get("distance_km", 999.0),
        nearest_asset_category=asset_context.get("category") or ""
    )

    return {
        "latitude": lat,
        "longitude": lon,
        "country": admin_context.get("country", "India"),
        "state": state,
        "district": district,
        "nearest_industrial_asset": {
            "id": asset_context.get("asset_id"),
            "name": asset_context.get("facility_name"),
            "type": asset_context.get("facility_type"),
            "operator": asset_context.get("operator"),
            "industry": asset_context.get("industry"),
            "category": asset_context.get("category"),
            "distance_km": asset_context.get("distance_km"),
            "distance_meters": asset_context.get("distance_meters"),
            "is_inside_facility": asset_context.get("is_inside_facility"),
            "hazard_category": asset_context.get("hazard_category")
        },
        "land_cover": land_context.get("primary_landcover"),
        "is_protected_area": land_context.get("is_protected_area"),
        "protected_area_name": land_context.get("protected_area_name"),
        "forest_context": land_context.get("forest_context"),
        "industrial_context": land_context.get("industrial_context"),
        "mining_context": land_context.get("mining_context"),
    }
