"""
Pytest configuration for FIREX v2 test suite.
Ensures v2/backend is always in sys.path regardless of where pytest is invoked.
"""
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
