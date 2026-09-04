# -*- coding: utf-8 -*-
import os
import json
import glob
import csv

"""
Prepares geospatial data for Section 6 GIS Map:
  1. Detailed benchmark incidents with AI vision classification & satellite crops
  2. Ambient FIRMS active thermal points for the national overlay
"""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 1. Load AI classifications
ai_file = os.path.join(BASE_DIR, "pipeline", "04_vision_ai", "ai_classifications.json")
ai_map = {}
if os.path.exists(ai_file):
    with open(ai_file, "r", encoding="utf-8") as f:
        ai_data = json.load(f)
        for item in ai_data:
            ai_map[item["case_id"]] = item

# 2. Load benchmark detections
bench_file = os.path.join(BASE_DIR, "pipeline", "02_selection", "test_detections.json")
incidents = []
if os.path.exists(bench_file):
    with open(bench_file, "r", encoding="utf-8") as f:
        bench_cases = json.load(f)
        
    for c in bench_cases:
        cid = c["id"]
        ai_info = ai_map.get(cid, {}).get("ai_assessment", {})
        
        incidents.append({
            "id": cid,
            "category_target": c.get("category_target"),
            "latitude": c["latitude"],
            "longitude": c["longitude"],
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
            "raw_image_url": f"/crops/{cid}/satellite_raw.jpg"
        })


# Save curated incidents

with open(os.path.join(DATA_DIR, "incidents.json"), "w", encoding="utf-8") as f:
    json.dump(incidents, f, indent=2)

# 3. Load latest FIRMS detections as ambient background points
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
                    "time": time_str
                })
            except Exception:
                continue

ambient_file = os.path.join(DATA_DIR, "ambient_firms.json")
with open(ambient_file, "w", encoding="utf-8") as f:
    json.dump(ambient_points, f, indent=2)

print(f"Loaded {len(latest_csvs)} latest CSV files:")
for c in latest_csvs:
    print(f"  - {os.path.basename(c)}")
print(f"Prepared {len(incidents)} AI-evaluated incidents and {len(ambient_points)} latest ambient FIRMS hotspots.")

# 4. Enrich incidents with Risk Engine
try:
    import sys
    sys.path.append(os.path.join(BASE_DIR, "pipeline", "06_risk_engine"))
    from risk_scorer import score_and_enrich_incidents
    score_and_enrich_incidents(os.path.join(DATA_DIR, "incidents.json"))
except Exception as e:
    print(f"Note: Risk engine enrichment skipped or error: {e}")

