import sys
from pathlib import Path
import sqlite3

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.gis.mining_basins import is_in_major_mining_basin

def migrate_mining_climatology():
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    con = sqlite3.connect(db_path, timeout=60.0)
    cur = con.cursor()
    
    print("[*] Inspecting thermal_climatology for mining basins...")
    cur.execute("SELECT spatial_key, latitude, longitude, active_days, night_ratio, is_routine_flare, site_classification_hint FROM thermal_climatology")
    rows = cur.fetchall()
    print(f"[*] Total rows in thermal_climatology: {len(rows)}")
    
    updated_count = 0
    updates = []
    
    for spatial_key, lat, lon, active_days, night_ratio, is_routine, hint in rows:
        is_mining, basin = is_in_major_mining_basin(lat, lon)
        if is_mining:
            # Must not be routine flare; hint must be COAL_MINING_BASIN
            if is_routine == 1 or hint != "COAL_MINING_BASIN":
                updates.append((0, "COAL_MINING_BASIN", spatial_key))
                updated_count += 1
    
    print(f"[*] Found {updated_count} cells in mining basins that need update.")
    if updates:
        cur.executemany("UPDATE thermal_climatology SET is_routine_flare = ?, site_classification_hint = ? WHERE spatial_key = ?", updates)
        con.commit()
        print(f"[OK] Successfully updated {updated_count} mining cells in thermal_climatology.")
    else:
        print("[OK] All cells already up to date.")
        
    con.close()

if __name__ == "__main__":
    migrate_mining_climatology()
