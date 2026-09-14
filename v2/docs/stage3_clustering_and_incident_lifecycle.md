# Stage 3 — Clustering + Incident Lifecycle Report
**Stage:** Stage 3  
**Status:** Completed & Fully Verified  
**Blueprint Reference:** [FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md#L3200-L3364)

---

## 1. Components Implemented

1. **Spatial-Temporal Clustering Engine**:
   - [`clustering.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/incidents/clustering.py):
     - Groups observations based on Euclidean/Haversine spatial reachability (default 2,000m) and temporal continuity (default 24h).
     - **Strict Invariant Enforced**: FRP values are **NEVER** summed. Derives `max_frp`, `mean_frp`, `min_frp`, and `observation_count`.
     - Generates dynamic incident centroid, footprint radius, and GeoJSON polygon envelope.

2. **Incident Association & Lifecycle Engine**:
   - [`association.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/incidents/association.py):
     - `match_cluster_to_incident`: Tests spatial footprint overlap and temporal continuity against existing active incidents.
     - `sync_clusters_to_incidents`: If matching incident found, updates its temporal window, dynamically expands its footprint, and updates `current_max_frp` without creating duplicates. If new, promotes to a new incident (e.g. `INC-2026-0001`).
     - Maintains join table `incident_observations` with `association_method` and `association_score` for full provenance.

3. **Incident State Machine & Timeline Audit**:
   - [`state.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/incidents/state.py):
     - Validates lifecycle states: `NEW` -> `INVESTIGATING` -> `ACTIVE` -> `PERSISTENT` -> `SUBSIDING` -> `RESOLVED`.
     - Logs immutable event records to `incident_events` (e.g., `incident.created`, `incident.updated`, `incident.state_changed`).

4. **Incidents REST API Router**:
   - [`incidents.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/api/incidents.py):
     - `GET /incidents`: Query incidents with status, severity, facility containment, and state filters.
     - `GET /incidents/{id}`: Detailed incident view with linked observations and complete timeline events.
     - `POST /incidents/cluster-sync`: Run clustering & association over unassigned observations.
     - `POST /incidents/{id}/state`: Manually transition incident state.

---

## 2. Acceptance Verification Results

Executed via automated test suite [`test_stage3_incidents.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/tests/test_stage3_incidents.py):
- **Hard Rule Verification**: In a 3-observation cluster (40 MW, 30 MW, 20 MW), verified `max_frp == 40.0`, `mean_frp == 30.0`, and `max_frp != 90.0` (no summation).
- **Case A**: 3 nearby points at same time -> exactly 1 cluster.
- **Case B**: 2 distant points (Panipat vs Jamnagar) -> 2 separate clusters.
- **Case C**: Same location 36h apart (>24h window) -> 2 separate clusters.
- **Lifecycle & Deduplication**: Successive runs with new observations inside the same facility updated the existing incident (`observation_count: 1 -> 2`, `current_max_frp: 45 -> 55 MW`) without creating duplicate incident codes.
- **State Transition**: Tested transition to `SUBSIDING` and verified audit event recording in `incident_events`.

```text
tests/test_stage0_foundation.py::test_health_endpoint PASSED          [  5%]
tests/test_stage0_foundation.py::test_api_status_endpoint PASSED      [ 10%]
tests/test_stage0_foundation.py::test_database_schema_tables PASSED   [ 15%]
tests/test_stage0_foundation.py::test_frontend_console_mount PASSED   [ 21%]
tests/test_stage1_ingestion.py::test_deterministic_fixture_ingestion_and_deduplication PASSED [ 26%]
tests/test_stage1_ingestion.py::test_get_observations_endpoint PASSED [ 31%]
tests/test_stage1_ingestion.py::test_spatial_query_filtering PASSED   [ 36%]
tests/test_stage1_ingestion.py::test_get_single_observation_by_id PASSED [ 42%]
tests/test_stage1_ingestion.py::test_live_firms_api_connectivity PASSED [ 47%]
tests/test_stage2_gis.py::test_haversine_distance_accuracy PASSED     [ 52%]
tests/test_stage2_gis.py::test_controlled_geometry_point_in_polygon PASSED [ 57%]
tests/test_stage2_gis.py::test_facility_containment_fixtures PASSED   [ 63%]
tests/test_stage2_gis.py::test_admin_boundary_resolution PASSED       [ 68%]
tests/test_stage2_gis.py::test_landcover_classification PASSED        [ 73%]
tests/test_stage2_gis.py::test_industries_api_endpoints PASSED        [ 78%]
tests/test_stage3_incidents.py::test_hard_rule_frp_non_summation_invariant PASSED [ 84%]
tests/test_stage3_incidents.py::test_clustering_cases_a_b_c PASSED    [ 89%]
tests/test_stage3_incidents.py::test_incident_lifecycle_and_association_dedup PASSED [ 94%]
tests/test_stage3_incidents.py::test_incident_state_transition_and_events PASSED [100%]

====================== 19 passed in 3.08s =======================
```
