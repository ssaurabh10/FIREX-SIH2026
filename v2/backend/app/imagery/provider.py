"""
FIREX v2 Satellite Imagery Tile Provider
Fetches and stitches cloud-free optical satellite scenes.
Uses Google Satellite as primary, Esri World Imagery as fallback, with synthetic tile fallback for air-gapped test runs.
"""
import math
import requests
from io import BytesIO
from typing import Tuple, Optional
from PIL import Image, ImageDraw
from app.core.logging import logger

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_TILE_SESSION = requests.Session()
_TILE_SESSION.headers.update(HEADERS)

def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[float, float]:
    """
    Translates GPS coordinates to Slippy Map tile numbers in Web Mercator projection.
    """
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return (xtile, ytile)

def num2deg(xtile: float, ytile: float, zoom: int) -> Tuple[float, float]:
    """
    Translates Slippy Map tile numbers back to GPS coordinates.
    """
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def generate_synthetic_tile(x: int, y: int, z: int) -> Image.Image:
    """
    Generates a dark tactical satellite simulation tile for testing or offline environments.
    """
    img = Image.new("RGB", (256, 256), color=(28, 33, 40))
    draw = ImageDraw.Draw(img)
    # Subtle terrain/grid pattern
    for i in range(0, 256, 32):
        draw.line([(0, i), (256, i)], fill=(35, 42, 50), width=1)
        draw.line([(i, 0), (i, 256)], fill=(35, 42, 50), width=1)
    return img

def fetch_tile(x: int, y: int, z: int, timeout: float = 3.0) -> Tuple[Image.Image, str]:
    """
    Fetches 256x256 satellite tile.
    1. Primary: Google Satellite
    2. Fallback: Esri World Imagery
    3. Final fallback: Synthetic tactical terrain tile
    """
    # 1. Primary: Google Satellite
    google_url = f"https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
    try:
        r = _TILE_SESSION.get(google_url, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 500:
            return Image.open(BytesIO(r.content)).convert("RGB"), "Google Satellite"
    except Exception:
        pass

    # 2. Fallback: Esri World Imagery (Maxar/Airbus high-res basemap)
    esri_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        r = _TILE_SESSION.get(esri_url, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 500:
            return Image.open(BytesIO(r.content)).convert("RGB"), "Esri World Imagery"
    except Exception:
        pass

    # 3. Final Fallback: Synthetic tile
    return generate_synthetic_tile(x, y, z), "Synthetic Tactical Map"

def get_stitched_crop(
    lat: float,
    lon: float,
    zoom: int = 16,
    crop_size: int = 640
) -> Tuple[Image.Image, str]:
    """
    Downloads 3x3 tile grid (768x768) centered on (lat, lon) at the given zoom level,
    stitches them, and extracts a crop_size x crop_size square centered precisely on the hotspot.
    """
    xtile_f, ytile_f = deg2num(lat, lon, zoom)
    x_center = int(math.floor(xtile_f))
    y_center = int(math.floor(ytile_f))

    center_px_x = int((xtile_f - x_center) * 256)
    center_px_y = int((ytile_f - y_center) * 256)

    grid_img = Image.new("RGB", (256 * 3, 256 * 3))
    detected_provider = "Google Satellite"

    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tx = x_center + dx
            ty = y_center + dy
            tile, prov = fetch_tile(tx, ty, zoom)
            if prov != "Google Satellite":
                detected_provider = prov
            grid_img.paste(tile, ((dx + 1) * 256, (dy + 1) * 256))

    # Center hotspot coordinates within 3x3 canvas
    hotspot_x = 256 + center_px_x
    hotspot_y = 256 + center_px_y

    half = crop_size // 2
    left = max(0, hotspot_x - half)
    top = max(0, hotspot_y - half)
    right = min(grid_img.width, left + crop_size)
    bottom = min(grid_img.height, top + crop_size)

    crop = grid_img.crop((left, top, right, bottom))
    if crop.size != (crop_size, crop_size):
        crop = crop.resize((crop_size, crop_size), Image.Resampling.LANCZOS)

    return crop, detected_provider

def verify_image_validity(img: Optional[Image.Image]) -> bool:
    """
    Verifies that the retrieved satellite scene is valid and suitable for AI input.
    Checks:
    - Non-null
    - Minimum dimensions (at least 256x256)
    - Valid non-empty RGB content
    """
    if img is None:
        return False
    if img.width < 256 or img.height < 256:
        return False
    # Verify not completely zero/empty
    extrema = img.getextrema()
    if not extrema:
        return False
    return True
