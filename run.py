#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIREX -- Unified Command-Line Interface (CLI)
=============================================
Smart India Hackathon 2026 - Problem Statement 162
Space-Borne Satellite Thermal Incident Command & AI Intelligence Platform

Usage:
  python run.py serve               # Launch v2 console + API (port 8000)
  python run.py pipeline            # Run one end-to-end v2 analysis pass
  python run.py data                # Regenerate console/dashboard data files
  python run.py severity-sweep      # Score the whole queue with the severity engine
  python run.py migrate             # Apply pending schema migrations
  python run.py legacy              # Launch the archived v1 prototype UI (port 8002)
  python run.py v1-pipeline         # Run the archived v1 vision pipeline
  python run.py v1-daemon           # Run the archived v1 ingestion daemon
  python run.py --help              # Display options

Four subcommands -- ``pipeline``, ``data``, ``severity-sweep`` and ``migrate``
-- are handed straight to ``v2/backend/cli.py``, which owns the v2
implementations; this dispatcher does not parse their flags, so ``--help`` on
any of them is passed through to it. ``serve`` is not one of them: it launches
``v2/backend/run.py`` (the uvicorn entrypoint) as a subprocess with PORT and
HOST in the environment. ``legacy``, ``v1-pipeline`` and ``v1-daemon`` run
scripts under the archived ``v1/`` tree -- they are explicitly named so that
running one is a deliberate act, not the default.
"""
import os
import sys
import argparse
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "v2", "backend")
V2_CLI = os.path.join(BACKEND_DIR, "cli.py")

BANNER = r"""
===========================================================================
  _______ _______ ______ _______ _     _   SIH 2026 | PS 162
  |______    |    |_____/ |______  \___/    Space-Borne Satellite AI
  |          |    |    \_ |______ _/   \_   Wildfire & Industrial Intel
===========================================================================
"""

# Subcommands that are implemented by the v2 CLI. These are forwarded verbatim,
# arguments and all, so the flag sets cannot drift apart between this dispatcher
# and the implementation -- `python run.py pipeline --help` describes the run
# this command actually performs.
V2_CLI_COMMANDS = ("pipeline", "data", "severity-sweep", "migrate")

# Archived v1 entrypoints. These paths moved under v1/ when the v2 tree landed;
# the dispatcher previously pointed at the pre-move locations (`pipeline/`,
# `dashboard/`, `archive/` at the repository root) and every one of them had
# been dead ever since (R14).
V1_SCRIPTS = {
    "v1-pipeline": os.path.join("v1", "pipeline", "05_orchestrator", "run_pipeline.py"),
    "v1-daemon": os.path.join("v1", "pipeline", "07_persistence", "daemon.py"),
}
V1_LEGACY_SERVER = os.path.join("v1", "archive", "legacy_ui", "server.py")


def cmd_serve(args):
    """Launch the v2 console and API server."""
    port = args.port or 8000
    backend_script = os.path.join(BACKEND_DIR, "run.py")
    if not os.path.exists(backend_script):
        print(f"[ERROR] Backend server script not found at: {backend_script}")
        sys.exit(1)

    print(BANNER)
    print(f"[FIREX v2] Launching Space-Borne Satellite Intelligence Console on port {port}...")
    print(f"[FIREX v2] Web Console: http://127.0.0.1:{port}/console/")
    print(f"[FIREX v2] API Docs:    http://127.0.0.1:{port}/docs")
    print("-" * 75)

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"

    if getattr(args, "open", False):
        import webbrowser
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/console/")).start()

    subprocess.run([sys.executable, backend_script], cwd=BACKEND_DIR, env=env)


def delegate_to_v2_cli(argv):
    """Forward a subcommand and its arguments to v2/backend/cli.py."""
    if not os.path.exists(V2_CLI):
        print(f"[ERROR] v2 CLI not found at: {V2_CLI}")
        return 1
    return subprocess.run([sys.executable, V2_CLI] + list(argv), cwd=BACKEND_DIR).returncode


def run_v1_script(rel_path, extra_args=()):
    """Run an archived v1 script from the repository root."""
    script = os.path.join(BASE_DIR, rel_path)
    if not os.path.exists(script):
        print(f"[ERROR] Script not found at: {script}")
        return 1
    print(BANNER)
    print(f"[FIREX v1] Executing archived script: {rel_path}")
    print("-" * 75)
    return subprocess.run(
        [sys.executable, script, *extra_args],
        cwd=os.path.dirname(script),
    ).returncode


def cmd_legacy(args):
    """Launch the archived v1 prototype UI."""
    port = args.port or 8002
    print(BANNER)
    print(f"[FIREX v1] Launching Archived Legacy Prototype on port {port}...")
    print(f"[FIREX v1] Web Access:   http://localhost:{port}/")
    print("-" * 75)

    env = os.environ.copy()
    # The legacy server binds FIREX_LEGACY_PORT (v1/archive/legacy_ui/server.py:7).
    # The name set here used to be FIREX_PORT, which only the v1 dashboard and the
    # v2 static server read -- neither of which is launched from here -- so
    # `legacy --port N` printed the requested port and then bound 8002 anyway.
    env["FIREX_LEGACY_PORT"] = str(port)
    if args.open:
        # This used to set FIREX_AUTO_OPEN, which nothing in the repository reads,
        # so --open was a silent no-op. cmd_serve opens the console itself
        # (run.py:81-84); the prototype gets the same treatment.
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}/")).start()

    script = os.path.join(BASE_DIR, V1_LEGACY_SERVER)
    if not os.path.exists(script):
        print(f"[ERROR] Legacy server script not found at: {script}")
        sys.exit(1)
    subprocess.run([sys.executable, script], cwd=os.path.dirname(script), env=env)


def main():
    argv = sys.argv[1:]

    # Delegate before argparse sees the arguments: the v2 CLI owns its own flag
    # set, and this dispatcher must not silently reject or reinterpret one.
    if argv and argv[0] in V2_CLI_COMMANDS:
        sys.exit(delegate_to_v2_cli(argv))

    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="FIREX - Autonomous Satellite Thermal Intelligence & GIS Incident Command",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational Subcommands")

    serve_parser = subparsers.add_parser("serve", help="Start the v2 console + API server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    serve_parser.add_argument("--open", action="store_true", help="Automatically open browser")

    for name, help_text in (
        ("pipeline", "Run one end-to-end v2 analysis pass (see: python run.py pipeline --help)"),
        ("data", "Regenerate console/dashboard data files (see: ... data --help)"),
        ("severity-sweep", "Score the whole queue (see: ... severity-sweep --help)"),
        ("migrate", "Apply pending schema migrations (see: ... migrate --help)"),
    ):
        subparsers.add_parser(name, help=help_text, add_help=False)

    legacy_parser = subparsers.add_parser("legacy", help="Start the archived v1 prototype server")
    legacy_parser.add_argument("--port", type=int, default=8002, help="Port to bind (default: 8002)")
    legacy_parser.add_argument("--open", action="store_true", help="Automatically open browser")

    for name in V1_SCRIPTS:
        subparsers.add_parser(name, help=f"Run the archived {name[3:]} script", add_help=False)

    args = parser.parse_args(argv)

    if args.command in ("serve", None):
        if args.command is None:
            args.port = 8000
            args.open = True
        cmd_serve(args)
    elif args.command == "legacy":
        cmd_legacy(args)
    elif args.command in V1_SCRIPTS:
        sys.exit(run_v1_script(V1_SCRIPTS[args.command]))
    else:
        print(BANNER)
        parser.print_help()


if __name__ == "__main__":
    main()
