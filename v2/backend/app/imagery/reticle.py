"""
FIREX v2 Tactical Thermal Hotspot Reticle Overlay
Draws professional target crosshairs, concentric range rings, scale bar, and telemetry HUD on optical crops.
"""
import math
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

def draw_tactical_reticle(
    img: Image.Image,
    lat: float,
    lon: float,
    incident_id: str,
    frp_mw: float,
    radius_meters: float,
    provider: str = "Google Satellite",
    meters_per_pixel: float = 1.2
) -> Image.Image:
    """
    Renders an intelligence target reticle on the satellite scene:
    - Optical hotspot center crosshair
    - Range rings calibrated to physical meters
    - Telemetry HUD banner (Incident ID, Coordinates, FRP, Provider)
    - Tactical scale bar & North indicator
    """
    annotated = img.copy().convert("RGBA")
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = annotated.size
    cx, cy = w // 2, h // 2

    # Load default font
    font = ImageFont.load_default()

    # Reticle Colors
    RETICLE_RED = (255, 50, 50, 230)
    RETICLE_AMBER = (255, 170, 0, 180)
    RETICLE_DIM = (255, 255, 255, 90)
    TEXT_WHITE = (255, 255, 255, 240)
    TEXT_CYAN = (0, 230, 255, 240)
    BG_DARK = (15, 20, 28, 200)

    # 1. Concentric Range Rings (40% and 80% radius)
    if meters_per_pixel > 0:
        for factor, color in [(0.4, RETICLE_AMBER), (0.8, RETICLE_DIM)]:
            r_m = radius_meters * factor
            r_px = int(r_m / meters_per_pixel)
            if 15 < r_px < min(w, h) // 2 - 10:
                draw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px], outline=color, width=1)
                draw.text((cx + r_px + 4, cy - 6), f"{int(r_m)}m", fill=color, font=font)

    # 2. Precision Crosshairs with gap at center
    gap = 12
    length = 40
    # Horizontal
    draw.line([(cx - length, cy), (cx - gap, cy)], fill=RETICLE_RED, width=2)
    draw.line([(cx + gap, cy), (cx + length, cy)], fill=RETICLE_RED, width=2)
    # Vertical
    draw.line([(cx, cy - length), (cx, cy - gap)], fill=RETICLE_RED, width=2)
    draw.line([(cx, cy + gap), (cx, cy + length)], fill=RETICLE_RED, width=2)
    # Center dot
    draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=RETICLE_RED)

    # 3. Top Telemetry Banner
    banner_h = 32
    draw.rectangle([0, 0, w, banner_h], fill=BG_DARK)
    draw.line([(0, banner_h), (w, banner_h)], fill=(0, 230, 255, 120), width=1)

    id_str = f"TARGET: {incident_id[:16]}"
    coord_str = f"LAT: {lat:.4f}° | LON: {lon:.4f}°"
    frp_str = f"FRP: {frp_mw:.1f} MW"

    draw.text((10, 8), id_str, fill=TEXT_CYAN, font=font)
    draw.text((w // 2 - 70, 8), coord_str, fill=TEXT_WHITE, font=font)
    draw.text((w - 110, 8), frp_str, fill=RETICLE_RED, font=font)

    # 4. Bottom Scale Bar & North Indicator
    bottom_h = 24
    draw.rectangle([0, h - bottom_h, w, h], fill=BG_DARK)
    draw.line([(0, h - bottom_h), (w, h - bottom_h)], fill=(255, 255, 255, 40), width=1)

    # Scale bar in meters
    scale_bar_m = 200.0 if radius_meters <= 800 else 500.0
    if meters_per_pixel > 0:
        scale_px = int(scale_bar_m / meters_per_pixel)
        if scale_px < w // 3:
            sx = 14
            sy = h - 12
            draw.line([(sx, sy), (sx + scale_px, sy)], fill=TEXT_WHITE, width=3)
            draw.line([(sx, sy - 4), (sx, sy + 4)], fill=TEXT_WHITE, width=2)
            draw.line([(sx + scale_px, sy - 4), (sx + scale_px, sy + 4)], fill=TEXT_WHITE, width=2)
            draw.text((sx + scale_px + 8, sy - 6), f"{int(scale_bar_m)} m", fill=TEXT_WHITE, font=font)

    # Provider & North
    prov_str = f"SRC: {provider} | N ↑"
    draw.text((w - 180, h - 18), prov_str, fill=(180, 195, 210, 220), font=font)

    # Composite overlay onto base image
    final_img = Image.alpha_composite(annotated, overlay).convert("RGB")
    return final_img
