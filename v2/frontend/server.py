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

# Safely load local .env if present (gitignored)
def _load_env():
    for path in [os.path.join(BASE_DIR, ".env"), os.path.join(os.path.dirname(BASE_DIR), ".env")]:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
_load_env()


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

                # Embed full FIREX prototype knowledge so the LLM answers revolve around this prototype
                system_prompt = f"""You are the FIREX Assistant — the dedicated AI helper for the FIREX Prototype (SIH 2026 Problem Statement 162: Autonomous Thermal Anomaly Detection & Monitoring Platform for India).

CORE PROTOTYPE DOMAIN KNOWLEDGE (Use these definitions in your answers):
1. What is FRP?
   - FRP stands for "Fire Radiative Power", measured in Megawatts (MW).
   - It quantifies the rate of radiant heat energy emitted by a thermal anomaly, detected by satellite infrared sensors (NASA VIIRS 375m band I4 at 3.9 μm).
   - In FIREX, FRP indicates fire intensity, fuel combustion rate, and is compared against the 365-day historical baseline to detect surges. Higher FRP = more intense fire.

2. What is the 365-Day Diurnal P95 Baseline?
   - For every 0.02° grid cell across India (~2.2 km), FIREX maintains a 365-day historical baseline of FRP percentiles (P50, P90, P95) separated by Day passes (~13:30 IST) and Night passes (~01:30 IST).
   - This eliminates false alarms on routine industrial sources (petroleum refineries in Jamnagar/Vadodara, steel plants like JSW Steel Vijayanagar, blast furnaces, brick kilns) because their normal heat stays within their historical P95 baseline.

3. What is a Critical Surge?
   - An anomaly where detected FRP exceeds 2.5 times (>2.5x) the location's historical 365-day P95 envelope. This flags uncontrolled wildfires, crop burn spikes, or industrial flaring blowouts.

4. Multi-Factor Priority Score (0–100):
   - Combines FRP anomaly surge ratio, proximity (<5 km) to monitored industrial assets/refineries, diurnal pass timing, and AI optical validation. High score = higher investigation priority.

5. Prototype Features & UI:
   - Live Map: Leaflet GIS displaying active thermal hotspots, basemap switcher (Canvas vs Satellite Imagery), and FRP filters (All, ≥2 MW, ≥5 MW).
   - Left Sidebar (Priority Incidents): Queue of ranked incidents with category badges (Agricultural, Industrial, Flare, Wildfire, Mining, Surge).
   - Tactical Dossier: Slide-out panel showing optical Sentinel-2 crop, thermal bounding box, diurnal FRP comparison graph, and nearest monitored industrial asset.

6. Current Live Satellite Pass Telemetry:
   - Active Qualified Hotspots: {total_inc} across India
   - Critical Surge Hotspots: {len(surges)}
   - Top Detected Hotspots Right Now:
{chr(10).join(sample_lines)}

CONVERSATION GUIDELINES:
- Ground your answers around the FIREX prototype, its metrics (FRP in MW, P95 baseline, false alarm suppression), and live telemetry.
- When asked "what is frp?", explain clearly that it stands for Fire Radiative Power (MW), measures radiant heat energy, and is used in FIREX to measure fire intensity and detect surges against historical baselines.
- Keep answers clear, natural, and concise (2 to 4 sentences).
- Do not use robotic military prefixes (e.g. do not say "SITREP").
- Do not offer options or buttons to edit/filter the map.
"""

                messages = [{"role": "system", "content": system_prompt}]
                for h in history[-6:]:
                    role = "user" if h.get("role") == "user" else "assistant"
                    messages.append({"role": role, "content": h.get("content", "")})
                messages.append({"role": "user", "content": user_msg})

                reply_text = None
                openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

                candidate_models = [
                    "dots-studio/dots-3-note-preview:free",
                    "meta-llama/llama-3.1-8b-instruct",
                    "meta-llama/llama-3.2-3b-instruct",
                    "mistralai/mistral-small-24b-instruct-2501",
                    "meta-llama/llama-3.2-1b-instruct"
                ]

                last_error = None
                for model_name in candidate_models:
                    try:
                        payload = json.dumps({
                            "model": model_name,
                            "messages": messages,
                            "temperature": 0.4,
                            "max_tokens": 250
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
                        with urllib.request.urlopen(req, timeout=12.0) as resp:
                            res = json.loads(resp.read().decode("utf-8"))
                            reply_text = res["choices"][0]["message"]["content"]
                            if reply_text and reply_text.strip():
                                print(f"[ServerChat] Live response generated by {model_name}")
                                break
                    except Exception as err:
                        last_error = str(err)
                        print(f"[ServerChat] Model {model_name} failed: {err}")
                        continue

                if not reply_text:
                    reply_text = f"API Error: Unable to retrieve response from AI model ({last_error}). Please check your connection."

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
