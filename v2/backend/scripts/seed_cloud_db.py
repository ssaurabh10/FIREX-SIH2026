"""
FIREX v2 Cloud Database Seeder (Option 1: Climatology & Baselines)

Transfers pre-computed thermal climatology, historical baselines, industrial assets,
and incident history from the local SQLite database into a target PostgreSQL instance (e.g. on Render).

Usage:
    python v2/backend/scripts/seed_cloud_db.py --target-url "postgresql://user:password@host/dbname"
    
Or set DATABASE_URL environment variable:
    $env:DATABASE_URL="postgresql://user:password@host/dbname"
    python v2/backend/scripts/seed_cloud_db.py
"""
import os
import sys
import argparse
import sqlite3
import time
from typing import List, Dict, Any

# Ensure backend directory is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine, text
from app.storage.database import Base, normalize_database_url
import app.storage.models  # Ensure all SQLAlchemy models are registered on Base

LOCAL_DB_PATH = os.path.join(BACKEND_DIR, "data", "firex_v2.db")

# Tables to migrate in strict dependency order (foreign keys respected)
SEED_TABLES = [
    "industrial_assets",
    "historical_baselines",
    "behavior_profiles",
    "observations",  # linked to incidents
    "incidents",
    "incident_observations",
    "imagery_records",
    "ai_investigations",
    "severity_assessments",
    "alert_records",
    "incident_events",
    "behavior_daily_summaries",
    "thermal_climatology",
]

BATCH_SIZE = 5000

def get_local_connection():
    if not os.path.exists(LOCAL_DB_PATH):
        raise FileNotFoundError(f"Local database not found at {LOCAL_DB_PATH}")
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def seed_database(target_url: str, wipe_existing: bool = False):
    print("=" * 70)
    print("FIREX v2 — Cloud Database Seeder (Option 1)")
    print("=" * 70)
    
    clean_target_url = normalize_database_url(target_url)
    display_url = clean_target_url.split("@")[-1] if "@" in clean_target_url else clean_target_url
    print(f"[*] Target Database : {display_url}")
    print(f"[*] Local Source    : {LOCAL_DB_PATH}")
    
    # 1. Connect and initialize schema
    print("\n[1/3] Connecting to target database and verifying schema...")
    target_engine = create_engine(clean_target_url, pool_pre_ping=True)
    
    with target_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("      Target connection verified.")
    
    # Create tables if not present
    Base.metadata.create_all(bind=target_engine)
    print("      Database tables verified/created.")

    local_conn = get_local_connection()
    start_time = time.time()
    total_migrated = 0

    print("\n[2/3] Seeding tables in dependency order...")

    with target_engine.connect() as target_conn:
        for table in SEED_TABLES:
            # Check existing target count
            existing_target_count = target_conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            
            if existing_target_count > 0 and not wipe_existing:
                print(f"  [-] {table:<26}: already has {existing_target_count:,} rows (skipping, use --wipe to overwrite)")
                continue

            if wipe_existing and existing_target_count > 0:
                print(f"  [!] Wiping existing {existing_target_count:,} rows from {table}...")
                target_conn.execute(text(f"DELETE FROM {table}"))
                target_conn.commit()

            # Query source rows
            if table == "observations":
                # Only transfer observations directly tied to incidents
                query = """
                    SELECT * FROM observations 
                    WHERE id IN (SELECT observation_id FROM incident_observations)
                """
            else:
                query = f"SELECT * FROM {table}"
            
            cursor = local_conn.execute(query)
            sample_row = cursor.fetchone()
            if not sample_row:
                print(f"  [.] {table:<26}: 0 source rows")
                continue
            
            columns = list(sample_row.keys())
            col_names = ", ".join(f'"{c}"' for c in columns)
            bind_params = ", ".join(f":{c}" for c in columns)
            insert_stmt = text(f'INSERT INTO {table} ({col_names}) VALUES ({bind_params})')

            # Re-fetch all rows
            cursor = local_conn.execute(query)
            batch = []
            table_inserted = 0

            print(f"  [+] Seeding {table}...", end="", flush=True)

            while True:
                rows = cursor.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                
                dicts = [dict(r) for r in rows]
                target_conn.execute(insert_stmt, dicts)
                target_conn.commit()
                table_inserted += len(dicts)
                total_migrated += len(dicts)
                print(f" {table_inserted:,}...", end="", flush=True)

            print(f" Done ({table_inserted:,} rows)")

    local_conn.close()
    elapsed = time.time() - start_time

    print(f"\n[3/3] Migration Complete!")
    print(f"[*] Total Rows Transferred : {total_migrated:,}")
    print(f"[*] Time Taken             : {elapsed:.2f} seconds")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Seed Cloud PostgreSQL with FIREX Climatology and Incidents")
    parser.add_argument(
        "--target-url",
        type=str,
        default=os.environ.get("DATABASE_URL"),
        help="Target database URL (e.g. postgresql://user:pass@host/dbname). Defaults to DATABASE_URL env var."
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Wipe and replace existing rows in target tables"
    )
    args = parser.parse_args()

    if not args.target_url:
        print("ERROR: No target database URL provided.")
        print("Please supply --target-url or set the DATABASE_URL environment variable.")
        print("\nExample:")
        print('  python v2/backend/scripts/seed_cloud_db.py --target-url "postgresql://user:pass@dpg-xxx.singapore-postgres.render.com/firex_db"')
        sys.exit(1)

    seed_database(args.target_url, wipe_existing=args.wipe)

if __name__ == "__main__":
    main()
