"""
Clean Foreign Points & Re-resolve Sovereign Admin Boundaries
1. Deletes foreign incidents (like INC-2026-0323 in Xinjiang, China)
2. Deletes raw foreign observations (latitude > 35.7°N)
3. Re-resolves state and district for all valid Indian incidents (e.g. Arunachal Pradesh, Bombay High offshore)
4. Re-exports incidents.json to frontend and v1 dashboard
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.storage.database import SessionLocal
from app.storage.models import Incident, Observation, IncidentObservation, AIInvestigation, SeverityAssessment, AlertRecord, IncidentEvent, ImageryRecord
from app.gis.boundaries import is_within_indian_sovereign_territory, resolve_admin_boundary
from app.orchestration.pipeline import export_v1_dashboard_data

def main():
    db = SessionLocal()
    try:
        # 1. Find foreign incidents
        all_incidents = db.query(Incident).all()
        foreign_incidents = [inc for inc in all_incidents if not is_within_indian_sovereign_territory(inc.latitude, inc.longitude)]
        print(f"Found {len(foreign_incidents)} foreign incidents to delete:")
        for inc in foreign_incidents:
            print(f"  Deleting {inc.incident_code} at {inc.latitude}, {inc.longitude} (Foreign Territory)")
            # Delete child relations
            db.query(IncidentObservation).filter(IncidentObservation.incident_id == inc.id).delete()
            db.query(AIInvestigation).filter(AIInvestigation.incident_id == inc.id).delete()
            db.query(SeverityAssessment).filter(SeverityAssessment.incident_id == inc.id).delete()
            db.query(AlertRecord).filter(AlertRecord.incident_id == inc.id).delete()
            db.query(IncidentEvent).filter(IncidentEvent.incident_id == inc.id).delete()
            db.query(ImageryRecord).filter(ImageryRecord.incident_id == inc.id).delete()
            db.delete(inc)
        db.commit()

        # 2. Delete foreign observations (> 35.7°N)
        del_obs_count = db.query(Observation).filter(Observation.latitude > 35.7).delete()
        print(f"Deleted {del_obs_count} foreign observations with latitude > 35.7°N")
        db.commit()

        # 3. Re-resolve state & district for remaining incidents
        remaining_incidents = db.query(Incident).all()
        updated_count = 0
        for inc in remaining_incidents:
            admin_ctx = resolve_admin_boundary(inc.latitude, inc.longitude)
            if admin_ctx.get("state") and (inc.state != admin_ctx["state"] or inc.district != admin_ctx.get("district")):
                inc.state = admin_ctx["state"]
                inc.district = admin_ctx.get("district") or inc.district
                updated_count += 1
        db.commit()
        print(f"Re-resolved administrative boundaries for {updated_count} incidents (Arunachal Pradesh, Bombay High, etc.)")

        # 4. Re-export incidents.json
        export_res = export_v1_dashboard_data(db)
        print("Re-exported dashboard incidents data:", export_res)

    finally:
        db.close()

if __name__ == "__main__":
    main()
