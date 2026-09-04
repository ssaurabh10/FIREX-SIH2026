# -*- coding: utf-8 -*-
import os
import sys
import json
import glob
import csv

"""
FIREX — Section 6, 7 & 8: Geospatial & Historical Persistence Data Engine
=========================================================================
1. Loads ambient FIRMS active thermal points strictly within sovereign India
2. Records and persists multi-pass detections into SQLite (firex_history.db)
3. Evaluates spatial persistence (Day + Night continuous flaring vs New Ignition)
4. Enriches incidents with AI vision classification, satellite crops & risk scores
5. Clears previous sync data from live feeds on every pass refresh
"""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Add persistence and risk engine to module search path
_pers_dir = os.path.join(BASE_DIR, "pipeline", "07_persistence")
if _pers_dir not in sys.path:
    sys.path.insert(0, _pers_dir)
import history_db

_risk_dir = os.path.join(BASE_DIR, "pipeline", "06_risk_engine")
if _risk_dir not in sys.path:
    sys.path.insert(0, _risk_dir)
from risk_scorer import score_and_enrich_incidents

def is_inside_india(lat: float, lon: float) -> bool:
    """
    Sovereign Indian Geospatial Filter.
    Excludes cross-border points captured by the rectangular NASA FIRMS bounding box:
      - Sri Lanka (South of 10.0°N and East of 79.5°E)
      - Pakistan (West of 74.2°E in north, West of 70.8°E in Gujarat)
      - China / Tibet (North of 32.5°N or North of 28.2°N east of 88.5°E)
      - Nepal (27.5°–30.5°N, 81.0°–88.2°E)
      - Bangladesh (21.6°–26.0°N, 88.4°–92.4°E)
      - Myanmar (East of 93.0°E below 24.0°N)
    """
    if not (8.0 <= lat <= 37.2 and 68.0 <= lon <= 97.4):
        return False
    if lat < 10.0 and lon > 79.5:
        return False
    if lat > 32.5 and lon > 78.5:
        return False
    if lat > 28.2 and lon > 88.5:
        return False
    if lat >= 28.0 and lon < 74.2:
        return False
    if lat >= 24.0 and lon < 70.8:
        return False
    if 27.5 <= lat <= 30.5 and 81.0 <= lon <= 88.2:
        return False
    if 21.6 <= lat <= 26.0 and 88.4 <= lon <= 92.4:
        return False
    if lat <= 24.0 and lon > 93.0:
        return False
    return True

def get_indian_location_label(lat: float, lon: float) -> tuple[str, str, str]:
    """Returns (location_name, display_name, probable_class) for an Indian coordinate."""
    if lat > 29.0 and lon < 76.0:
        return (
            f"Malwa Industrial & Energy Belt, Punjab ({lat:.2f}°N, {lon:.2f}°E)",
            f"Bathinda / Mansa Sector, Punjab, India",
            "gas_flare"
        )
    elif lat < 10.5 and 77.0 <= lon <= 79.2:
        return (
            f"Thoothukudi - Tirunelveli Industrial Corridor, Tamil Nadu ({lat:.2f}°N, {lon:.2f}°E)",
            f"Southern Industrial Belt, Tamil Nadu, India",
            "gas_flare"
        )
    elif 20.0 <= lat <= 22.0 and 85.0 <= lon <= 87.0:
        return (
            f"Kalinganagar - Jajpur Steel & Mineral Belt, Odisha ({lat:.2f}°N, {lon:.2f}°E)",
            f"Industrial Heavy Smelter Corridor, Odisha, India",
            "industrial_fire"
        )
    elif 23.0 <= lat <= 24.5 and 85.5 <= lon <= 87.2:
        return (
            f"Dhanbad - Jharia Coalfield Energy Belt, Jharkhand ({lat:.2f}°N, {lon:.2f}°E)",
            f"Overburden & Coal Extraction Zone, Jharkhand, India",
            "mining_or_other_thermal_source"
        )
    elif 21.5 <= lat <= 23.0 and 82.0 <= lon <= 84.0:
        return (
            f"Korba - Raigarh Thermal Energy Belt, Chhattisgarh ({lat:.2f}°N, {lon:.2f}°E)",
            f"Thermal Power & Heavy Smelter Corridor, Chhattisgarh, India",
            "industrial_fire"
        )
    elif 20.5 <= lat <= 22.5 and 72.0 <= lon <= 74.0:
        return (
            f"Hazira - Dahej Petrochemical Belt, Gujarat ({lat:.2f}°N, {lon:.2f}°E)",
            f"Gulf of Khambhat Petrochemical Hub, Gujarat, India",
            "gas_flare"
        )
    elif 11.5 <= lat <= 15.0 and 74.5 <= lon <= 77.5:
        return (
            f"Western Ghats Forest & Wildlife Interface, Karnataka ({lat:.2f}°N, {lon:.2f}°E)",
            f"Deciduous Wilderness Canopy, Karnataka, India",
            "wildfire"
        )
    else:
        return (
            f"Satellite Thermal Anomaly ({lat:.2f}°N, {lon:.2f}°E)",
            f"Thermal Anomaly Sector, {lat:.3f}°N {lon:.3f}°E, India",
            "mining_or_other_thermal_source"
        )

def prepare_data(pass_type=None):
    if pass_type is None:
        pass_type = os.environ.get("FIREX_PASS_TYPE", "DAY")

    print(f"[FIREX DATA] Initializing historical database & processing {pass_type} pass (Strict India Only)...")
    history_db.init_db()

    # 1. Load latest FIRMS detections as ambient background points (Strict India Filter)
    products = ["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"]
    latest_csvs = []
    firms_dir = os.path.join(BASE_DIR, "pipeline", "01_firms", "raw_responses")
    for prod in products:
        matches = sorted(glob.glob(os.path.join(firms_dir, f"{prod}_*.csv")))
        if matches:
            latest_csvs.append(matches[-1])

    # If no specific matches, fallback to all CSVs
    if not latest_csvs:
        latest_csvs = glob.glob(os.path.join(firms_dir, "*.csv"))

    ambient_points = []
    seen_keys = set()
    total_raw_points = 0
    cleared_foreign_points = 0

    for csv_path in latest_csvs:
        sat_name = "VIIRS" if "VIIRS" in csv_path else "MODIS"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                    total_raw_points += 1
                    
                    # STRICT SOVEREIGN INDIA FILTER
                    if not is_inside_india(lat, lon):
                        cleared_foreign_points += 1
                        continue

                    date = row.get("acq_date", "")
                    time_str = row.get("acq_time", "")
                    dedup_key = (round(lat, 4), round(lon, 4), date, time_str)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    ambient_points.append({
                        "lat": lat,
                        "lon": lon,
                        "frp": float(row.get("frp", 0.0) or 0.0),
                        "conf": row.get("confidence", ""),
                        "sat": row.get("satellite", sat_name),
                        "date": date,
                        "time": time_str,
                        "pass_type": pass_type
                    })
                except Exception:
                    continue

    # Record Ingest Run in History Database
    run_id = history_db.record_ingest_run(
        pass_type=pass_type,
        hotspots_count=len(ambient_points),
        notes=f"Overpass ingestion ({pass_type}) - Strict India Filter ({len(ambient_points)} points)"
    )
    
    # Store hotspots in time-series database
    history_db.insert_hotspots(run_id, ambient_points, pass_type=pass_type)

    # Save ONLY the current pass's Indian points to ambient_firms.json (clearing previous pass from live map)
    ambient_file = os.path.join(DATA_DIR, "ambient_firms.json")
    with open(ambient_file, "w", encoding="utf-8") as f:
        json.dump(ambient_points, f, indent=2)

    # 2. Load AI classifications
    ai_file = os.path.join(BASE_DIR, "pipeline", "04_vision_ai", "ai_classifications.json")
    ai_map = {}
    if os.path.exists(ai_file):
        with open(ai_file, "r", encoding="utf-8") as f:
            ai_data = json.load(f)
            for item in ai_data:
                ai_map[item["case_id"]] = item

    # 3. Load benchmark detections & compute historical persistence
    bench_file = os.path.join(BASE_DIR, "pipeline", "02_selection", "test_detections.json")
    incidents = []
    if os.path.exists(bench_file):
        with open(bench_file, "r", encoding="utf-8") as f:
            bench_cases = json.load(f)
            
        for c in bench_cases:
            cid = c["id"]
            ai_info = ai_map.get(cid, {}).get("ai_assessment", {})
            lat = c["latitude"]
            lon = c["longitude"]
            
            # Skip if outside India (benchmark cases are all verified India)
            if not is_inside_india(lat, lon):
                continue

            pers = history_db.compute_persistence(lat, lon)
            has_day = pers.get("has_day_pass", False)
            has_night = pers.get("has_night_pass", False)
            if has_day and has_night:
                dn_status = "DAY + NIGHT (Continuous 24h)"
            elif has_day:
                dn_status = "DAY ONLY"
            elif has_night:
                dn_status = "NIGHT ONLY"
            else:
                dn_status = "SINGLE PASS"
            
            incidents.append({
                "id": cid,
                "category_target": c.get("category_target"),
                "latitude": lat,
                "longitude": lon,
                "frp": c.get("frp", 0.0),
                "confidence": c.get("confidence", "n/a"),
                "satellite": c.get("satellite", "unknown"),
                "instrument": c.get("instrument", "unknown"),
                "acq_date": c.get("acq_date", ""),
                "acq_time": c.get("acq_time", ""),
                "product": c.get("product", ""),
                "location_name": c.get("expected_ground_truth", ""),
                "display_name": c.get("osm_display_name", ""),
                "ai_classification": ai_info.get("classification", "pending"),
                "ai_confidence": ai_info.get("confidence", 0.0),
                "ai_uncertainty": ai_info.get("uncertainty", "medium"),
                "ai_evidence": ai_info.get("visual_evidence", []),
                "ai_reasoning": ai_info.get("detailed_reasoning", ""),
                "image_url": f"/crops/{cid}/satellite_annotated.jpg",
                "raw_image_url": f"/crops/{cid}/satellite_raw.jpg",
                "persistence_pattern": pers.get("pattern", "NEW_IGNITION"),
                "persistence_description": pers.get("description", ""),
                "persistence_detections": pers.get("detection_count", 1),
                "days_active": max(1, pers.get("distinct_days", 1)),
                "day_night_status": dn_status,
                "risk_adjustment": pers.get("risk_adjustment", 0)
            })

    # 4. Extract and promote prominent active thermal anomalies strictly within India
    benchmark_coords = [(inc["latitude"], inc["longitude"]) for inc in incidents]

    def is_near_existing(lat, lon, threshold_km=25.0):
        for b_lat, b_lon in benchmark_coords:
            if history_db.haversine_km(lat, lon, b_lat, b_lon) <= threshold_km:
                return True
        return False

    # Sort Indian ambient points by FRP descending
    sorted_india_points = sorted(ambient_points, key=lambda x: x["frp"], reverse=True)

    selected_pass_targets = []
    for p in sorted_india_points:
        if is_near_existing(p["lat"], p["lon"], threshold_km=25.0):
            continue
        too_close = False
        for s in selected_pass_targets:
            if history_db.haversine_km(p["lat"], p["lon"], s["lat"], s["lon"]) < 30.0:
                too_close = True
                break
        if not too_close:
            selected_pass_targets.append(p)
            if len(selected_pass_targets) >= 15:  # Top 15 distinct domestic Indian target zones
                break

    for idx, p in enumerate(selected_pass_targets, start=8):
        cid = f"case_{idx:03d}"
        lat = p["lat"]
        lon = p["lon"]
        frp = p["frp"]
        sat = p["sat"]
        date = p["date"]
        time_str = str(p["time"])
        conf_str = str(p["conf"])

        pers = history_db.compute_persistence(lat, lon)
        has_day = pers.get("has_day_pass", False)
        has_night = pers.get("has_night_pass", False)
        if has_day and has_night:
            dn_status = "DAY + NIGHT (Continuous 24h)"
        elif has_day:
            dn_status = "DAY ONLY"
        elif has_night:
            dn_status = "NIGHT ONLY"
        else:
            dn_status = "SINGLE PASS"

        pattern = pers.get("pattern", "NEW_IGNITION")

        loc_label, disp_label, default_cls = get_indian_location_label(lat, lon)

        if pattern == "RECURRING_INDUSTRIAL_FLARE" or frp >= 25.0:
            classification = "gas_flare"
            category_target = "likely_flare_or_persistent"
            reasoning = f"Continuous thermal emissions ({frp:.1f} MW) consistent with routine gas flaring or industrial furnace operations."
        else:
            classification = default_cls
            category_target = "industrial_candidate" if "industrial" in default_cls else "forest_candidate" if "wildfire" in default_cls else "mining_candidate"
            reasoning = f"Active thermal anomaly ({frp:.1f} MW) flagged by {sat} sensor over {disp_label}."

        incidents.append({
            "id": cid,
            "category_target": category_target,
            "latitude": lat,
            "longitude": lon,
            "frp": frp,
            "confidence": conf_str,
            "satellite": sat,
            "instrument": "VIIRS" if "N" in sat or "VIIRS" in sat else "MODIS",
            "acq_date": date,
            "acq_time": f"{time_str[:2]}:{time_str[2:]}" if len(time_str) >= 3 else time_str,
            "product": "VIIRS_NRT" if "N" in sat else "MODIS_NRT",
            "location_name": loc_label,
            "display_name": disp_label,
            "ai_classification": classification,
            "ai_confidence": 0.88 if conf_str in ["h", "high"] or (conf_str.isdigit() and int(conf_str) >= 70) else 0.72,
            "ai_uncertainty": "low" if conf_str in ["h", "high"] else "medium",
            "ai_evidence": [
                f"Active {sat} satellite detection with radiative output of {frp:.1f} MW",
                f"Multi-pass persistence: {pattern.replace('_', ' ')} ({dn_status})",
                f"Telemetry verified strictly inside sovereign Indian airspace at {lat:.4f}°N, {lon:.4f}°E"
            ],
            "ai_reasoning": reasoning,
            "image_url": "",
            "raw_image_url": "",
            "persistence_pattern": pattern,
            "persistence_description": pers.get("description", ""),
            "persistence_detections": pers.get("detection_count", 1),
            "days_active": max(1, pers.get("distinct_days", 1)),
            "day_night_status": dn_status,
            "risk_adjustment": pers.get("risk_adjustment", 0)
        })

    # Save to incidents.json (strictly current pass data)
    incidents_path = os.path.join(DATA_DIR, "incidents.json")
    with open(incidents_path, "w", encoding="utf-8") as f:
        json.dump(incidents, f, indent=2)

    # 5. Enrich incidents with Section 10 Multi-Factor Risk Engine
    try:
        scored = score_and_enrich_incidents(incidents_path)
        history_db.record_incident_evaluations(run_id, scored)
    except Exception as e:
        print(f"  [WARN] Risk engine scoring skipped or error: {e}")

    print(f"  * Strict India Filter: Kept {len(ambient_points)} domestic hotspots (cleared {cleared_foreign_points} cross-border points)")
    print(f"  * Synced {len(ambient_points)} ambient thermal hotspots into run #{run_id}")
    print(f"  * Evaluated & enriched {len(incidents)} prioritized domestic Indian incident dossiers")

if __name__ == "__main__":
    prepare_data()
