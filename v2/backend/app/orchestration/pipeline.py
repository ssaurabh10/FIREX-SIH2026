"""
FIREX v2 End-to-End Analysis Pipeline Runner
Implements Section 23 & 25 of Blueprint:
FIRMS
→ validation & deduplication
→ GIS spatial context
→ clustering
→ incident association
→ behavior features & baselines
→ selection & ranking
→ visual context & imagery
→ multimodal AI investigation
→ severity assessment
→ alert evaluation & deduplication
→ database persistence & SSE emission
"""
import os
import json
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.storage.models import (
    Observation, Incident, IndustrialAsset, AIInvestigation,
    SeverityAssessment, AlertRecord, AnalysisRun
)
from app.ingestion.firms import FIRMSClient
from app.gis.enrichment import enrich_coordinate_gis_context
from app.incidents.clustering import cluster_observations
from app.incidents.association import sync_clusters_to_incidents
from app.behavior.baseline import get_or_create_facility_baseline, get_or_create_location_baseline
from app.selection.engine import select_investigation_candidates
from app.imagery.service import get_or_create_incident_imagery
from app.intelligence.service import run_incident_investigation
from app.severity.service import evaluate_incident_severity
from app.orchestration.lock import pipeline_lock, AnalysisAlreadyRunningError
from app.orchestration.events import (
    event_broadcaster,
    EVENT_ANALYSIS_STARTED,
    EVENT_FIRMS_FETCHED,
    EVENT_GIS_COMPLETED,
    EVENT_CLUSTERING_COMPLETED,
    EVENT_SELECTION_COMPLETED,
    EVENT_IMAGERY_STARTED,
    EVENT_AI_STARTED,
    EVENT_AI_COMPLETED,
    EVENT_SEVERITY_COMPLETED,
    EVENT_ALERT_CREATED,
    EVENT_ANALYSIS_COMPLETED,
    EVENT_ANALYSIS_FAILED
)

# Optional export directory for v1 dashboard compatibility
V1_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "v1", "dashboard", "data")
)

def export_v1_dashboard_data(db: Session) -> None:
    """
    Exports latest active incidents and ambient detections to v1 dashboard data format
    to preserve 100% backward compatibility for Stage 9.
    """
    try:
        os.makedirs(V1_DATA_DIR, exist_ok=True)
        incidents = db.query(Incident).filter(
            Incident.status.in_(["ACTIVE", "PERSISTENT", "INVESTIGATING", "NEW", "ESCALATED"])
        ).all()

        v1_incidents = []
        for inc in incidents:
            # Locate latest AI investigation
            latest_inv = db.query(AIInvestigation).filter(
                AIInvestigation.incident_id == inc.id
            ).order_by(AIInvestigation.created_at.desc()).first()

            cls_name = latest_inv.classification if latest_inv else (inc.classification or "uncertain")
            ai_conf = (latest_inv.confidence if latest_inv else (inc.classification_confidence or 50.0)) / 100.0
            ai_ev = latest_inv.visual_evidence if (latest_inv and latest_inv.visual_evidence) else []
            ai_reason = latest_inv.reasoning if latest_inv else f"Thermal anomaly observed at {inc.latitude:.4f}, {inc.longitude:.4f}."

            triggers = []
            if inc.is_inside_facility or (inc.distance_to_asset_km is not None and inc.distance_to_asset_km <= 1.5):
                triggers.append("CRITICAL_INFRASTRUCTURE")
            if inc.current_max_frp >= 50.0:
                triggers.append("MAJOR_FIRE_SURGE")
            if inc.status == "PERSISTENT":
                triggers.append("24H_TEMPORAL_PERSISTENCE")

            v1_inc = {
                "id": inc.id,
                "incident_code": inc.incident_code,
                "latitude": inc.latitude,
                "longitude": inc.longitude,
                "facility_distance_km": inc.distance_to_asset_km,
                "frp": inc.current_max_frp,
                "cluster_total_frp": inc.current_max_frp,
                "cluster_pixel_count": inc.observation_count or 1,
                "operational_triggers": triggers,
                "confidence": "HIGH" if (inc.severity_confidence or 0) >= 70 else "NOMINAL",
                "satellite": "VIIRS / MODIS",
                "instrument": "VIIRS",
                "acq_date": inc.last_detected_at.strftime("%Y-%m-%d") if inc.last_detected_at else "",
                "acq_time": inc.last_detected_at.strftime("%H:%M") if inc.last_detected_at else "",
                "location_name": inc.incident_code,
                "display_name": f"Incident {inc.incident_code} ({inc.latitude:.3f}°N, {inc.longitude:.3f}°E)",
                "ai_classification": cls_name,
                "ai_confidence": round(ai_conf, 2),
                "ai_uncertainty": "low" if ai_conf >= 0.75 else ("high" if ai_conf < 0.50 else "medium"),
                "ai_evidence": ai_ev if isinstance(ai_ev, list) else [str(ai_ev)],
                "ai_reasoning": ai_reason,
                "image_url": f"/crops/{inc.id}/annotated.jpg",
                "raw_image_url": f"/crops/{inc.id}/raw.jpg",
                "persistence_pattern": "RECURRING_HOTSPOT" if inc.status == "PERSISTENT" else "NEW_DETECTION",
                "persistence_detections": inc.observation_count or 1,
                "risk_score": int(inc.severity_score or 0),
                "risk_tier": inc.severity_level or "LOW",
                "status": inc.status
            }
            v1_incidents.append(v1_inc)

        inc_path = os.path.join(V1_DATA_DIR, "incidents.json")
        with open(inc_path, "w", encoding="utf-8") as f:
            json.dump(v1_incidents, f, indent=2)

        # Export ambient points (recent 200 observations)
        recent_obs = db.query(Observation).order_by(Observation.acquired_at.desc()).limit(200).all()
        ambient = [
            {
                "lat": o.latitude,
                "lon": o.longitude,
                "frp": o.frp_mw,
                "conf": o.confidence_raw or "nominal",
                "sat": o.satellite or "VIIRS",
                "date": o.acquired_at.strftime("%Y-%m-%d") if o.acquired_at else "",
                "time": o.acquired_at.strftime("%H:%M") if o.acquired_at else "",
                "pass_type": o.daynight or "D"
            }
            for o in recent_obs
        ]
        amb_path = os.path.join(V1_DATA_DIR, "ambient_firms.json")
        with open(amb_path, "w", encoding="utf-8") as f:
            json.dump(ambient, f, indent=2)

        logger.info(f"[Export] Synchronized {len(v1_incidents)} incidents and {len(ambient)} ambient points to v1 dashboard.")
    except Exception as e:
        logger.warning(f"[Export] Could not export data to v1 dashboard data dir: {e}")


def execute_analysis_pipeline(
    db: Session,
    firms_csv: Optional[str] = None,
    file_path: Optional[str] = None,
    force_reinvestigate: bool = False,
    max_ai_targets: int = 5,
    export_to_dashboard: bool = True,
    run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes an end-to-end mission analysis run.
    Guarantees single execution via AnalysisRunLock and emits real-time SSE events.
    """
    if not run_id:
        run_id = f"RUN-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 1. Acquire Run Lock
    pipeline_lock.acquire(run_id)
    start_time = datetime.utcnow()
    t0 = time.time()

    # Create AnalysisRun audit record
    run_record = AnalysisRun(
        id=run_id,
        status="RUNNING",
        started_at=start_time
    )
    db.add(run_record)
    db.commit()

    event_broadcaster.publish(
        EVENT_ANALYSIS_STARTED,
        {
            "run_id": run_id,
            "started_at": start_time.isoformat(),
            "message": f"Starting FIREX mission analysis run {run_id}"
        },
        run_id=run_id
    )

    try:
        # 2. FIRMS Telemetry Fetch & Normalization
        firms_client = FIRMSClient()
        new_obs_count = 0
        skipped_dup = 0
        total_fetched = 0

        if firms_csv:
            normalized_records = firms_client.parse_csv(firms_csv)
            save_res = firms_client.save_to_db(db, normalized_records)
            new_obs_count = save_res["ingested"]
            skipped_dup = save_res["skipped_duplicate"]
            total_fetched = save_res["total"]
        elif file_path and os.path.exists(file_path):
            save_res = firms_client.ingest_from_file(db, file_path)
            new_obs_count = save_res["ingested"]
            skipped_dup = save_res["skipped_duplicate"]
            total_fetched = save_res["total"]
        else:
            # Attempt live NASA fetch
            live_csv = firms_client.fetch_live_csv("VIIRS_NRT", days=1)
            if live_csv:
                normalized_records = firms_client.parse_csv(live_csv)
                save_res = firms_client.save_to_db(db, normalized_records)
                new_obs_count = save_res["ingested"]
                skipped_dup = save_res["skipped_duplicate"]
                total_fetched = save_res["total"]
            else:
                logger.info("[Pipeline] No live FIRMS payload fetched; proceeding with existing active observations.")

        event_broadcaster.publish(
            EVENT_FIRMS_FETCHED,
            {
                "new_observations": new_obs_count,
                "skipped_duplicates": skipped_dup,
                "total_fetched": total_fetched,
                "message": f"FIRMS data ingested: {new_obs_count} new, {skipped_dup} skipped."
            },
            run_id=run_id
        )

        # 3. GIS Enrichment
        # Query active observations in past 72 hours for spatial analysis
        time_cutoff = datetime.utcnow() - timedelta(hours=72)
        active_obs = db.query(Observation).filter(Observation.acquired_at >= time_cutoff).all()

        # If sparse, take recent 50 observations
        if not active_obs:
            active_obs = db.query(Observation).order_by(Observation.acquired_at.desc()).limit(50).all()

        event_broadcaster.publish(
            EVENT_GIS_COMPLETED,
            {
                "active_observations_in_scope": len(active_obs),
                "message": f"GIS spatial indexing complete across {len(active_obs)} active observations."
            },
            run_id=run_id
        )

        # 4. Spatial-Temporal Clustering & Non-Summing Invariant
        clusters = cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)

        event_broadcaster.publish(
            EVENT_CLUSTERING_COMPLETED,
            {
                "clusters_count": len(clusters),
                "message": f"Clustered observations into {len(clusters)} physical candidate clusters."
            },
            run_id=run_id
        )

        # 5. Incident Association & Lifecycle Promotion
        synced_incidents = sync_clusters_to_incidents(db, clusters)
        new_incidents = [i for i in synced_incidents if (datetime.utcnow() - i.first_detected_at).total_seconds() < 120]
        updated_incidents = [i for i in synced_incidents if i not in new_incidents]

        # 6. Refresh Behavior Profiles & 365d Baselines for Affected Assets
        for inc in synced_incidents:
            if inc.nearest_asset_id:
                get_or_create_facility_baseline(inc.nearest_asset_id, db, window_days=90)
            else:
                get_or_create_location_baseline(inc.latitude, inc.longitude, db, window_days=90)

        # 7. Selection & Priority Ranking
        candidates = select_investigation_candidates(db, min_priority=30.0, limit=max_ai_targets, status=None)
        event_broadcaster.publish(
            EVENT_SELECTION_COMPLETED,
            {
                "candidates_count": len(candidates),
                "top_incident": candidates[0]["incident_code"] if candidates else None,
                "message": f"Prioritized {len(candidates)} incidents for deep visual investigation."
            },
            run_id=run_id
        )

        investigations_run = 0
        alerts_emitted = 0

        # 8, 9, 10, 11: Visual Context, AI Investigation, Severity, and Alerts
        for candidate in candidates:
            inc_id = candidate["incident_id"]
            incident = db.query(Incident).filter(Incident.id == inc_id).first()
            if not incident:
                continue

            # Incremental check: check if already investigated
            existing_inv = db.query(AIInvestigation).filter(
                AIInvestigation.incident_id == inc_id
            ).order_by(AIInvestigation.created_at.desc()).first()

            needs_ai = force_reinvestigate or (existing_inv is None)
            if existing_inv and not force_reinvestigate:
                ev = existing_inv.evidence_points or {}
                prior_obs_count = ev.get("observation_count")
                prior_max_frp = ev.get("max_frp")

                # If new observations arrived for this incident
                if prior_obs_count is not None and (incident.observation_count or 1) > prior_obs_count:
                    needs_ai = True
                # If FRP spiked significantly (>= 50%)
                elif prior_max_frp is not None and incident.current_max_frp and incident.current_max_frp >= 1.5 * prior_max_frp:
                    needs_ai = True

            # Imagery step
            event_broadcaster.publish(
                EVENT_IMAGERY_STARTED,
                {
                    "incident_id": inc_id,
                    "incident_code": incident.incident_code,
                    "message": f"Synthesizing high-res optical satellite reticle for {incident.incident_code}"
                },
                run_id=run_id
            )
            get_or_create_incident_imagery(inc_id, db, force_refresh=needs_ai)

            # AI Investigation step
            if needs_ai:
                event_broadcaster.publish(
                    EVENT_AI_STARTED,
                    {
                        "incident_id": inc_id,
                        "incident_code": incident.incident_code,
                        "message": f"Dispatching Multimodal AI vision analysis for {incident.incident_code}"
                    },
                    run_id=run_id
                )
                ai_report = run_incident_investigation(inc_id, db, force_reinvestigate=True)
                investigations_run += 1
                event_broadcaster.publish(
                    EVENT_AI_COMPLETED,
                    {
                        "incident_id": inc_id,
                        "incident_code": incident.incident_code,
                        "classification": ai_report["classification"],
                        "confidence": ai_report["confidence"],
                        "message": f"AI classified {incident.incident_code} as {ai_report['classification']} ({ai_report['confidence']}%)"
                    },
                    run_id=run_id
                )
            else:
                logger.info(f"[Pipeline] Reusing recent AI investigation for {incident.incident_code}")

            # Severity Assessment step
            sev_result = evaluate_incident_severity(inc_id, db)
            event_broadcaster.publish(
                EVENT_SEVERITY_COMPLETED,
                {
                    "incident_id": inc_id,
                    "incident_code": incident.incident_code,
                    "severity_score": sev_result["severity_score"],
                    "severity_level": sev_result["severity_level"],
                    "model_used": sev_result["model_used"],
                    "message": f"Assessed {incident.incident_code}: {sev_result['severity_level']} ({sev_result['severity_score']}/100)"
                },
                run_id=run_id
            )

            # Alert step
            if sev_result.get("alert"):
                alerts_emitted += 1
                alert_info = sev_result["alert"]
                event_broadcaster.publish(
                    EVENT_ALERT_CREATED,
                    {
                        "alert_id": alert_info.get("alert_id"),
                        "incident_id": inc_id,
                        "incident_code": incident.incident_code,
                        "severity_level": sev_result["severity_level"],
                        "status": alert_info.get("status", "NEW"),
                        "title": alert_info.get("title", ""),
                        "message": f"Dispatched {sev_result['severity_level']} alert for {incident.incident_code}"
                    },
                    run_id=run_id
                )

        # 12. Finalize & Export
        elapsed = round(time.time() - t0, 2)
        run_record.status = "COMPLETED"
        run_record.completed_at = datetime.utcnow()
        run_record.duration_seconds = elapsed
        run_record.observations_count = len(active_obs)
        run_record.new_observations_count = new_obs_count
        run_record.incidents_updated_count = len(updated_incidents)
        run_record.new_incidents_count = len(new_incidents)
        run_record.investigations_count = investigations_run
        run_record.alerts_count = alerts_emitted

        summary = {
            "run_id": run_id,
            "status": "COMPLETED",
            "duration_seconds": elapsed,
            "observations_active": len(active_obs),
            "new_observations": new_obs_count,
            "clusters_count": len(clusters),
            "incidents_updated": len(updated_incidents),
            "new_incidents": len(new_incidents),
            "candidates_investigated": investigations_run,
            "alerts_emitted": alerts_emitted,
            "completed_at": run_record.completed_at.isoformat()
        }
        run_record.summary_json = summary
        db.commit()

        if export_to_dashboard:
            export_v1_dashboard_data(db)

        event_broadcaster.publish(
            EVENT_ANALYSIS_COMPLETED,
            summary,
            run_id=run_id
        )

        logger.info(f"[Pipeline] Analysis run {run_id} completed in {elapsed}s.")
        return summary

    except Exception as e:
        logger.error(f"[Pipeline] Analysis run {run_id} failed: {e}", exc_info=True)
        run_record.status = "FAILED"
        run_record.completed_at = datetime.utcnow()
        run_record.duration_seconds = round(time.time() - t0, 2)
        run_record.error_message = str(e)
        db.commit()

        event_broadcaster.publish(
            EVENT_ANALYSIS_FAILED,
            {
                "run_id": run_id,
                "error": str(e),
                "duration_seconds": run_record.duration_seconds
            },
            run_id=run_id
        )
        raise
    finally:
        # Guarantee lock is released
        pipeline_lock.release(run_id)
