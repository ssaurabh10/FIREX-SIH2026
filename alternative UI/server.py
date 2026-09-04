# -*- coding: utf-8 -*-
"""
FIREX alternative UI - static server.

Serves this folder at /, and mounts two read-only routes so that
section6_gis_map stays completely untouched:

    /crops/...  ->  ../section3_imagery/crops/...
    /data/...   ->  ../section6_gis_map/data/...

The /crops/ mount is required because incidents.json stores absolute
image paths ("/crops/case_004/satellite_annotated.jpg").
"""

import os
import posixpath
import http.server
import socketserver
from urllib.parse import unquote, urlsplit

# 8010 unless asked otherwise, so nothing that already points at this console
# moves. FIREX_PORT exists so a second instance can be brought up beside a
# running one, which is what checking a change to this file needs.
PORT = int(os.environ.get("FIREX_PORT", "8010"))

# Loopback by default. This server has no authentication in front of it and it
# mounts two directories from outside this folder, so ("", PORT) published the
# pipeline's imagery and its data files to every interface on the machine, to
# anyone who could reach it. Opening that up is a deliberate act now, and the
# banner says which way it went:
#
#     FIREX_HOST=0.0.0.0 python server.py     # reachable from a phone or a
#                                             # second laptop on the same LAN
HOST = os.environ.get("FIREX_HOST", "127.0.0.1")

UI_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(UI_DIR)
CROPS_DIR = os.path.join(BASE_DIR, "section3_imagery", "crops")
DATA_DIR = os.path.join(BASE_DIR, "section6_gis_map", "data")

MOUNTS = (
    ("/crops/", CROPS_DIR),
    ("/data/", DATA_DIR),
)


class FirexUIHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update({
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    })

    def translate_path(self, path):
        # Drop query/fragment, decode, then collapse to a safe relative path.
        path = unquote(urlsplit(path).path)
        path = posixpath.normpath(path)

        root = UI_DIR
        for prefix, target in MOUNTS:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                root = target
                path = path[len(prefix.rstrip("/")):]
                break

        parts = [p for p in path.split("/") if p and p not in (os.curdir, os.pardir)]
        resolved = os.path.join(root, *parts)

        # Refuse anything that escaped the intended root.
        if os.path.commonpath([os.path.abspath(resolved), root]) != root:
            return root
        return resolved

    def list_directory(self, path):
        # No index of anything. send_head only reaches here for a directory with
        # no index.html, so "/" is unaffected: it is still served from this
        # folder's index.html. Everything else the console asks for it asks for
        # by name, and a walkable listing of /crops/ and /data/ only hands a
        # reader the shape of the pipeline's output. 404, not 403, so the reply
        # does not confirm the directory is there.
        self.send_error(404, "No listing available")
        return None

    def end_headers(self):
        # No Access-Control-Allow-Origin. Every fetch this console makes is same
        # origin, so a wildcard bought nothing and told any other page on the
        # machine it was welcome to read the feed.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Keep the console readable: only report failures.
        status = args[1] if len(args) > 1 else ""
        if str(status).startswith(("4", "5")):
            super().log_message(fmt, *args)


def run_server():
    os.chdir(UI_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), FirexUIHandler) as httpd:
        shown = "localhost" if HOST in ("", "0.0.0.0", "127.0.0.1") else HOST
        line = "-" * 62
        print(line)
        print("  FIREX / alternative UI")
        print(line)
        print("  Dashboard   http://%s:%d" % (shown, PORT))
        print("  Bound to    %s" % (HOST or "0.0.0.0"))
        print("  UI          %s" % UI_DIR)
        print("  /data/      %s" % DATA_DIR)
        print("  /crops/     %s" % CROPS_DIR)
        print(line)
        if HOST not in ("127.0.0.1", "localhost", "::1"):
            print("  WARNING: reachable from the network, with no authentication.")
        for label, target in (("crops", CROPS_DIR), ("data", DATA_DIR)):
            if not os.path.isdir(target):
                print("  WARNING: %s directory not found: %s" % (label, target))
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")


if __name__ == "__main__":
    run_server()
