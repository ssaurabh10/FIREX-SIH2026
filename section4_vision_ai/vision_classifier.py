# -*- coding: utf-8 -*-
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


"""
FIREX --- Section 4: Vision AI Analysis (MiniMax M3 via OpenRouter)
===================================================================
Sends high-resolution satellite imagery + FIRMS thermal metadata to MiniMax M3
via OpenRouter with reasoning enabled to classify the probable nature and cause of the hotspot.

Output classes:
  - industrial_fire
  - gas_flare
  - wildfire
  - agricultural_burning
  - mining_or_other_thermal_source
  - uncertain
"""

import os
import glob
import json
import base64
import re
import requests

try:
    from config import OPENROUTER_API_KEYS, MODEL_NAME
except ImportError:
    print("[ERROR] config.py not found. Fill in your OPENROUTER_API_KEYS in config.py.")
    sys.exit(1)


CROPS_DIR = os.path.join(os.path.dirname(__file__), "..", "section3_imagery", "crops")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "ai_classifications.json")

def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def build_prompt(meta):
    prompt = f"""You are an expert geospatial intelligence analyst evaluating a satellite-detected thermal anomaly for the FIREX incident system.

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
    return prompt

def analyze_case_with_pool(case_meta, model_name, key_pool, key_state):
    cid = case_meta.get("id")
    case_dir = os.path.join(CROPS_DIR, cid)
    
    img_path = os.path.join(case_dir, "satellite_annotated.jpg")
    if not os.path.exists(img_path):
        img_path = os.path.join(case_dir, "satellite_raw.jpg")
        
    if not os.path.exists(img_path):
        print(f"  [ERROR] Image not found for {cid}")
        return None, "no_image"
        
    b64_img = encode_image(img_path)
    prompt = build_prompt(case_meta)
    
    attempts = 0
    max_attempts = len(key_pool) * 2
    
    while attempts < max_attempts:
        attempts += 1
        current_idx = key_state["idx"]
        api_key = key_pool[current_idx]
        key_label = f"Key #{current_idx + 1} ({api_key[:14]}...)"
        
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_img}"
                            }
                        }
                    ]
                }
            ],
            "reasoning": {"enabled": True},
            "temperature": 0.1,
            "max_tokens": 1600
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/FIREX-SIH2026",
            "X-Title": "FIREX Thermal Intelligence"
        }
        
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]["message"]
                content = choice.get("content", "")
                reasoning = choice.get("reasoning_details") or choice.get("reasoning", "")
                
                clean = re.sub(r"^```json\s*", "", content, flags=re.MULTILINE)
                clean = re.sub(r"^```\s*", "", clean, flags=re.MULTILINE)
                match = re.search(r"\{.*\}", clean, re.DOTALL)
                if match:
                    clean = match.group(0)
                    
                parsed = json.loads(clean)
                if reasoning:
                    parsed["ai_reasoning_trace"] = str(reasoning)[:250] + "..."
                # Advance to next key for next call to distribute load
                key_state["idx"] = (current_idx + 1) % len(key_pool)
                return parsed, key_label
            elif resp.status_code in [429, 401, 402, 403]:
                print(f"\n  [!] {key_label} returned HTTP {resp.status_code}. Auto-failing over...", end="", flush=True)
                key_state["idx"] = (current_idx + 1) % len(key_pool)
            else:
                print(f"\n  [!] Error with {key_label} (HTTP {resp.status_code}): {resp.text[:80]}", end="", flush=True)
                key_state["idx"] = (current_idx + 1) % len(key_pool)
        except Exception as e:
            print(f"\n  [!] Network/Parse error with {key_label}: {e}", end="", flush=True)
            key_state["idx"] = (current_idx + 1) % len(key_pool)
            
    return None, "keys_exhausted"

def main():
    print("=" * 65)
    print("  FIREX — SECTION 4: VISION AI ANALYSIS (MiniMax M3)")
    print("=" * 65)
    print(f"Model         : {MODEL_NAME}")
    print(f"API Key Pool  : {len(OPENROUTER_API_KEYS)} keys active (Round-Robin)")
    
    valid_keys = [k.strip() for k in OPENROUTER_API_KEYS if k.strip()]
    if not valid_keys:
        print("[ERROR] No valid API keys found in OPENROUTER_API_KEYS.")
        return
        
    case_dirs = sorted(glob.glob(os.path.join(CROPS_DIR, "case_*")))
    if not case_dirs:
        print(f"[ERROR] No cases found in {CROPS_DIR}. Run Section 3 first.")
        return
        
    all_results = []
    print(f"Found {len(case_dirs)} benchmark cases to evaluate.\n")
    
    key_state = {"idx": 0}
    
    for cdir in case_dirs:
        meta_file = os.path.join(cdir, "metadata.json")
        if not os.path.exists(meta_file):
            continue
        with open(meta_file, "r", encoding="utf-8") as f:
            case_meta = json.load(f)
            
        cid = case_meta["id"]
        target_cat = case_meta.get("category_target", "unknown")
        print(f"Evaluating {cid} [{target_cat}] (FRP: {case_meta.get('frp')} MW)... ", end="", flush=True)
        
        ai_resp, used_key = analyze_case_with_pool(case_meta, MODEL_NAME, valid_keys, key_state)
        if ai_resp:
            cls = ai_resp.get("classification")
            conf = ai_resp.get("confidence")
            unc = ai_resp.get("uncertainty")
            print(f"DONE -> {cls} (Conf: {conf}, Unc: {unc}) [{used_key}]")
            res_record = {
                "case_id": cid,
                "target_ground_truth": target_cat,
                "ground_truth_details": case_meta.get("expected_ground_truth"),
                "key_used": used_key,
                "firms_metadata": {
                    "latitude": case_meta.get("latitude"),
                    "longitude": case_meta.get("longitude"),
                    "frp": case_meta.get("frp"),
                    "satellite": case_meta.get("satellite"),
                    "confidence": case_meta.get("confidence")
                },
                "ai_assessment": ai_resp
            }
            all_results.append(res_record)
        else:
            print(f"FAILED [{used_key}]")

            
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
        
    print("\n" + "=" * 65)
    print("  SECTION 4 EVALUATION RESULTS SUMMARY")
    print("=" * 65)
    for r in all_results:
        cid = r["case_id"]
        gt = r["target_ground_truth"]
        pred = r["ai_assessment"].get("classification")
        conf = r["ai_assessment"].get("confidence")
        unc = r["ai_assessment"].get("uncertainty")
        print(f"[{cid}] Ground Truth: {gt:<26} -> MiniMax: {pred:<24} (Conf: {conf})")
    print("=" * 65)
    print(f"Results saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
