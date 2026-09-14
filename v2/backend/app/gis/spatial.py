"""
FIREX v2 Core Spatial Mathematics & Geodetic Algorithms
Provides:
1. Haversine great-circle distance (meters & kilometers)
2. Ray-casting Point-in-Polygon (PIP) testing for 2D GeoJSON coordinates
3. Bounding box expansion and intersection
"""
import math
from typing import List, Tuple, Dict, Any, Union

EARTH_RADIUS_METERS = 6371000.0

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes exact spherical great-circle distance between two points in meters.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes distance in kilometers.
    """
    return haversine_distance_meters(lat1, lon1, lat2, lon2) / 1000.0

def point_in_polygon(lat: float, lon: float, polygon_coords: List[List[float]]) -> bool:
    """
    Ray casting algorithm for 2D Point-in-Polygon detection.
    polygon_coords is a list of [lon, lat] pairs (GeoJSON standard) or [lat, lon].
    We assume GeoJSON standard [longitude, latitude] for rings.
    """
    if not polygon_coords or len(polygon_coords) < 3:
        return False

    # Check if coords are [lon, lat] or [lat, lon]
    # Standard GeoJSON is [x, y] -> [lon, lat]
    x, y = lon, lat
    inside = False
    n = len(polygon_coords)

    p1x, p1y = polygon_coords[0][0], polygon_coords[0][1]
    for i in range(1, n + 1):
        p2x, p2y = polygon_coords[i % n][0], polygon_coords[i % n][1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    xinters = x  # default: treat as intersection when edge is horizontal
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

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
