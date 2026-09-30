import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(SCRIPT_DIR, "..")))

from app.storage.database import SessionLocal
from app.storage.models import Incident, AIInvestigation, IndustrialAsset
from app.gis.mining_basins import is_in_major_mining_basin
from app.gis.assets import find_nearest_asset, is_metallurgical_or_manufacturing_facility, is_flaring_facility, seed_industrial_assets
from app.intelligence.provider import FALLBACK_CONFIDENCE_CEILING
from app.orchestration.pipeline import export_v1_dashboard_data

def refresh_industrial_incidents():
    db = SessionLocal()
    try:
        # 1. Sync industrial assets registry
        asset_count = seed_industrial_assets(db, force_refresh=True)
        print(f"[*] Verified {asset_count} industrial facilities in database registry.")

        incidents = db.query(Incident).all()
        print(f"[*] Total incidents in DB: {len(incidents)}")
        
        metal_rectified = 0
        mining_rectified = 0
        associated_count = 0

        for inc in incidents:
            # Check mining basin first
            is_mining, basin = is_in_major_mining_basin(inc.latitude, inc.longitude)
            if is_mining:
                # Confidence is the fallback ceiling, not 90.0: this label is
                # derived from a basin polygon with no vision model in the loop,
                # so it is a spatial prior. At 90.0 it satisfied the
                # `ai_confidence >= 80` gate on the CRITICAL industrial override
                # in `severity/scoring.py` (INV-1).
                if inc.classification in ["gas_flare", "mining_related", None, "uncertain"]:
                    inc.classification = "mining_or_other_thermal_source"
                    inc.classification_confidence = FALLBACK_CONFIDENCE_CEILING
                    mining_rectified += 1

                latest_inv = (
                    db.query(AIInvestigation)
                    .filter(AIInvestigation.incident_id == inc.id)
                    .order_by(AIInvestigation.created_at.desc())
                    .first()
                )
                if latest_inv and latest_inv.classification in ["gas_flare", "mining_related"]:
                    vision_verdict = latest_inv.classification
                    latest_inv.classification = "mining_or_other_thermal_source"
                    latest_inv.reasoning = f"Spatial prior: detection inside the mapped {basin['name']} concession ({basin['operator']}). Vision returned {vision_verdict}."
                continue

            # Check nearest industrial facility
            asset_info = find_nearest_asset(inc.latitude, inc.longitude, db)
            dist_km = asset_info.get("distance_km") or 999.0
            is_inside = asset_info.get("is_inside_facility", False)
            is_near = is_inside or (dist_km <= 5.0)

            if is_near and asset_info.get("asset_id"):
                inc.nearest_asset_id = asset_info["asset_id"]
                inc.distance_to_asset_km = dist_km
                inc.is_inside_facility = is_inside
                associated_count += 1

                ftype = asset_info.get("facility_type")
                findustry = asset_info.get("industry")
                fcategory = asset_info.get("category")
                fname = asset_info.get("facility_name")
                foperator = asset_info.get("operator")

                is_metal = is_metallurgical_or_manufacturing_facility(ftype, findustry) or fcategory == "industrial_fire"
                
                if is_metal:
                    # Same reasoning as the mining branch above. `industrial_fire`
                    # is a specific event claim and this one is the most
                    # consequential: it is the label severity Override 2
                    # (`severity/scoring.py`) escalates to CRITICAL, so a
                    # geometry-only 88.0 here produced CRITICAL bands on
                    # ordinary process heat.
                    if inc.classification in ["gas_flare", None, "uncertain"]:
                        inc.classification = "industrial_fire"
                        inc.classification_confidence = FALLBACK_CONFIDENCE_CEILING
                        metal_rectified += 1

                    latest_inv = (
                        db.query(AIInvestigation)
                        .filter(AIInvestigation.incident_id == inc.id)
                        .order_by(AIInvestigation.created_at.desc())
                        .first()
                    )
                    if latest_inv and latest_inv.classification == "gas_flare":
                        latest_inv.classification = "industrial_fire"
                        latest_inv.reasoning = f"Spatial prior: detection inside the mapped metallurgical facility {fname} ({foperator}). Vision returned gas_flare."
        
        db.commit()
        print(f"[OK] Re-associated {associated_count} incidents to nearest industrial assets.")
        print(f"[OK] Rectified {metal_rectified} incidents near metallurgical & steel facilities.")
        print(f"[OK] Maintained {mining_rectified} rectified mining basin incidents.")
        
        print("[*] Re-exporting synchronized dashboard feed (incidents.json)...")
        export_v1_dashboard_data(db)
        print("[OK] Successfully exported synchronized feeds.")
        
    finally:
        db.close()

if __name__ == "__main__":
    refresh_industrial_incidents()
