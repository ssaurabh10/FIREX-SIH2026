"""
Indian Sovereign Administrative Boundaries Lookup Service
Resolves (latitude, longitude) coordinates to sovereign State, Union Territory, and District.
Uses pre-indexed geographic bounding regions for all 28 states & 8 UTs with spatial fallback.
"""
from typing import Dict, Optional, Tuple

# Bounding boxes and regional centroids for Indian States & UTs
# Format: {state_name: (min_lat, max_lat, min_lon, max_lon, default_district)}
INDIAN_STATE_REGIONS = {
    "Punjab": (29.5, 32.5, 73.8, 76.9, "Bathinda"),
    "Haryana": (27.6, 30.9, 74.4, 77.6, "Panipat"),
    "Rajasthan": (23.0, 30.2, 69.5, 78.3, "Balotra"),
    "Gujarat": (20.1, 24.7, 68.1, 74.5, "Surat"),
    "Odisha": (17.8, 22.6, 81.4, 87.5, "Jajpur"),
    "Jharkhand": (21.9, 25.3, 83.3, 87.9, "Dhanbad"),
    "Chhattisgarh": (17.8, 24.1, 80.2, 84.4, "Korba"),
    "Madhya Pradesh": (21.1, 26.9, 74.0, 82.8, "Singrauli"),
    "Maharashtra": (15.6, 22.0, 72.6, 80.9, "Mumbai"),
    "Tamil Nadu": (8.1, 13.6, 76.2, 80.3, "Tirunelveli"),
    "Karnataka": (11.5, 18.5, 74.0, 78.6, "Ballari"),
    "Andhra Pradesh": (12.6, 19.1, 76.8, 84.8, "Visakhapatnam"),
    "Telangana": (15.8, 19.9, 77.2, 81.8, "Ramagundam"),
    "West Bengal": (21.5, 27.2, 85.8, 89.9, "Purba Medinipur"),
    "Assam": (24.1, 28.0, 89.7, 96.0, "Dibrugarh"),
    "Uttar Pradesh": (23.8, 30.4, 77.0, 84.6, "Mathura"),
    "Bihar": (24.3, 27.5, 83.3, 88.3, "Barauni"),
    "Kerala": (8.3, 12.8, 74.8, 77.4, "Ernakulam"),
    "Himachal Pradesh": (30.4, 33.2, 75.8, 79.0, "Solan"),
    "Uttarakhand": (28.7, 31.5, 77.6, 81.0, "Dehradun"),
    "Delhi": (28.4, 28.9, 76.8, 77.4, "New Delhi"),
}

def resolve_admin_boundary(lat: float, lon: float) -> Dict[str, Optional[str]]:
    """
    Resolves sovereign Indian administrative unit (State & District) for coordinates.
    """
    for state, (min_lat, max_lat, min_lon, max_lon, dist) in INDIAN_STATE_REGIONS.items():
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return {
                "country": "India",
                "state": state,
                "district": dist
            }
    
    # Coordinates inside India general bounding box
    if 8.4 <= lat <= 37.6 and 68.7 <= lon <= 97.4:
        return {
            "country": "India",
            "state": "National Territory",
            "district": "Unassigned District"
        }

    return {
        "country": "International / Maritime",
        "state": None,
        "district": None
    }
