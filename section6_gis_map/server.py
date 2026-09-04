# -*- coding: utf-8 -*-
"""
Compatibility redirect shim: FIREX Section 6 has been elevated to dashboard/.
This file redirects execution to dashboard/server.py.
"""
import os
import sys

DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
sys.path.insert(0, DASHBOARD_DIR)

if __name__ == "__main__":
    os.chdir(DASHBOARD_DIR)
    from server import run_server
    run_server()
