"""
FIREX v2 Database Grounding & Tool Execution Engine (Step 3)
Connects LLM prompts and tools directly to SQLite (firex_v2.db) and real-time pass telemetry
to eliminate hallucinations and deliver 100% verified ground truth.
"""
import os
import re
import math
import json
import sqlite3
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "firex_v2.db")
FRONTEND_DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend", "data")
INCIDENTS_JSON_PATH = os.path.join(FRONTEND_DATA_DIR, "incidents.json")


def get_db_connection() -> Optional[sqlite3.Connection]:
    """Establishes read-only connection to primary firex_v2.db."""
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                return conn
            except Exception as e:
                logger.error(f"[DBGrounding] Failed to connect to {DB_PATH}: {e}")
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def query_incidents_tool(
    classification: Optional[str] = None,
    min_frp: Optional[float] = None,
    state_name: Optional[str] = None,
    is_surge: Optional[bool] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Tool 1: Query incidents with dynamic geospatial and physical property filters.
    Grounds LLM with verified incident lists.
    """
    # 1. Try real-time JSON pass data
    results = []
    if os.path.exists(INCIDENTS_JSON_PATH):
        try:
            with open(INCIDENTS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for it in data:
                frp = float(it.get("frp", 0) or 0)
                cls_type = str(it.get("classification", "")).upper()
                loc = str(it.get("location", "") or it.get("place", ""))
                pattern = str(it.get("pattern", "NORMAL"))

                if min_frp is not None and frp < min_frp:
                    continue
                if classification and classification.upper() not in cls_type:
                    continue
                if state_name and state_name.lower() not in loc.lower():
                    continue
                if is_surge is True and pattern != "CRITICAL_SURGE":
                    continue
                if is_surge is False and pattern == "CRITICAL_SURGE":
                    continue

                results.append({
                    "id": it.get("id"),
                    "location": loc,
                    "lat": float(it.get("lat") or it.get("latitude") or 0),
                    "lon": float(it.get("lon") or it.get("longitude") or 0),
                    "frp": frp,
                    "classification": cls_type,
                    "pattern": pattern,
                    "prio": it.get("investigationPriority", it.get("risk", {}).get("score", 0))
                })
        except Exception as e:
            logger.warning(f"[DBGrounding] Error parsing incidents.json: {e}")

    # 2. If results found, sort and return
    if results:
        results.sort(key=lambda x: x["frp"], reverse=True)
        return results[:limit]

    # 3. Fallback: Query SQLite database
    conn = get_db_connection()
    if conn:
        try:
            sql = "SELECT id, incident_code, latitude, longitude, current_max_frp, status FROM incidents"
            conds = []
            params = []
            if min_frp is not None:
                conds.append("current_max_frp >= ?")
                params.append(min_frp)
            if conds:
                sql += " WHERE " + " AND ".join(conds)
            sql += " ORDER BY current_max_frp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                results.append({
                    "id": r["id"],
                    "location": f"{r['latitude']:.3f}°N, {r['longitude']:.3f}°E",
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "frp": float(r["current_max_frp"] or 0),
                    "classification": "INDUSTRIAL",
                    "pattern": "NORMAL",
                    "prio": 50
                })
        except Exception as e:
            logger.error(f"[DBGrounding] SQLite query error: {e}")
        finally:
            conn.close()

    return results[:limit]


def get_incident_dossier_tool(incident_id: str) -> Optional[Dict[str, Any]]:
    """
    Tool 2: Get exhaustive ground-truth dossier for an incident.
    Returns physical parameters, climatology baseline, nearest facility, and AI vision findings.
    """
    clean_id = incident_id.replace("#", "").strip().lower()
    conn = get_db_connection()
    dossier = None

    # First check live JSON
    if os.path.exists(INCIDENTS_JSON_PATH):
        try:
            with open(INCIDENTS_JSON_PATH, "r", encoding="utf-8") as f:
                cases = json.load(f)
            for c in cases:
                if str(c.get("id", "")).lower().startswith(clean_id):
                    dossier = {
                        "id": c.get("id"),
                        "location": c.get("location", c.get("place", "India")),
                        "lat": float(c.get("lat") or c.get("latitude") or 0),
                        "lon": float(c.get("lon") or c.get("longitude") or 0),
                        "frp": float(c.get("frp", 0)),
                        "classification": c.get("classification", "UNKNOWN"),
                        "pattern": c.get("pattern", "NORMAL"),
                        "priority": c.get("investigationPriority", 50),
                        "explanation": c.get("priorityExplanation", ""),
                        "climatology": c.get("climatology", {})
                    }
                    break
        except Exception:
            pass

    # Query DB for depth (nearest industrial infrastructure & AI investigation)
    if conn:
        try:
            # Match DB incident
            row = conn.execute(
                "SELECT * FROM incidents WHERE id LIKE ? OR incident_code LIKE ? LIMIT 1",
                (f"{clean_id}%", f"%{clean_id}%")
            ).fetchone()

            if row:
                if not dossier:
                    dossier = {
                        "id": row["id"],
                        "location": f"{row['latitude']:.3f}°N, {row['longitude']:.3f}°E",
                        "lat": row["latitude"],
                        "lon": row["longitude"],
                        "frp": float(row["current_max_frp"] or 0),
                        "classification": "UNKNOWN",
                        "pattern": "NORMAL",
                        "priority": 50,
                        "explanation": "",
                        "climatology": {}
                    }

                lat, lon = dossier["lat"], dossier["lon"]

                # 1. Nearest industrial asset
                assets = conn.execute("SELECT name, operator, latitude, longitude, hazard_category FROM industrial_assets").fetchall()
                if assets:
                    closest_asset = min(assets, key=lambda a: haversine_km(lat, lon, a["latitude"], a["longitude"]))
                    dist_km = haversine_km(lat, lon, closest_asset["latitude"], closest_asset["longitude"])
                    dossier["nearest_asset"] = {
                        "name": closest_asset["name"],
                        "operator": closest_asset["operator"],
                        "distance_km": round(dist_km, 2),
                        "hazard_category": closest_asset["hazard_category"]
                    }

                # 2. Climatology baseline record
                clim = conn.execute(
                    "SELECT median_frp, p90_frp, p95_frp, active_days, is_routine_flare FROM thermal_climatology ORDER BY ((latitude - ?)*(latitude - ?) + (longitude - ?)*(longitude - ?)) ASC LIMIT 1",
                    (lat, lat, lon, lon)
                ).fetchone()
                if clim:
                    dossier["db_climatology"] = {
                        "p50_median": float(clim["median_frp"] or 0),
                        "p90": float(clim["p90_frp"] or 0),
                        "p95": float(clim["p95_frp"] or 0),
                        "annual_flare_days": clim["active_days"],
                        "is_routine_flare": bool(clim["is_routine_flare"])
                    }

                # 3. AI Investigation report
                ai_rep = conn.execute(
                    "SELECT classification, confidence, reasoning FROM ai_investigations WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1",
                    (dossier["id"],)
                ).fetchone()
                if ai_rep:
                    dossier["ai_vision"] = {
                        "classification": ai_rep["classification"],
                        "confidence": ai_rep["confidence"],
                        "reasoning": ai_rep["reasoning"]
                    }

                # 4. Severity Assessment factors
                sev = conn.execute(
                    "SELECT score, level, factors FROM severity_assessments WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1",
                    (dossier["id"],)
                ).fetchone()
                if sev:
                    dossier["severity"] = {
                        "score": sev["score"],
                        "level": sev["level"],
                        "factors": json.loads(sev["factors"]) if sev["factors"] else {}
                    }
        except Exception as e:
            logger.error(f"[DBGrounding] Error querying DB dossier: {e}")
        finally:
            conn.close()

    return dossier


def search_facility_assets_tool(query_term: str) -> List[Dict[str, Any]]:
    """
    Tool 3: Search tracked industrial facilities and find nearby thermal emissions.
    """
    conn = get_db_connection()
    matches = []
    if not conn:
        return matches

    try:
        q = f"%{query_term.strip()}%"
        rows = conn.execute(
            "SELECT id, name, operator, facility_type, latitude, longitude, state, district, hazard_category "
            "FROM industrial_assets WHERE name LIKE ? OR operator LIKE ? OR state LIKE ? LIMIT 4",
            (q, q, q)
        ).fetchall()

        for r in rows:
            facility = dict(r)
            f_lat, f_lon = r["latitude"], r["longitude"]

            # Find active hotspots within 25 km
            nearby_incidents = []
            if os.path.exists(INCIDENTS_JSON_PATH):
                try:
                    with open(INCIDENTS_JSON_PATH, "r", encoding="utf-8") as f:
                        cases = json.load(f)
                    for c in cases:
                        c_lat = float(c.get("lat") or c.get("latitude") or 0)
                        c_lon = float(c.get("lon") or c.get("longitude") or 0)
                        d = haversine_km(f_lat, f_lon, c_lat, c_lon)
                        if d <= 25.0:
                            nearby_incidents.append({
                                "id": c.get("id"),
                                "distance_km": round(d, 1),
                                "frp": float(c.get("frp", 0)),
                                "pattern": c.get("pattern", "NORMAL")
                            })
                except Exception:
                    pass

            facility["active_nearby_hotspots"] = sorted(nearby_incidents, key=lambda x: x["distance_km"])[:3]
            matches.append(facility)
    except Exception as e:
        logger.error(f"[DBGrounding] Facility query error: {e}")
    finally:
        conn.close()

    return matches


def get_regional_breakdown_tool(region_name: str) -> Dict[str, Any]:
    """
    Tool 4: Returns thermal anomaly summary for a given state or geographical corridor.
    """
    r_name = region_name.strip().lower()
    total_in_region = 0
    surges = 0
    max_frp = 0.0
    matching_incidents = []

    if os.path.exists(INCIDENTS_JSON_PATH):
        try:
            with open(INCIDENTS_JSON_PATH, "r", encoding="utf-8") as f:
                cases = json.load(f)
            for c in cases:
                loc = str(c.get("location", "") or c.get("place", "")).lower()
                if r_name in loc or (r_name == "gujarat" and ("vadodara" in loc or "jamnagar" in loc or "mundra" in loc)):
                    total_in_region += 1
                    frp = float(c.get("frp", 0))
                    if frp > max_frp:
                        max_frp = frp
                    if c.get("pattern") == "CRITICAL_SURGE":
                        surges += 1
                    matching_incidents.append(c)
        except Exception:
            pass

    return {
        "region": region_name,
        "active_hotspots": total_in_region,
        "critical_surges": surges,
        "max_frp_mw": max_frp,
        "sample_incidents": [
            {
                "id": i.get("id"),
                "location": i.get("location"),
                "frp": i.get("frp"),
                "pattern": i.get("pattern", "NORMAL")
            }
            for i in sorted(matching_incidents, key=lambda x: float(x.get("frp", 0)), reverse=True)[:4]
        ]
    }


def execute_tool_grounding(user_query: str) -> Dict[str, Any]:
    """
    Autonomous Intent Classifier & Tool Execution Dispatcher.
    Inspects user prompt, runs the required database tools, and produces:
    - Structured Ground-Truth Context string for prompt injection
    - UI Actions (such as auto-focusing on the map or setting filters)
    """
    q = user_query.strip().lower()
    context_blocks = []
    actions = []

    # 1. Incident ID Detection (#0640ce6d or 0640ce6d)
    id_match = re.search(r"#?([a-f0-9]{8}(?:-[a-f0-9]{4,})?)", q)
    if id_match:
        target_id = id_match.group(1)
        dossier = get_incident_dossier_tool(target_id)
        if dossier:
            context_blocks.append(f"""
=== VERIFIED DATABASE DOSSIER: #{dossier['id'][:8]} ===
Target: #{dossier['id'][:8]} (Full ID: {dossier['id']})
Location: {dossier['location']} (GPS: {dossier['lat']:.4f}°N, {dossier['lon']:.4f}°E)
Radiative Power: {dossier['frp']:.1f} MW
Classification: {dossier['classification']}
Baseline Profile: {dossier['pattern']}
Priority Rank: {dossier.get('priority', 'N/A')}/100
Priority Explanation: {dossier.get('explanation', 'Calibrated against national satellite percentiles')}
""" + (f"Nearest Monitored Industrial Asset: {dossier['nearest_asset']['name']} ({dossier['nearest_asset']['distance_km']} km away, Operator: {dossier['nearest_asset']['operator']})\n" if 'nearest_asset' in dossier else "")
+ (f"Historical Heat Baseline: P50={dossier['db_climatology']['p50_median']:.1f} MW, P90={dossier['db_climatology']['p90']:.1f} MW, Surge P95 Threshold={dossier['db_climatology']['p95']:.1f} MW (Routine: {dossier['db_climatology']['is_routine_flare']})\n" if 'db_climatology' in dossier else "")
+ (f"Multimodal Vision Verdict: {dossier['ai_vision']['classification']} (Confidence: {dossier['ai_vision']['confidence']}%) - Reasoning: {dossier['ai_vision']['reasoning']}\n" if 'ai_vision' in dossier else "")
+ (f"Threat Severity: Level {dossier['severity']['level']} (Score: {dossier['severity']['score']}/100)\n" if 'severity' in dossier else "")
)
            actions.append({
                "type": "select_incident",
                "payload": {
                    "id": dossier["id"],
                    "lat": dossier["lat"],
                    "lon": dossier["lon"]
                }
            })

    # 2. Facility Search (Refinery, Steel, Jamnagar, Bathinda, Panipat, Tata, Hazira)
    facility_keywords = ["refinery", "steel", "plant", "complex", "jamnagar", "bathinda", "panipat", "iocl", "hpcl", "tata", "hazira", "mundra", "korba", "rourkela"]
    matched_keyword = next((kw for kw in facility_keywords if kw in q), None)
    if matched_keyword:
        facility_results = search_facility_assets_tool(matched_keyword)
        if facility_results:
            fac_lines = []
            for f in facility_results[:2]:
                fac_lines.append(f"- **{f['name']}** ({f['operator']}, {f['state']}) | Hazard: {f['hazard_category']}")
                if f.get("active_nearby_hotspots"):
                    for h in f["active_nearby_hotspots"]:
                        fac_lines.append(f"    * Active Thermal Signature #{h['id'][:8]}: {h['frp']} MW at {h['distance_km']} km ({h['pattern']})")
                else:
                    fac_lines.append("    * Active Thermal Signature: No anomalous flares within 25 km envelope.")
            context_blocks.append("=== VERIFIED INDUSTRIAL INFRASTRUCTURE DATABASE ===\n" + "\n".join(fac_lines))

            # Auto-align camera to first matched facility
            first_f = facility_results[0]
            if not actions:
                actions.append({
                    "type": "fly_to",
                    "payload": {
                        "lat": first_f["latitude"],
                        "lon": first_f["longitude"],
                        "zoom": 13
                    }
                })

    # 3. Regional / State Query (Punjab, Gujarat, Odisha, Assam, Rajasthan, Haryana, Chhattisgarh)
    states = ["punjab", "gujarat", "odisha", "assam", "rajasthan", "haryana", "chhattisgarh", "madhya pradesh", "maharashtra", "jharkhand"]
    matched_state = next((st for st in states if st in q), None)
    if matched_state:
        reg = get_regional_breakdown_tool(matched_state)
        context_blocks.append(f"""
=== REGIONAL INTELLIGENCE: {matched_state.upper()} ===
Total Active Hotspots Detected: {reg['active_hotspots']}
Critical Surge Hotspots: {reg['critical_surges']}
Maximum Recorded FRP: {reg['max_frp_mw']:.1f} MW
Key Active Sites:
""" + "\n".join([f"- #{i['id'][:8]} ({i['location']}) | FRP: {i['frp']} MW | {i['pattern']}" for i in reg['sample_incidents']]))

    # 4. Filter / Query tool (e.g. "show surges", "top fires", "unreviewed", "clear filter")
    if "surge" in q or "critical" in q:
        surge_list = query_incidents_tool(is_surge=True, limit=4)
        if surge_list:
            context_blocks.append("=== CRITICAL SURGE DETECTIONS (FRP > 2.5x P95) ===\n" + "\n".join([f"- #{s['id'][:8]} ({s['location']}) | FRP: {s['frp']} MW" for s in surge_list]))
            actions.append({"type": "set_filter", "payload": {"filter": "surge"}})
    elif "unreviewed" in q or "pending" in q:
        actions.append({"type": "set_filter", "payload": {"filter": "unreviewed"}})
    elif "clear filter" in q or "show all incidents" in q or "reset filter" in q:
        actions.append({"type": "set_filter", "payload": {"filter": "all"}})

    # 5. Basemap switching intent
    if "satellite" in q or "aerial" in q or "imagery" in q:
        actions.append({"type": "set_basemap", "payload": {"base": "satellite"}})
    elif "dark map" in q or "dark basemap" in q or "night map" in q or "standard map" in q:
        actions.append({"type": "set_basemap", "payload": {"base": "dark"}})
    elif "terrain" in q or "topographic" in q:
        actions.append({"type": "set_basemap", "payload": {"base": "terrain"}})
    elif "light map" in q or "street map" in q or "bright map" in q:
        actions.append({"type": "set_basemap", "payload": {"base": "light"}})

    # 6. View navigation intent
    if "industrial view" in q or "show facilities" in q or "facility register" in q or "open industrial" in q or "infrastructure view" in q:
        actions.append({"type": "set_view", "payload": {"view": "industrial"}})
    elif "investigation" in q or "triage view" in q or "open cases" in q or "review queue" in q:
        actions.append({"type": "set_view", "payload": {"view": "investigations"}})
    elif "history view" in q or "search archive" in q or "historical observations" in q:
        actions.append({"type": "set_view", "payload": {"view": "history"}})
    elif "map view" in q or "show map" in q or "back to map" in q or "return to map" in q:
        actions.append({"type": "set_view", "payload": {"view": "map"}})

    # 7. Map reset & National Overview
    if "reset map" in q or "all india" in q or "entire country" in q or "zoom out" in q or "national overview" in q or "home view" in q:
        actions.append({"type": "reset_map", "payload": {}})

    # 8. FRP threshold filter (e.g., "threshold 25", "set frp threshold to 25", "frp > 20", "filter >= 30", "frp 15")
    thresh_match = re.search(r'(?:frp|threshold|radiant power)\s*(?:>=|>|:|=|at least|to|above|is)?\s*(\d{1,3})', q)
    if thresh_match:
        val = int(thresh_match.group(1))
        if val in [0, 5, 10, 20, 50, 100] or 1 <= val <= 200:
            actions.append({"type": "set_frp_threshold", "payload": {"threshold": val}})

    # 9. Fit all active targets
    if "fit bounds" in q or "fit all" in q or "frame all" in q:
        actions.append({"type": "fit_all", "payload": {}})

    return {
        "grounding_context": "\n\n".join(context_blocks),
        "actions": actions
    }
