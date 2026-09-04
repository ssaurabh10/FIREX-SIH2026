# -*- coding: utf-8 -*-
import os
import sys
import http.server
import socketserver

PORT = int(os.environ.get("FIREX_LEGACY_PORT", "8002"))
LEGACY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(LEGACY_DIR))
CROPS_DIR = os.path.join(BASE_DIR, "pipeline", "03_imagery", "crops")
DATA_DIR = os.path.join(BASE_DIR, "dashboard", "data")

class FIREXLegacyMapHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Route /crops/ to pipeline/03_imagery/crops/
        if path.startswith("/crops/"):
            rel_path = path[len("/crops/"):]
            return os.path.join(CROPS_DIR, rel_path.replace("/", os.sep))
        # Route /data/ to dashboard/data/
        if path.startswith("/data/"):
            rel_path = path[len("/data/"):]
            return os.path.join(DATA_DIR, rel_path.replace("/", os.sep))
        # Otherwise serve from previous_ui/
        rel_path = path.lstrip("/")
        return os.path.join(LEGACY_DIR, rel_path.replace("/", os.sep))

    def end_headers(self):
        # Add CORS and no-cache headers for smooth local dev
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

def run_server():
    os.chdir(LEGACY_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), FIREXLegacyMapHandler) as httpd:
        print(f"============================================================")
        print(f"  FIREX PREVIOUS / LEGACY UI (ARCHIVED)")
        print(f"============================================================")
        print(f"  Legacy Map Dashboard URL: http://localhost:{PORT}")
        print(f"  Serving Legacy UI from : {LEGACY_DIR}")
        print(f"  Mounting Data from      : {DATA_DIR}")
        print(f"  Mounting Crops from     : {CROPS_DIR}")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down legacy server.")

if __name__ == "__main__":
    run_server()
