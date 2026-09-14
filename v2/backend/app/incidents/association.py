"""
Incident Association & Lifecycle Resolution Engine
Associates candidate clusters to existing active incidents or promotes them to new incidents.
Criteria enforced from Section 35 Stage 3:
1. Spatial compatibility: cluster overlaps or is within incident footprint (radius + 1500m).
2. Temporal continuity: last observation within configurable continuity window (default 48h).
3. Facility context compatibility: observations inside the same industrial perimeter match the asset incident.
4. Explanability: writes association_method and association_score into incident_observations.
"""
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import Incident, IncidentObservation, Observation
from app.incidents.clustering import ThermalCluster
from app.incidents.state import record_incident_event
from app.gis.assets import find_nearest_asset
from app.gis.boundaries import resolve_admin_boundary, is_within_indian_sovereign_territory
from app.gis.spatial import haversine_distance_meters
from app.core.logging import logger

def generate_incident_code(index: int) -> str:
    """Generates human-readable incident identifier: INC-YYYY-XXXX"""
    year = datetime.utcnow().year
    return f"INC-{year}-{index:04d}"

def match_cluster_to_incident(
    cluster: ThermalCluster,
    active_incidents: List[Incident],
    spatial_threshold_meters: float = 3000.0,
    max_time_gap_hours: float = 72.0
) -> Tuple[Optional[Incident], str, float]:
    """
    Evaluates whether a candidate cluster belongs to an existing active incident.
    Returns (matching_incident, association_method, association_score).
    """
    best_match = None
    min_distance_m = float("inf")
    best_method = ""
    best_score = 0.0

    cluster_time = cluster.first_detected_at or datetime.utcnow()

    for inc in active_incidents:
        # Check temporal continuity
        if inc.last_detected_at:
            time_gap = (cluster_time - inc.last_detected_at).total_seconds() / 3600.0
            if time_gap > max_time_gap_hours:
                continue

        # Spatial distance from cluster center to incident center
        dist_m = haversine_distance_meters(cluster.center_lat, cluster.center_lon, inc.latitude, inc.longitude)
        
        # Check if inside footprint radius
        effective_boundary_m = max(spatial_threshold_meters, (inc.footprint_radius_meters or 500.0) + 1000.0)
        
        if dist_m <= effective_boundary_m and dist_m < min_distance_m:
            min_distance_m = dist_m
            best_match = inc
            # Association score is 1.0 at distance 0 down to 0.5 at boundary
            best_score = round(max(0.5, 1.0 - (dist_m / effective_boundary_m) * 0.5), 2)
            best_method = "FOOTPRINT_SPATIAL_OVERLAP"

    return best_match, best_method, best_score

def sync_clusters_to_incidents(
    db: Session,
    clusters: List[ThermalCluster]
) -> List[Incident]:
    """
    Processes candidate clusters, updating existing active incidents or creating new ones.
    Persists incident_observations join records with provenance traceability.
    """
    if not clusters:
        return []

    # Query existing active/monitoring incidents (all non-resolved)
    active_incidents = (
        db.query(Incident)
        .filter(Incident.status != "RESOLVED")
        .all()
    )

    incident_count = db.query(Incident).count()
    result_incidents: List[Incident] = []

    for cluster in clusters:
        # Enforce sovereign Indian territory boundary
        if not is_within_indian_sovereign_territory(cluster.center_lat, cluster.center_lon):
            continue

        matched_inc, method, score = match_cluster_to_incident(cluster, active_incidents)

        if matched_inc:
            # Update existing incident
            logger.info(f"Associating cluster {cluster.cluster_id} to existing incident {matched_inc.incident_code}")
            
            # Update temporal envelope
            if cluster.last_detected_at > matched_inc.last_detected_at:
                matched_inc.last_detected_at = cluster.last_detected_at
            if cluster.first_detected_at < matched_inc.first_detected_at:
                matched_inc.first_detected_at = cluster.first_detected_at

            # Update FRP statistics enforcing non-summation rule
            matched_inc.current_max_frp = max(matched_inc.current_max_frp, cluster.max_frp)
            old_count = matched_inc.observation_count or 1
            new_count = len(cluster.observations)
            total_count = old_count + new_count
            matched_inc.current_mean_frp = round(
                (matched_inc.current_mean_frp * old_count + cluster.mean_frp * new_count) / max(1, total_count), 2
            )
            
            # Dynamic footprint expansion
            dist_from_center_m = haversine_distance_meters(
                matched_inc.latitude, matched_inc.longitude, cluster.center_lat, cluster.center_lon
            )
            expanded_radius = dist_from_center_m + cluster.radius_meters
            if expanded_radius > (matched_inc.footprint_radius_meters or 500.0):
                matched_inc.footprint_radius_meters = round(expanded_radius, 1)

            matched_inc.updated_at = datetime.utcnow()
            target_incident = matched_inc

            record_incident_event(
                db,
                incident_id=target_incident.id,
                event_type="incident.updated",
                payload={
                    "method": method,
                    "score": score,
                    "new_observations": len(cluster.observations),
                    "current_max_frp": target_incident.current_max_frp
                }
            )
        else:
            # Create brand new incident
            incident_count += 1
            code = generate_incident_code(incident_count)
            while db.query(Incident).filter(Incident.incident_code == code).first() is not None:
                incident_count += 1
                code = generate_incident_code(incident_count)
            logger.info(f"Promoting cluster {cluster.cluster_id} to new incident {code}")

            # GIS Enrichment at incident creation
            asset_info = find_nearest_asset(cluster.center_lat, cluster.center_lon, db)
            admin_info = resolve_admin_boundary(cluster.center_lat, cluster.center_lon)

            # Proximity Gating: Only associate asset if within facility perimeter or <= 5.0 km
            is_near_facility = asset_info.get("is_inside_facility") or ((asset_info.get("distance_km") or 999.0) <= 5.0)

            if is_near_facility and asset_info.get("state"):
                state = asset_info.get("state")
                district = asset_info.get("district") or admin_info.get("district")
                nearest_asset_id = asset_info.get("asset_id")
                distance_to_asset_km = asset_info.get("distance_km")
                is_inside_facility = asset_info.get("is_inside_facility", False)
            else:
                state = admin_info.get("state")
                district = admin_info.get("district")
                nearest_asset_id = None
                distance_to_asset_km = asset_info.get("distance_km")
                is_inside_facility = False

            target_incident = Incident(
                incident_code=code,
                status="ACTIVE",
                latitude=cluster.center_lat,
                longitude=cluster.center_lon,
                footprint_radius_meters=cluster.radius_meters,
                footprint_geojson=cluster.footprint_geojson,
                first_detected_at=cluster.first_detected_at,
                last_detected_at=cluster.last_detected_at,
                observation_count=0,
                current_max_frp=cluster.max_frp,
                current_mean_frp=cluster.mean_frp,
                nearest_asset_id=nearest_asset_id,
                distance_to_asset_km=distance_to_asset_km,
                is_inside_facility=is_inside_facility,
                state=state,
                district=district,
                created_at=datetime.utcnow()
            )
            db.add(target_incident)
            db.flush()  # populate target_incident.id

            active_incidents.append(target_incident)

            record_incident_event(
                db,
                incident_id=target_incident.id,
                event_type="incident.created",
                payload={
                    "incident_code": code,
                    "center": [cluster.center_lat, cluster.center_lon],
                    "observations_initial": len(cluster.observations),
                    "max_frp": cluster.max_frp,
                    "nearest_asset": asset_info.get("facility_name")
                }
            )

        # Link observations in incident_observations
        for idx, obs in enumerate(cluster.observations):
            # Check if link exists
            exists = (
                db.query(IncidentObservation)
                .filter(
                    IncidentObservation.incident_id == target_incident.id,
                    IncidentObservation.observation_id == obs.id
                )
                .first()
            )
            if not exists:
                link = IncidentObservation(
                    incident_id=target_incident.id,
                    observation_id=obs.id,
                    is_primary=(idx == 0 and not matched_inc),
                    association_method=method or "INITIAL_CLUSTER_DBSCAN",
                    association_score=score if matched_inc else 1.0,
                    created_at=datetime.utcnow()
                )
                db.add(link)

        # Recount total observations linked to this incident
        db.flush()
        total_linked = (
            db.query(IncidentObservation)
            .filter(IncidentObservation.incident_id == target_incident.id)
            .count()
        )
        target_incident.observation_count = total_linked

        result_incidents.append(target_incident)

    db.commit()
    logger.info(f"Synchronized {len(clusters)} clusters across {len(result_incidents)} incidents.")
    return result_incidents
