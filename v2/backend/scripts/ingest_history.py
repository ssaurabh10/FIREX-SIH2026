"""
High-Speed Bulk Ingestion for NASA FIRMS Historical Archive Data (Compacted Last 365 Days)
Features:
1. Compacted Last 365 Days (Acquisition Date >= 2025-09-14).
2. Sovereign India Bounding Box filtering (8.4 <= Lat <= 37.6, 68.7 <= Lon <= 97.4) - trims foreign border data.
3. Hardware-accelerated SQLite batch inserts with WAL mode and temporary index suspension.
4. Deterministic SHA256 external_id deduplication via UNIQUE index.
5. Database compaction via VACUUM to reclaim disk space.
6. Auto-calculation of 90-day and 365-day historical baselines for all seeded industrial facilities.
"""
import os
import sys
import csv
import time
import hashlib
import sqlite3
from datetime import datetime
from typing import Tuple

# Add backend directory to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)

from app.storage.database import SessionLocal
from app.storage.models import IndustrialAsset
from app.behavior.baseline import get_or_create_facility_baseline

DATA_DIR = r"c:\Users\ssaur\OneDrive\Desktop\PS162\History data"
DB_PATH = os.path.join(BASE_DIR, "data", "firex_v2.db")

# Sovereign India Bounding Box
MIN_LAT = 8.4
MAX_LAT = 37.6
MIN_LON = 68.7
MAX_LON = 97.4

# Compacted Window: Last 365 Days
MIN_ACQ_DATE = "2025-09-14"

BATCH_SIZE = 50000

def parse_time_and_iso(acq_date: str, acq_time: str) -> Tuple[str, str]:
    cleaned = acq_time.replace(":", "").strip()
    try:
        t_int = int(cleaned)
        hour = t_int // 100
        minute = t_int % 100
    except ValueError:
        hour, minute = 0, 0
    
    date_clean = acq_date.strip()
    iso_str = f"{date_clean} {hour:02d}:{minute:02d}:00"
    compact_dt = f"{date_clean.replace('-', '')}{hour:02d}{minute:02d}"
    return iso_str, compact_dt

def normalize_confidence(conf_raw: str, instrument: str) -> float:
    c = conf_raw.strip().lower()
    inst = instrument.strip().lower()
    if "viirs" in inst or c in ["l", "n", "h", "low", "nominal", "high"]:
        if c in ["l", "low"]:
            return 0.35
        elif c in ["n", "nominal"]:
            return 0.70
        elif c in ["h", "high"]:
            return 0.95
        return 0.50
    try:
        val = float(c)
        return max(0.0, min(1.0, val / 100.0))
    except ValueError:
        return 0.50

def run_ingestion():
    print(f"=== FIREX v2 Historical Ingestion (Compacted 365 Days) ===")
    print(f"Source Directory: {DATA_DIR}")
    print(f"Target Database: {DB_PATH}")
    print(f"Bounding Box: Lat [{MIN_LAT}, {MAX_LAT}], Lon [{MIN_LON}, {MAX_LON}] (India Only)")
    print(f"Date Cutoff: Acquired >= {MIN_ACQ_DATE} (Last 365 Days)\n")

    if not os.path.exists(DATA_DIR):
        print(f"ERROR: Data directory '{DATA_DIR}' not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Configure SQLite for bulk loading performance
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA cache_size = -150000;") # 150MB page cache
    cursor.execute("PRAGMA temp_store = MEMORY;")

    # Ensure unique index on external_id exists for deduplication
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_observations_external_id ON observations (external_id);")

    # Temporarily drop secondary indexes to maximize bulk insert speed
    print("Preparing table indexes for high-speed streaming...")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_latitude;")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_longitude;")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_acquired_at;")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_spatial;")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_satellite;")
    cursor.execute("DROP INDEX IF EXISTS ix_observations_source;")
    conn.commit()

    # Discover all CSV files
    csv_files = []
    for root, _, files in os.walk(DATA_DIR):
        for f in sorted(files):
            if f.endswith(".csv"):
                csv_files.append(os.path.join(root, f))

    print(f"Discovered {len(csv_files)} historical FIRMS CSV files.\n")

    total_read = 0
    total_trimmed_geo = 0
    total_trimmed_date = 0
    total_inserted = 0
    ingested_now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    insert_sql = """
        INSERT OR IGNORE INTO observations (
            id, source, external_id, latitude, longitude, frp_mw,
            confidence_raw, confidence_score, satellite, sensor,
            product, daynight, acquired_at, ingested_at, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    start_time = time.time()

    for file_idx, filepath in enumerate(csv_files, 1):
        filename = os.path.basename(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"[{file_idx}/{len(csv_files)}] Processing {filename} ({size_mb:.1f} MB)...")

        # Determine product name
        prod_name = "VIIRS_ARCHIVE"
        if "J1V" in filename:
            prod_name = "VIIRS_NOAA20"
        elif "J2V" in filename:
            prod_name = "VIIRS_NOAA21"
        elif "SV" in filename:
            prod_name = "VIIRS_SNPP"
        elif "M-C61" in filename:
            prod_name = "MODIS"

        if "_nrt_" in filename:
            prod_name += "_NRT"
        else:
            prod_name += "_ARCHIVE"

        file_read = 0
        file_trimmed_geo = 0
        file_trimmed_date = 0
        file_inserted = 0
        batch = []

        with open(filepath, "r", encoding="utf-8", errors="ignore") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                file_read += 1
                
                # Date filter (365 days)
                acq_date = row.get("acq_date", "").strip()
                if acq_date < MIN_ACQ_DATE:
                    file_trimmed_date += 1
                    continue

                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                except (ValueError, KeyError):
                    continue

                # Bounding Box Filter: Trim neighboring foreign data
                if lat < MIN_LAT or lat > MAX_LAT or lon < MIN_LON or lon > MAX_LON:
                    file_trimmed_geo += 1
                    continue

                acq_time = row.get("acq_time", "")
                iso_dt, compact_dt = parse_time_and_iso(acq_date, acq_time)

                sat = row.get("satellite", "VIIRS").strip()
                instrument = row.get("instrument", "VIIRS").strip()
                conf_raw = row.get("confidence", "n").strip()
                conf_score = normalize_confidence(conf_raw, instrument)

                try:
                    frp = float(row.get("frp", 0.0) or 0.0)
                except ValueError:
                    frp = 0.0

                dn = row.get("daynight", "D").strip().upper()
                daynight = "NIGHT" if dn == "N" else "DAY"

                # Deterministic external_id hash
                key = f"{sat.upper()}_{instrument.upper()}_{lat:.4f}_{lon:.4f}_{compact_dt}"
                ext_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
                obs_id = f"obs_{ext_id}"

                batch.append((
                    obs_id,
                    "NASA_FIRMS",
                    ext_id,
                    lat,
                    lon,
                    frp,
                    conf_raw,
                    conf_score,
                    sat,
                    instrument,
                    prod_name,
                    daynight,
                    iso_dt,
                    ingested_now_iso,
                    None
                ))

                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(insert_sql, batch)
                    conn.commit()
                    file_inserted += cursor.rowcount
                    batch.clear()

            # Flush remaining batch
            if batch:
                cursor.executemany(insert_sql, batch)
                conn.commit()
                file_inserted += cursor.rowcount
                batch.clear()

        total_read += file_read
        total_trimmed_geo += file_trimmed_geo
        total_trimmed_date += file_trimmed_date
        total_inserted += file_inserted
        print(f"   -> Read: {file_read:,} | Date-trimmed: {file_trimmed_date:,} | Geo-trimmed: {file_trimmed_geo:,} | Ingested: {file_inserted:,}")

    # Rebuild high-performance spatial & temporal indexes
    print("\nRebuilding optimized indexes (spatial, temporal, satellite)...")
    reindex_start = time.time()
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_latitude ON observations (latitude);")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_longitude ON observations (longitude);")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_acquired_at ON observations (acquired_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_spatial ON observations (latitude, longitude, acquired_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_satellite ON observations (satellite);")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_observations_source ON observations (source);")
    cursor.execute("PRAGMA optimize;")
    conn.commit()
    print(f"Indexes rebuilt successfully in {time.time() - reindex_start:.1f}s.")

    # Compact database with VACUUM
    print("\nCompacting SQLite database file with VACUUM...")
    vacuum_start = time.time()
    conn.close()

    # Reconnect and run VACUUM outside transaction
    conn_vac = sqlite3.connect(DB_PATH)
    conn_vac.execute("VACUUM;")
    conn_vac.close()
    print(f"Database compacted in {time.time() - vacuum_start:.1f}s.")

    # Reconnect to get final count and file size
    conn_final = sqlite3.connect(DB_PATH)
    cursor_final = conn_final.cursor()
    cursor_final.execute("SELECT COUNT(*) FROM observations;")
    final_count = cursor_final.fetchone()[0]
    conn_final.close()

    final_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    elapsed = time.time() - start_time
    print("\n=== Ingestion & Compaction Complete ===")
    print(f"Total Rows Read:         {total_read:,}")
    print(f"Older Rows Trimmed:      {total_trimmed_date:,} (< 2025-09-14)")
    print(f"Foreign Borders Trimmed: {total_trimmed_geo:,} (Outside India BBox)")
    print(f"Total Ingested:          {total_inserted:,}")
    print(f"Final Observations in DB:{final_count:,}")
    print(f"Final Compacted DB Size: {final_size_mb:.1f} MB")
    print(f"Total Time Taken:        {elapsed:.1f} seconds\n")

    # Step 2: Calculate Historical Baselines for all seeded industrial facilities
    print("=== Computing Historical Baselines for Industrial Facilities ===")
    db = SessionLocal()
    assets = db.query(IndustrialAsset).all()
    print(f"Found {len(assets)} industrial facilities to baseline across 365 days of FIRMS data...\n")

    baseline_results = []
    for asset in assets:
        bl_365 = get_or_create_facility_baseline(asset.id, db, window_days=365, force_refresh=True)
        bl_90 = get_or_create_facility_baseline(asset.id, db, window_days=90, force_refresh=True)
        
        baseline_results.append({
            "name": asset.name,
            "type": asset.facility_type,
            "state": asset.state,
            "obs_90d": bl_90.get("observation_count", 0),
            "obs_365d": bl_365.get("observation_count", 0),
            "median_frp": bl_365.get("median_frp", 0.0),
            "p95_frp": bl_365.get("p95_frp", 0.0),
            "reliability": bl_365.get("history_reliability_label", "NONE"),
            "persistent": bl_365.get("is_persistent", False)
        })

    db.close()

    print(f"{'Facility Name':<35} | {'Type':<18} | {'365d Obs':<8} | {'Med FRP':<8} | {'P95 FRP':<8} | {'Reliability':<10} | {'Persistent'}")
    print("-" * 115)
    for b in baseline_results:
        print(f"{b['name'][:34]:<35} | {b['type'][:17]:<18} | {b['obs_365d']:<8} | {b['median_frp']:<8.1f} | {b['p95_frp']:<8.1f} | {b['reliability']:<10} | {b['persistent']}")
    print("-" * 115)
    print("\nAll historical baselines and persistent thermal source signatures generated successfully!")

if __name__ == "__main__":
    run_ingestion()
