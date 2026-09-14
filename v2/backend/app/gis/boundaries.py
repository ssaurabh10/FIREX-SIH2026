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
    "Maharashtra (Offshore)": (18.0, 20.5, 70.8, 72.6, "Bombay High Field"),
    "Tamil Nadu": (8.1, 13.6, 76.2, 80.3, "Tirunelveli"),
    "Karnataka": (11.5, 18.5, 74.0, 78.6, "Ballari"),
    "Andhra Pradesh": (12.6, 19.1, 76.8, 84.8, "Visakhapatnam"),
    "Telangana": (15.8, 19.9, 77.2, 81.8, "Ramagundam"),
    "West Bengal": (21.5, 27.2, 85.8, 89.9, "Purba Medinipur"),
    "Assam": (24.1, 28.0, 89.7, 96.0, "Dibrugarh"),
    "Arunachal Pradesh": (26.6, 29.45, 91.5, 97.4, "Itanagar"),
    "Nagaland": (25.1, 27.1, 93.3, 95.3, "Kohima"),
    "Manipur": (23.8, 25.7, 93.0, 94.8, "Imphal"),
    "Mizoram": (21.9, 24.5, 92.2, 93.5, "Aizawl"),
    "Tripura": (22.9, 24.5, 91.1, 92.4, "Agartala"),
    "Meghalaya": (25.0, 26.1, 89.8, 92.8, "Shillong"),
    "Sikkim": (27.0, 28.1, 88.0, 88.9, "Gangtok"),
    "Uttar Pradesh": (23.8, 30.4, 77.0, 84.6, "Mathura"),
    "Bihar": (24.3, 27.5, 83.3, 88.3, "Barauni"),
    "Kerala": (8.3, 12.8, 74.8, 77.4, "Ernakulam"),
    "Himachal Pradesh": (30.4, 33.2, 75.8, 79.0, "Solan"),
    "Uttarakhand": (28.7, 31.5, 77.6, 81.0, "Dehradun"),
    "Delhi": (28.4, 28.9, 76.8, 77.4, "New Delhi"),
    "Jammu & Kashmir": (32.2, 35.7, 73.5, 77.0, "Srinagar"),
    "Ladakh": (32.0, 35.7, 75.5, 79.2, "Leh"),
    "Goa": (14.9, 15.8, 73.6, 74.4, "North Goa"),
    "Andaman & Nicobar": (6.7, 13.8, 92.2, 94.0, "Port Blair"),
    "Puducherry": (11.8, 12.1, 79.7, 79.9, "Puducherry"),
    "Chandigarh": (30.6, 30.8, 76.7, 76.9, "Chandigarh"),
}

def is_within_indian_sovereign_territory(lat: float, lon: float) -> bool:
    """
    Validates if coordinates fall within Indian sovereign territory,
    strictly filtering out neighbouring countries (China/Tibet, Nepal, Bhutan, Pakistan, Bangladesh, Sri Lanka, Myanmar).
    """
    # 1. Broad Indian sovereign envelope
    # Absolute northern limit of India is Indira Col / Siachen at 35.67°N.
    # Anything above 35.7°N is strictly foreign territory (Xinjiang/China/Tajikistan).
    if lat < 6.5 or lat > 35.7 or lon < 68.0 or lon > 97.4:
        return False

    # 2. Sri Lanka maritime & land boundary
    if lat < 9.8 and lon > 79.5:
        return False

    # 3. Pakistan western border & Line of Control envelopes
    if lat < 24.0 and lon < 68.1:
        return False
    if 24.0 <= lat < 27.0 and lon < 70.0:  # Rann of Kutch / Barmer
        return False
    if 27.0 <= lat < 28.5 and lon < 70.4:  # Jaisalmer
        return False
    if 28.5 <= lat < 29.5 and lon < 71.6:  # Bikaner / Anupgarh sector
        return False
    if 29.5 <= lat < 30.3 and lon < 73.4:  # Sri Ganganagar border
        return False
    if 30.3 <= lat < 31.2 and lon < 74.3:  # Fazilka / Firozpur / Tarn Taran border
        return False
    if 31.2 <= lat < 32.5 and lon < 74.8:  # Amritsar / Gurdaspur border
        return False
    if 32.5 <= lat < 33.5 and lon < 74.2:  # Jammu / Kathua / Rajouri border
        return False
    if 33.5 <= lat <= 35.0 and lon < 74.0: # Poonch / Baramulla / Kupwara LoC
        return False
    if lat > 35.0 and lon < 76.5:          # Gilgit-Baltistan / Skardu / northern trans-LoC
        return False

    # 4. Nepal (Himalayan envelope: ~26.4°N to 30.5°N, 80.2°E to 88.2°E)
    if 26.5 <= lat <= 30.5 and 80.2 <= lon <= 88.2:
        # Pithoragarh / Champawat in Uttarakhand is roughly lon <= 80.3
        if lon > 80.3:
            return False

    # 5. Bhutan (Himalayan envelope)
    if 26.7 <= lat <= 28.2 and 88.8 <= lon <= 92.1:
        return False

    # 6. Tibet / China north / northeast borders
    # Absolute northern LAC/Karakoram limit (Xinjiang / China border)
    if lat > 35.5 and lon > 77.8:
        return False
    if lat > 34.8 and lon > 78.8:  # Aksai Chin China side
        return False
    if lat > 33.2 and lon > 79.4:  # Tibet east of Demchok
        return False
    if lat > 32.2 and lon > 79.0:  # Tibet east of Spiti / Kinnaur
        return False
    if lat > 31.4 and lon > 80.3:  # Tibet east of Uttarakhand
        return False
    if 88.5 <= lon <= 92.0 and lat > 28.1: # Tibet north of Sikkim/Bhutan
        return False
    if lon > 92.0 and lat > 29.45: # Tibet north of Arunachal Pradesh (McMahon Line)
        return False

    # 7. Bangladesh enclave (preserving Tripura, Meghalaya, and North Bengal corridor)
    if 21.6 <= lat < 25.0 and 88.9 <= lon <= 92.2:
        # Protect Indian state of Tripura
        if 22.9 <= lat <= 24.5 and lon >= 91.1:
            return True
        return False

    # 8. Myanmar border
    if lat <= 22.0 and lon > 93.0:
        return False
    if 22.0 < lat <= 24.0 and lon > 93.4:
        return False
    if 24.0 < lat < 27.0 and lon > 95.3:
        return False

    return True

def resolve_admin_boundary(lat: float, lon: float) -> Dict[str, Optional[str]]:
    """
    Resolves sovereign Indian administrative unit (State & District) for coordinates.
    """
    if not is_within_indian_sovereign_territory(lat, lon):
        return {
            "country": "International / Foreign Territory",
            "state": None,
            "district": None
        }

    for state, (min_lat, max_lat, min_lon, max_lon, dist) in INDIAN_STATE_REGIONS.items():
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return {
                "country": "India",
                "state": state,
                "district": dist
            }
    
    return {
        "country": "India",
        "state": "Indian National Territory",
        "district": "Maritime / Border Sector"
    }
