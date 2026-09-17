"""
FIREX v2 Intelligence Prompts (Version 2.0)
Strictly enforces Section 17 (12 AI Prompt Rules) of FIREX-SIH2026 Blueprint.
"""
from typing import Dict, Any

from app.imagery.viewport import crop_coverage_radius_meters, get_meters_per_pixel

PROMPT_VERSION = "2.0.0"

SYSTEM_PROMPT = """You are an elite satellite imagery and industrial thermal intelligence analyst for India's national FIREX platform.

You are provided with:
1. NASA FIRMS satellite thermal anomaly telemetry (FRP MW, coordinates, sensor, confidence).
2. GIS spatial context (nearest industrial facility, distance in meters, facility type/sector, administrative region).
3. 365-Day Historical Baseline (median FRP, 95th-percentile normal flare ceiling, persistence rating).
4. High-resolution map/satellite visual context centered exactly at the crosshair with tactical distance range rings.

CRITICAL OPERATIONAL RULES (MANDATORY):
1. Treat NASA FIRMS as a thermal anomaly detection, NOT guaranteed proof of an uncontrolled fire.
2. Visually inspect the satellite image inside the range rings; do NOT rely exclusively on tabular metadata.
3. Use GIS and FIRMS as contextual guidance to interpret the visual scene.
4. Never invent or hallucinate missing values. If an attribute is unknown, explicitly state "Unknown".
5. Do NOT calculate or assign final disaster severity scores (handled downstream by the Severity Engine).
6. Provide both a primary classification AND an alternative competing hypothesis.
7. Detail specific visual evidence observed (e.g. blast furnace, process units, smokestacks, smoke plumes, flame core, forest canopy, agricultural fields, open pit mine).
8. Detail specific contextual evidence (e.g. proximity to critical asset, comparison of observed FRP to 365-day P95 normal ceiling).
9. Clearly state uncertainties, optical constraints, cloud obscuration, or temporal lag.
10. If evidence is ambiguous, low quality, or cloud-obscured, classify as "uncertain" rather than guessing.
11. Never claim definitive ground truth from optical imagery alone; provide probabilistic assessment.
12. Output MUST be ONLY a valid JSON object strictly conforming to the requested schema.
"""

def build_investigation_prompt(package: Dict[str, Any]) -> str:
    """
    Builds the user prompt synthesizing the Stage 5 Investigation Package.
    """
    inc = package.get("incident", {})
    gis = package.get("gis_context", {})
    hist = package.get("historical_features", {})
    vis = package.get("visual_context", {})

    lat = inc.get("latitude", 0.0)
    lon = inc.get("longitude", 0.0)
    frp = inc.get("max_frp_mw", 0.0)
    mean_frp = inc.get("mean_frp_mw", frp)
    inc_code = inc.get("incident_code", "UNKNOWN")
    satellite = inc.get("satellite", "VIIRS/MODIS")
    obs_count = inc.get("observation_count", 1)

    facility_name = gis.get("facility_name") or "None in immediate vicinity"
    facility_type = gis.get("facility_type") or "N/A"
    industry = gis.get("industry") or "N/A"
    facility_dist_m = gis.get("facility_distance_m")
    dist_str = f"{facility_dist_m:.1f} meters" if facility_dist_m is not None else "Unknown"
    is_inside = "YES" if gis.get("is_inside_facility") else "NO"
    state = gis.get("state") or "India"
    district = gis.get("district") or "N/A"

    median_frp = hist.get("median_frp_mw", 0.0)
    p95_frp = hist.get("p95_frp_mw", 0.0)
    history_label = hist.get("history_reliability_label", "NO_HISTORY")
    is_persistent = "YES" if hist.get("is_persistent") else "NO"
    active_days = hist.get("active_days_365d", 0)
    night_ratio = hist.get("night_ratio", 0.0)
    night_pct = round(night_ratio * 100.0, 1)
    surge_mult = hist.get("surge_multiplier", 1.0)
    is_routine_flare = "YES" if hist.get("is_routine_flare") else "NO"
    site_hint = hist.get("site_classification_hint", "EPISODIC_THERMAL")

    mining_basin = gis.get("mining_basin")
    mining_line = ""
    operational_notice = ""
    if mining_basin:
        mining_line = f"\n- Sovereign Mining Basin: {mining_basin.get('basin_name')} (Operator: {mining_basin.get('operator')})"
        is_routine_flare = "NO (Open-Cast Mining / Coal Seam Basin)"
        site_hint = "COAL_MINING_BASIN"
        operational_notice = f"\nOPERATIONAL GUIDANCE FOR MINING BASINS:\n- This coordinate is located inside {mining_basin.get('basin_name')}.\n- Persistent thermal emissions with high nocturnal recurrence in terraced pits, coal seams, and overburden dumps represent active mining processes, spontaneous coal combustion, or heavy excavation heat, NOT petroleum gas flares.\n- Prefer 'mining_related' unless a refinery or chemical flare stack structure is clearly discernible in the optical crop.\n"

    from app.gis.assets import is_metallurgical_or_manufacturing_facility
    is_metal = is_metallurgical_or_manufacturing_facility(facility_type, industry) or hist.get("is_metallurgical_facility", False)
    dist_km = (facility_dist_m / 1000.0) if facility_dist_m is not None else None
    if is_inside == "YES" or (dist_km is not None and dist_km <= 5.0):
        if is_metal:
            is_routine_flare = "NO (Integrated Steel Plant / Metallurgical Smelter)"
            site_hint = "METALLURGICAL_INDUSTRIAL"
            operational_notice += (
                f"\nOPERATIONAL GUIDANCE FOR HEAVY INDUSTRIAL / METALLURGICAL FACILITIES:\n"
                f"- This coordinate is located inside or adjacent to {facility_name} ({facility_type}).\n"
                f"- Continuous thermal emissions with high nocturnal recurrence represent industrial blast furnaces, basic oxygen furnaces, coke ovens, or metal smelting processes, NOT petroleum gas flares.\n"
                f"- Classify as 'industrial_fire' (operational metallurgical furnace or industrial blaze). Do NOT classify as 'gas_flare' unless an oil refinery / hydrocarbon flare stack is clearly discernible in the optical crop.\n"
            )

    # R12 / F-009: the figure this line hands the model is ground truth it reasons
    # about, and it used to be the viewport's *nominal request* (e.g. "radius
    # ~1000m"), which is not what the pixels cover. A 640px crop at web-mercator
    # zoom z and latitude phi spans 320 * (156543.03392 * cos(phi) / 2**z) metres
    # of half-width -- app/imagery/viewport.crop_coverage_radius_meters, the same
    # function the viewport and the reticle use -- so at lat 20.97 / zoom 16 the
    # scene is ~714m, not 1000m. Coverage moves in 2x zoom steps, so no zoom lands
    # exactly on an arbitrary request; the prompt therefore states the coverage the
    # crop really has, with the assumptions it rests on (crop size, zoom, latitude,
    # m/px) named alongside it.
    #
    # `visual_context.radius_meters` is deliberately not read: since F-009 the
    # viewport stores this same real coverage under that name, so quoting it as a
    # separate "nominal request" states the correct number and then misdescribes
    # what it means -- which is the one thing this line exists to prevent.
    zoom = vis.get("zoom_level", 16)
    provider = vis.get("provider", "Google Satellite")

    m_per_px = get_meters_per_pixel(lat, zoom)
    coverage_half_m = crop_coverage_radius_meters(lat, zoom, 640)
    coverage_full_m = coverage_half_m * 2.0

    prompt = f"""ANALYSIS TARGET:
- Incident Code: {inc_code}
- Geographic Coordinates: Latitude {lat:.5f}°, Longitude {lon:.5f}° ({district}, {state})
- Thermal Radiative Power: Max {frp:.1f} MW (Mean: {mean_frp:.1f} MW) across {obs_count} detections
- Satellite Platform: {satellite}
- Optical Scene Context: {provider} optical crop centred on the target at web-mercator zoom {zoom}, {m_per_px:.2f} m/pixel at latitude {abs(lat):.2f}°
- Ground Coverage of this crop: a 640px scene at that zoom spans ~{coverage_half_m:.0f}m from the crosshair to each edge (~{coverage_full_m:.0f}m across). That half-width is the real scale of the scene and the radius the reticle's range rings are drawn from; distances you judge visually must be read against this coverage.

GEOSPATIAL & INDUSTRIAL INFRASTRUCTURE CONTEXT:
- Nearest Facility: {facility_name}
- Facility Type / Sector: {facility_type} ({industry})
- Distance to Facility Boundary/Center: {dist_str}
- Inside Facility Boundary: {is_inside}{mining_line}

365-DAY SATELLITE CLIMATOLOGY & HISTORICAL BEHAVIOR (EMPIRICAL):
- Historical Data Reliability: {history_label}
- Annual Recurrence: Active on {active_days} distinct calendar days out of 365 ({round(active_days / 3.65, 1)}% of year)
- Historical Median FRP: {median_frp:.1f} MW | Normal Operational Ceiling (P95): {p95_frp:.1f} MW
- Thermal Excursion: Observed FRP ({frp:.1f} MW) is {surge_mult:.1f}x of historical median
- Diurnal Pattern: {night_pct}% of historical detections occur at NIGHT (Flaring/Furnace Profile)
- Persistent Thermal Source Flag: {is_persistent} (Known Routine Flare: {is_routine_flare})
- Climatology Site Signature: {site_hint}
{operational_notice}
TAXONOMY CHOICES:
Select EXACTLY one primary and one alternative category from:
- "industrial_fire" (uncontrolled accidental fire, major structural/process unit blaze, explosion)
- "gas_flare" (routine or elevated industrial flare stack, continuous smokestack burn)
- "wildfire" (natural brush, forest, or grassland fire)
- "agricultural_burning" (crop residue, stubble, agricultural clearance)
- "mining_related" (open-cast pit, coal seam fire, active quarrying heat)
- "uncertain" (insufficient clarity, cloud obscuration, or inconclusive evidence)

REQUIRED JSON RESPONSE SCHEMA:
{{
  "classification": "<one of the 6 taxonomy choices>",
  "confidence": <number between 0 and 100>,
  "alternative": {{
    "classification": "<different taxonomy choice>",
    "confidence": <number between 0 and 100>
  }},
  "visual_evidence": [
    "<specific visible ground feature in the scene, e.g. chimneys, blast furnace, tanks, smoke, vegetation>"
  ],
  "contextual_evidence": [
    "<comparison of observed FRP to the 365-day P95 ceiling, proximity to industrial assets, persistence>"
  ],
  "uncertainties": [
    "<optical resolution constraints, potential cloud cover, time lapse between satellite pass and imagery>"
  ],
  "image_quality": {{
    "score": <0 to 100>,
    "cloud_cover": "<low|medium|high|obscured>",
    "visibility": "<good|moderate|poor>"
  }},
  "needs_reinvestigation": <true|false>,
  "reasoning_summary": "<concise analytical synthesis explaining the classification>"
}}

Return ONLY the raw JSON object. Do not include introductory text, conversational pleasantries, or markdown wrappers."""
    return prompt
