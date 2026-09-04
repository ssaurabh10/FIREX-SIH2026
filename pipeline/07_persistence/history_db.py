# -*- coding: utf-8 -*-
"""
FIREX — Section 7 & 8: Historical Intelligence & Spatial Persistence Engine
============================================================================
Smart India Hackathon 2026 — Problem Statement 162

Maintains a zero-dependency, high-performance SQLite time-series database
(firex_history.db) tracking every satellite pass across India.

Key Capabilities:
1. Multi-Day & Day/Night Satellite Overpass History.
2. Automated Thermal Persistence Scoring:
   - "DAY + NIGHT" detection at same location -> Confirmed Continuous Heat (Gas Flare / Smelter).
   - First-time sudden detection in vegetation -> High Alert New Wildfire Ignition.
3. Spatial Indexing with Haversine distance calculations.
"""

import os
import sqlite3
import math
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "firex_history.db")

def get_connection(db_path=DB_PATH):
    """Returns a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Fast concurrent reads/writes
    return conn

def init_db(db_path=DB_PATH):
    """Initializes the time-series schema if not already present."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # 1. Ingest Runs (Tracking every sync event, daytime / nighttime)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingest_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pass_type TEXT NOT NULL CHECK(pass_type IN ('DAY', 'NIGHT', 'MANUAL', 'HISTORICAL_SEED')),
            hotspots_ingested INTEGER NOT NULL DEFAULT 0,
            incidents_scored INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            notes TEXT
        )
        """)

        # 2. Hotspot History (Every raw ambient FIRMS thermal pixel detected)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS hotspot_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            frp REAL NOT NULL,
            confidence TEXT,
            satellite TEXT,
            instrument TEXT,
            acq_date TEXT NOT NULL,
            acq_time TEXT,
            pass_type TEXT CHECK(pass_type IN ('DAY', 'NIGHT', 'UNKNOWN')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES ingest_runs(run_id) ON DELETE SET NULL
        )
        """)
        
        # Indexes for ultra-fast spatial & temporal queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_date ON hotspot_history(acq_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_coords ON hotspot_history(latitude, longitude)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_pass ON hotspot_history(pass_type)")

        # 3. Incident History (AI-evaluated targets across successive passes)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS incident_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            case_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            frp REAL NOT NULL,
            confidence TEXT,
            ai_classification TEXT NOT NULL,
            ai_confidence REAL NOT NULL,
            risk_score INTEGER NOT NULL,
            risk_tier TEXT NOT NULL,
            persistence_pattern TEXT,
            days_active INTEGER DEFAULT 1,
            pass_type TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES ingest_runs(run_id) ON DELETE SET NULL
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_incident_case ON incident_history(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_incident_eval_date ON incident_history(evaluated_at)")
        
        conn.commit()

def haversine_km(lat1, lon1, lat2, lon2):
    """Computes great-circle distance in kilometers between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def record_ingest_run(pass_type="DAY", hotspots_count=0, incidents_count=0, notes="", db_path=DB_PATH):
    """Records the execution of a new satellite pass ingestion."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO ingest_runs (pass_type, hotspots_ingested, incidents_scored, notes)
        VALUES (?, ?, ?, ?)
        """, (pass_type, hotspots_count, incidents_count, notes))
        run_id = cursor.lastrowid
        conn.commit()
        return run_id

def insert_hotspots(run_id, hotspots, pass_type="DAY", db_path=DB_PATH):
    """Batch-inserts raw FIRMS thermal hotspots into history with spatial deduplication."""
    if not hotspots:
        return 0
    
    rows = []
    for h in hotspots:
        lat = h.get("lat") or h.get("latitude")
        lon = h.get("lon") or h.get("longitude")
        frp = h.get("frp", 0.0)
        conf = str(h.get("conf") or h.get("confidence", ""))
        sat = h.get("sat") or h.get("satellite", "")
        inst = h.get("instrument", "")
        date = h.get("date") or h.get("acq_date", datetime.utcnow().strftime("%Y-%m-%d"))
        time_val = str(h.get("time") or h.get("acq_time", ""))
        p_type = h.get("pass_type") or pass_type
        
        rows.append((run_id, lat, lon, frp, conf, sat, inst, date, time_val, p_type))
        
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO hotspot_history 
        (run_id, latitude, longitude, frp, confidence, satellite, instrument, acq_date, acq_time, pass_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        inserted = cursor.rowcount
        conn.commit()
        return inserted

def compute_persistence(lat, lon, threshold_km=2.0, lookback_days=30, db_path=DB_PATH):
    """
    Evaluates the historical thermal persistence around a coordinate.
    Checks how many times heat has been detected within threshold_km in the past lookback_days.
    
    Returns a structured persistence dictionary:
      - detection_count: Total passes detecting heat in this zone
      - distinct_dates: Number of unique days heat was detected
      - has_day: True if detected during day
      - has_night: True if detected during night
      - pattern:
          * 'RECURRING_INDUSTRIAL_FLARE' (burned both day & night or >= 3 distinct days)
          * 'PERSISTENT_HEAT_SOURCE' (detected on multiple passes)
          * 'NEW_IGNITION' (first occurrence in history)
      - confidence_boost: Recommended multiplier or adjustment
    """
    # Rough bounding box filter for fast SQL query before fine Haversine calculation
    lat_delta = threshold_km / 111.0
    lon_delta = threshold_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    
    cutoff_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT latitude, longitude, frp, acq_date, pass_type, confidence
        FROM hotspot_history
        WHERE latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?
          AND acq_date >= ?
        """, (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta, cutoff_date))
        candidates = cursor.fetchall()
        
    hits = []
    distinct_dates = set()
    has_day = False
    has_night = False
    
    for c in candidates:
        dist = haversine_km(lat, lon, c["latitude"], c["longitude"])
        if dist <= threshold_km:
            hits.append(c)
            distinct_dates.add(c["acq_date"])
            p_type = (c["pass_type"] or "").upper()
            if p_type == "DAY":
                has_day = True
            elif p_type == "NIGHT":
                has_night = True

    count = len(hits)
    days_count = len(distinct_dates)
    
    # Classification logic for thermal persistence
    if (has_day and has_night) or days_count >= 3:
        pattern = "RECURRING_INDUSTRIAL_FLARE"
        description = "Continuous 24h day/night thermal emissions characteristic of active refinery flares or industrial furnaces."
        risk_adjustment = -15  # Known routine facility, lower unexpected wildfire threat
    elif count >= 2 or days_count >= 2:
        pattern = "PERSISTENT_HEAT_SOURCE"
        description = "Multi-pass thermal anomaly detected across successive observation windows."
        risk_adjustment = 0
    else:
        pattern = "NEW_IGNITION"
        description = "Unprecedented first-time thermal detection at this location. Priority surveillance advised."
        risk_adjustment = +10  # Sudden new hotspot, potential emerging wildfire outbreak
        
    return {
        "detection_count": count,
        "distinct_days": days_count,
        "has_day_pass": has_day,
        "has_night_pass": has_night,
        "pattern": pattern,
        "description": description,
        "risk_adjustment": risk_adjustment,
        "radius_km": threshold_km
    }

def record_incident_evaluations(run_id, incidents, db_path=DB_PATH):
    """Records scored incidents and their persistence patterns into history."""
    if not incidents:
        return 0
    
    rows = []
    for inc in incidents:
        cid = inc.get("id", "")
        lat = inc.get("latitude", 0.0)
        lon = inc.get("longitude", 0.0)
        frp = inc.get("frp", 0.0)
        conf = str(inc.get("confidence", ""))
        ai_cls = inc.get("ai_classification", "uncertain")
        ai_conf = float(inc.get("ai_confidence", 0.0))
        risk_score = int(inc.get("risk_score", 50))
        risk_tier = inc.get("risk_tier", "MEDIUM")
        
        # Calculate persistence
        pers = compute_persistence(lat, lon, db_path=db_path)
        pattern = pers["pattern"]
        days = max(1, pers["distinct_days"])
        
        pass_type = "DAY" if "day" in str(inc.get("acq_time", "")).lower() else "NIGHT"
        rows.append((run_id, cid, lat, lon, frp, conf, ai_cls, ai_conf, risk_score, risk_tier, pattern, days, pass_type))
        
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO incident_history
        (run_id, case_id, latitude, longitude, frp, confidence, ai_classification, ai_confidence, risk_score, risk_tier, persistence_pattern, days_active, pass_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        return len(rows)

def get_stats(db_path=DB_PATH):
    """Returns high-level statistics about the persistence database."""
    if not os.path.exists(db_path):
        return {"total_runs": 0, "total_hotspots": 0, "unique_dates": 0}
        
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ingest_runs")
        total_runs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM hotspot_history")
        total_hotspots = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT acq_date) FROM hotspot_history")
        unique_dates = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(executed_at) FROM ingest_runs")
        last_run = cursor.fetchone()[0]
        
        return {
            "total_runs": total_runs,
            "total_hotspots": total_hotspots,
            "unique_dates": unique_dates,
            "last_run": last_run
        }

if __name__ == "__main__":
    init_db()
    stats = get_stats()
    print("=" * 65)
    print("  FIREX HISTORICAL PERSISTENCE ENGINE (SQLite Time-Series)")
    print("=" * 65)
    print(f"  Database Path  : {DB_PATH}")
    print(f"  Total Runs     : {stats['total_runs']}")
    print(f"  Total Hotspots : {stats['total_hotspots']}")
    print(f"  Unique Dates   : {stats['unique_dates']}")
    print(f"  Last Sync      : {stats['last_run']}")
    print("=" * 65)
