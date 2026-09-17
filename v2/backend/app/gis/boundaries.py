"""
Indian Sovereign Administrative Boundaries Lookup Service
Resolves (latitude, longitude) coordinates to sovereign State, Union Territory, and District.
Uses pre-indexed geographic bounding regions for all 28 states & 8 UTs with spatial fallback.
"""
from typing import Dict, List, Optional, Tuple

from app.gis.spatial import point_in_geojson_geometry

# Bounding boxes and regional centroids for Indian States & UTs
# Format: {state_name: (min_lat, max_lat, min_lon, max_lon, default_district)}
INDIAN_STATE_REGIONS = {
    "Punjab": (29.5, 32.5, 73.8, 76.9, "Bathinda"),
    "Haryana": (27.6, 30.9, 74.4, 77.6, "Panipat"),
    "Rajasthan": (23.0, 30.2, 69.5, 78.3, "Balotra"),
    "Gujarat": (20.1, 24.7, 68.1, 74.5, "Surat"),
    "Chhattisgarh": (17.8, 24.1, 80.2, 83.4, "Korba"),
    "Odisha": (17.8, 22.6, 82.8, 87.5, "Jajpur"),
    "Jharkhand": (21.9, 25.3, 83.3, 87.9, "Dhanbad"),
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

# ---------------------------------------------------------------------------
# INV-3: Sovereign Territorial Boundary
#
# The specification (Section 2, INV-3) defines the sovereign filter as an
# outer envelope of 68.7 deg E - 97.4 deg E / 8.4 deg N - 37.6 deg N *plus a
# high-fidelity polygon mask*. The envelope alone is a rectangle spanning
# roughly 3,200 km x 3,250 km, so its corners and long edges fall over
# Pakistan, Nepal, Bhutan, Bangladesh, Myanmar, Sri Lanka and the open
# Arabian Sea and Bay of Bengal.
#
# The previous implementation replaced the mask with ~20 hand-written
# rectangles tracing the land borders. That approach admitted 1.9 degrees of
# latitude (6.5-8.4N) and 0.7 degrees of longitude (68.0-68.7E) that the spec
# places outside the envelope, rejected the 35.7-37.6N band the spec places
# inside it, and admitted open ocean, because the fallback returned
# `country: "India"` for anything that survived the boxes.
#
# The mask below is the documented form: envelope gate first, then polygon
# containment through `app.gis.spatial.point_in_geojson_geometry`, so the
# predicate now agrees with the primitive the rest of the platform already
# uses for facility containment (`app/gis/assets.py`).
# ---------------------------------------------------------------------------

SOVEREIGN_ENVELOPE_MIN_LAT = 8.4
SOVEREIGN_ENVELOPE_MAX_LAT = 37.6
SOVEREIGN_ENVELOPE_MIN_LON = 68.7
SOVEREIGN_ENVELOPE_MAX_LON = 97.4

# Simplified [lon, lat] outline of the Indian mainland, traced clockwise from
# the northern LoC and following the de-facto sovereign border. Vertex
# density is highest along the coastline and at the land borders that face the
# envelope corners; the exclusion polygons below carry the fine detail at
# those borders, and the Tripura salient (which the Bangladesh flank cuts off)
# is restored as its own ring.
INDIA_MAINLAND_RING: List[List[float]] = [
    # Northern LoC / Karakoram / Aksai Chin
    [73.9, 34.7], [74.6, 35.0], [75.5, 35.7], [76.9, 35.7], [78.0, 35.6],
    [79.3, 35.4], [79.0, 32.5],
    # Uttarakhand (Tibet border) down to the Kalapani tri-junction, then the
    # Mahakali down to Banbasa -- traced without a northward back-track, which
    # would cut a spurious wedge out of the Pithoragarh strip
    [79.9, 30.4], [80.9, 30.2], [80.5, 29.6], [80.07, 28.98],
    # India-Nepal border east of Banbasa
    [81.1, 28.3], [82.0, 27.9], [83.0, 27.5], [84.0, 27.5], [84.6, 27.15],
    [85.3, 26.9], [86.2, 26.65], [87.0, 26.4], [87.6, 26.35], [88.05, 26.4],
    # Sikkim and the Bhutan flank
    [88.1, 26.9], [88.15, 27.9], [88.9, 27.3], [89.1, 26.6], [89.7, 26.7],
    [91.6, 27.8],
    # Arunachal Pradesh and the McMahon Line
    [92.5, 27.5], [94.0, 27.5], [95.4, 29.0], [96.4, 29.4], [97.4, 28.2],
    [97.0, 27.2], [96.5, 26.0],
    # India-Myanmar border (Nagaland, Manipur, Mizoram)
    [95.2, 26.0], [94.6, 24.0], [93.4, 23.0], [93.2, 22.0], [92.6, 21.5],
    # West flank of the Bangladesh salient (the Tripura ring carries the
    # salient itself; this chord runs through Bangladeshi airspace only)
    [91.9, 23.0], [91.0, 23.3], [89.1, 22.1], [89.0, 21.65], [88.0, 21.55],
    [86.9, 21.5],
    # Eastern coast
    [86.5, 20.3], [85.85, 19.81], [85.3, 19.7], [84.0, 18.4],
    [83.4, 17.7], [80.3, 15.9], [80.35, 13.1], [80.3, 11.5], [79.9, 10.3],
    [79.3, 9.2], [78.35, 8.9], [78.25, 8.75], [77.6, 8.35], [77.55, 8.05],
    # Western coast
    [76.9, 8.45], [76.55, 8.9], [76.2, 9.95], [75.8, 11.25], [74.75, 12.9],
    [74.5, 14.0], [73.8, 15.0], [72.75, 19.0], [72.55, 20.6], [72.9, 21.4],
    [72.3, 21.6],
    # Saurashtra and the Gulf of Kutch
    [70.7, 20.9], [70.0, 21.4], [69.5, 21.6], [68.95, 22.25], [68.7, 23.0],
    [68.7, 23.6],
    # India-Pakistan border (Rann of Kutch north to the LoC)
    [70.0, 24.2], [70.0, 25.0], [70.6, 26.0], [70.0, 27.0], [71.9, 28.0],
    [72.9, 28.5], [73.4, 29.6], [73.4, 30.3], [74.3, 30.9], [74.4, 31.7],
    [74.2, 32.5], [74.0, 33.4], [74.0, 34.3], [73.9, 34.7],
]

# The Tripura salient is Indian territory enclosed on three sides by
# Bangladesh. The mainland ring's Bangladesh flank runs south of it, so the
# salient is carried as its own ring (the Bangladesh exclusion below notches
# around it).
TRIPURA_RING: List[List[float]] = [
    [91.15, 22.9], [91.05, 23.6], [91.2, 24.3], [91.9, 24.35],
    [92.35, 24.3], [92.3, 23.5], [92.3, 22.95], [91.6, 23.0], [91.15, 22.9],
]

# Andaman & Nicobar and Lakshadweep are separate island groups; the mainland
# ring does not reach them. Only the northern Andamans clear the 8.4N floor.
ANDAMAN_NICOBAR_RING: List[List[float]] = [
    [92.5, 13.7], [93.15, 13.6], [93.05, 12.0], [93.0, 10.5], [92.85, 9.2],
    [92.8, 8.4], [92.4, 8.4], [92.2, 9.0], [92.55, 10.5], [92.7, 12.0],
    [92.3, 13.4], [92.5, 13.7],
]

LAKSHADWEEP_RING: List[List[float]] = [
    [71.6, 11.5], [73.2, 11.2], [73.5, 10.5], [72.8, 8.4], [71.9, 8.6],
    [71.6, 10.0], [71.6, 11.5],
]

INDIA_SOVEREIGN_MASK: Dict[str, object] = {
    "type": "MultiPolygon",
    "coordinates": [
        [INDIA_MAINLAND_RING],
        [TRIPURA_RING],
        [ANDAMAN_NICOBAR_RING],
        [LAKSHADWEEP_RING],
    ],
}

# Neighbouring-state footprints, traced along the side that faces India. These
# are the "rectangle corners" the envelope admits but sovereignty rejects; each
# ring is drawn so that its India-facing edge sits on (never inside) Indian
# territory. Containment in any one of them rejects the point outright.
FOREIGN_EXCLUSION_GEOMETRIES: List[Dict[str, object]] = [
    # Pakistan (incl. the Sir Creek / Rann of Kutch and the LoC sector). The
    # north-east edge follows the LoC terminus NJ9842 and the Shaksgam line, so
    # it does not clip the Siachen apex (Indira Col, 35.67N 76.90E).
    {"type": "Polygon", "coordinates": [[
        [68.0, 37.6], [76.4, 37.6], [76.85, 35.5], [74.5, 34.6], [74.0, 33.4],
        [74.3, 32.6], [74.6, 31.6], [74.0, 30.4], [73.5, 29.9], [73.2, 29.2],
        [71.9, 28.0], [70.5, 27.2], [70.0, 25.5], [70.0, 24.2], [68.9, 24.0],
        [68.5, 23.6], [68.0, 23.6], [68.0, 37.6],
    ]]},
    # Nepal (Kalapani tri-junction and the Mahakali in the west, to the
    # Mechi / Sikkim line in the east). The India-facing edge matches
    # INDIA_MAINLAND_RING exactly, so the two gates can never disagree.
    {"type": "Polygon", "coordinates": [[
        [80.9, 30.2], [80.5, 29.6], [80.07, 28.98], [81.1, 28.3],
        [82.0, 27.9], [83.0, 27.5], [84.0, 27.5], [84.6, 27.15], [85.3, 26.9],
        [86.2, 26.65], [87.0, 26.4], [87.6, 26.35], [88.15, 26.4],
        [88.2, 28.2], [80.9, 30.45], [80.9, 30.2],
    ]]},
    # Bhutan (Sikkim's eastern neighbour, between the Teesta and the Manas)
    {"type": "Polygon", "coordinates": [[
        [88.75, 26.6], [89.4, 26.7], [90.5, 26.7], [91.6, 26.8], [92.1, 26.9],
        [92.1, 28.3], [89.0, 28.3], [88.75, 26.6],
    ]]},
    # Bangladesh (the West Bengal notch, the Meghalaya/Assam arc and the
    # Tripura/Mizoram eastern flank). The Tripura salient is notched out so
    # the Indian salient registered above is not swallowed by this ring.
    {"type": "Polygon", "coordinates": [[
        [88.1, 21.6], [89.1, 21.7], [89.1, 22.8], [88.85, 23.2], [88.7, 24.0],
        [88.05, 24.6], [88.3, 25.2], [88.7, 25.3], [88.4, 26.0], [88.6, 26.5],
        [89.0, 26.35], [89.8, 25.3], [89.9, 26.0], [90.0, 25.2],
        [90.5, 25.15], [91.4, 25.2], [92.1, 25.2], [92.35, 25.2], [92.3, 24.4],
        [91.9, 24.35], [91.2, 24.3], [91.05, 23.6],
        [91.15, 22.9], [91.5, 22.3], [92.0, 22.0], [92.3, 22.0], [92.3, 21.4],
        [91.0, 21.5], [90.0, 21.8], [89.05, 21.7], [88.1, 21.6],
    ]]},
    # Myanmar (Chin / Sagaing / Kachin, east of the Patkai and the
    # Manipur-Mizoram border)
    {"type": "Polygon", "coordinates": [[
        [92.6, 21.5], [93.2, 22.0], [93.4, 23.0], [94.6, 24.0], [95.2, 26.0],
        [96.5, 26.0], [97.4, 27.2], [97.4, 16.0], [92.6, 16.0], [92.6, 21.5],
    ]]},
    # Sri Lanka (the Palk Strait and Gulf of Mannar; its northern tip reaches
    # 9.83N, inside the envelope's 8.4N floor)
    {"type": "Polygon", "coordinates": [[
        [79.6, 9.9], [80.4, 9.9], [81.3, 9.2], [81.9, 7.0], [81.9, 5.9],
        [79.6, 5.9], [79.6, 9.9],
    ]]},
]


def is_within_indian_sovereign_territory(lat: float, lon: float) -> bool:
    """
    Validates if coordinates fall within Indian sovereign territory.

    Invariant INV-3: the sovereign terrestrial boundary and airspace is the
    68.7 deg E - 97.4 deg E / 8.4 deg N - 37.6 deg N envelope *intersected
    with* a polygon mask. Points outside either gate -- open ocean, or the
    corners of the envelope that lie over Pakistan, Nepal, Bhutan,
    Bangladesh, Myanmar or Sri Lanka -- are not sovereign Indian territory.

    NOTE: callers rely on the boolean return only. `orchestration/pipeline.py`
    uses it to build the console feed and the `active_obs` set, so widening or
    narrowing this predicate directly changes which incidents are displayed.
    """
    # 1. Outer sovereign envelope (INV-3). The former gate (6.5N-35.7N /
    #    68.0E-97.4E) admitted 1.9 degrees of latitude and 0.7 degrees of
    #    longitude the spec places outside the envelope, and rejected the
    #    35.7-37.6N band the spec places inside it.
    if lat < SOVEREIGN_ENVELOPE_MIN_LAT or lat > SOVEREIGN_ENVELOPE_MAX_LAT:
        return False
    if lon < SOVEREIGN_ENVELOPE_MIN_LON or lon > SOVEREIGN_ENVELOPE_MAX_LON:
        return False

    # 2. Polygon mask. This is the gate that removes the envelope's rectangle
    #    corners and every stretch of open sea inside it.
    if not point_in_geojson_geometry(lat, lon, INDIA_SOVEREIGN_MASK):
        return False

    # 3. Neighbouring-state exclusion. Belt-and-braces against the simplified
    #    mainland ring: each footprint is drawn along the side that faces
    #    India, never past it, so a point inside one cannot be Indian
    #    territory.
    for foreign in FOREIGN_EXCLUSION_GEOMETRIES:
        if point_in_geojson_geometry(lat, lon, foreign):
            return False

    return True

# Fine-grained regional/district bounding boxes for high-priority industrial & geographic subregions
# Format: (min_lat, max_lat, min_lon, max_lon, state, district)
INDIAN_DISTRICT_SUBREGIONS = [
    # Gujarat subregions
    (21.9, 23.0, 68.8, 70.8, "Gujarat", "Jamnagar"),
    (22.8, 24.7, 68.1, 71.6, "Gujarat", "Kutch"),
    (21.7, 22.8, 70.5, 71.5, "Gujarat", "Rajkot"),
    (22.7, 23.6, 72.1, 73.2, "Gujarat", "Ahmedabad"),
    (23.0, 23.6, 72.5, 73.0, "Gujarat", "Gandhinagar"),
    (23.4, 24.2, 71.2, 72.2, "Gujarat", "Patan"),
    (23.2, 23.9, 72.0, 72.7, "Gujarat", "Mehsana"),
    (23.8, 24.7, 71.5, 73.0, "Gujarat", "Banaskantha"),
    (23.4, 24.3, 72.8, 73.5, "Gujarat", "Sabarkantha"),
    (22.5, 23.2, 71.3, 72.3, "Gujarat", "Surendranagar"),
    (22.3, 23.0, 72.6, 73.4, "Gujarat", "Anand"),
    (22.6, 23.1, 72.6, 73.3, "Gujarat", "Kheda"),
    (21.9, 22.7, 73.0, 73.8, "Gujarat", "Vadodara"),
    (21.4, 22.0, 72.6, 73.3, "Gujarat", "Bharuch"),
    (20.8, 21.5, 72.6, 73.3, "Gujarat", "Surat"),
    (20.3, 21.0, 72.7, 73.4, "Gujarat", "Valsad"),
    (21.2, 22.1, 71.5, 72.3, "Gujarat", "Bhavnagar"),
    # Maharashtra subregions
    (18.8, 19.4, 72.7, 73.2, "Maharashtra", "Mumbai"),
    (18.2, 19.0, 73.6, 74.2, "Maharashtra", "Pune"),
    (20.9, 21.4, 78.9, 79.3, "Maharashtra", "Nagpur"),
    (19.8, 20.3, 79.1, 79.5, "Maharashtra", "Chandrapur"),
    # Odisha subregions
    (20.7, 21.2, 85.8, 86.4, "Odisha", "Jajpur"),
    (20.2, 20.5, 86.5, 87.0, "Odisha", "Jagatsinghpur"),
    (21.8, 22.4, 84.7, 85.3, "Odisha", "Sundargarh"),
    # Jharkhand subregions
    (23.6, 24.0, 86.1, 86.7, "Jharkhand", "Dhanbad"),
    (23.5, 24.0, 85.9, 86.5, "Jharkhand", "Bokaro"),
    (23.2, 23.6, 85.1, 85.5, "Jharkhand", "Ranchi"),
    (22.6, 23.0, 86.0, 86.4, "Jharkhand", "East Singhbhum"),
]

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

    # 1. Fine-grained sub-regional district match
    for min_lat, max_lat, min_lon, max_lon, st, dist in INDIAN_DISTRICT_SUBREGIONS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return {
                "country": "India",
                "state": st,
                "district": dist
            }

    # 2. Broad state-level bounding box match
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
