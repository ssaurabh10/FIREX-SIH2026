#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIREX -- Unified Command-Line Interface (CLI)
=============================================
Smart India Hackathon 2026 - Problem Statement 162
Space-Borne Satellite Thermal Incident Command & AI Intelligence Platform

Usage:
  python run.py serve              # Launch primary GIS Dashboard (port 8000)
  python run.py pipeline           # Run Section 5 End-to-End Vision AI Pipeline
  python run.py data               # Prepare & score FIRMS incident map data
  python run.py legacy             # Launch archived legacy prototype (port 8002)
  python run.py --help             # Display options
"""

import os
import sys
import argparse
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BANNER = r"""
===========================================================================
  _______ _______ ______ _______ _     _   SIH 2026 | PS 162
  |______    |    |_____/ |______  \___/    Space-Borne Satellite AI
  |          |    |    \_ |______ _/   \_   Wildfire & Industrial Intel
===========================================================================
"""

def cmd_serve(args):
    """Launch the primary GIS Dashboard server."""
    port = args.port or 8000
    server_script = os.path.join(BASE_DIR, "dashboard", "server.py")
    if not os.path.exists(server_script):
        print(f"[ERROR] Dashboard server script not found at: {server_script}")
        sys.exit(1)
    
    print(BANNER)
    print(f"[FIREX] Launching Unified GIS Command Center on port {port}...")
    print(f"[FIREX] Serving from: {os.path.join(BASE_DIR, 'dashboard')}")
    print(f"[FIREX] Web Access:   http://localhost:{port}/")
    print("-" * 75)
    
    env = os.environ.copy()
    env["FIREX_PORT"] = str(port)
    if args.open:
        env["FIREX_AUTO_OPEN"] = "1"
    subprocess.run([sys.executable, server_script], cwd=BASE_DIR, env=env)

def cmd_pipeline(args):
    """Execute the end-to-end AI detection & classification pipeline."""
    script = os.path.join(BASE_DIR, "pipeline", "05_orchestrator", "run_pipeline.py")
    if not os.path.exists(script):
        print(f"[ERROR] Pipeline orchestrator not found at: {script}")
        sys.exit(1)
    
    print(BANNER)
    print("[FIREX] Executing End-to-End Satellite Intelligence Pipeline...")
    print("-" * 75)
    subprocess.run([sys.executable, script], cwd=os.path.join(BASE_DIR, "pipeline", "05_orchestrator"))

def cmd_data(args):
    """Prepare and enrich FIRMS detections and AI assessments for the dashboard."""
    script = os.path.join(BASE_DIR, "dashboard", "prepare_map_data.py")
    if not os.path.exists(script):
        print(f"[ERROR] Data prep script not found at: {script}")
        sys.exit(1)
    
    print(BANNER)
    print("[FIREX] Refreshing and Scoring GIS Incident Datasets...")
    print("-" * 75)
    subprocess.run([sys.executable, script], cwd=BASE_DIR)

def cmd_legacy(args):
    """Launch the archived legacy prototype."""
    port = args.port or 8002
    server_script = os.path.join(BASE_DIR, "archive", "legacy_ui", "server.py")
    if not os.path.exists(server_script):
        print(f"[ERROR] Legacy server script not found at: {server_script}")
        sys.exit(1)
    
    print(BANNER)
    print(f"[FIREX] Launching Archived Legacy Prototype on port {port}...")
    print(f"[FIREX] Serving from: {os.path.join(BASE_DIR, 'archive', 'legacy_ui')}")
    print(f"[FIREX] Web Access:   http://localhost:{port}/")
    print("-" * 75)
    
    env = os.environ.copy()
    env["FIREX_PORT"] = str(port)
    if args.open:
        env["FIREX_AUTO_OPEN"] = "1"
    subprocess.run([sys.executable, server_script], cwd=BASE_DIR, env=env)

def main():
    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="FIREX - Autonomous Satellite Thermal Intelligence & GIS Incident Command"
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational Subcommands")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the primary GIS Dashboard server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    serve_parser.add_argument("--open", action="store_true", help="Automatically open browser")

    # pipeline command
    subparsers.add_parser("pipeline", help="Run the automated Section 5 AI intelligence pipeline")

    # data command
    subparsers.add_parser("data", help="Synchronize, score, and compile GIS incident datasets")

    # legacy command
    legacy_parser = subparsers.add_parser("legacy", help="Start the archived legacy prototype server")
    legacy_parser.add_argument("--port", type=int, default=8002, help="Port to bind (default: 8002)")
    legacy_parser.add_argument("--open", action="store_true", help="Automatically open browser")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    elif args.command == "data":
        cmd_data(args)
    elif args.command == "legacy":
        cmd_legacy(args)
    else:
        print(BANNER)
        parser.print_help()

if __name__ == "__main__":
    main()
