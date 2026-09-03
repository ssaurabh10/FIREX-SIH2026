# -*- coding: utf-8 -*-
import os
import sys
import http.server
import socketserver

PORT = 8000
GIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(GIS_DIR)
CROPS_DIR = os.path.join(BASE_DIR, "section3_imagery", "crops")

class FIREXMapHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Route /crops/ to section3_imagery/crops/
        if path.startswith("/crops/"):
            rel_path = path[len("/crops/"):]
            return os.path.join(CROPS_DIR, rel_path.replace("/", os.sep))
        # Otherwise serve from section6_gis_map/
        rel_path = path.lstrip("/")
        return os.path.join(GIS_DIR, rel_path.replace("/", os.sep))

    def end_headers(self):
        # Add CORS and no-cache headers for smooth local dev
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

def run_server():
    os.chdir(GIS_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), FIREXMapHandler) as httpd:
        print(f"============================================================")
        print(f"  FIREX SECTION 6: INTERACTIVE GIS MAP SERVER")
        print(f"============================================================")
        print(f"  Map Dashboard URL: http://localhost:{PORT}")
        print(f"  Serving UI from  : {GIS_DIR}")
        print(f"  Serving Crops from: {CROPS_DIR}")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    run_server()
