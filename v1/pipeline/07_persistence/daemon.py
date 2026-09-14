# -*- coding: utf-8 -*-
"""
FIREX — Section 7 & 8: Automated Ingestion Daemon & Satellite Pass Scheduler
============================================================================
Smart India Hackathon 2026 — Problem Statement 162

Automates 2-times-daily (12-hour cadence) or scheduled satellite pass ingestion
synchronized with NASA polar-orbiting satellites (VIIRS & MODIS):
  - Daytime Overpass  : ~13:30 - 15:00 IST (S-NPP, NOAA-20, Aqua)
  - Nighttime Overpass: ~01:30 - 03:30 IST (Terra, S-NPP, NOAA-20)

Maintains continuous time-series persistence in SQLite (firex_history.db)
and updates live GIS map datasets (incidents.json, ambient_firms.json).

Usage:
  python daemon.py --once                  # Run single cycle and exit
  python daemon.py --interval 12           # Run continuously every 12 hours
  python daemon.py --schedule 14:00,02:30  # Run at specific daily overpass times (IST)
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_persistence_dir = os.path.join(BASE_DIR, "pipeline", "07_persistence")
if _persistence_dir not in sys.path:
    sys.path.insert(0, _persistence_dir)
import history_db

BANNER = r"""
===========================================================================
  _______ _______ ______ _______ _     _   SIH 2026 | PS 162
  |______    |    |_____/ |______  \___/    Space-Borne Satellite AI
  |          |    |    \_ |______ _/   \_   Section 7 & 8: Ingestion Daemon
===========================================================================
"""

def determine_pass_type(now_dt: datetime) -> str:
    """Determines whether current hour corresponds to DAY or NIGHT satellite overpass."""
    hour = now_dt.hour
    if 6 <= hour < 18:
        return "DAY"
    else:
        return "NIGHT"

def execute_sync_cycle(pass_type: str = None, live_fetch: bool = False):
    """Executes a complete ingestion, persistence scoring, and map dataset generation cycle."""
    now = datetime.now()
    if pass_type is None:
        pass_type = determine_pass_type(now)
        
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] >>> INITIATING SATELLITE PASS INGESTION CYCLE <<<")
    print(f"  * Overpass Type       : {pass_type} PASS")
    print(f"  * Live API Fetch Mode : {'ENABLED' if live_fetch else 'CACHED / LOCAL TELEMETRY'}")
    
    # 1. Optional live fetch from NASA FIRMS API
    if live_fetch:
        firms_script = os.path.join(BASE_DIR, "pipeline", "01_firms", "firms_fetch.py")
        if os.path.exists(firms_script):
            print("  * Querying NASA FIRMS API endpoints...")
            try:
                subprocess.run([sys.executable, firms_script], cwd=os.path.dirname(firms_script), check=True)
            except Exception as e:
                print(f"  [WARN] Live fetch returned non-zero code or failed: {e}. Falling back to cached datasets.")
                
    # 2. Run data preparation & persistence engine
    prep_script = os.path.join(BASE_DIR, "dashboard", "prepare_map_data.py")
    env = os.environ.copy()
    env["FIREX_PASS_TYPE"] = pass_type
    
    try:
        res = subprocess.run([sys.executable, prep_script], cwd=BASE_DIR, env=env, capture_output=True, text=True, check=True)
        for line in res.stdout.strip().split("\n"):
            if line:
                print(f"    {line}")
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Data preparation failed: {e}")
        if e.stderr:
            print(f"  [STDERR] {e.stderr}")
        return False

    # 3. Print Database Stats
    stats = history_db.get_stats()
    print("\n  +--- HISTORICAL PERSISTENCE DATABASE SUMMARY ---+")
    print(f"  | Total Ingest Cycles  : {stats['total_runs']:<24} |")
    print(f"  | Total Hotspots Stored: {stats['total_hotspots']:<24} |")
    print(f"  | Unique Calendar Days : {stats['unique_dates']:<24} |")
    print(f"  | Last Ingest Timestamp: {str(stats['last_run']):<24} |")
    print("  +-----------------------------------------------+\n")
    return True

def calculate_sleep_seconds_for_schedule(schedule_times: list[str]) -> tuple[float, str]:
    """Calculates seconds to sleep until the next scheduled time (HH:MM)."""
    now = datetime.now()
    candidate_times = []
    
    for t_str in schedule_times:
        try:
            parts = t_str.strip().split(":")
            h, m = int(parts[0]), int(parts[1])
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            candidate_times.append(target)
        except Exception:
            continue
            
    if not candidate_times:
        # Fallback to 12 hours
        return 12 * 3600, (now + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        
    next_time = min(candidate_times)
    seconds = (next_time - now).total_seconds()
    return max(1.0, seconds), next_time.strftime("%Y-%m-%d %H:%M:%S")

def run_daemon(interval_hours: float = 12.0, schedule: str = None, once: bool = False, live_fetch: bool = False):
    """Main daemon loop."""
    print(BANNER)
    print("  FIREX SATELLITE PASS INGESTION & TIME-SERIES DAEMON")
    print("  Ensures continuous 24/7 multi-pass surveillance and tracking")
    print("-" * 75)
    
    history_db.init_db()
    
    if once:
        print("[FIREX DAEMON] Mode: SINGLE EXECUTION (--once)")
        execute_sync_cycle(live_fetch=live_fetch)
        print("[FIREX DAEMON] Completed single run successfully. Exiting.")
        return

    if schedule:
        schedule_list = [s.strip() for s in schedule.split(",") if s.strip()]
        print(f"[FIREX DAEMON] Mode: SCHEDULED SYNCHRONIZATION")
        print(f"[FIREX DAEMON] Configured Overpass Times: {', '.join(schedule_list)} IST")
    else:
        schedule_list = None
        print(f"[FIREX DAEMON] Mode: INTERVAL CADENCE")
        print(f"[FIREX DAEMON] Execution Cadence: Every {interval_hours:.1f} Hours (2x Daily)")
        
    print("-" * 75)
    
    while True:
        try:
            execute_sync_cycle(live_fetch=live_fetch)
            
            if schedule_list:
                sleep_secs, next_run_str = calculate_sleep_seconds_for_schedule(schedule_list)
                print(f"[FIREX DAEMON] Next scheduled satellite pass at: {next_run_str} IST (~{sleep_secs/3600:.2f} hrs)")
            else:
                sleep_secs = interval_hours * 3600.0
                next_run_str = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%Y-%m-%d %H:%M:%S")
                print(f"[FIREX DAEMON] Next cadence cycle at: {next_run_str} (~{interval_hours:.1f} hrs)")
                
            print("[FIREX DAEMON] Standing by for satellite orbital window... (Press Ctrl+C to terminate)")
            time.sleep(sleep_secs)
        except KeyboardInterrupt:
            print("\n[FIREX DAEMON] Received shutdown interrupt. Terminating daemon cleanly.")
            break
        except Exception as e:
            print(f"[FIREX DAEMON ERROR] Unexpected error in loop: {e}")
            print("[FIREX DAEMON] Retrying in 60 seconds...")
            time.sleep(60)

def main():
    parser = argparse.ArgumentParser(
        description="FIREX Section 7 & 8: Automated Ingestion Daemon & Satellite Pass Scheduler"
    )
    parser.add_argument("--interval", type=float, default=12.0, help="Ingestion cadence in hours (default: 12.0)")
    parser.add_argument("--schedule", type=str, default=None, help="Comma-separated HH:MM times in IST (e.g. '14:00,02:30')")
    parser.add_argument("--once", action="store_true", help="Execute one ingestion cycle immediately and exit")
    parser.add_argument("--live-fetch", action="store_true", help="Trigger live NASA FIRMS API request")
    
    args = parser.parse_args()
    run_daemon(
        interval_hours=args.interval,
        schedule=args.schedule,
        once=args.once,
        live_fetch=args.live_fetch
    )

if __name__ == "__main__":
    main()
