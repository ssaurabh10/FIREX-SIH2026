"""
FIREX v2 - National Thermal Climatology Generator
Aggregates 2.89 Million Historical FIRMS Observations into 0.02° (~2.2 km) Climatology Grid Cells.
Identifies:
1. Permanent Industrial Flares (INV-4: active_days >= 10 inside the cell's own empirical P95 envelope)
2. Coal Seam / Mining Basins (active_days >= 15, high density)
3. Recurrent Agricultural / Biomass Fire Corridors
4. Sub-millisecond lookup cache for live operations

Grid convention
---------------
Cells are the Section 4.2 / Section 9 `thermal_climatology` 0.02° grid (key form `GRID_21.15_72.68`),
snapped through `app.gis.spatial.climatology_cell` so this offline producer and the live
`behavior.baseline` lookup resolve a coordinate to the *identical* key. The previous release
aggregated with `ROUND(latitude, 2)` / `ROUND(longitude, 2)`, which is a 0.01° grid -- half the
documented cell -- so every genuine 2.2 km cell was split in two and carried roughly half of its
`active_days`. That matters because INV-4's routine-flare rule is a threshold on `active_days`:
halving the cell population pushes genuinely continuous sites below the cutoff.

The cell is therefore computed per row in Python, never in SQL. SQLite's `round()` is
half-away-from-zero while Python's `round()` is half-to-even, and the two disagree on this corpus:
a sample of 60,000 observations puts 50 rows (0.083%) in a different cell than the live lookup
would query, which would silently orphan those rows.

Window
------
Every statistic is gathered over a 365-day rolling window (`acquired_at >= reference - 365 days`),
per Section 4.4 and INV-4. The previous release had no time predicate at all: it mixed whatever
history happened to be in `observations` into a table the spec advertises as a 365-day baseline.

Percentiles
-----------
`median_frp`, `p90_frp` and `p95_frp` are empirical percentiles of the member observations' FRP
values, computed with the same linear-interpolation estimator the live path uses
(`behavior.baseline.compute_percentiles`). The previous release fabricated them as
`mean * 0.80 / 1.60 / 2.10` clamped by `max_frp`; INV-4's entire suppression test is a comparison
against the P95 envelope, so a synthetic P95 makes the flag meaningless.

Publishing
----------
This script publishes by `DELETE FROM thermal_climatology` followed by a full reinsert, so it is a
whole-table replace, not an incremental update. Changing the grid (as this release does, 0.01° ->
0.02°) invalidates *every* existing row: old rows are deleted and the whole table is rebuilt, and no
pre-existing 0.01° row survives. Any `HistoricalBaseline` cache materialised from the old grid must
be regenerated (baseline.py:132 refreshes a cache entry older than 24 h on its own, or pass
`force_refresh=True`); `scripts/migrate_climatology_industrial.py` and
`scripts/migrate_climatology_mining.py` only clear `is_routine_flare` on existing rows, so they are
not a substitute for re-running this generator.
"""
import os
import sys
import time
from array import array
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple
import sqlite3

from sqlalchemy import create_engine

# Ensure backend directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.storage.database import Base
from app.storage.models import ThermalClimatology
from app.behavior.baseline import compute_percentiles
from app.gis.mining_basins import is_in_major_mining_basin
from app.gis.assets import INITIAL_INDUSTRIAL_FACILITIES, is_flaring_facility, is_metallurgical_or_manufacturing_facility
from app.gis.spatial import climatology_cell, haversine_distance_km
from app.core.logging import logger

# INV-4 (V2_LOGIC_SPECIFICATION.md:32): the routine-flare rule is ">= 10 active days/year operating
# within their empirical 365-day P95 baseline envelope". The previous release keyed on 25 active
# days, which under-suppresses genuinely continuous 10-24 active-day flares.
ROUTINE_FLARE_MIN_ACTIVE_DAYS = 10
# Supporting discriminator, not part of INV-4: gas flares burn around the clock, so a routine flare
# cell is dominated by night-time VIIRS detections. Agricultural residue burning peaks in daylight.
ROUTINE_FLARE_MIN_NIGHT_RATIO = 0.25
# INV-4 defines the envelope over a 365-day window; Section 4.4 repeats it for the location cell.
CLIMATOLOGY_WINDOW_DAYS = 365
# Sovereign offshore petroleum flaring sector (Bombay High).
BOMBAY_HIGH_LAT_RANGE = (18.0, 20.5)
BOMBAY_HIGH_LON_RANGE = (70.5, 72.5)


def is_routine_flare_cell(active_days: int, night_ratio: float, p95_frp: float) -> bool:
    """INV-4 test for a cell already established to be inside a flaring context.

    Only a *persistent* site (>= ROUTINE_FLARE_MIN_ACTIVE_DAYS active days/year) whose empirical
    365-day P95 envelope is known can be asserted routine. `p95_frp` is the cell's own observed
    95th percentile; when it is missing or zero the cell has no measurable envelope, so the site
    has not been demonstrated to operate inside it and the flag stays off (INV-5: an unmeasured
    baseline must never be penalised, but it must not be silently blessed either).
    """
    if active_days < ROUTINE_FLARE_MIN_ACTIVE_DAYS:
        return False
    if p95_frp is None or p95_frp <= 0.0:
        return False
    return night_ratio >= ROUTINE_FLARE_MIN_NIGHT_RATIO


def classify_cell(lat: float, lon: float, active_days: int, night_ratio: float, p95_frp: float) -> Tuple[bool, str]:
    """Classify one 0.02° climatology cell. Returns ``(is_routine_flare, site_classification_hint)``.

    Pure in the static GIS registries (mining basins, industrial assets) so the decision logic can be
    exercised without a database.
    """
    # Check if coordinate is inside a verified sovereign Indian mining basin or coalfield
    is_mining, _basin = is_in_major_mining_basin(lat, lon)

    # Check nearest industrial facility
    nearest_fac = None
    min_dist_km = 999.0
    for fac in INITIAL_INDUSTRIAL_FACILITIES:
        d_km = haversine_distance_km(lat, lon, fac["latitude"], fac["longitude"])
        if d_km < min_dist_km:
            min_dist_km = d_km
            nearest_fac = fac

    is_near_facility = bool(nearest_fac and min_dist_km <= (nearest_fac["buffer_radius_meters"] / 1000.0 + 2.0))
    is_metal_fac = bool(nearest_fac and (is_metallurgical_or_manufacturing_facility(nearest_fac["facility_type"], nearest_fac.get("industry")) or nearest_fac.get("category") == "industrial_fire"))
    is_flare_fac = bool(nearest_fac and is_flaring_facility(nearest_fac["facility_type"], nearest_fac.get("category")))
    in_bombay_high = BOMBAY_HIGH_LAT_RANGE[0] <= lat <= BOMBAY_HIGH_LAT_RANGE[1] and BOMBAY_HIGH_LON_RANGE[0] <= lon <= BOMBAY_HIGH_LON_RANGE[1]

    # Classification heuristics grounded in empirical sovereign data:
    # 1. Mining basins emit heat continuously from coal seams & open-cast pits -> NEVER routine gas flares!
    # 2. Steel plants, smelters & blast furnaces operate 24/7 metallurgical heat -> METALLURGICAL_INDUSTRIAL, NOT gas flares!
    # 3. Only verified petroleum flaring assets (refineries, LNG terminals, offshore platforms) are ROUTINE_FLARE.
    is_routine_flare = False
    if is_mining:
        hint = "COAL_MINING_BASIN"
    elif is_near_facility and is_metal_fac:
        hint = "METALLURGICAL_INDUSTRIAL"
    elif (is_near_facility and is_flare_fac) or in_bombay_high:
        is_routine_flare = is_routine_flare_cell(active_days, night_ratio, p95_frp)
        hint = "ROUTINE_FLARE" if is_routine_flare else "EPISODIC_THERMAL"
    elif active_days >= 30 and night_ratio >= 0.30:
        hint = "PERSISTENT_INDUSTRIAL"
    elif active_days >= 15 and night_ratio >= 0.25:
        hint = "PERSISTENT_INDUSTRIAL"
    elif active_days >= 5 and night_ratio < 0.15:
        hint = "RECURRENT_BIOMASS"
    else:
        hint = "EPISODIC_THERMAL"

    return is_routine_flare, hint


def aggregate_thermal_cells(cur: sqlite3.Cursor, window_start_iso: str, min_detections: int,
                            window_start_date: date) -> Dict[str, Dict[str, Any]]:
    """Buckets every observation inside the window into its 0.02° cell.

    The cell key comes from `app.gis.spatial.climatology_cell` row by row -- the same helper the live
    baseline lookup uses -- so the two can never drift. Per-cell state is kept deliberately small so
    the 2.89M-row corpus streams without materialising it: active days are a 366-bit integer mask
    (one bit per calendar day of the window) and the FRP values live in an `array('d')`.

    Returns only cells with at least `min_detections` observations, keyed by spatial key.
    """
    cells: Dict[str, Dict[str, Any]] = {}

    cur.execute(
        """
        SELECT latitude, longitude, frp_mw, daynight, SUBSTR(acquired_at, 1, 10) AS day
        FROM observations
        WHERE acquired_at >= ?
        """,
        (window_start_iso,),
    )

    for lat, lon, frp_mw, daynight, day in cur:
        if lat is None or lon is None:
            continue

        cell_lat, cell_lon, key = climatology_cell(lat, lon)
        cell = cells.get(key)
        if cell is None:
            cell = {
                "latitude": cell_lat,
                "longitude": cell_lon,
                "observation_count": 0,
                "night_count": 0,
                "day_mask": 0,
                "frp_values": array("d"),
            }
            cells[key] = cell

        cell["observation_count"] += 1
        if daynight == "NIGHT":
            cell["night_count"] += 1
        cell["frp_values"].append(float(frp_mw) if frp_mw is not None else 0.0)

        # Bit i marks calendar day i of the window as active.
        try:
            day_index = (date(int(day[0:4]), int(day[5:7]), int(day[8:10])) - window_start_date).days
        except (TypeError, ValueError):
            day_index = -1
        if 0 <= day_index < 366:
            cell["day_mask"] |= 1 << day_index

    return {key: cell for key, cell in cells.items() if cell["observation_count"] >= min_detections}


def build_climatology(min_detections: int = 3, db_path: str = None,
                      window_days: int = CLIMATOLOGY_WINDOW_DAYS,
                      reference_time: Optional[datetime] = None) -> int:
    """Rebuild the whole `thermal_climatology` table over a `window_days` rolling window."""
    start_time = time.time()

    # Resolve SQLite database path
    if db_path is None:
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(os.path.join(BACKEND_DIR, db_path))

    print(f"[*] Connecting to database: {db_path}")

    # 1. Ensure table schema is created in the *resolved* database. The previous release created the
    #    schema through the globally-configured engine, so a custom db_path ran against nothing.
    target_engine = create_engine("sqlite:///" + db_path.replace("\\", "/"))
    try:
        Base.metadata.create_all(bind=target_engine)
    finally:
        target_engine.dispose()

    # 2. The 365-day rolling window of Section 4.4 / INV-4. `acquired_at` is stored as an ISO-8601
    #    UTC string ('YYYY-MM-DD HH:MM:SS'), so a lexicographic comparison is exact and index-safe.
    reference = reference_time or datetime.utcnow()
    window_start = reference - timedelta(days=window_days)
    window_start_iso = window_start.strftime("%Y-%m-%d %H:%M:%S")

    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()

    print(f"[*] Aggregating observations since {window_start_iso} by 0.02° grid cells "
          f"(min_detections >= {min_detections})...")

    cells = aggregate_thermal_cells(cur, window_start_iso, min_detections, window_start.date())
    agg_time = time.time() - start_time
    print(f"[+] Aggregation complete in {agg_time:.2f}s. Extracted {len(cells)} recurring thermal cells.")

    # Prepare batch records
    climatology_records = []
    routine_flares_count = 0
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    for key, cell in cells.items():
        lat = cell["latitude"]
        lon = cell["longitude"]
        obs_count = cell["observation_count"]
        active_days = bin(cell["day_mask"]).count("1")
        night_ratio = round(cell["night_count"] / max(1, obs_count), 3)

        # Empirical percentiles of this cell's own FRP distribution (INV-4 compares against the P95).
        stats = compute_percentiles(list(cell["frp_values"]))
        median_frp = stats["median"]
        p90_frp = stats["p90"]
        p95_frp = stats["p95"]
        max_frp = stats["max"]

        is_routine_flare, hint = classify_cell(lat, lon, active_days, night_ratio, p95_frp)
        if is_routine_flare:
            routine_flares_count += 1

        climatology_records.append((
            key, lat, lon, obs_count, active_days,
            median_frp, p90_frp, p95_frp, max_frp,
            night_ratio, 1 if is_routine_flare else 0, hint, now_iso
        ))

    print(f"[*] Identified {routine_flares_count} permanent flaring / industrial hot cells in India.")
    print(f"[*] Inserting / updating {len(climatology_records)} records in 'thermal_climatology'...")

    # Insert or replace into thermal_climatology. Whole-table replace: changing the grid invalidates
    # every existing row (see the module docstring), and the 0.01° rows of the previous release must
    # not survive alongside the 0.02° rows.
    cur.execute("DELETE FROM thermal_climatology")
    cur.executemany("""
    INSERT INTO thermal_climatology (
        spatial_key, latitude, longitude, observation_count, active_days,
        median_frp, p90_frp, p95_frp, max_frp,
        night_ratio, is_routine_flare, site_classification_hint, last_updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, climatology_records)

    con.commit()
    con.close()

    total_time = time.time() - start_time
    print(f"[OK] Climatology successfully built! Stored {len(climatology_records)} cells in {total_time:.2f}s total.")
    return len(climatology_records)

if __name__ == "__main__":
    count = build_climatology()
    print(f"Done. Processed {count} grid cells.")
