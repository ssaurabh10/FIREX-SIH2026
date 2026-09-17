"""
Industrial Asset Manager & Spatial Proximity Engine
Capabilities:
1. Loads authoritative Indian industrial registry (refineries, steel complexes, power plants, mines, LNG terminals).
2. Computes nearest industrial asset to any coordinate with exact Haversine distance.
3. Tests geometric point-in-polygon containment against asset perimeters.
4. Searches facilities by name, operator, category, state, and district.
"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session, object_session
from app.storage.models import IndustrialAsset
from app.gis.spatial import (
    haversine_distance_meters,
    haversine_distance_km,
    point_in_geojson_geometry,
    generate_bounding_circle_polygon
)
from app.core.logging import logger

# Authoritative Initial Seed Dataset of Verified High-Risk Indian Industrial Facilities
INITIAL_INDUSTRIAL_FACILITIES = [
    # Refineries & Petrochemical Complexes
    {
        "name": "HMEL Guru Gobind Singh Oil Refinery, Talwandi Sabo, Bathinda",
        "facility_type": "oil_refinery",
        "operator": "HPCL-Mittal Energy Limited (HMEL)",
        "industry": "Oil & Gas Refining",
        "category": "gas_flare",
        "latitude": 29.9100,
        "longitude": 74.9520,
        "state": "Punjab",
        "district": "Bathinda",
        "display_address": "Rattangarh Kanakwal, Bathinda, Punjab, India",
        "hazard_category": "CRITICAL_INFRASTRUCTURE_HAZOP_4",
        "buffer_radius_meters": 2000.0,
    },
    {
        "name": "Panipat IOCL Refinery & Petrochemical Complex, Matlauda",
        "facility_type": "oil_refinery",
        "operator": "Indian Oil Corporation Limited (IOCL)",
        "industry": "Petrochemicals & Refining",
        "category": "gas_flare",
        "latitude": 29.4780,
        "longitude": 76.8540,
        "state": "Haryana",
        "district": "Panipat",
        "display_address": "Sithana, Matlauda Tahsil, Panipat, Haryana, India",
        "hazard_category": "CRITICAL_INFRASTRUCTURE_HAZOP_4",
        "buffer_radius_meters": 2500.0,
    },
    {
        "name": "HPCL Rajasthan Refinery & Petrochemicals (HRRL), Pachpadra",
        "facility_type": "oil_refinery",
        "operator": "HPCL Rajasthan Refinery Limited",
        "industry": "Petroleum Refining",
        "category": "gas_flare",
        "latitude": 25.9360,
        "longitude": 72.1920,
        "state": "Rajasthan",
        "district": "Balotra",
        "display_address": "Pachpadra, Balotra District, Rajasthan, India",
        "hazard_category": "CRITICAL_INFRASTRUCTURE_HAZOP_4",
        "buffer_radius_meters": 2500.0,
    },
    {
        "name": "Jamnagar Reliance Refinery Complex, Motikhavdi",
        "facility_type": "oil_refinery",
        "operator": "Reliance Industries Limited (RIL)",
        "industry": "Petroleum Refining & Aromatics",
        "category": "gas_flare",
        "latitude": 22.3550,
        "longitude": 69.8730,
        "state": "Gujarat",
        "district": "Jamnagar",
        "display_address": "Motikhavdi, Jamnagar, Gujarat, India",
        "hazard_category": "MEGA_COMPLEX_HAZOP_5",
        "buffer_radius_meters": 3500.0,
    },
    {
        "name": "Hazira ONGC & AM/NS Steel Heavy Industrial Hub",
        "facility_type": "petrochemical",
        "operator": "ONGC / ArcelorMittal Nippon Steel",
        "industry": "Petrochemicals & Heavy Steel",
        "category": "industrial_fire",
        "latitude": 21.1030,
        "longitude": 72.6490,
        "state": "Gujarat",
        "district": "Surat",
        "display_address": "Hazira Industrial Belt, Chorasi, Surat, Gujarat, India",
        "hazard_category": "MAJOR_ACCIDENT_HAZARD",
        "buffer_radius_meters": 2200.0,
    },

    # Integrated Steel Plants & Smelters
    {
        "name": "TATA Steel Kalinganagar Integrated Smelter & Plant",
        "facility_type": "steel_plant",
        "operator": "Tata Steel Limited",
        "industry": "Iron, Steel & Smelters",
        "category": "industrial_fire",
        "latitude": 20.9650,
        "longitude": 86.0110,
        "state": "Odisha",
        "district": "Jajpur",
        "display_address": "Kalinganagar Industrial Complex, Jajpur, Odisha, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3000.0,
    },
    {
        "name": "Bhilai Steel Plant (SAIL), Durg",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Steel Manufacturing",
        "category": "industrial_fire",
        "latitude": 21.1890,
        "longitude": 81.3850,
        "state": "Chhattisgarh",
        "district": "Durg",
        "display_address": "Bhilai, Durg District, Chhattisgarh, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3000.0,
    },
    {
        "name": "JSW Steel Vijayanagar Works, Toranagallu",
        "facility_type": "steel_plant",
        "operator": "JSW Steel Limited",
        "industry": "Integrated Steel Plant",
        "category": "industrial_fire",
        "latitude": 15.1950,
        "longitude": 76.6710,
        "state": "Karnataka",
        "district": "Ballari",
        "display_address": "Toranagallu, Sandur Taluk, Ballari, Karnataka, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3000.0,
    },
    {
        "name": "TATA Steel Works, Jamshedpur",
        "facility_type": "steel_plant",
        "operator": "Tata Steel Limited",
        "industry": "Integrated Iron & Steel Works",
        "category": "industrial_fire",
        "latitude": 22.7950,
        "longitude": 86.2000,
        "state": "Jharkhand",
        "district": "East Singhbhum",
        "display_address": "Bistupur / Sakchi Industrial Zone, Jamshedpur, Jharkhand, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 5000.0,
    },
    {
        "name": "Rourkela Steel Plant (SAIL), Rourkela",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Integrated Steel Plant & Rolling Mills",
        "category": "industrial_fire",
        "latitude": 22.2150,
        "longitude": 84.8600,
        "state": "Odisha",
        "district": "Sundargarh",
        "display_address": "Sector 1, Rourkela, Sundargarh District, Odisha, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4500.0,
    },
    {
        "name": "Visakhapatnam Steel Plant (RINL / Vizag Steel)",
        "facility_type": "steel_plant",
        "operator": "Rashtriya Ispat Nigam Limited (RINL)",
        "industry": "Shore-based Integrated Steel Plant",
        "category": "industrial_fire",
        "latitude": 17.6150,
        "longitude": 83.2050,
        "state": "Andhra Pradesh",
        "district": "Visakhapatnam",
        "display_address": "Kurmannapalem, Visakhapatnam, Andhra Pradesh, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4500.0,
    },
    {
        "name": "Jindal Steel & Power (JSPL) & NALCO Smelter, Angul",
        "facility_type": "steel_plant",
        "operator": "Jindal Steel & Power / National Aluminium Company",
        "industry": "Integrated Steel & Aluminium Smelting Complex",
        "category": "industrial_fire",
        "latitude": 20.7850,
        "longitude": 85.2750,
        "state": "Odisha",
        "district": "Angul",
        "display_address": "Nisha Industrial Zone, Angul, Odisha, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 5000.0,
    },
    {
        "name": "Vedanta Aluminium Smelter & Captive Power, Jharsuguda",
        "facility_type": "smelter",
        "operator": "Vedanta Limited",
        "industry": "Mega Aluminium Smelting Complex",
        "category": "industrial_fire",
        "latitude": 22.0400,
        "longitude": 83.7350,
        "state": "Odisha",
        "district": "Jharsuguda",
        "display_address": "Bhurkhamunda, Jharsuguda, Odisha, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4000.0,
    },
    {
        "name": "JSW Steel Dolvi Works, Raigad",
        "facility_type": "steel_plant",
        "operator": "JSW Steel Limited",
        "industry": "Integrated Steel Manufacturing & Sinter",
        "category": "industrial_fire",
        "latitude": 18.6900,
        "longitude": 73.0380,
        "state": "Maharashtra",
        "district": "Raigad",
        "display_address": "Dolvi, Pen Taluk, Raigad District, Maharashtra, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3500.0,
    },
    {
        "name": "Bokaro Steel Plant (SAIL), Bokaro",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Integrated Steel Plant & Blast Furnaces",
        "category": "industrial_fire",
        "latitude": 23.6680,
        "longitude": 86.1550,
        "state": "Jharkhand",
        "district": "Bokaro",
        "display_address": "Bokaro Steel City, Jharkhand, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4500.0,
    },
    {
        "name": "Durgapur Steel Plant (SAIL), Durgapur",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Alloy & Structural Steel Plant",
        "category": "industrial_fire",
        "latitude": 23.5500,
        "longitude": 87.2700,
        "state": "West Bengal",
        "district": "Paschim Bardhaman",
        "display_address": "Durgapur, Paschim Bardhaman, West Bengal, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4000.0,
    },
    {
        "name": "IISCO Steel Plant (SAIL), Burnpur, Asansol",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Integrated Iron & Steel Plant",
        "category": "industrial_fire",
        "latitude": 23.6300,
        "longitude": 86.9500,
        "state": "West Bengal",
        "district": "Paschim Bardhaman",
        "display_address": "Burnpur, Asansol, Paschim Bardhaman, West Bengal, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3500.0,
    },
    {
        "name": "Tata Metaliks & Rashmi Metaliks Complex, Kharagpur",
        "facility_type": "steel_plant",
        "operator": "Tata Metaliks / Rashmi Group",
        "industry": "Pig Iron, Sinter & Ductile Iron Pipes",
        "category": "industrial_fire",
        "latitude": 22.3700,
        "longitude": 87.2900,
        "state": "West Bengal",
        "district": "Paschim Medinipur",
        "display_address": "Gokulpur Industrial Area, Kharagpur, West Bengal, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4000.0,
    },
    {
        "name": "Chanderiya Lead-Zinc Smelter (Hindustan Zinc), Chittorgarh",
        "facility_type": "smelter",
        "operator": "Hindustan Zinc Limited (Vedanta)",
        "industry": "World's Largest Integrated Zinc Smelting Complex",
        "category": "industrial_fire",
        "latitude": 24.6650,
        "longitude": 74.6300,
        "state": "Rajasthan",
        "district": "Chittorgarh",
        "display_address": "Putholi, Chanderiya, Chittorgarh, Rajasthan, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 4500.0,
    },
    {
        "name": "NMDC Iron & Steel Plant (NISP), Nagarnar",
        "facility_type": "steel_plant",
        "operator": "NMDC Limited",
        "industry": "Integrated Steel Plant & Blast Furnace",
        "category": "industrial_fire",
        "latitude": 19.1000,
        "longitude": 82.1650,
        "state": "Chhattisgarh",
        "district": "Bastar",
        "display_address": "Nagarnar, Jagdalpur, Bastar District, Chhattisgarh, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3500.0,
    },
    {
        "name": "Siltara & Urla Heavy Industrial Complex, Raipur",
        "facility_type": "steel_plant",
        "operator": "Raipur Steel & Sponge Iron Consortium",
        "industry": "Sponge Iron, Billet & Ferro Alloy Rolling Mills",
        "category": "industrial_fire",
        "latitude": 21.3700,
        "longitude": 81.6600,
        "state": "Chhattisgarh",
        "district": "Raipur",
        "display_address": "Siltara Industrial Area, Raipur, Chhattisgarh, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 5500.0,
    },
    {
        "name": "Salem Steel Plant (SAIL), Salem",
        "facility_type": "steel_plant",
        "operator": "Steel Authority of India Limited (SAIL)",
        "industry": "Special Steel & Cold Rolling Mill",
        "category": "industrial_fire",
        "latitude": 11.8150,
        "longitude": 77.9200,
        "state": "Tamil Nadu",
        "district": "Salem",
        "display_address": "Steel Plant Road, Salem, Tamil Nadu, India",
        "hazard_category": "HIGH_THERMAL_METALLURGIC",
        "buffer_radius_meters": 3000.0,
    },
    {
        "name": "Bombay High Offshore Oil & Gas Production Platform",
        "facility_type": "offshore_platform",
        "operator": "Oil and Natural Gas Corporation (ONGC)",
        "industry": "Offshore Hydrocarbon Flaring & Production",
        "category": "gas_flare",
        "latitude": 19.3000,
        "longitude": 71.4000,
        "state": "Maharashtra",
        "district": "Mumbai Offshore",
        "display_address": "Mumbai High Basin, Arabian Sea, India",
        "hazard_category": "MAJOR_ACCIDENT_HAZARD",
        "buffer_radius_meters": 20000.0,
    },
    {
        "name": "Oil India Duliajan & Digboi Oilfields Flare Hub",
        "facility_type": "oil_production",
        "operator": "Oil India Limited (OIL)",
        "industry": "Crude Oil Extraction & Gas Flaring",
        "category": "gas_flare",
        "latitude": 27.3800,
        "longitude": 95.3300,
        "state": "Assam",
        "district": "Dibrugarh",
        "display_address": "Duliajan / Digboi Oilfield Zone, Dibrugarh, Assam, India",
        "hazard_category": "MAJOR_ACCIDENT_HAZARD",
        "buffer_radius_meters": 10000.0,
    },

    # Coal Mining Basins & Super Thermal Power Stations
    {
        "name": "Talcher Coalfields & NTPC Super Thermal Power Complex",
        "facility_type": "thermal_power",
        "operator": "Mahanadi Coalfields / NTPC",
        "industry": "Coal Mining & Power Generation",
        "category": "mining_or_other_thermal_source",
        "latitude": 20.9650,
        "longitude": 85.1710,
        "state": "Odisha",
        "district": "Angul",
        "display_address": "Talcher Sadar, Angul District, Odisha, India",
        "hazard_category": "THERMAL_COALFIELD_HAZARD",
        "buffer_radius_meters": 4000.0,
    },
    {
        "name": "Jharia Underground Coal Seam Fire & Coking Basin",
        "facility_type": "mining",
        "operator": "Bharat Coking Coal Limited (BCCL)",
        "industry": "Coal Mining & Underground Seam Fires",
        "category": "mining_or_other_thermal_source",
        "latitude": 23.6790,
        "longitude": 86.3940,
        "state": "Jharkhand",
        "district": "Dhanbad",
        "display_address": "Jamadoba, Jharia Coalfields, Dhanbad, Jharkhand, India",
        "hazard_category": "CHRONIC_SUBSURFACE_FIRE",
        "buffer_radius_meters": 5000.0,
    },
    {
        "name": "Korba Open-Cast Coal & NTPC Super Thermal Power Plant",
        "facility_type": "thermal_power",
        "operator": "South Eastern Coalfields / NTPC",
        "industry": "Thermal Power & Coalfields",
        "category": "mining_or_other_thermal_source",
        "latitude": 22.3550,
        "longitude": 82.2980,
        "state": "Chhattisgarh",
        "district": "Korba",
        "display_address": "Pali Tahsil, Korba District, Chhattisgarh, India",
        "hazard_category": "THERMAL_COALFIELD_HAZARD",
        "buffer_radius_meters": 3500.0,
    },
    {
        "name": "Singrauli Super Thermal Power & Northern Coalfields",
        "facility_type": "thermal_power",
        "operator": "NTPC / Northern Coalfields Limited",
        "industry": "Energy Capital of India",
        "category": "mining_or_other_thermal_source",
        "latitude": 24.1030,
        "longitude": 82.6840,
        "state": "Madhya Pradesh",
        "district": "Singrauli",
        "display_address": "Shaktinagar, Singrauli, Madhya Pradesh, India",
        "hazard_category": "THERMAL_COALFIELD_HAZARD",
        "buffer_radius_meters": 4000.0,
    },

    # LNG Terminals & Cryogenic Storage
    {
        "name": "Petronet Dahej LNG Regasification Terminal & Petrochem",
        "facility_type": "lng_terminal",
        "operator": "Petronet LNG Limited",
        "industry": "LNG Cryogenic & Gas Terminal",
        "category": "gas_flare",
        "latitude": 21.6780,
        "longitude": 72.5410,
        "state": "Gujarat",
        "district": "Bharuch",
        "display_address": "Dahej Port Industrial Zone, Bharuch, Gujarat, India",
        "hazard_category": "CRYOGENIC_VOLATILE_GAS_HAZOP_5",
        "buffer_radius_meters": 2000.0,
    },
    {
        "name": "Kochi LNG Regasification Terminal (Petronet)",
        "facility_type": "lng_terminal",
        "operator": "Petronet LNG Limited",
        "industry": "LNG Marine Terminal",
        "category": "gas_flare",
        "latitude": 9.9890,
        "longitude": 76.2230,
        "state": "Kerala",
        "district": "Ernakulam",
        "display_address": "Puthuvype Special Economic Zone, Kochi, Kerala, India",
        "hazard_category": "CRYOGENIC_VOLATILE_GAS_HAZOP_5",
        "buffer_radius_meters": 1800.0,
    },
]

FLARING_FACILITY_TYPES = {
    "oil_refinery", "lng_terminal", "offshore_platform", "oil_production", "gas_terminal", "hydrocarbon_flare"
}

def is_flaring_facility(facility_type: Optional[str], category: Optional[str] = None) -> bool:
    """Returns True only if facility is a verified petroleum flaring asset (refinery/LNG/wellhead)."""
    ft = (facility_type or "").lower()
    cat = (category or "").lower()
    if cat == "gas_flare" and any(f in ft for f in FLARING_FACILITY_TYPES):
        return True
    return any(f in ft for f in FLARING_FACILITY_TYPES)

def is_metallurgical_or_manufacturing_facility(facility_type: Optional[str], industry: Optional[str] = None) -> bool:
    """Returns True if facility is a steel plant, smelter, foundry, cement plant, or heavy manufacturing unit."""
    text = f"{facility_type or ''} {industry or ''}".lower()
    keywords = ["steel", "smelter", "blast_furnace", "furnace", "foundry", "metal", "coke", "rolling", "iron", "cement", "kiln", "aluminium", "zinc"]
    return any(k in text for k in keywords)

def get_facility_classification_category(facility_type: Optional[str], industry: Optional[str] = None, category: Optional[str] = None) -> str:
    """
    Returns the canonical fire classification category for a facility.
    - Petroleum flaring facilities (refinery/LNG/wellhead) -> 'gas_flare'
    - Metallurgical / manufacturing / power / chemical plants -> 'industrial_fire'
    """
    if is_flaring_facility(facility_type, category):
        return "gas_flare"
    return "industrial_fire"

def is_in_industrial_facility(lat: float, lon: float, db: Session, max_distance_km: float = 5.0) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Checks whether a coordinate is inside an industrial facility boundary or within max_distance_km.
    Returns (is_inside_or_near, asset_info).
    """
    asset_info = find_nearest_asset(lat, lon, db)
    if not asset_info or not asset_info.get("asset_id"):
        return False, None
    dist = asset_info.get("distance_km") or 999.0
    is_inside = asset_info.get("is_inside_facility", False)
    if is_inside or dist <= max_distance_km:
        return True, asset_info
    return False, asset_info

def seed_industrial_assets(db: Session, force_refresh: bool = False) -> int:
    """
    Seeds database with initial Indian industrial infrastructure assets.
    Upserts missing assets so updates to INITIAL_INDUSTRIAL_FACILITIES are automatically reflected.
    """
    existing_assets = {a.name: a for a in db.query(IndustrialAsset).all()}
    added_count = 0

    for item in INITIAL_INDUSTRIAL_FACILITIES:
        if item["name"] in existing_assets and not force_refresh:
            continue

        coords = generate_bounding_circle_polygon(
            center_lat=item["latitude"],
            center_lon=item["longitude"],
            radius_meters=item["buffer_radius_meters"]
        )
        poly_geom = {
            "type": "Polygon",
            "coordinates": [coords]
        }

        if item["name"] in existing_assets:
            asset = existing_assets[item["name"]]
            asset.facility_type = item["facility_type"]
            asset.operator = item["operator"]
            asset.industry = item["industry"]
            asset.category = item["category"]
            asset.latitude = item["latitude"]
            asset.longitude = item["longitude"]
            asset.state = item["state"]
            asset.district = item["district"]
            asset.display_address = item["display_address"]
            asset.hazard_category = item["hazard_category"]
            asset.buffer_radius_meters = item["buffer_radius_meters"]
            asset.polygon_geojson = poly_geom
        else:
            asset = IndustrialAsset(
                name=item["name"],
                facility_type=item["facility_type"],
                operator=item["operator"],
                industry=item["industry"],
                category=item["category"],
                latitude=item["latitude"],
                longitude=item["longitude"],
                state=item["state"],
                district=item["district"],
                display_address=item["display_address"],
                hazard_category=item["hazard_category"],
                buffer_radius_meters=item["buffer_radius_meters"],
                polygon_geojson=poly_geom,
                source="NATIONAL_INDUSTRIAL_REGISTRY"
            )
            db.add(asset)
            added_count += 1

    db.commit()
    total = db.query(IndustrialAsset).count()
    global _ASSETS_CACHE
    _ASSETS_CACHE = None
    logger.info(f"Industrial registry synced. {added_count} new facilities added. Total: {total}")
    return total

FACILITY_PROXIMITY_THRESHOLD_KM = 5.0
_ASSETS_CACHE = None

def invalidate_assets_cache() -> None:
    """Invalidates the in-memory cache of industrial assets."""
    global _ASSETS_CACHE
    _ASSETS_CACHE = None

def get_cached_assets(db: Session) -> List[IndustrialAsset]:
    global _ASSETS_CACHE
    if _ASSETS_CACHE is not None and len(_ASSETS_CACHE) > 0:
        sess = object_session(_ASSETS_CACHE[0])
        if sess is None or not sess.is_active or sess != db:
            _ASSETS_CACHE = None

    if _ASSETS_CACHE is None:
        _ASSETS_CACHE = db.query(IndustrialAsset).all()
        if not _ASSETS_CACHE:
            seed_industrial_assets(db)
            _ASSETS_CACHE = db.query(IndustrialAsset).all()
    return _ASSETS_CACHE

def find_nearest_asset(lat: float, lon: float, db: Session) -> Dict[str, Any]:
    """
    Finds the closest industrial asset to (lat, lon).
    Performs Point-in-Polygon containment check and returns exact distance in km.
    """
    assets = get_cached_assets(db)

    nearest = None
    min_dist_meters = float("inf")
    is_inside = False

    for asset in assets:
        dist_m = haversine_distance_meters(lat, lon, asset.latitude, asset.longitude)
        if dist_m < min_dist_meters:
            min_dist_meters = dist_m
            nearest = asset

    if nearest:
        # Check point in polygon containment
        if nearest.polygon_geojson:
            is_inside = point_in_geojson_geometry(lat, lon, nearest.polygon_geojson)
        else:
            is_inside = min_dist_meters <= nearest.buffer_radius_meters

        dist_km = round(min_dist_meters / 1000.0, 3)
        return {
            "asset_id": nearest.id,
            "facility_name": nearest.name,
            "facility_type": nearest.facility_type,
            "operator": nearest.operator,
            "industry": nearest.industry,
            "category": nearest.category,
            "distance_km": dist_km,
            "distance_meters": round(min_dist_meters, 1),
            "is_inside_facility": is_inside,
            "state": nearest.state,
            "district": nearest.district,
            "hazard_category": nearest.hazard_category
        }

    return {
        "asset_id": None,
        "facility_name": None,
        "facility_type": None,
        "operator": None,
        "industry": None,
        "category": None,
        "distance_km": 999.0,
        "distance_meters": 999000.0,
        "is_inside_facility": False,
        "state": None,
        "district": None,
        "hazard_category": None
    }
