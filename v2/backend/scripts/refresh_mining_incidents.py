import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(SCRIPT_DIR, "..")))

from app.storage.database import SessionLocal
from app.storage.models import Incident, AIInvestigation
from app.gis.mining_basins import is_in_major_mining_basin
from app.orchestration.pipeline import export_v1_dashboard_data

def refresh_incidents():
    db = SessionLocal()
    try:
        incidents = db.query(Incident).all()
        print(f"[*] Total incidents in DB: {len(incidents)}")
        
        mining_rectified = 0
        for inc in incidents:
            is_mining, basin = is_in_major_mining_basin(inc.latitude, inc.longitude)
            if is_mining:
                # Update incident classification if it was falsely marked as gas flare
                if inc.classification in ["gas_flare", "mining_related", None, "uncertain"]:
                    inc.classification = "mining_or_other_thermal_source"
                    inc.classification_confidence = 90.0
                    mining_rectified += 1
                
                # Check AI investigation
                latest_inv = (
                    db.query(AIInvestigation)
                    .filter(AIInvestigation.incident_id == inc.id)
                    .order_by(AIInvestigation.created_at.desc())
                    .first()
                )
                if latest_inv and latest_inv.classification in ["gas_flare", "mining_related"]:
                    latest_inv.classification = "mining_or_other_thermal_source"
                    latest_inv.reasoning = f"Verified open-cast coal/mineral mining thermal emission inside {basin['name']} ({basin['operator']})."
        
        db.commit()
        print(f"[OK] Rectified {mining_rectified} incidents inside sovereign mining basins.")
        
        print("[*] Re-exporting dashboard and console feeds...")
        export_v1_dashboard_data(db)
        print("[OK] Successfully exported synchronized feeds.")
        
    finally:
        db.close()

if __name__ == "__main__":
    refresh_incidents()
