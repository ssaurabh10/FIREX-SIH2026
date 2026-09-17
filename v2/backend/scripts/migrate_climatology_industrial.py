import sys
from pathlib import Path
import sqlite3

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.gis.assets import INITIAL_INDUSTRIAL_FACILITIES, is_metallurgical_or_manufacturing_facility, is_flaring_facility
from app.gis.spatial import haversine_distance_km

def migrate_industrial_climatology():
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()
    
    print("[*] Inspecting thermal_climatology for industrial metallurgical & steel facilities...")
    cur.execute("SELECT spatial_key, latitude, longitude, active_days, night_ratio, is_routine_flare, site_classification_hint FROM thermal_climatology")
    rows = cur.fetchall()
    print(f"[*] Total rows in thermal_climatology: {len(rows)}")
    
    # Pre-filter metallurgical assets
    metal_assets = [
        f for f in INITIAL_INDUSTRIAL_FACILITIES 
        if is_metallurgical_or_manufacturing_facility(f["facility_type"], f.get("industry")) or f.get("category") == "industrial_fire"
    ]
    print(f"[*] Total metallurgical/manufacturing facilities in registry: {len(metal_assets)}")
    
    updated_count = 0
    updates = []
    
    for spatial_key, lat, lon, active_days, night_ratio, is_routine, hint in rows:
        # Check proximity to any metallurgical asset
        for ma in metal_assets:
            dist_km = haversine_distance_km(lat, lon, ma["latitude"], ma["longitude"])
            radius_km = (ma["buffer_radius_meters"] / 1000.0) + 2.0  # Facility buffer + 2km zone
            if dist_km <= radius_km:
                if is_routine == 1 or hint == "ROUTINE_FLARE":
                    updates.append((0, "METALLURGICAL_INDUSTRIAL", spatial_key))
                    updated_count += 1
                break
    
    print(f"[*] Found {updated_count} cells near metallurgical assets falsely tagged as routine gas flares.")
    if updates:
        cur.executemany("UPDATE thermal_climatology SET is_routine_flare = ?, site_classification_hint = ? WHERE spatial_key = ?", updates)
        con.commit()
        print(f"[OK] Successfully migrated {updated_count} industrial cells in thermal_climatology.")
    else:
        print("[OK] All industrial cells are already accurately calibrated.")
        
    con.close()

if __name__ == "__main__":
    migrate_industrial_climatology()
