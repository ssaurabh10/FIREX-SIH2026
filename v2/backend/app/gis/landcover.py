"""
Land Cover & Protected Eco-Sensitive Area Resolver
Classifies land-use / land-cover characteristics around coordinates:
- industrial_complex
- dense_forest / wildlife_sanctuary
- agricultural_cropland
- open_cast_mine / barren_rock
- waterbody / coastal
"""
from typing import Dict, Any
from app.gis.spatial import haversine_distance_km

# Prominent National Parks and Protected Forest Zones in India
PROTECTED_ZONES = [
    {"name": "Jim Corbett National Park", "lat": 29.53, "lon": 78.77, "radius_km": 30.0},
    {"name": "Kaziranga National Park", "lat": 26.58, "lon": 93.17, "radius_km": 25.0},
    {"name": "Sundarbans Biosphere Reserve", "lat": 21.94, "lon": 88.89, "radius_km": 40.0},
    {"name": "Similipal Tiger Reserve", "lat": 21.65, "lon": 86.32, "radius_km": 35.0},
    {"name": "Bandipur National Park", "lat": 11.66, "lon": 76.63, "radius_km": 25.0},
    {"name": "Kanha Tiger Reserve", "lat": 22.33, "lon": 80.61, "radius_km": 30.0},
    {"name": "Gir National Park & Wildlife Sanctuary", "lat": 21.12, "lon": 70.82, "radius_km": 35.0},
    {"name": "Ranthambore National Park", "lat": 26.01, "lon": 76.50, "radius_km": 20.0},
]

def resolve_landcover(
    lat: float,
    lon: float,
    nearest_asset_distance_km: float = 999.0,
    nearest_asset_category: str = ""
) -> Dict[str, Any]:
    """
    Infers land cover and eco-sensitive protected area status based on proximity
    to industrial assets, protected forest reserves, and geography.
    """
    # 1. Check Protected Area / Reserve Forest proximity
    for park in PROTECTED_ZONES:
        # Quick lat/lon diff check before full calculation
        dlat = abs(lat - park["lat"])
        dlon = abs(lon - park["lon"])
        if dlat < 0.5 and dlon < 0.5:
            dist = haversine_distance_km(lat, lon, park["lat"], park["lon"])
            if dist <= park["radius_km"]:
                return {
                    "primary_landcover": "dense_forest",
                    "is_protected_area": True,
                    "protected_area_name": park["name"],
                    "forest_context": "High-Canopy Protected Forest Reserve",
                    "industrial_context": "Non-Industrial (Eco-Sensitive Zone)",
                    "mining_context": "Prohibited Zone"
                }

    # 2. Check Industrial Zone proximity
    if nearest_asset_distance_km <= 2.5:
        return {
            "primary_landcover": "industrial_complex",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Low / Peripheral Vegetation Buffer",
            "industrial_context": f"Active Industrial Corridor ({nearest_asset_category})",
            "mining_context": "Active Mining Area" if "mining" in nearest_asset_category.lower() else "Industrial Operational Zone"
        }

    # 3. Check Mining Basin Context
    if "mining" in nearest_asset_category.lower() and nearest_asset_distance_km <= 10.0:
        return {
            "primary_landcover": "open_cast_mine",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Sparse / Degraded Mining Buffer",
            "industrial_context": "Mining Operations & Coal Extraction Basin",
            "mining_context": "Active Coal Seam / Overburden Zone"
        }

    # 4. Regional Agrarian Cropland defaults for Indo-Gangetic and Deccan plains
    if (28.0 <= lat <= 32.0 and 74.0 <= lon <= 78.0) or (24.0 <= lat <= 27.0 and 80.0 <= lon <= 88.0):
        return {
            "primary_landcover": "agricultural_cropland",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Agricultural Perimeter",
            "industrial_context": "Rural / Agro-Industrial Hinterland",
            "mining_context": "Non-Mining"
        }

    # General rural / mixed terrain
    return {
        "primary_landcover": "mixed_vegetation_and_shrubland",
        "is_protected_area": False,
        "protected_area_name": None,
        "forest_context": "Open Scrub / Shrubland",
        "industrial_context": "Rural / Non-Industrial",
        "mining_context": "Non-Mining"
    }
