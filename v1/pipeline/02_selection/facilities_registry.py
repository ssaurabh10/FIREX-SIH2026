# -*- coding: utf-8 -*-
"""
FIREX — Geographic Reference & Known Facilities Registry
=========================================================
Authoritative database of verified Indian industrial facilities, refineries,
power complexes, coalfield basins, forest reserves, and agrarian zones.
Provides spatial Haversine distance computation to ground assets.
"""

import math

KNOWN_FACILITIES_REGISTRY = [
    # Refineries & Petrochemical Complexes (Gas Flares / Continuous Flaring)
    {
        "lat": 29.910, "lon": 74.952,
        "name": "HMEL Guru Gobind Singh Oil Refinery, Talwandi Sabo, Bathinda, Punjab",
        "disp": "Rattangarh Kanakwal, Bathinda, Punjab, India",
        "cls": "gas_flare", "cat": "likely_flare_or_persistent",
        "asset_type": "petrochemical"
    },
    {
        "lat": 29.478, "lon": 76.854,
        "name": "Panipat IOCL Refinery & Petrochemical Complex, Matlauda, Panipat, Haryana",
        "disp": "Sithana, Matlauda Tahsil, Panipat, Haryana, India",
        "cls": "gas_flare", "cat": "likely_flare_or_persistent",
        "asset_type": "petrochemical"
    },
    {
        "lat": 25.936, "lon": 72.192,
        "name": "HPCL Rajasthan Refinery & Petrochemicals (HRRL), Pachpadra, Balotra, Rajasthan",
        "disp": "Pachpadra, Balotra District, Rajasthan, India",
        "cls": "gas_flare", "cat": "likely_flare_or_persistent",
        "asset_type": "petrochemical"
    },

    # Steel Plants, Smelters & Heavy Manufacturing (Industrial High-Thermal Heat)
    {
        "lat": 20.965, "lon": 86.011,
        "name": "TATA Steel Kalinganagar Integrated Smelter & Plant, Jajpur, Odisha",
        "disp": "Kalinganagar Industrial Complex, Jajpur, Odisha, India",
        "cls": "industrial_fire", "cat": "industrial_candidate",
        "asset_type": "heavy_industry"
    },
    {
        "lat": 21.103, "lon": 72.649,
        "name": "Hazira Petrochemical & Heavy Industrial Hub (ONGC / AM/NS Steel), Surat, Gujarat",
        "disp": "Hazira Industrial Belt, Chorasi, Surat, Gujarat, India",
        "cls": "industrial_fire", "cat": "industrial_candidate",
        "asset_type": "petrochemical"
    },
    {
        "lat": 8.846, "lon": 77.702,
        "name": "Gangaikondan / Pallikottai Heavy Industrial Corridor, Tirunelveli, Tamil Nadu",
        "disp": "Pallikottai, Manur Taluk, Tirunelveli, Tamil Nadu, India",
        "cls": "industrial_fire", "cat": "industrial_candidate",
        "asset_type": "heavy_industry"
    },
    {
        "lat": 9.203, "lon": 77.644,
        "name": "Kuruvikulam Industrial & Mineral Processing Sector, Tenkasi, Tamil Nadu",
        "disp": "Kuruvikulam, Sankarankoil, Tenkasi, Tamil Nadu, India",
        "cls": "industrial_fire", "cat": "industrial_candidate",
        "asset_type": "heavy_industry"
    },

    # Coal Mining, Seam Fires & Thermal Power Belts (Mining / Subsurface)
    {
        "lat": 20.965, "lon": 85.171,
        "name": "Talcher Coalfields & NTPC Super Thermal Power Complex, Angul, Odisha",
        "disp": "Talcher Sadar, Angul District, Odisha, India",
        "cls": "mining_or_other_thermal_source", "cat": "mining_candidate",
        "asset_type": "mining_power"
    },
    {
        "lat": 23.801, "lon": 86.331,
        "name": "Sijua Coal Basin & Coking Coal Fields, Baghmara, Dhanbad, Jharkhand",
        "disp": "Sijua, Baghmara-Cum-Katras, Dhanbad, Jharkhand, India",
        "cls": "mining_or_other_thermal_source", "cat": "mining_candidate",
        "asset_type": "mining"
    },
    {
        "lat": 23.679, "lon": 86.394,
        "name": "Jamadoba / Jharia Underground Coal Seam Fire Zone, Dhanbad, Jharkhand",
        "disp": "Jamadoba, Jharia Coalfields, Dhanbad, Jharkhand, India",
        "cls": "mining_or_other_thermal_source", "cat": "mining_candidate",
        "asset_type": "mining"
    },
    {
        "lat": 22.355, "lon": 82.298,
        "name": "Pali - Korba Open-Cast Coal & Thermal Power Corridor, Korba, Chhattisgarh",
        "disp": "Pali Tahsil, Korba District, Chhattisgarh, India",
        "cls": "mining_or_other_thermal_source", "cat": "mining_candidate",
        "asset_type": "mining_power"
    },
    {
        "lat": 23.321, "lon": 68.857,
        "name": "Panandhro - Lakhpat Lignite & Mineral Mining Basin, Kutch, Gujarat",
        "disp": "Lakhpat Taluka, Kutch, Gujarat, India",
        "cls": "mining_or_other_thermal_source", "cat": "mining_candidate",
        "asset_type": "mining"
    },

    # Wildfires & Forest Reserves (Dense Canopy / Hilly Wilderness)
    {
        "lat": 12.097, "lon": 77.066,
        "name": "Biligiriranga (BR) Hills Wildlife Sanctuary & Tiger Reserve, Chamarajanagar, Karnataka",
        "disp": "Shivakalli, Yalanduru Taluk, Chamarajanagar, Karnataka, India",
        "cls": "wildfire", "cat": "forest_candidate",
        "asset_type": "forest_reserve"
    },
    {
        "lat": 27.984, "lon": 95.939,
        "name": "Lower Dibang Valley Himalayan Rainforest Wilderness, Roing, Arunachal Pradesh",
        "disp": "Roing Sub-division, Lower Dibang Valley, Arunachal Pradesh, India",
        "cls": "wildfire", "cat": "forest_candidate",
        "asset_type": "forest_reserve"
    },
    {
        "lat": 27.724, "lon": 94.386,
        "name": "Gensi Mountain Forest Canopy, Lower Siang, Arunachal Pradesh",
        "disp": "Gensi Circle, Lower Siang District, Arunachal Pradesh, India",
        "cls": "wildfire", "cat": "forest_candidate",
        "asset_type": "forest_reserve"
    },
    {
        "lat": 24.259, "lon": 96.544,
        "name": "Indo-Myanmar Mountain Forest Ridge, Chandel District, Manipur",
        "disp": "Chandel Forest Division, Manipur, India",
        "cls": "wildfire", "cat": "forest_candidate",
        "asset_type": "forest_reserve"
    },

    # Agricultural Burning & Rural Biomass Crop Residue
    {
        "lat": 22.366, "lon": 87.303,
        "name": "Paschim Medinipur Agricultural Plain & Farmlands, Kharagpur, West Bengal",
        "disp": "Kharagpur Rural, Paschim Medinipur, West Bengal, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
    {
        "lat": 10.237, "lon": 79.196,
        "name": "Cauvery Delta Farmlands & Biomass Plain, Peravurani, Thanjavur, Tamil Nadu",
        "disp": "Peravurani, Thanjavur District, Tamil Nadu, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
    {
        "lat": 9.965, "lon": 77.896,
        "name": "Usilampatti Agrarian Crop Belt, Madurai District, Tamil Nadu",
        "disp": "Usilampatti Taluk, Madurai, Tamil Nadu, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
    {
        "lat": 9.176, "lon": 78.226,
        "name": "Vilathikulam Rural Agrarian & Salt Plain, Thoothukudi, Tamil Nadu",
        "disp": "Keilavilattikulam, Vilathikulam, Thoothukudi, Tamil Nadu, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
    {
        "lat": 9.623, "lon": 78.117,
        "name": "Kariapatti Rural Farmland & Crop Fields, Virudhunagar, Tamil Nadu",
        "disp": "Valayamkulam, Kariapatti, Virudhunagar, Tamil Nadu, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
    {
        "lat": 10.167, "lon": 78.791,
        "name": "Karaikkudi Agrarian & Biomass Sector, Sivagangai, Tamil Nadu",
        "disp": "Kanadukathan, Karaikkudi, Sivagangai, Tamil Nadu, India",
        "cls": "agricultural_burning", "cat": "agricultural_burning",
        "asset_type": "agriculture"
    },
]

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle geodesic distance in kilometers between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def find_nearest_facility(lat: float, lon: float, registry=None) -> tuple[dict | None, float]:
    """
    Finds the closest registered strategic facility or ecological landmark.
    Returns (nearest_facility_dict, distance_in_km).
    """
    if registry is None:
        registry = KNOWN_FACILITIES_REGISTRY

    best_fac = None
    min_dist = float("inf")
    for fac in registry:
        d = haversine_km(lat, lon, fac["lat"], fac["lon"])
        if d < min_dist:
            min_dist = d
            best_fac = fac

    return best_fac, min_dist
