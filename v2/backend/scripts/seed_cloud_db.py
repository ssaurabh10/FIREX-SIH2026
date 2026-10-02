"""
FIREX v2 Cloud Database Seeder (Option 1: Climatology & Baselines)

High-performance bulk seeder using psycopg2.extras.execute_values for multi-row
batching over WAN connections to Render PostgreSQL.

Usage:
    python v2/backend/scripts/seed_cloud_db.py --target-url "postgresql://user:pass@host/dbname" --wipe
"""
import os
import sys
import argparse
import sqlite3
import time
import json
from typing import List, Dict, Any, Set

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import psycopg2
from psycopg2.extras import execute_values
from app.storage.database import Base, normalize_database_url
import app.storage.models
from sqlalchemy import create_engine, Boolean, JSON

LOCAL_DB_PATH = os.path.join(BACKEND_DIR, "data", "firex_v2.db")

# Strict dependency order for relational integrity
SEED_TABLES = [
    "industrial_assets",
    "behavior_profiles",
    "historical_baselines",
    "observations",
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

PAGE_SIZE = 5000

def get_local_connection():
    if not os.path.exists(LOCAL_DB_PATH):
        raise FileNotFoundError(f"Local database not found at {LOCAL_DB_PATH}")
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def seed_database(target_url: str, wipe_existing: bool = False):
    print("=" * 70)
    print("FIREX v2 — High-Speed Cloud Database Seeder (Option 1)")
    print("=" * 70)

    clean_target_url = normalize_database_url(target_url)
    display_url = clean_target_url.split("@")[-1] if "@" in clean_target_url else clean_target_url
    print(f"[*] Target Database : {display_url}")
    print(f"[*] Local Source    : {LOCAL_DB_PATH}")

    # 1. Connect and verify/create schema
    print("\n[1/3] Initializing schema on target database...")
    engine = create_engine(clean_target_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    print("      Database tables verified/created.")

    # 2. Open psycopg2 connection for fast execute_values
    pg_dsn = clean_target_url.replace("postgresql+psycopg2://", "postgresql://")
    pg_conn = psycopg2.connect(pg_dsn)
    pg_cur = pg_conn.cursor()

    local_conn = get_local_connection()
    start_time = time.time()
    total_migrated = 0

    print("\n[2/3] Seeding tables in dependency order with bulk batching...")

    for table in SEED_TABLES:
        # Check existing row count
        pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        existing_count = pg_cur.fetchone()[0]

        if existing_count > 0 and not wipe_existing:
            print(f"  [-] {table:<26}: already has {existing_count:,} rows (skipping)")
            continue

        if wipe_existing and existing_count > 0:
            print(f"  [!] Wiping existing {existing_count:,} rows from {table}...")
            pg_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
            pg_conn.commit()

        # Query filtered source rows for relational integrity
        if table == "observations":
            query = """
                SELECT * FROM observations 
                WHERE id IN (SELECT observation_id FROM incident_observations)
            """
        elif table == "behavior_profiles":
            query = """
                SELECT * FROM behavior_profiles
                WHERE facility_id IS NULL OR facility_id IN (SELECT id FROM industrial_assets)
            """
        elif table == "historical_baselines":
            query = """
                SELECT * FROM historical_baselines
                WHERE profile_id IS NULL OR profile_id IN (
                    SELECT id FROM behavior_profiles 
                    WHERE facility_id IS NULL OR facility_id IN (SELECT id FROM industrial_assets)
                )
            """
        elif table == "imagery_records":
            query = """
                SELECT * FROM imagery_records
                WHERE incident_id IS NULL OR incident_id IN (SELECT id FROM incidents)
            """
        elif table == "incident_events":
            query = """
                SELECT * FROM incident_events
                WHERE incident_id IS NULL OR incident_id IN (SELECT id FROM incidents)
            """
        elif table == "behavior_daily_summaries":
            query = """
                SELECT * FROM behavior_daily_summaries
                WHERE profile_id IS NULL OR profile_id IN (
                    SELECT id FROM behavior_profiles 
                    WHERE facility_id IS NULL OR facility_id IN (SELECT id FROM industrial_assets)
                )
            """
        else:
            query = f"SELECT * FROM {table}"

        cursor = local_conn.execute(query)
        sample = cursor.fetchone()
        if not sample:
            print(f"  [.] {table:<26}: 0 source rows")
            continue

        cols = list(sample.keys())
        col_names = ", ".join(f'"{c}"' for c in cols)
        insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES %s'

        # Column type detection from SQLAlchemy metadata
        table_obj = Base.metadata.tables.get(table)
        bool_cols: Set[str] = set()
        json_cols: Set[str] = set()
        if table_obj is not None:
            bool_cols = {c.name for c in table_obj.columns if isinstance(c.type, Boolean)}
            json_cols = {c.name for c in table_obj.columns if isinstance(c.type, JSON)}

        # Stream and insert with execute_values
        cursor = local_conn.execute(query)
        table_inserted = 0
        print(f"  [+] Seeding {table:<22} :", end="", flush=True)

        while True:
            rows = cursor.fetchmany(PAGE_SIZE)
            if not rows:
                break

            tuples = []
            for r in rows:
                vals = []
                for c in cols:
                    v = r[c]
                    if c in bool_cols and v is not None:
                        v = bool(v)
                    elif c in json_cols and v is not None:
                        if isinstance(v, (dict, list)):
                            v = json.dumps(v)
                    vals.append(v)
                tuples.append(tuple(vals))

            execute_values(pg_cur, insert_sql, tuples, page_size=PAGE_SIZE)
            pg_conn.commit()
            table_inserted += len(tuples)
            total_migrated += len(tuples)
            print(f" {table_inserted:,}...", end="", flush=True)

        print(f" Done ({table_inserted:,} rows)")

    pg_cur.close()
    pg_conn.close()
    local_conn.close()

    elapsed = time.time() - start_time
    print(f"\n[3/3] Migration Complete!")
    print(f"[*] Total Rows Transferred : {total_migrated:,}")
    print(f"[*] Total Time             : {elapsed:.2f} seconds")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Seed Cloud PostgreSQL with FIREX Climatology and Incidents")
    parser.add_argument(
        "--target-url",
        type=str,
        default=os.environ.get("DATABASE_URL"),
        help="Target database URL. Defaults to DATABASE_URL env var."
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Wipe and replace existing rows in target tables"
    )
    args = parser.parse_args()

    if not args.target_url:
        print("ERROR: No target database URL provided.")
        sys.exit(1)

    seed_database(args.target_url, wipe_existing=args.wipe)

if __name__ == "__main__":
    main()
