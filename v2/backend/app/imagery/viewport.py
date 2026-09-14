"""
FIREX v2 Dynamic & Custom Viewport Engine
Implements Section 14 / Stage 5 Dynamic Viewport and Custom Radius logic.
Determines optimal ground radius, tile zoom level, and bounding box for optical satellite imagery.
"""
import math
from typing import Dict, Any, Optional, List
from pydantic import BaseModel

class ViewportSpec(BaseModel):
    center_lat: float
    center_lon: float
    radius_meters: float
    zoom_level: int
    bounding_box: List[float]  # [min_lat, min_lon, max_lat, max_lon]
    meters_per_pixel: float
    crop_size_px: int = 640
    is_custom_radius: bool = False
    scale_label: str = "medium cluster"

def get_meters_per_pixel(lat: float, zoom: int) -> float:
    """
    Standard Web Mercator ground resolution in meters per pixel.
    Ground resolution = 156543.03392 * cos(lat) / (2 ^ zoom)
    """
    lat_rad = math.radians(lat)
    return 156543.03392 * math.cos(lat_rad) / (2.0 ** zoom)

def determine_zoom_for_radius(radius_meters: float) -> int:
    """
    Chooses zoom level so that 2 * radius fits comfortably inside a 640px crop:
    - radius <= 500m  -> Zoom 17 (~300m radius visible)
    - radius <= 1000m -> Zoom 16 (~600m radius visible)
    - radius <= 2000m -> Zoom 15 (~1200m radius visible)
    - radius > 2000m  -> Zoom 14 (~2400m radius visible)
    """
    return 17 if radius_meters <= 500.0 else 16 if radius_meters <= 1000.0 else 15 if radius_meters <= 2000.0 else 14

def calculate_incident_viewport(
    lat: float,
    lon: float,
    observation_count: int = 1,
    cluster_radius_meters: float = 0.0,
    custom_radius_meters: Optional[float] = None,
    zoom_level: Optional[int] = None,
    crop_size_px: int = 640
) -> ViewportSpec:
    """
    Calculates optical satellite viewport.
    Supports:
    1. Custom radius / zoom override if provided.
    2. Dynamic cluster-based scaling per Blueprint Stage 5:
       - isolated event (1 point)        -> ~500 m  (zoom 17)
       - small cluster (2-3 points)      -> ~750 m  (zoom 16)
       - medium cluster (4-8 points)     -> ~1000 m (zoom 16)
       - large cluster (>8 points/zone)  -> ~1500-2000 m (zoom 15)
       Formula: max(min_radius, cluster_radius + buffer)
    """
    is_custom = False
    scale_label = "dynamic"

    if custom_radius_meters is not None and custom_radius_meters > 0.0:
        # Clamp custom radius between 250m and 5000m
        radius_m = max(250.0, min(5000.0, float(custom_radius_meters)))
        zoom = zoom_level if (zoom_level and 12 <= zoom_level <= 19) else determine_zoom_for_radius(radius_m)
        is_custom = True
        scale_label = f"custom ({radius_m:.0f}m)"
    else:
        # Dynamic cluster tiering
        if observation_count <= 1:
            radius_m = 500.0
            zoom = 17
            scale_label = "isolated event (~500m)"
        elif observation_count <= 3:
            radius_m = 750.0
            zoom = 16
            scale_label = "small cluster (~750m)"
        elif observation_count <= 8:
            radius_m = 1000.0
            zoom = 16
            scale_label = "medium cluster (~1km)"
        else:
            # Scale dynamically with cluster radius + 500m buffer, capped at 2000m
            radius_m = min(2000.0, max(1200.0, cluster_radius_meters + 500.0))
            zoom = 15
            scale_label = "large cluster (~1.5-2km)"

        # Override zoom if explicitly provided
        if zoom_level and 12 <= zoom_level <= 19:
            zoom = zoom_level

    m_per_px = get_meters_per_pixel(lat, zoom)

    # Compute bounding box [min_lat, min_lon, max_lat, max_lon]
    # 1 deg lat ~ 111,320 meters
    # 1 deg lon ~ 111,320 * cos(lat) meters
    lat_delta = radius_m / 111320.0
    lon_delta = radius_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))

    bbox = [
        round(lat - lat_delta, 6),
        round(lon - lon_delta, 6),
        round(lat + lat_delta, 6),
        round(lon + lon_delta, 6)
    ]

    return ViewportSpec(
        center_lat=round(lat, 6),
        center_lon=round(lon, 6),
        radius_meters=round(radius_m, 1),
        zoom_level=zoom,
        bounding_box=bbox,
        meters_per_pixel=round(m_per_px, 3),
        crop_size_px=crop_size_px,
        is_custom_radius=is_custom,
        scale_label=scale_label
    )
