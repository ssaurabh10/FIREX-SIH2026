# -*- coding: utf-8 -*-
"""
FIREX Unified Command Platform - Primary Server (Section 6).
Serves the permanent GIS Command UI at /, mounts ../section3_imagery/crops/ at /crops/,
and provides live hot reloading headers and MIME types.
"""

import os
import sys
import posixpath
import http.server
import socketserver
from urllib.parse import unquote, urlsplit

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
            rel_path = path[len("/crops/"):]
            return os.path.join(CROPS_DIR, *[p for p in rel_path.split("/") if p and p not in (os.curdir, os.pardir)])

        rel_path = path.lstrip("/")
        parts = [p for p in rel_path.split("/") if p and p not in (os.curdir, os.pardir)]
        return os.path.join(GIS_DIR, *parts)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def run_server():
    os.chdir(GIS_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), FIREXMapHandler) as httpd:
        shown = "localhost" if HOST in ("", "0.0.0.0", "127.0.0.1") else HOST
        print("=" * 62)
        print("  FIREX UNIFIED COMMAND PLATFORM (PRIMARY)")
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
