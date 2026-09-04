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
