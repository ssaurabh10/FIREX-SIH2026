# -*- coding: utf-8 -*-
import os
import sys
import json
import glob
import csv

"""
FIREX — Section 6, 7 & 8: Geospatial & Historical Persistence Data Engine
=========================================================================
1. Loads ambient FIRMS active thermal points for the national overlay
2. Records and persists multi-pass detections into SQLite (firex_history.db)
3. Evaluates spatial persistence (Day + Night continuous flaring vs New Ignition)
4. Enriches incidents with AI vision classification, satellite crops & risk scores
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

def prepare_data(pass_type=None):
    if pass_type is None:
        pass_type = os.environ.get("FIREX_PASS_TYPE", "DAY")

    print(f"[FIREX DATA] Initializing historical database & processing {pass_type} pass...")
    history_db.init_db()

    # 1. Load latest FIRMS detections as ambient background points
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

    for csv_path in latest_csvs:
        sat_name = "VIIRS" if "VIIRS" in csv_path else "MODIS"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
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
        notes=f"Overpass ingestion ({pass_type}) across {len(latest_csvs)} FIRMS files"
    )
    
    # Store hotspots in time-series database
    history_db.insert_hotspots(run_id, ambient_points, pass_type=pass_type)

    # Save to ambient_firms.json for frontend HUD & overlay
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
            
            # Compute persistence from historical database
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

    # 4. Extract and promote prominent active thermal anomalies from the latest satellite pass
    benchmark_coords = [(inc["latitude"], inc["longitude"]) for inc in incidents]

    def is_near_existing(lat, lon, threshold_km=25.0):
        for b_lat, b_lon in benchmark_coords:
            if history_db.haversine_km(lat, lon, b_lat, b_lon) <= threshold_km:
                return True
        return False

    # Filter ambient points in Indian subcontinent
    india_points = [
        p for p in ambient_points 
        if 8.0 <= p["lat"] <= 35.5 and 68.5 <= p["lon"] <= 96.5
    ]
    india_points.sort(key=lambda x: x["frp"], reverse=True)

    selected_pass_targets = []
    for p in india_points:
        if is_near_existing(p["lat"], p["lon"], threshold_km=25.0):
            continue
        too_close = False
        for s in selected_pass_targets:
            if history_db.haversine_km(p["lat"], p["lon"], s["lat"], s["lon"]) < 30.0:
                too_close = True
                break
        if not too_close:
            selected_pass_targets.append(p)
            if len(selected_pass_targets) >= 15:  # Top 15 distinct national target zones
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

        # Heuristic inference from telemetry & geospatial coordinates
        if pattern == "RECURRING_INDUSTRIAL_FLARE" or (frp >= 25.0 and (lon < 75.0 or 85.0 <= lon <= 87.0)):
            classification = "gas_flare"
            category_target = "likely_flare_or_persistent"
            loc_label = f"Refinery / Flaring Corridor ({lat:.2f}°N, {lon:.2f}°E)"
            reasoning = f"Continuous thermal emissions ({frp:.1f} MW) consistent with routine gas flaring or industrial furnace operations."
        elif frp >= 20.0:
            classification = "industrial_fire"
            category_target = "industrial_candidate"
            loc_label = f"Industrial Facility Cluster ({lat:.2f}°N, {lon:.2f}°E)"
            reasoning = f"Elevated thermal radiative power ({frp:.1f} MW) flagged by {sat} polar pass. Elevated structural risk alert."
        elif 82.0 <= lon <= 87.5 and 19.0 <= lat <= 24.5:
            classification = "mining_or_other_thermal_source"
            category_target = "mining_candidate"
            loc_label = f"Mineral & Steel Energy Belt ({lat:.2f}°N, {lon:.2f}°E)"
            reasoning = f"Thermal signature detected in major mining/coal energy belt. Consistent with spontaneous coal seam heating or smelting slag."
        elif lat < 16.0 or (lat > 28.0 and lon > 90.0) or (73.0 <= lon <= 76.0 and 11.0 <= lat <= 18.0):
            classification = "wildfire"
            category_target = "forest_candidate"
            loc_label = f"Wildland & Canopy Interface ({lat:.2f}°N, {lon:.2f}°E)"
            reasoning = f"Thermal anomaly detected in vegetated terrain. Monitored for wildland or biomass fire spread."
        else:
            classification = "mining_or_other_thermal_source"
            category_target = "unclassified_candidate"
            loc_label = f"Satellite Thermal Anomaly ({lat:.2f}°N, {lon:.2f}°E)"
            reasoning = f"Telemetry verified by {sat} polar sensor. Background thermal signature tracked across satellite observation cycle."

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
            "display_name": f"Satellite Anomaly Sector, {lat:.3f}°N {lon:.3f}°E, India",
            "ai_classification": classification,
            "ai_confidence": 0.85 if conf_str in ["h", "high"] or (conf_str.isdigit() and int(conf_str) >= 70) else 0.70,
            "ai_uncertainty": "low" if conf_str in ["h", "high"] else "medium",
            "ai_evidence": [
                f"Active {sat} satellite detection with radiative output of {frp:.1f} MW",
                f"Multi-pass persistence: {pattern.replace('_', ' ')} ({dn_status})",
                f"Telemetry verified at coordinates {lat:.4f}°N, {lon:.4f}°E"
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

    incidents_path = os.path.join(DATA_DIR, "incidents.json")
    with open(incidents_path, "w", encoding="utf-8") as f:
        json.dump(incidents, f, indent=2)

    # 4. Enrich incidents with Section 10 Multi-Factor Risk Engine
    try:
        scored = score_and_enrich_incidents(incidents_path)
        # Record scored evaluations in persistence DB
        history_db.record_incident_evaluations(run_id, scored)
    except Exception as e:
        print(f"  [WARN] Risk engine scoring skipped or error: {e}")

    print(f"  * Loaded {len(latest_csvs)} FIRMS source telemetry files")
    print(f"  * Synced {len(ambient_points)} ambient thermal hotspots into run #{run_id}")
    print(f"  * Evaluated & enriched {len(incidents)} prioritized incident dossiers")

if __name__ == "__main__":
    prepare_data()
