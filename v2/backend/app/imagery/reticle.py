"""
FIREX v2 Tactical Thermal Hotspot Reticle Overlay
Draws professional target crosshairs, concentric range rings, scale bar, and telemetry HUD on optical crops.
"""
import math
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from app.core.logging import logger

# Spec Section 7: physical meter circles at 40% and 80% of the viewport radius.
RING_FACTORS = (0.4, 0.8)

# Round metric distances the scale bar is allowed to show, longest first.
SCALE_BAR_LADDER_M = (2000.0, 1000.0, 500.0, 250.0, 200.0, 100.0, 50.0, 25.0, 10.0)

# Reticle Colors
RETICLE_RED = (255, 50, 50, 230)
RETICLE_AMBER = (255, 170, 0, 180)
RETICLE_DIM = (255, 255, 255, 90)
TEXT_WHITE = (255, 255, 255, 240)
TEXT_CYAN = (0, 230, 255, 240)
BG_DARK = (15, 20, 28, 200)

SCALE_BAR_X = 14
SCALE_BAR_LABEL_PX = 48  # the widest label at the default 6px font, plus the 8px gap

def plan_reticle_geometry(
    width: int,
    height: int,
    radius_meters: float,
    meters_per_pixel: float
) -> dict:
    """
    Computes the reticle's physical geometry on a width x height frame without touching pixels,
    so the drawing code, the tests and any log/metadata trace agree on what the frame will show.
    Returns the rings that will be drawn (with their true ground distance in meters), the rings
    that cannot be drawn and why, and the scale bar (or None with a reason).
    """
    frame_radius_px = min(width, height) // 2
    rings = []
    skipped_rings = []

    if meters_per_pixel > 0:
        # F-008: ring radii come from the frame the reticle is drawing into. The declared
        # radius_meters is only the crop's own ground coverage (viewport.py F-009 fix), so a ring
        # at factor * frame_radius_px is exactly factor * radius_meters of ground -- the rings
        # scale with the image instead of falling outside it. The old form
        # (int(radius_meters * factor / meters_per_pixel) guarded by `min(w,h)//2 - 10`) put the
        # 0.8 ring at 361px on a 640px crop, past the 310px guard, so it vanished with no trace.
        for factor in RING_FACTORS:
            r_px = int(round(factor * frame_radius_px))
            # A ring can only fail on a frame too small to hold it; that must be visible,
            # never a silent absence.
            if r_px < 4 or r_px > frame_radius_px:
                skipped_rings.append({"factor": factor, "radius_px": r_px, "reason": "does not fit the frame"})
                continue
            rings.append({
                "factor": factor,
                "radius_px": r_px,
                "ground_meters": r_px * meters_per_pixel
            })
    else:
        for factor in RING_FACTORS:
            skipped_rings.append({"factor": factor, "radius_px": None, "reason": "meters_per_pixel <= 0"})

    # F-010: the bar used to be dropped whole -- bar and label -- whenever the nominal distance
    # overflowed `w // 3`, which for a 500m bar meant every latitude north of ~10.7 deg
    # (cos(lat) <= 0.9826 at 2.214 m/px). The bar and its label must now clear the provider/North
    # block that shares the bottom strip; when the nominal distance does not fit, the bar shrinks
    # to the largest round distance that does, and the label states the distance actually drawn.
    nominal_m = 200.0 if radius_meters <= 800.0 else 500.0
    scale_bar = None
    if meters_per_pixel > 0:
        max_bar_px = width - 180 - SCALE_BAR_X - SCALE_BAR_LABEL_PX
        for distance_m in [nominal_m] + [d for d in SCALE_BAR_LADDER_M if d < nominal_m]:
            length_px = int(round(distance_m / meters_per_pixel))
            if not (4 <= length_px <= max_bar_px):
                continue
            scale_bar = {
                "nominal_meters": nominal_m,
                "distance_meters": distance_m,
                "length_px": length_px,
                "shrunk": distance_m < nominal_m
            }
            break

    return {
        "frame_radius_px": frame_radius_px,
        "frame_radius_meters": frame_radius_px * meters_per_pixel,
        "rings": rings,
        "skipped_rings": skipped_rings,
        "scale_bar": scale_bar,
        "scale_bar_nominal_meters": nominal_m
    }

def draw_tactical_reticle(
    img: Image.Image,
    lat: float,
    lon: float,
    incident_id: str,
    frp_mw: float,
    radius_meters: float,
    meters_per_pixel: float,
    provider: str = "Google Satellite"
) -> Image.Image:
    """
    Renders an intelligence target reticle on the satellite scene:
    - Optical hotspot center crosshair
    - Range rings calibrated to physical meters
    - Telemetry HUD banner (Incident ID, Coordinates, FRP, Provider)
    - Tactical scale bar & North indicator
    meters_per_pixel is required: F-009(c) showed the old 1.2 default is arithmetically wrong for
    Indian latitudes (Web Mercator gives 2.0-2.4 m/px at zooms 15-16), so every distance the
    reticle labels would have been understated. Callers pass the resolution of the crop they
    actually fetched -- viewport.ViewportSpec.meters_per_pixel.
    """
    annotated = img.copy().convert("RGBA")
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = annotated.size
    cx, cy = w // 2, h // 2

    # Load default font
    font = ImageFont.load_default()

    geometry = plan_reticle_geometry(w, h, radius_meters, meters_per_pixel)

    # 1. Concentric Range Rings (40% and 80% of the frame radius)
    ring_colors = {0.4: RETICLE_AMBER, 0.8: RETICLE_DIM}
    for ring in geometry["rings"]:
        r_px = ring["radius_px"]
        color = ring_colors[ring["factor"]]
        draw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px], outline=color, width=1)
        draw.text((cx + r_px + 4, cy - 6), f"{int(round(ring['ground_meters']))}m", fill=color, font=font)
    for miss in geometry["skipped_rings"]:
        logger.warning(
            f"Reticle ring {miss['factor']:.0%} not drawn on {w}x{h} frame "
            f"(radius {miss['radius_px']}px): {miss['reason']}"
        )

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
    scale_bar = geometry["scale_bar"]
    if scale_bar is None:
        logger.warning(
            f"Scale bar not drawn on {w}x{h} frame: no round distance fits "
            f"{geometry['scale_bar_nominal_meters']:.0f}m at {meters_per_pixel:.3f} m/px"
        )
    else:
        scale_px = scale_bar["length_px"]
        sx = SCALE_BAR_X
        sy = h - 12
        draw.line([(sx, sy), (sx + scale_px, sy)], fill=TEXT_WHITE, width=3)
        draw.line([(sx, sy - 4), (sx, sy + 4)], fill=TEXT_WHITE, width=2)
        draw.line([(sx + scale_px, sy - 4), (sx + scale_px, sy + 4)], fill=TEXT_WHITE, width=2)
        draw.text((sx + scale_px + 8, sy - 6), f"{int(scale_bar['distance_meters'])} m", fill=TEXT_WHITE, font=font)

    # Provider & North
    prov_str = f"SRC: {provider} | N ↑"
    draw.text((w - 180, h - 18), prov_str, fill=(180, 195, 210, 220), font=font)

    # Composite overlay onto base image
    final_img = Image.alpha_composite(annotated, overlay).convert("RGB")
    return final_img

