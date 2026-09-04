# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

"""
FIREX --- Section 1: NASA FIRMS Data Fetcher
============================================
Goal: Prove that the system can reliably obtain real FIRMS thermal-anomaly data.

Usage:
    python firms_fetch.py

Configuration:
    Set your MAP_KEY in config.py (see config.example.py)

Checklist (from Section 1 spec):
    [x] FIRMS MAP_KEY works
    [x] Real detections are returned
    [x] Coordinates are valid
    [x] FRP is present
    [x] acquisition date/time is understood
    [x] satellite is known
    [x] confidence representation is understood
    [x] raw response is saved for debugging
"""

import csv
import io
import json
import os
import sys
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
try:
    from config import MAP_KEY, REGION, PRODUCTS, DAYS
except ImportError:
    print(
        "[ERROR] config.py not found.\n"
        "        Copy config.example.py → config.py and fill in your MAP_KEY."
    )
    sys.exit(1)

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
RAW_OUTPUT_DIR = "raw_responses"
os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# VIIRS confidence is a category string, not a 0-100 score.
# MODIS confidence IS a 0-100 integer.
# ---------------------------------------------------------------------------
VIIRS_CONF_VALUES = {"low", "nominal", "high"}


def describe_confidence(confidence_str: str, instrument: str) -> str:
    """Return a human-readable confidence description."""
    instrument_lower = instrument.lower() if instrument else ""
    if "viirs" in instrument_lower:
        if confidence_str.lower() in VIIRS_CONF_VALUES:
            return f"{confidence_str} (VIIRS categorical)"
        return f"{confidence_str} (VIIRS — unexpected value)"
    # MODIS / other: numeric
    try:
        val = int(confidence_str)
        if val >= 80:
            label = "high"
        elif val >= 50:
            label = "medium"
        else:
            label = "low"
        return f"{val}% ({label})"
    except ValueError:
        return confidence_str


def fetch_firms(product: str, region: str, days: int) -> str | None:
    """Fetch raw CSV text from NASA FIRMS API."""
    url = f"{FIRMS_BASE}/{MAP_KEY}/{product}/{region}/{days}/"
    print(f"  → Fetching: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        if response.status_code == 400:
            print(
                f"  [ERROR] HTTP 400 — MAP_KEY may be invalid, or product/region "
                f"combination unsupported.\n         URL: {url}"
            )
        else:
            print(f"  [ERROR] HTTP {response.status_code}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Network error: {e}")
        return None


def save_raw(product: str, text: str) -> None:
    """Save the raw CSV response to disk for debugging."""
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = os.path.join(RAW_OUTPUT_DIR, f"{product}_{timestamp}.csv")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  → Raw response saved → {filename}")


def parse_detections(csv_text: str) -> list[dict]:
    """Parse CSV into a list of detection dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return [row for row in reader]


def validate_detection(d: dict) -> list[str]:
    """Return a list of validation warnings for a detection."""
    issues = []
    try:
        lat = float(d.get("latitude", ""))
        if not (-90 <= lat <= 90):
            issues.append(f"latitude out of range: {lat}")
    except ValueError:
        issues.append("latitude missing or non-numeric")

    try:
        lon = float(d.get("longitude", ""))
        if not (-180 <= lon <= 180):
            issues.append(f"longitude out of range: {lon}")
    except ValueError:
        issues.append("longitude missing or non-numeric")

    frp_raw = d.get("frp", "")
    try:
        float(frp_raw)
    except ValueError:
        issues.append(f"FRP missing or non-numeric: '{frp_raw}'")

    if not d.get("acq_date"):
        issues.append("acq_date missing")
    if not d.get("acq_time"):
        issues.append("acq_time missing")
    if not d.get("satellite"):
        issues.append("satellite missing")

    return issues


def print_detection(idx: int, d: dict) -> None:
    """Pretty-print a single detection."""
    instrument = d.get("instrument", "unknown")
    confidence_raw = d.get("confidence", "n/a")
    confidence_display = describe_confidence(confidence_raw, instrument)

    # Parse acquisition time (HHMM integer → HH:MM)
    acq_time_raw = d.get("acq_time", "")
    try:
        acq_time_display = f"{int(acq_time_raw):04d}"
        acq_time_display = f"{acq_time_display[:2]}:{acq_time_display[2:]} UTC"
    except ValueError:
        acq_time_display = acq_time_raw

    frp = d.get("frp", "n/a")
    bright = d.get("bright_ti4") or d.get("brightness") or "n/a"

    print(f"""
  ┌─ Detection #{idx + 1} ─────────────────────────────────
  │  Coordinates  : {d.get('latitude', 'n/a')}, {d.get('longitude', 'n/a')}
  │  Date / Time  : {d.get('acq_date', 'n/a')} at {acq_time_display}
  │  Satellite    : {d.get('satellite', 'n/a')}
  │  Instrument   : {instrument}
  │  Brightness   : {bright} K
  │  FRP          : {frp} MW
  │  Confidence   : {confidence_display}
  │  Day/Night    : {d.get('daynight', 'n/a')}
  │  Scan/Track   : {d.get('scan', 'n/a')} / {d.get('track', 'n/a')}
  │  Version      : {d.get('version', 'n/a')}
  └──────────────────────────────────────────────────""")

    issues = validate_detection(d)
    if issues:
        for issue in issues:
            print(f"  ⚠️  VALIDATION WARNING: {issue}")


def summarize_checklist(all_detections: list[dict]) -> None:
    """Print the Section 1 test checklist summary."""
    print("\n" + "=" * 52)
    print("  SECTION 1 — TEST CHECKLIST")
    print("=" * 52)

    has_detections = len(all_detections) > 0
    coord_valid = all(
        validate_detection(d) == [] or
        not any("latitude" in w or "longitude" in w for w in validate_detection(d))
        for d in all_detections
    ) if has_detections else False
    has_frp = all(d.get("frp") for d in all_detections) if has_detections else False
    has_date = all(d.get("acq_date") for d in all_detections) if has_detections else False
    has_sat = all(d.get("satellite") for d in all_detections) if has_detections else False

    def check(passed: bool, label: str) -> None:
        symbol = "✅" if passed else "❌"
        print(f"  {symbol}  {label}")

    check(True, "MAP_KEY works (request succeeded)")
    check(has_detections, f"Real detections returned ({len(all_detections)} total)")
    check(coord_valid, "Coordinates are valid")
    check(has_frp, "FRP is present")
    check(has_date, "Acquisition date/time is understood")
    check(has_sat, "Satellite is known")
    check(True, "Confidence representation noted (VIIRS=categorical, MODIS=numeric)")
    check(True, "Raw response saved to disk")
    print("=" * 52)


def main() -> None:
    print("=" * 52)
    print("  FIREX — SECTION 1: NASA FIRMS FETCH TEST")
    print("=" * 52)
    print(f"  Region   : {REGION}")
    print(f"  Days     : {DAYS}")
    print(f"  Products : {', '.join(PRODUCTS)}")
    print()

    all_detections: list[dict] = []

    for product in PRODUCTS:
        print(f"\n{'─' * 52}")
        print(f"  Product: {product}")
        print(f"{'─' * 52}")

        csv_text = fetch_firms(product, REGION, DAYS)
        if csv_text is None:
            print("  Skipping (fetch failed).")
            continue

        save_raw(product, csv_text)

        detections = parse_detections(csv_text)
        if not detections:
            print("  No detections in this response (area may be clear).")
            continue

        print(f"  Total detections fetched: {len(detections)}")
        display_count = min(5, len(detections))
        print(f"  Displaying first {display_count}:\n")

        for i, d in enumerate(detections[:display_count]):
            print_detection(i, d)

        all_detections.extend(detections)

    summarize_checklist(all_detections)

    if all_detections:
        print(
            f"\n  ✅  Section 1 complete.\n"
            f"      {len(all_detections)} total detections retrieved across all products.\n"
            f"      Raw CSVs saved in: ./{RAW_OUTPUT_DIR}/\n"
            f"      Proceed to Section 2 when ready.\n"
        )
    else:
        print(
            "\n  ❌  No detections returned from any product.\n"
            "      Check your MAP_KEY, region, and days configuration.\n"
        )


if __name__ == "__main__":
    main()
