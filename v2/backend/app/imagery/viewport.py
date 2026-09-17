"""
FIREX v2 Dynamic & Custom Viewport Engine
Implements Section 14 / Stage 5 Dynamic Viewport and Custom Radius logic.
Determines optimal ground radius, tile zoom level, and bounding box for optical satellite imagery.
"""
import math
from typing import Optional, List
from pydantic import BaseModel

# F-104: bounds on the *requested* custom radius, in metres -- they say what a caller may ask
# for, not what the render will report. See calculate_incident_viewport for why the declared
# radius can sit one zoom step outside them.
MIN_CUSTOM_RADIUS_M = 250.0
MAX_CUSTOM_RADIUS_M = 5000.0

class ViewportSpec(BaseModel):
    center_lat: float
    center_lon: float
    radius_meters: float  # real ground half-width of the fetched crop (F-009), never the nominal request
    requested_radius_meters: Optional[float] = None  # F-104: the custom radius asked for, clamped; None if none was asked
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

def crop_coverage_radius_meters(lat: float, zoom: int, crop_size_px: int = 640) -> float:
    """
    Ground half-width, in meters, that a crop_size_px crop really spans at this latitude and zoom.
    F-009: the fetched scene is crop_size_px wide on a square tile grid, so its half-width is
    (crop_size_px / 2) * meters_per_pixel -- not the radius the caller asked for.
    """
    return (crop_size_px / 2.0) * get_meters_per_pixel(lat, zoom)

def determine_zoom_for_radius(radius_meters: float, lat: float, crop_size_px: int = 640) -> int:
    """
    Chooses the zoom level whose 640px crop ground coverage comes closest to the requested
    radius (in ground meters, so larger zooms are finer and cover less):
    - ~500m radius  -> Zoom 17 (Indian latitudes; coverage shrinks with cos(lat))
    - ~750m radius  -> Zoom 16
    - ~1000m radius -> Zoom 16
    - ~1200m+ radius -> Zoom 15
    F-009: the old table was latitude-blind and implied ~3.125 m/px at Zoom 16, which Web
    Mercator reaches at no latitude at all (its own "2 * radius inside 640px" criterion
    would need cos(lat) > 1). Ground resolution scales with cos(lat), so the zoom has to be
    chosen from the resolution at the incident's own latitude. Because coverage moves in 2x
    steps, the requested radius can only be met to within one zoom step -- which is why the
    caller declares the coverage it actually got instead of the request.
    """
    return min(
        range(12, 20),
        key=lambda z: abs(crop_coverage_radius_meters(lat, z, crop_size_px) - radius_meters)
    )

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
       - large cluster (>8 points/zone)  -> ~1200-2000 m (zoom 15)
       Formula: max(min_radius, cluster_radius + buffer)

    Those figures are request targets. The radius this function returns is the ground
    half-width the 640px crop really covers at the chosen zoom (F-009) -- i.e. the request
    snapped to the satellite tile grid (F-104). A zoom level quantises the ground radius: the
    same 640px crop covers exactly twice as much ground per zoom step down, so the radii a
    crop can have form a geometric grid of ratio 2 and the zoom chooser picks the grid point
    nearest the request. The declared radius therefore tracks the request to within one grid
    step: it lies within a factor 2/3..4/3 of the clamped request and is NOT bounded by it in
    either direction. It can be larger -- a 5000 m request derives 5668.7 m at zoom 13 -- and
    smaller -- a 250 m request derives 177.1 m at zoom 18 (lat 22.025). The old docstring's
    claim that it is "never larger" than the request was simply false; the claim in the other
    direction is the dangerous one, because a declared radius below the range actually
    rendered understates the scene an operator is told was searched, and it would also stop
    the reticle's 40%/80% rings from describing the frame they are drawn in. So the declared
    value is always the crop's real coverage, never a clamp of it.

    The custom-radius clamp (MIN_CUSTOM_RADIUS_M..MAX_CUSTOM_RADIUS_M) bounds the REQUEST:
    it is what a caller may ask for, and the declared radius may land one zoom step outside it
    in either direction for the same quantisation reason. The request that was honoured after
    clamping is reported back as ViewportSpec.requested_radius_meters (None when no custom
    radius was asked for), so request, clamp and declared coverage can be compared directly.
    """
    is_custom = False
    tier = "dynamic"

    if custom_radius_meters is not None and custom_radius_meters > 0.0:
        # Clamp the request between 250m and 5000m (F-104). The clamp applies here, to the
        # request, and deliberately not to radius_m below: clamping the declared value up to
        # the floor would overstate ground the crop does not hold (and push the outer reticle
        # ring outside the frame), while clamping it down to the ceiling would understate a
        # render that reached further.
        requested_m = max(MIN_CUSTOM_RADIUS_M, min(MAX_CUSTOM_RADIUS_M, float(custom_radius_meters)))
        zoom = zoom_level if (zoom_level and 12 <= zoom_level <= 19) else determine_zoom_for_radius(requested_m, lat, crop_size_px)
        is_custom = True
    else:
        # Dynamic cluster tiering
        if observation_count <= 1:
            requested_m = 500.0
            tier = "isolated event"
        elif observation_count <= 3:
            requested_m = 750.0
            tier = "small cluster"
        elif observation_count <= 8:
            requested_m = 1000.0
            tier = "medium cluster"
        else:
            # Scale dynamically with cluster radius + 500m buffer, capped at 2000m
            requested_m = min(2000.0, max(1200.0, cluster_radius_meters + 500.0))
            tier = "large cluster"

        zoom = determine_zoom_for_radius(requested_m, lat, crop_size_px)

        # Override zoom if explicitly provided
        if zoom_level and 12 <= zoom_level <= 19:
            zoom = zoom_level

    m_per_px = get_meters_per_pixel(lat, zoom)

    # F-009: the declared radius is the ground half-width the 640px crop really covers, not the
    # nominal request. The old bbox (radius_m / 111320) described up to 41% more ground than the
    # fetched pixels held -- 1000m declared versus 708m of scene at lat 22 / zoom 16 -- and that
    # figure reached the vision prompt verbatim. Shrinking the declared radius rather than
    # dropping to a coarser zoom is the honest option: coverage moves in 2x steps, so no zoom
    # makes coverage land on an arbitrary request (a 1000m request is 708m at zoom 16 or 1417m at
    # zoom 15), and the coarser crop would additionally discard resolution. Declaring the coverage
    # also keeps the reticle's 40%/80% rings at 40%/80% of the declared viewport radius.
    radius_m = crop_coverage_radius_meters(lat, zoom, crop_size_px)

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

    scale_label = f"custom ({radius_m:.0f}m)" if is_custom else f"{tier} (~{radius_m:.0f}m)"

    return ViewportSpec(
        center_lat=round(lat, 6),
        center_lon=round(lon, 6),
        radius_meters=round(radius_m, 1),
        # F-104: the request, after the clamp, is reported next to the coverage it derived --
        # None distinguishes "no custom radius asked for" from any request that was made.
        requested_radius_meters=round(requested_m, 1) if is_custom else None,
        zoom_level=zoom,
        bounding_box=bbox,
        meters_per_pixel=round(m_per_px, 3),
        crop_size_px=crop_size_px,
        is_custom_radius=is_custom,
        scale_label=scale_label
    )
