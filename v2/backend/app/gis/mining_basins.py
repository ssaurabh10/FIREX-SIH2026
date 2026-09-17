"""
Authoritative Geographic Registry of Sovereign Indian Mining Basins & Coalfields
Provides fast spatial containment checks to prevent open-cast mining thermal emissions
from being falsely identified as routine petroleum gas flares or uncontrolled wildfires.
"""
from typing import Tuple, Optional, Dict, Any, List

MAJOR_INDIAN_MINING_BASINS = [
    {
        "id": "KORBA_COALFIELD",
        "name": "Korba Open-Cast Coal Basin (Gevra, Kusmunda, Dipka, Korba)",
        "operator": "South Eastern Coalfields Limited (SECL)",
        "state": "Chhattisgarh",
        "district": "Korba",
        "min_lat": 22.15,
        "max_lat": 22.58,
        "min_lon": 82.15,
        "max_lon": 82.85,
    },
    {
        "id": "JHARIA_BOKARO_COALFIELD",
        "name": "Jharia & Bokaro Coking Coal Basin (Dhanbad, Katras, Sijua)",
        "operator": "Bharat Coking Coal Limited (BCCL) / Central Coalfields Limited (CCL)",
        "state": "Jharkhand",
        "district": "Dhanbad",
        "min_lat": 23.50,
        "max_lat": 23.95,
        "min_lon": 85.50,
        "max_lon": 86.65,
    },
    {
        "id": "RANIGANJ_COALFIELD",
        "name": "Raniganj Coalfield & Industrial Mining Belt (Asansol, Raniganj, Kulti)",
        "operator": "Eastern Coalfields Limited (ECL)",
        "state": "West Bengal",
        "district": "Paschim Bardhaman",
        "min_lat": 23.45,
        "max_lat": 23.85,
        "min_lon": 86.70,
        "max_lon": 87.35,
    },
    {
        "id": "TALCHER_COALFIELD",
        "name": "Talcher Coalfields & NTPC Super Thermal Corridor (Angul)",
        "operator": "Mahanadi Coalfields Limited (MCL)",
        "state": "Odisha",
        "district": "Angul",
        "min_lat": 20.80,
        "max_lat": 21.20,
        "min_lon": 84.80,
        "max_lon": 85.40,
    },
    {
        "id": "IB_VALLEY_COALFIELD",
        "name": "Ib Valley & Jharsuguda Coalfield (Belpahar, Brajrajnagar, Lakhanpur)",
        "operator": "Mahanadi Coalfields Limited (MCL)",
        "state": "Odisha",
        "district": "Jharsuguda",
        "min_lat": 21.55,
        "max_lat": 21.95,
        "min_lon": 83.65,
        "max_lon": 84.15,
    },
    {
        "id": "SINGRAULI_COALFIELD",
        "name": "Singrauli & Northern Coalfields Basin (Shaktinagar, Jayant, Dudhichua)",
        "operator": "Northern Coalfields Limited (NCL)",
        "state": "Madhya Pradesh",
        "district": "Singrauli",
        "min_lat": 23.90,
        "max_lat": 24.35,
        "min_lon": 82.35,
        "max_lon": 82.95,
    },
    {
        "id": "KARANPURA_COALFIELD",
        "name": "North & South Karanpura Coal Basin (Barkakana, Khalari, Kuju)",
        "operator": "Central Coalfields Limited (CCL)",
        "state": "Jharkhand",
        "district": "Ramgarh",
        "min_lat": 23.60,
        "max_lat": 23.98,
        "min_lon": 84.75,
        "max_lon": 85.60,
    },
    {
        "id": "WARDHA_VALLEY_COALFIELD",
        "name": "Wardha Valley & Chandrapur Coalfields (Chandrapur, Ballarpur)",
        "operator": "Western Coalfields Limited (WCL)",
        "state": "Maharashtra",
        "district": "Chandrapur",
        "min_lat": 19.80,
        "max_lat": 20.35,
        "min_lon": 79.05,
        "max_lon": 79.50,
    },
    {
        "id": "GODAVARI_VALLEY_COALFIELD",
        "name": "Godavari Valley Singareni Collieries (Kothagudem, Ramagundam)",
        "operator": "Singareni Collieries Company Limited (SCCL)",
        "state": "Telangana",
        "district": "Bhadradri Kothagudem",
        "min_lat": 17.35,
        "max_lat": 19.05,
        "min_lon": 79.25,
        "max_lon": 80.75,
    },
    {
        "id": "PANANDHRO_LIGNITE_BASIN",
        "name": "Panandhro - Lakhpat Lignite & Mineral Mining Basin",
        "operator": "Gujarat Mineral Development Corporation (GMDC)",
        "state": "Gujarat",
        "district": "Kutch",
        "min_lat": 23.20,
        "max_lat": 23.85,
        "min_lon": 68.60,
        "max_lon": 69.15,
    },
    {
        "id": "NEYVELI_LIGNITE_BASIN",
        "name": "Neyveli Lignite Open-Cast Mine Complex",
        "operator": "NLC India Limited",
        "state": "Tamil Nadu",
        "district": "Cuddalore",
        "min_lat": 11.45,
        "max_lat": 11.68,
        "min_lon": 79.35,
        "max_lon": 79.62,
    },
    {
        "id": "BALLARI_HOSPET_IRON_ORE_BASIN",
        "name": "Ballari - Hospet - Sandur Iron Ore & Mineral Mining Basin",
        "operator": "National Mineral Development Corporation (NMDC) / JSW Mines",
        "state": "Karnataka",
        "district": "Ballari",
        "min_lat": 14.80,
        "max_lat": 15.65,
        "min_lon": 76.15,
        "max_lon": 76.95,
    },
    {
        "id": "KEONJHAR_BARBIL_IRON_ORE_BELT",
        "name": "Keonjhar - Barbil - Joda Iron Ore & Manganese Mining Belt",
        "operator": "Odisha Mining Corporation (OMC) / TATA Steel / SAIL",
        "state": "Odisha",
        "district": "Kendujhar (Keonjhar)",
        "min_lat": 21.70,
        "max_lat": 22.45,
        "min_lon": 85.10,
        "max_lon": 85.65,
    },
    {
        "id": "MAND_RAIGARH_COALFIELD",
        "name": "Mand-Raigarh & Gharghoda Coal Mining Basin",
        "operator": "South Eastern Coalfields Limited (SECL)",
        "state": "Chhattisgarh",
        "district": "Raigarh",
        "min_lat": 21.65,
        "max_lat": 22.45,
        "min_lon": 82.85,
        "max_lon": 83.65,
    },
    {
        "id": "HASDEO_KOREA_COALFIELD",
        "name": "Hasdeo-Arand & Korea-Chirimiri Coal Basin",
        "operator": "South Eastern Coalfields Limited (SECL)",
        "state": "Chhattisgarh",
        "district": "Koriya",
        "min_lat": 22.60,
        "max_lat": 23.40,
        "min_lon": 82.15,
        "max_lon": 83.15,
    },
    {
        "id": "DALTONGANJ_PALAMU_MINING_BASIN",
        "name": "Daltonganj - Rajhara Coal & Mineral Basin",
        "operator": "Central Coalfields Limited (CCL)",
        "state": "Jharkhand",
        "district": "Palamu",
        "min_lat": 23.70,
        "max_lat": 24.15,
        "min_lon": 83.95,
        "max_lon": 84.75,
    },
]

def is_in_major_mining_basin(lat: float, lon: float) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Checks if a geographic coordinate falls inside a verified major Indian coalfield or mineral mining basin.
    Returns: (is_mining_basin, basin_metadata)
    """
    for basin in MAJOR_INDIAN_MINING_BASINS:
        if basin["min_lat"] <= lat <= basin["max_lat"] and basin["min_lon"] <= lon <= basin["max_lon"]:
            return True, basin
    return False, None

def get_mining_basin_metadata(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Returns structured metadata for coordinate if inside a sovereign mining basin, else None.
    """
    is_inside, basin = is_in_major_mining_basin(lat, lon)
    if is_inside and basin:
        return {
            "is_mining_basin": True,
            "basin_id": basin["id"],
            "basin_name": basin["name"],
            "operator": basin["operator"],
            "state": basin["state"],
            "district": basin["district"]
        }
    return None

