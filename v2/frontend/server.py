# -*- coding: utf-8 -*-
"""
FIREX Unified Command Platform - Primary Server (Section 6).
Serves the permanent GIS Command UI at /, mounts ../section3_imagery/crops/ at /crops/,
and provides live hot reloading headers and MIME types.
"""

import os
import sys
import json
import posixpath
import http.server
import socketserver
import time
from datetime import datetime
from urllib.parse import unquote, urlsplit
import urllib.request
import re

PORT = int(os.environ.get("FIREX_PORT", "8000"))
HOST = os.environ.get("FIREX_HOST", "127.0.0.1")

GIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(GIS_DIR)
CROPS_DIR = os.path.join(BASE_DIR, "pipeline", "03_imagery", "crops")
DATA_DIR = os.path.join(GIS_DIR, "data")


class FIREXMapHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update({
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    })

    def translate_path(self, path):
        # Drop query/fragment, decode, then collapse to safe relative path
        path = unquote(urlsplit(path).path)
        path = posixpath.normpath(path)

        if path == "/crops" or path.startswith("/crops/"):
            rel_path = path.replace("/crops", "", 1).lstrip("/")
            return os.path.join(CROPS_DIR, *[p for p in rel_path.split("/") if p and p not in (os.curdir, os.pardir)])

        rel_path = path.lstrip("/")
        parts = [p for p in rel_path.split("/") if p and p not in (os.curdir, os.pardir)]
        return os.path.join(GIS_DIR, *parts)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/health":
            payload = json.dumps({"status": "OK", "timestamp": datetime.now().isoformat()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/api/history-stats":
            try:
                _pers_dir = os.path.join(BASE_DIR, "pipeline", "07_persistence")
                if _pers_dir not in sys.path:
                    sys.path.insert(0, _pers_dir)
                import history_db
                stats = history_db.get_stats()
                now = datetime.now()
                pass_type = "DAY" if 6 <= now.hour < 18 else "NIGHT"
                data = {
                    "total_runs": stats.get("total_runs", 0),
                    "total_hotspots": stats.get("total_hotspots", 0),
                    "unique_dates": stats.get("unique_dates", 0),
                    "last_run": stats.get("last_run", "Never"),
                    "current_pass": pass_type,
                    "cadence": "2x Daily (12-Hour Cadence)",
                    "overpass_times": "14:00 IST (Day) / 02:30 IST (Night)"
                }
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                err_payload = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_payload)))
                self.end_headers()
                self.wfile.write(err_payload)
                return

        elif parsed.path == "/api/trigger-sync-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def send_event(stage, pct, label, detail, extra=None):
                event_data = {
                    "stage": stage,
                    "pct": pct,
                    "label": label,
                    "detail": detail,
                    "extra": extra or {},
                    "done": (pct >= 100)
                }
                msg = f"data: {json.dumps(event_data)}\n\n"
                try:
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass

            try:
                import importlib
                if GIS_DIR not in sys.path:
                    sys.path.insert(0, GIS_DIR)
                import prepare_map_data
                importlib.reload(prepare_map_data)

                now = datetime.now()
                current_pass = "DAY" if 6 <= now.hour < 18 else "NIGHT"
                send_event(0, 5, "Initializing Mission Orbit Pipeline", f"Starting {current_pass} pass telemetry sync and persistence engine...")
                time.sleep(0.3)

                prepare_map_data.prepare_data(pass_type=current_pass, progress_cb=send_event)
            except Exception as e:
                send_event(5, 100, "Sync Error", str(e), {"error": True})
            return

        elif parsed.path == "/api/trigger-sync":
            try:
                import importlib
                if GIS_DIR not in sys.path:
                    sys.path.insert(0, GIS_DIR)
                import prepare_map_data
                importlib.reload(prepare_map_data)
                now = datetime.now()
                current_pass = "DAY" if 6 <= now.hour < 18 else "NIGHT"
                prepare_map_data.prepare_data(pass_type=current_pass)

                _pers_dir = os.path.join(BASE_DIR, "pipeline", "07_persistence")
                if _pers_dir not in sys.path:
                    sys.path.insert(0, _pers_dir)
                import history_db
                stats = history_db.get_stats()
                data = {
                    "status": "SUCCESS",
                    "stats": stats,
                    "message": "Satellite pass telemetry ingested and GIS layers updated."
                }
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as e:
                err_payload = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_payload)))
                self.end_headers()
                self.wfile.write(err_payload)
                return

        return super().do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/chat":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                try:
                    body = json.loads(raw_body)
                except Exception:
                    body = {}

                user_msg = body.get("message", "").strip()
                history = body.get("history", [])

                total_inc = 58
                inc_data = []
                live_context = ""
                try:
                    inc_file = os.path.join(DATA_DIR, "incidents.json")
                    if os.path.exists(inc_file):
                        with open(inc_file, "r", encoding="utf-8") as f:
                            inc_data = json.load(f)
                        total_inc = len(inc_data)
                        surges = [i for i in inc_data if i.get("pattern") == "CRITICAL_SURGE" or i.get("is_surge")]
                        top_by_frp = sorted(inc_data, key=lambda x: float(x.get("frp", 0) or 0), reverse=True)[:5]

                        sample_lines = []
                        for it in top_by_frp:
                            sample_lines.append(f"- #{it.get('id', '')[:8]} | {it.get('location', 'Unknown')} | {it.get('classification', '')} | FRP: {float(it.get('frp', 0)):.1f} MW | Pattern: {it.get('pattern', 'NORMAL')}")

                        live_context = f"""
LIVE MISSION TELEMETRY (Current Orbit Pass):
Total Qualified Thermal Targets: {total_inc}
Critical Surge Targets Flagged: {len(surges)}
Top Thermal Anomalies:
{chr(10).join(sample_lines)}
"""
                except Exception:
                    live_context = "Telemetry DB online. Incident tracking active."

                # Step 3: Database Grounding & Tool Execution
                # Database Grounding for Telemetry Knowledge
                tool_context = ""
                try:
                    backend_dir = os.path.join(os.path.dirname(GIS_DIR), "backend")
                    if backend_dir not in sys.path:
                        sys.path.insert(0, backend_dir)
                    from app.intelligence.db_grounding import execute_tool_grounding
                    tool_res = execute_tool_grounding(user_msg)
                    tool_context = tool_res.get("grounding_context", "")
                except Exception as dbg_err:
                    print("[ServerChat] db_grounding fallback:", dbg_err)

                system_prompt = f"""You are the FIREX Assistant — a helpful, clear, and friendly AI chatbot for the FIREX Thermal Anomaly Monitoring Platform (developed for SIH 2026 Problem Statement 162).
You explain how the platform detects thermal anomalies, forest fires, and industrial flaring across India using NASA VIIRS/MODIS satellites, 365-day diurnal P95 historical baselines, and optical satellite imagery.

CURRENT LIVE MISSION TELEMETRY:
{live_context}

CONTEXT & KNOWLEDGE:
{tool_context}

Guidelines:
1. Act like a usual, friendly AI chatbot (like ChatGPT or Claude).
2. Answer the user's questions in simple, plain, easy-to-understand English.
3. Be concise and well-structured: use short paragraphs or clean bullet points.
4. Explain technical concepts simply (for example: explain FRP as the heat intensity of a fire, and explain the diurnal baseline as normal day/night temperature cycles so factory chimneys are not mistaken for wildfires).
5. DO NOT provide command tags, edit options, filter options, or map control tags (no [FILTER], no [TARGET], etc.). You are purely a conversational chat assistant.
6. ABSOLUTE CONSTRAINT: DO NOT USE ANY EMOJIS in your responses. Zero emojis.
"""

                messages = [{"role": "system", "content": system_prompt}]
                for h in history[-6:]:
                    role = "user" if h.get("role") == "user" else "assistant"
                    messages.append({"role": role, "content": h.get("content", "")})
                messages.append({"role": "user", "content": user_msg})

                reply_text = None
                openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
                offline_mode = os.environ.get("FIREX_OFFLINE", "0") == "1"

                if not offline_mode and openrouter_key:
                    candidate_models = [
                        "dots-studio/dots-3-note-preview:free",
                        "liquid/lfm-2.5-2.6b:free",
                        "nvidia/nemotron-3.5-lightning:free",
                        "qwen/qwen3.8-27b:free"
                    ]
                    for model_name in candidate_models:
                        try:
                            payload = json.dumps({
                                "model": model_name,
                                "messages": messages,
                                "temperature": 0.4,
                                "max_tokens": 400
                            }).encode("utf-8")
                            req = urllib.request.Request(
                                "https://openrouter.ai/api/v1/chat/completions",
                                data=payload,
                                headers={
                                    "Authorization": f"Bearer {openrouter_key}",
                                    "Content-Type": "application/json",
                                    "HTTP-Referer": "http://127.0.0.1:8000",
                                    "X-Title": "FIREX Assistant"
                                }
                            )
                            with urllib.request.urlopen(req, timeout=12) as resp:
                                res = json.loads(resp.read().decode("utf-8"))
                                choice = res.get("choices", [{}])[0].get("message", {})
                                raw_content = choice.get("content") or choice.get("reasoning") or ""
                                raw_content = raw_content.strip()
                                if raw_content:
                                    reply_text = raw_content
                                    break
                        except Exception as api_err:
                            print(f"[ServerChat] OpenRouter model {model_name} failed: {api_err}")
                            continue

                if not reply_text:
                    q_lower = user_msg.lower()
                    if "surge" in q_lower or "critical" in q_lower:
                        top_surges = surges[:3] if surges else top_by_frp[:3]
                        s_lines = [f"- Hotspot #{s.get('id', '')[:8]} in {s.get('location', 'India')}: {float(s.get('frp', 0)):.1f} MW heat output (Status: Critical Surge)" for s in top_surges]
                        reply_text = f"There are currently {len(surges)} critical surge hotspots detected across India out of {total_inc} monitored locations.\n\nKey hotspots:\n" + "\n".join(s_lines) + "\n\nA critical surge means the detected thermal heat is more than 2.5 times higher than the location's normal historical baseline."
                    elif "ps162" in q_lower or "problem statement" in q_lower or "sih" in q_lower or "objective" in q_lower or "what is firex" in q_lower:
                        reply_text = """FIREX is an autonomous thermal anomaly monitoring system developed for Smart India Hackathon (SIH 2026 Problem Statement 162).

Its primary goals are:
- Detect potential forest fires and thermal hotspots across India in near real-time using NASA satellites.
- Eliminate false alarms caused by industrial sites, like refinery flare stacks, power plants, and brick kilns.
- Provide emergency response teams and forest departments with verified fire incidents ranked by severity."""
                    elif "false alarm" in q_lower or "accuracy" in q_lower or "precision" in q_lower:
                        reply_text = """FIREX prevents false alarms using historical baselines and geospatial mapping:

1. Diurnal Historical Baseline: The system tracks 365 days of temperature data for every location. If an industrial chimney routinely radiates heat, FIREX marks it as normal.
2. Anomaly Ratio: An alert is only triggered if heat spikes significantly above normal levels (more than 2.5 times the 95th percentile).
3. Industrial Asset Mapping: Hotspots are cross-checked with known refineries and factories so routine industrial activity isn't mistaken for a forest fire."""
                    elif "p95" in q_lower or "baseline" in q_lower:
                        reply_text = """The 365-day P95 baseline is a statistical threshold that represents the normal heat level for a specific coordinate:

- P95 stands for the 95th percentile of heat observations over the past year.
- 95% of normal daily readings fall below this line.
- If a new satellite observation exceeds this baseline significantly, FIREX flags it as a true anomaly or potential wildfire rather than everyday background heat."""
                    elif "score" in q_lower or "severity" in q_lower or "priority" in q_lower or "formula" in q_lower:
                        reply_text = """FIREX calculates a composite priority score from 0 to 100 based on four factors:

- Fire Radiative Power (35%): How intense the heat emission is compared to normal.
- Infrastructure Proximity (30%): How close the fire is to hazardous sites or communities.
- Day vs. Night Timing (20%): Nighttime anomalies receive higher priority because forest fires at night are more dangerous.
- Multimodal AI Inspection (15%): Computer vision analysis confirming active fire or smoke plumes."""
                    elif "satellite" in q_lower or "sensor" in q_lower or "viirs" in q_lower or "firms" in q_lower:
                        reply_text = """FIREX uses NASA VIIRS and MODIS satellite instruments:

- VIIRS (Visible Infrared Imaging Radiometer Suite): Flown on Suomi-NPP and NOAA-20 satellites, offering 375-meter thermal resolution.
- Pass Schedule: Satellites pass over India twice a day (daytime around 1:30 PM IST and nighttime around 2:00 AM IST).
- Optical Imagery: Sentinel-2 and high-resolution optical surface imagery are also used to visually verify flagged areas."""
                    else:
                        top_lines = [f"- Hotspot #{i.get('id', '')[:8]} in {i.get('location', 'India')}: {float(i.get('frp', 0)):.1f} MW" for i in top_by_frp[:3]]
                        reply_text = f"Currently, FIREX is monitoring {total_inc} active thermal locations across India, including {len(surges)} critical surge detections.\n\nTop heat locations:\n" + "\n".join(top_lines) + "\n\nFeel free to ask any question about how FIREX detects fires, satellite passes, or how false alarms are filtered."

                resp_payload = json.dumps({
                    "reply": reply_text,
                    "actions": [],
                    "telemetry": {"total_targets": total_inc, "surge_targets": len(surges)},
                    "status": "ok"
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(resp_payload)
                self.wfile.flush()
                return
            except Exception as e:
                import traceback
                traceback.print_exc()
                err_payload = json.dumps({"error": str(e), "reply": "FIREX AI telemetry service temporarily interrupted. Local thermal database remains fully functional."}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(err_payload)
                self.wfile.flush()
                return

        self.send_error(404, "Endpoint not found")


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_server():
    os.chdir(GIS_DIR)
    with ThreadingServer((HOST, PORT), FIREXMapHandler) as httpd:
        shown = "localhost" if HOST in ("", "0.0.0.0", "127.0.0.1") else HOST
        print("=" * 62)
        print("  FIREX GIS CONSOLE (STANDALONE)")
        print("  (Note: backend/run.py is the canonical full-stack runner)")
        print("=" * 62)
        print("  Dashboard URL : http://%s:%d" % (shown, PORT))
        print("  UI Directory  : %s" % GIS_DIR)
        print("  Data Directory: %s" % DATA_DIR)
        print("  Crops Mount   : %s" % CROPS_DIR)
        print("=" * 62)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


if __name__ == "__main__":
    run_server()
