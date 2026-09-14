# -*- coding: utf-8 -*-
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

"""
FIREX --- Section 5: First End-to-End Automated Pipeline
=========================================================
Connects the complete intelligence pipeline:
  FIRMS Anomaly Data
        ↓
  Coordinates & Thermal Metrics
        ↓
  High-Res Satellite Crop & Thermal Reticle
        ↓
  MiniMax M3 Vision AI (4-Key Load Balanced Pool)
        ↓
  Structured Incident Assessment Dossier

Runs 5 benchmark cases autonomously without human intervention.
"""

import os
import json
import base64
import time
from config import OPENROUTER_API_KEYS, MODEL_NAME, NUM_PIPELINE_CASES
from key_pool import KeyPoolManager

# Import satellite stitching and annotation from imagery module
_sec3_dir = os.path.join(os.path.dirname(__file__), "..", "03_imagery")
if not os.path.exists(_sec3_dir):
    _sec3_dir = os.path.join(os.path.dirname(__file__), "..", "section3_imagery")
sys.path.append(_sec3_dir)
from fetch_satellite_crops import get_stitched_crop, draw_thermal_annotation

_sec2_dir = os.path.join(os.path.dirname(__file__), "..", "02_selection")
if not os.path.exists(_sec2_dir):
    _sec2_dir = os.path.join(os.path.dirname(__file__), "..", "section2_selection")
INPUT_BENCHMARK = os.path.join(_sec2_dir, "test_detections.json")
INCIDENTS_DIR = os.path.join(os.path.dirname(__file__), "incidents")
os.makedirs(INCIDENTS_DIR, exist_ok=True)

def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def build_prompt(meta):
    return f"""You are an expert geospatial intelligence analyst evaluating a satellite-detected thermal anomaly for the FIREX incident system.

NASA FIRMS reported a thermal anomaly at the center coordinates marked with the red target crosshair on this ~1.2 km satellite image:
- Latitude: {meta.get('latitude')}
- Longitude: {meta.get('longitude')}
- Fire Radiative Power (FRP): {meta.get('frp')} MW
- Satellite / Sensor: {meta.get('satellite')} ({meta.get('instrument')})
- Detection Confidence: {meta.get('confidence')}
- Acquisition Date/Time: {meta.get('acq_date')} at {meta.get('acq_time')} UTC

EVALUATION RULES:
1. FIRMS detects thermal anomalies (heat), NOT confirmed fires.
2. Inspect the visible ground features within the ~1.2 km radius around the red target:
   - Industrial structures: Flare stacks, oil storage tanks, chemical pipelines, cooling towers, factories.
   - Natural terrain: Forest cover, wilderness, hills, rivers.
   - Agricultural parcels: Crop fields, farming grids.
   - Mining: Coal mines, open-pit quarries.
3. If visual evidence is ambiguous, contradictory, or insufficient, you MUST set classification to "uncertain".

Allowed classification values:
- "industrial_fire"
- "gas_flare"
- "wildfire"
- "agricultural_burning"
- "mining_or_other_thermal_source"
- "uncertain"

Return ONLY a valid JSON object without markdown fences, matching this structure:
{{
  "classification": "industrial_fire",
  "confidence": 0.85,
  "alternative_classification": "gas_flare",
  "visual_evidence": [
    "description of visible ground features within 1km",
    "proximity to infrastructure or vegetation"
  ],
  "uncertainty": "low",
  "detailed_reasoning": "brief explanation of why this classification was chosen"
}}
"""

def run_single_incident(case_data, pool_manager, case_idx, total_cases):
    cid = case_data["id"]
    lat = case_data["latitude"]
    lon = case_data["longitude"]
    frp = case_data.get("frp", "n/a")
    conf = case_data.get("confidence", "n/a")
    sat = case_data.get("satellite", "unknown")
    inst = case_data.get("instrument", "unknown")
    
    print("\n" + "=" * 48)
    print(f"FIREX TEST: CASE {case_idx}/{total_cases} [{cid.upper()}]")
    print("=" * 48)
    print("FIRMS:")
    print(f"Lat: {lat:.5f}")
    print(f"Lon: {lon:.5f}")
    print(f"FRP: {frp} MW")
    print(f"Confidence: {conf}")
    print(f"Satellite: {sat} ({inst})")
    
    # Step 1: Satellite Image Crop & Reticle Generation
    incident_folder = os.path.join(INCIDENTS_DIR, cid)
    os.makedirs(incident_folder, exist_ok=True)
    
    raw_crop, hotspot_xy = get_stitched_crop(lat, lon, zoom=16, crop_size=640)
    annotated_crop = draw_thermal_annotation(raw_crop, hotspot_xy, case_data)
    
    annotated_path = os.path.join(incident_folder, "satellite_annotated.jpg")
    annotated_crop.save(annotated_path, quality=92)
    print("\nSatellite image: SUCCESS")
    
    # Step 2: MiniMax M3 Vision AI Analysis with Key Rotation
    b64_img = encode_image(annotated_path)
    prompt = build_prompt(case_data)
    
    ai_result, used_key_info, reasoning = pool_manager.call_minimax_vision(prompt, b64_img)
    
    if ai_result:
        classification = ai_result.get("classification", "uncertain")
        confidence = ai_result.get("confidence", 0.0)
        
        print("\nAI:")
        print(f"Classification: {classification}")
        print(f"Confidence: {confidence}")
        
        print(f"\nStatus: SUCCESS ({used_key_info})")
        print("=" * 48)
        
        # Save complete incident dossier
        dossier = {
            "incident_id": cid,
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "SUCCESS",
            "firms_observation": {
                "latitude": lat,
                "longitude": lon,
                "frp": frp,
                "confidence": conf,
                "satellite": sat,
                "instrument": inst,
                "acq_date": case_data.get("acq_date"),
                "acq_time": case_data.get("acq_time")
            },
            "ground_truth_context": case_data.get("expected_ground_truth"),
            "ai_assessment": ai_result,
            "satellite_image": os.path.abspath(annotated_path),
            "key_used": used_key_info
        }
        
        with open(os.path.join(incident_folder, "incident_dossier.json"), "w", encoding="utf-8") as f:
            json.dump(dossier, f, indent=2)
            
        return True, dossier
    else:
        print("\nStatus: FAILED")
        print("=" * 48)
        return False, None

def main():
    print("=" * 65)
    print("  FIREX — SECTION 5: END-TO-END AUTONOMOUS PIPELINE TEST")
    print("=" * 65)
    print(f"AI Model      : {MODEL_NAME}")
    print(f"API Key Pool  : {len(OPENROUTER_API_KEYS)} keys active (Round-Robin with Failover)")
    print(f"Target Cases  : {NUM_PIPELINE_CASES} consecutive cases")
    
    if not os.path.exists(INPUT_BENCHMARK):
        print(f"[ERROR] Benchmark dataset not found at {INPUT_BENCHMARK}")
        return
        
    with open(INPUT_BENCHMARK, "r", encoding="utf-8") as f:
        all_cases = json.load(f)
        
    pipeline_cases = all_cases[:NUM_PIPELINE_CASES]
    pool_manager = KeyPoolManager(OPENROUTER_API_KEYS, MODEL_NAME)
    
    successful_cases = 0
    dossiers = []
    
    for i, case in enumerate(pipeline_cases):
        success, dossier = run_single_incident(case, pool_manager, i + 1, len(pipeline_cases))
        if success:
            successful_cases += 1
            dossiers.append(dossier)
        time.sleep(1.0) # brief pause between calls
        
    print("\n" + "=" * 65)
    print("  SECTION 5 CHECKLIST & STOP CONDITION VERIFICATION")
    print("=" * 65)
    print(f"  Processed Cases       : {len(pipeline_cases)}")
    print(f"  Successful End-to-End : {successful_cases}/{len(pipeline_cases)}")
    print(f"  Load Balancing        : Distributed across {len(OPENROUTER_API_KEYS)} API keys")
    print(f"  Saved Incident Dossiers in: {INCIDENTS_DIR}")
    
    if successful_cases == len(pipeline_cases):
        print("\n  [x] STOP CONDITION SATISFIED:")
        print("      The end-to-end pipeline ran autonomously across 5 diverse cases.")
        print("      PROCEED TO SECTION 6: BASIC GIS MAP FRONTEND.")
    else:
        print("\n  [!] STOP CONDITION NOT MET: Fix issues before proceeding to frontend.")
    print("=" * 65)

if __name__ == "__main__":
    main()
