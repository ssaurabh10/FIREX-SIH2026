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
from app.gis.mining_basins import is_in_major_mining_basin

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
        is_mining_basin, basin = is_in_major_mining_basin(lat, lon)
        basin_note = f" in {basin['name']}" if is_mining_basin else ""
        return {
            "primary_landcover": "industrial_complex" if not is_mining_basin else "open_cast_mine",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Low / Peripheral Vegetation Buffer",
            "industrial_context": f"Active Industrial Corridor ({nearest_asset_category}){basin_note}",
            "mining_context": f"Active Mining Basin: {basin['name']} ({basin['operator']})" if is_mining_basin else ("Active Mining Area" if "mining" in nearest_asset_category.lower() else "Industrial Operational Zone")
        }

    # 3. Check Sovereign Mining Basin Containment & Asset Context
    is_mining_basin, basin = is_in_major_mining_basin(lat, lon)
    if is_mining_basin and basin:
        return {
            "primary_landcover": "open_cast_mine",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Sparse / Degraded Mining Buffer & Pit Perimeter",
            "industrial_context": f"Sovereign Mineral & Mining Extraction Belt ({basin['name']})",
            "mining_context": f"Active Mining Basin: {basin['name']} (Operator: {basin['operator']})"
        }

    if "mining" in nearest_asset_category.lower() and nearest_asset_distance_km <= 10.0:
        return {
            "primary_landcover": "open_cast_mine",
            "is_protected_area": False,
            "protected_area_name": None,
            "forest_context": "Sparse / Degraded Mining Buffer",
            "industrial_context": "Mining Operations & Coal Extraction Basin",
            "mining_context": "Active Coal Seam / Overburden Zone"
        }

    # 4. Regional Agrarian Cropland defaults for Indo-Gangetic, Deccan, and Coastal Plains
    # Central Andhra open scrub / rocky hills exclusion (retains unclassified scrubland)
    is_kurnool_scrub = (15.65 <= lat <= 15.75 and 78.15 <= lon <= 78.25)
    
    is_agrarian_cropland = not is_kurnool_scrub and (
        # Northern Indo-Gangetic Plains (Punjab, Haryana, Delhi, Western UP)
        (28.0 <= lat <= 32.5 and 74.0 <= lon <= 79.0)
        # Central & Eastern Indo-Gangetic Plains (UP, Bihar)
        or (24.0 <= lat <= 28.5 and 79.0 <= lon <= 88.5)
        # Bengal Delta & Brahmaputra Valley (West Bengal, Assam)
        or (22.0 <= lat <= 27.5 and 87.5 <= lon <= 95.5)
        # Southern Agrarian Plains (Tamil Nadu Cauvery Basin & Southern Plains)
        or (8.2 <= lat <= 13.5 and 76.5 <= lon <= 80.5)
        # Deccan Plateau & Peninsular Cropland (Karnataka, Andhra Pradesh, Telangana)
        or (13.5 <= lat <= 19.5 and 76.0 <= lon <= 83.5)
        # Western Agricultural Belt (Maharashtra Marathwada/Vidarbha, Gujarat Saurashtra/Plains)
        or (17.5 <= lat <= 24.5 and 69.5 <= lon <= 80.0)
        # Central Agricultural Belt (Madhya Pradesh, Eastern Rajasthan plains)
        or (21.5 <= lat <= 28.5 and 73.5 <= lon <= 82.5)
    )

    if is_agrarian_cropland:
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
