"""
FIREX v2 Spatial-Temporal Clustering Engine
Strict Invariant Compliance:
1. Hard rule: NEVER sum FRP values of observations to derive incident FRP.
   Derives max_frp, mean_frp, min_frp, and count.
2. Formulates clusters from raw observations using adaptive spatial-temporal DBSCAN.
   - Spatial epsilon: 1,500m (configurable)
   - Temporal window: 24 hours (configurable)
3. Computes cluster centroid, dynamic footprint radius, and GeoJSON polygon envelope.
"""
import math
from collections import deque
from typing import List, Dict, Any, Set
from datetime import datetime, timedelta
from app.storage.models import Observation
from app.gis.spatial import (
    haversine_distance_meters,
    generate_bounding_circle_polygon
)
from app.core.logging import logger

class ThermalCluster:
    def __init__(self, cluster_id: str):
        self.cluster_id = cluster_id
        self.observations: List[Observation] = []
        self.center_lat: float = 0.0
        self.center_lon: float = 0.0
        self.radius_meters: float = 500.0
        self.max_frp: float = 0.0
        self.mean_frp: float = 0.0
        self.min_frp: float = 0.0
        self.first_detected_at: datetime = datetime.max
        self.last_detected_at: datetime = datetime.min
        self.footprint_geojson: Dict[str, Any] = {}

    def add_observation(self, obs: Observation):
        self.observations.append(obs)

    def finalize(self):
        """
        Computes cluster summary statistics enforcing the hard rule:
        NO FRP summation.
        """
        if not self.observations:
            return

        n = len(self.observations)
        frps = [float(obs.frp_mw or 0.0) for obs in self.observations]
        
        # Centroid
        self.center_lat = round(sum(obs.latitude for obs in self.observations) / n, 6)
        self.center_lon = round(sum(obs.longitude for obs in self.observations) / n, 6)
        
        # FRP statistics (Preserves individual observation FRPs)
        self.max_frp = round(max(frps), 2)
        self.min_frp = round(min(frps), 2)
        self.mean_frp = round(sum(frps) / n, 2)

        # Time range
        dates = [obs.acquired_at for obs in self.observations if obs.acquired_at]
        if dates:
            self.first_detected_at = min(dates)
            self.last_detected_at = max(dates)
        else:
            now = datetime.utcnow()
            self.first_detected_at = now
            self.last_detected_at = now

        # Dynamic Footprint Radius -- Section 4.3 (V2_LOGIC_SPECIFICATION.md:142):
        #   R_footprint = max(500.0, max_i d_H((phi_bar, lambda_bar), o_i) * 1000.0 + 375.0)
        # d_H is kilometers in the spec, so the x1000 lands it in the meters this
        # module works in; the additive 375 m is the sensor-pixel buffer on top of
        # the furthest member. This used to be 300.0, which under-sized every
        # persisted footprint_radius_meters by 75 m.
        max_dist_m = 0.0
        for obs in self.observations:
            d = haversine_distance_meters(self.center_lat, self.center_lon, obs.latitude, obs.longitude)
            if d > max_dist_m:
                max_dist_m = d

        self.radius_meters = max(500.0, round(max_dist_m + 375.0, 1))
        
        # Generate GeoJSON bounding polygon ring
        ring_coords = generate_bounding_circle_polygon(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_meters=self.radius_meters
        )
        self.footprint_geojson = {
            "type": "Polygon",
            "coordinates": [ring_coords]
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "observation_count": len(self.observations),
            "center_lat": self.center_lat,
            "center_lon": self.center_lon,
            "footprint_radius_meters": self.radius_meters,
            "max_frp": self.max_frp,
            "mean_frp": self.mean_frp,
            "min_frp": self.min_frp,
            "first_detected_at": self.first_detected_at.isoformat() if self.first_detected_at else None,
            "last_detected_at": self.last_detected_at.isoformat() if self.last_detected_at else None,
            "observation_ids": [obs.id for obs in self.observations]
        }


def cluster_observations(
    observations: List[Observation],
    spatial_eps_meters: float = 1500.0,
    time_window_hours: float = 24.0
) -> List[ThermalCluster]:
    """
    Groups observations into deterministic spatial-temporal clusters using density reachability.
    Edge cases handled:
    - Case A: 3 nearby observations at nearly same time -> 1 cluster, individual FRPs preserved.
    - Case B: distant observations -> separate clusters.
    - Case C: same location but > 24h apart -> separate clusters.

    Defaults are the Section 4.3 reachability parameters
    (V2_LOGIC_SPECIFICATION.md:129): eps_s = 1500 m, tau = 24.0 h. spatial_eps_meters
    defaulted to 2000.0, so a direct caller got a 33% wider radius than the spec
    mandates and than the pipeline passes explicitly (orchestration/pipeline.py:518
    passes 1500.0).
    """
    if not observations:
        return []

    visited: Set[str] = set()
    clusters: List[ThermalCluster] = []
    cluster_idx = 1

    time_delta_limit = timedelta(hours=time_window_hours)

    def get_neighbors(target: Observation) -> List[Observation]:
        neighbors = []
        for other in observations:
            if other.id == target.id:
                continue

            # Temporal check
            if target.acquired_at and other.acquired_at:
                time_diff = abs(target.acquired_at - other.acquired_at)
                if time_diff > time_delta_limit:
                    continue

            # Spatial distance check
            dist_m = haversine_distance_meters(target.latitude, target.longitude, other.latitude, other.longitude)
            if dist_m <= spatial_eps_meters:
                neighbors.append(other)
        return neighbors

    for obs in observations:
        if obs.id in visited:
            continue

        visited.add(obs.id)
        neighbors = get_neighbors(obs)

        current_cluster = ThermalCluster(cluster_id=f"cluster_{cluster_idx:04d}")
        cluster_idx += 1
        current_cluster.add_observation(obs)

        # Expand cluster
        queue = deque(neighbors)
        while queue:
            neighbor = queue.popleft()
            if neighbor.id not in visited:
                visited.add(neighbor.id)
                sub_neighbors = get_neighbors(neighbor)
                queue.extend([sn for sn in sub_neighbors if sn.id not in visited])

            # Add to cluster if not already in one
            if neighbor not in current_cluster.observations:
                current_cluster.add_observation(neighbor)

        current_cluster.finalize()
        clusters.append(current_cluster)

    logger.info(f"Clustered {len(observations)} observations into {len(clusters)} physical incident candidates.")
    return clusters
