"""
FIREX v2 Core Spatial Mathematics & Geodetic Algorithms
Provides:
1. Haversine great-circle distance (meters & kilometers)
2. Ray-casting Point-in-Polygon (PIP) testing for 2D GeoJSON coordinates
3. Bounding box expansion and intersection
4. Climatology grid quantisation (the 0.02 degree cell convention)
"""
import math
from typing import List, Tuple, Dict, Any, Union

EARTH_RADIUS_METERS = 6371000.0

# The thermal-climatology grid resolution (Section 4.2 / Section 9's
# `thermal_climatology` entry describe a 0.02 degree, ~2.2 km cell). The
# generator and the live lookup must quantise identically or every lookup
# misses -- and they do not. `climatology_cell` below is the 0.02 convention
# the generator writes; `behavior/baseline.py`'s `generate_spatial_key` rounds
# to 0.01 instead, so a live lookup resolves a key on a lattice only 24.9% of
# the stored rows sit on (measured: 82,581 of 331,418). An earlier version of
# this comment asserted "both go through `climatology_cell`"; neither the
# reader nor that identity exists. Reconciling the two needs a decision on
# which lattice wins plus a rebuild of the table, so the split is stated here
# rather than papered over.
CLIMATOLOGY_GRID_DEGREES = 0.02

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes exact spherical great-circle distance between two points in meters.

    Section 4.1 mandates d = 2 * R * arcsin(min(1.0, sqrt(a))). The clamp is
    load-bearing, not cosmetic: for near-antipodal inputs the floating-point
    value of `a` can exceed 1.0 by an ulp (e.g. (45,0) to (-45,180) yields
    a = 1.0000000000000002), and `math.sqrt(1.0 - a)` then raises
    ValueError('expected a nonnegative input') rather than returning a
    distance. `max(0.0, ...)` on the radicand closes the symmetric case where
    rounding pushes `a` slightly below zero.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    return EARTH_RADIUS_METERS * 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes distance in kilometers.
    """
    return haversine_distance_meters(lat1, lon1, lat2, lon2) / 1000.0

def point_in_polygon(lat: float, lon: float, polygon_coords: List[List[float]]) -> bool:
    """
    Ray casting algorithm for 2D Point-in-Polygon detection.

    Section 4.1 specifies the canonical PNPOLY test verbatim:

        inside = False
        for (i, j):  # j == i-1
            if (phi_i > phi_p) != (phi_j > phi_p):
                lam_intersect = (lam_j - lam_i) * (phi_p - phi_i) / (phi_j - phi_i) + lam_i
                if lam_p < lam_intersect:
                    inside = not inside

    Two deviations used to sit here and both changed containment answers on the
    boundary, which is not a cosmetic region: `assets.py` feeds this result into
    `is_inside_facility`, which gates the CRITICAL industrial-catastrophe
    override in `severity/scoring.py`.

    * Latitude band. The code tested `y > min(p1y, p2y)` and
      `y <= max(p1y, p2y)` -- the half-open convention (min, max]. The spec's
      `(phi_i > phi_p) != (phi_j > phi_p)` is [min, max). A point on the low
      edge of a square tested outside; the same point on the high edge tested
      inside.
    * Longitude crossing. The code tested `x <= xinters` with an extra
      `p1x == p2x` short-circuit, so a point on a left vertical edge or on the
      hypotenuse tested outside. The spec's strict `lam_p < lam_intersect`
      needs no vertical-edge special case: for a vertical edge `phi_j == phi_i`
      the latitude test `(phi_i > phi_p) != (phi_j > phi_p)` is False, so the
      division is never evaluated.

    `polygon_coords` is a list of [lon, lat] pairs (GeoJSON order).
    """
    if not polygon_coords or len(polygon_coords) < 3:
        return False

    x, y = lon, lat
    inside = False
    n = len(polygon_coords)

    j = n - 1
    for i in range(n):
        yi, xi = polygon_coords[i][1], polygon_coords[i][0]
        yj, xj = polygon_coords[j][1], polygon_coords[j][0]
        if (yi > y) != (yj > y):
            xinters = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xinters:
                inside = not inside
        j = i

    return inside

def point_in_geojson_geometry(lat: float, lon: float, geometry: Dict[str, Any]) -> bool:
    """
    Evaluates point containment inside GeoJSON Polygon or MultiPolygon.
    """
    if not geometry:
        return False
    
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Polygon":
        # First ring is the exterior boundary
        if coords and len(coords) > 0:
            return point_in_polygon(lat, lon, coords[0])
    elif geom_type == "MultiPolygon":
        for poly in coords:
            if poly and len(poly) > 0 and point_in_polygon(lat, lon, poly[0]):
                return True
    return False

def climatology_cell(lat: float, lon: float) -> Tuple[float, float, str]:
    """Snap a coordinate to its thermal-climatology grid cell.

    Returns ``(cell_lat, cell_lon, spatial_key)``.

    Section 4.2 and the Section 9 `thermal_climatology` definition both describe
    a 0.02 degree (~2.2 km) grid, and the documented key form is
    ``GRID_21.15_72.68``. The generator used ``ROUND(latitude, 2)``, which is a
    0.01 degree grid -- half the documented cell size, so adjacent 2.2 km cells
    were split in two and each half carried roughly half the active-day count.
    That matters because INV-4's routine-flare rule is a threshold on
    ``active_days``: halving the cell population pushes genuinely continuous
    sites below the cutoff.

    Both the offline generator and the live baseline lookup must snap
    identically; this function is the single definition of that convention.
    Multiples of 0.02 always have at most two decimals, so the documented
    ``:.2f`` key format is preserved.
    """
    cell_lat = round(round(lat / CLIMATOLOGY_GRID_DEGREES) * CLIMATOLOGY_GRID_DEGREES, 2)
    cell_lon = round(round(lon / CLIMATOLOGY_GRID_DEGREES) * CLIMATOLOGY_GRID_DEGREES, 2)
    return cell_lat, cell_lon, f"GRID_{cell_lat:.2f}_{cell_lon:.2f}"


def generate_bounding_circle_polygon(center_lat: float, center_lon: float, radius_meters: float, num_points: int = 32) -> List[List[float]]:
    """
    Generates a regular polygon approximation of a circle with radius_meters around center.
    Returns GeoJSON format: [[lon, lat], [lon, lat], ...]
    """
    coords = []
    lat_rad = math.radians(center_lat)
    
    # 1 deg lat in meters
    meters_per_deg_lat = 111132.954
    # 1 deg lon in meters
    meters_per_deg_lon = 111412.84 * math.cos(lat_rad)

    d_lat = radius_meters / meters_per_deg_lat
    d_lon = radius_meters / max(100.0, meters_per_deg_lon)

    for i in range(num_points):
        theta = 2.0 * math.pi * i / num_points
        dx = d_lon * math.cos(theta)
        dy = d_lat * math.sin(theta)
        coords.append([round(center_lon + dx, 6), round(center_lat + dy, 6)])

    # Close the ring
    coords.append(coords[0])
    return coords
