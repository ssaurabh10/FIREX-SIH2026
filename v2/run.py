#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIREX v2 -- Standalone Command-Line Interface
=============================================
Smart India Hackathon 2026 - Problem Statement 162
Space-Borne Satellite Thermal Incident Command & AI Intelligence Platform

This is v2's own entrypoint, so the platform can be run, deployed and packaged
from this directory alone:

  python run.py serve               # Launch the v2 console + API (port 8000)
  python run.py pipeline            # Run one end-to-end analysis pass
  python run.py data                # Regenerate console data files
  python run.py severity-sweep      # Score the whole queue with the severity engine
  python run.py migrate             # Apply pending schema migrations
  python run.py --help              # Display options

The repository-root ``run.py`` does the same job from one level up and adds the
archived v1 commands (``legacy``, ``v1-pipeline``, ``v1-daemon``); those live in
the v1 tree, which this dispatcher deliberately knows nothing about. Neither
dispatcher is required: ``python backend/cli.py <command>`` and
``python backend/run.py`` work on their own, and this file only exists so the
common case does not have to remember the two paths.

The four subcommands are handed straight to ``backend/cli.py``, which owns the
v2 implementations; this dispatcher does not parse their flags, so ``--help``
on any of them is passed through to it. ``serve`` is not one of them: it
launches ``backend/run.py`` (the uvicorn entrypoint) as a subprocess with PORT
and HOST in the environment.
"""
import os
import sys
import argparse
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
V2_CLI = os.path.join(BACKEND_DIR, "cli.py")
V2_SERVER = os.path.join(BACKEND_DIR, "run.py")

BANNER = r"""
===========================================================================
  _______ _______ ______ _______ _     _   SIH 2026 | PS 162
  |______    |    |_____/ |______  \___/    Space-Borne Satellite AI
  |          |    |    \_ |______ _/   \_   Wildfire & Industrial Intel
===========================================================================
"""

# Forwarded verbatim, arguments and all, so the flag sets cannot drift apart
# between this dispatcher and the implementation -- `python run.py pipeline
# --help` describes the run this command actually performs.
V2_CLI_COMMANDS = ("pipeline", "data", "severity-sweep", "migrate")


def cmd_serve(args):
    """Launch the v2 console and API server."""
    port = args.port or 8000
    if not os.path.exists(V2_SERVER):
        print(f"[ERROR] Backend server script not found at: {V2_SERVER}")
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

    subprocess.run([sys.executable, V2_SERVER], cwd=BACKEND_DIR, env=env)


def delegate_to_v2_cli(argv):
    """Forward a subcommand and its arguments to backend/cli.py."""
    if not os.path.exists(V2_CLI):
        print(f"[ERROR] v2 CLI not found at: {V2_CLI}")
        return 1
    return subprocess.run([sys.executable, V2_CLI] + list(argv), cwd=BACKEND_DIR).returncode


def main():
    argv = sys.argv[1:]

    # Delegate before argparse sees the arguments: the v2 CLI owns its own flag
    # set, and this dispatcher must not silently reject or reinterpret one.
    if argv and argv[0] in V2_CLI_COMMANDS:
        sys.exit(delegate_to_v2_cli(argv))

    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="FIREX v2 - Autonomous Satellite Thermal Intelligence & GIS Incident Command",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational Subcommands")

    serve_parser = subparsers.add_parser("serve", help="Start the v2 console + API server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    serve_parser.add_argument("--open", action="store_true", help="Automatically open browser")

    for name, help_text in (
        ("pipeline", "Run one end-to-end analysis pass (see: python run.py pipeline --help)"),
        ("data", "Regenerate console data files (see: ... data --help)"),
        ("severity-sweep", "Score the whole queue (see: ... severity-sweep --help)"),
        ("migrate", "Apply pending schema migrations (see: ... migrate --help)"),
    ):
        subparsers.add_parser(name, help=help_text, add_help=False)

    args = parser.parse_args(argv)

    if args.command in ("serve", None):
        if args.command is None:
            args.port = 8000
            args.open = True
        cmd_serve(args)
    else:
        print(BANNER)
        parser.print_help()


if __name__ == "__main__":
    main()
