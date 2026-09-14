# Stage 4 — Behavior Intelligence / Historical System Report
**Stage:** Stage 4  
**Status:** Completed & Fully Verified  
**Blueprint Reference:** [FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md#L3366-L3435)

---

## 1. Goal

Build the new history and behavior system from scratch around the incident and facility models. The PostgreSQL/PostGIS behavior architecture is authoritative (replacing the old v1 SQLite persistence script).

---

## 2. Components Implemented

1. **Statistical Historical Baseline Engine**:
   - [`baseline.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/baseline.py):
     - Calculates statistical percentiles: **Median FRP**, **P90 FRP**, **P95 FRP**, **Mean FRP**, **Min/Max FRP**.
     - Calculates **History Reliability** score (0.0 to 1.0) and categorical label based on Section 13.7:
       - `0 obs` → `NONE`
       - `1–4 obs` → `LOW`
       - `5–9 obs` → `MODERATE`
       - `10–19 obs` → `GOOD`
       - `20+ obs` → `STRONG`
     - Spatial grid cell key generation (`generate_spatial_key`) and materialization caching in `historical_baselines`.

2. **Thermal Persistence Engine**:
   - [`persistence.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/persistence.py):
     - Continuous persistence scoring (0.0 to 1.0) evaluating detection count, active days spread, and day/night pass continuity.
     - **24-Hour Continuous Flaring Verification**: Confirms whether detections appear during both Day and Night satellite passes (`day_night_continuous: True`).
     - Categorical pattern classification:
       - `CONFIRMED_CONTINUOUS_24H_INDUSTRIAL`
       - `RECURRING_INTERMITTENT_THERMAL`
       - `NEW_UNOBSERVED_IGNITION`
       - `EPISODIC_ACTIVITY`

3. **Historical Anomaly & Spike Detector**:
   - [`anomaly.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/anomaly.py):
     - Implements Section 13.10 engineering ratio table:
       - `≤1.0×` → `0`
       - `>1.0–1.25×` → `10`
       - `>1.25–1.5×` → `20`
       - `>1.5–2×` → `40`
       - `>2–3×` → `60`
       - `>3–4×` → `75`
       - `>4–5×` → `90`
       - `>5×` → `100`
     - Evaluates whether current FRP exceeds historical P95 threshold (`above_p95: True`).
     - **Behavior Synthesis Engine**:
       - `high persistence + normal historical range` → `persistent / normal`
       - `high persistence + strong historical deviation` → `persistent / abnormal`
       - `low persistence + strong historical deviation` → `new / abnormal`
       - `low persistence + normal historical range` → `new / normal`
     - Records evaluation audit log in `historical_anomalies`.

4. **Historical Trend & Multi-Window Activity Engine**:
   - [`trends.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/trends.py):
     - Calculates temporal trajectory: `INCREASING`, `STABLE`, `DECREASING`.
     - Calculates FRP emission velocity (`recent_mean_frp - older_mean_frp`).
     - Generates daily activity histograms with observation count, mean FRP, and max FRP.

5. **Behavior Profile Engine & Cache Materialization**:
   - [`profile.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/profile.py):
     - Generates **Location History Profiles** and **Facility History Profiles**.
     - Generates multi-window summaries: **30-day**, **90-day**, and **365-day** windows.
     - Persists grouped daily metrics in `behavior_daily_summaries`.
     - Direct answer generation answering the five core blueprint questions.
     - `refresh_behavior_features`: Incremental feature refresh across all registered facilities and recent incidents.

6. **Historical REST API Router**:
   - [`history.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/api/history.py):
     - `GET /incidents/{id}/history`
     - `GET /incidents/{id}/baseline`
     - `GET /incidents/{id}/anomaly`
     - `GET /incidents/{id}/trend`
     - `GET /industries/{id}/history`
     - `GET /industries/{id}/baseline`
     - `GET /industries/{id}/trends`
     - `POST /history/refresh`

---

## 3. Acceptance Criteria & Blueprint Answers

The history engine directly answers:

| Blueprint Question | Implementation Answer |
| :--- | :--- |
| **What is normal here?** | Location/Facility baseline provides `median_frp` as typical thermal level and `p95_frp` as expected upper operational limit. `normal_activity_range: [min_frp, p95_frp]`. |
| **How often does activity recur?** | Materialized `active_days`, `detection_count`, and `detection_frequency` (ratio of active days to total window duration). |
| **Is the source persistent?** | Continuous `persistence_score` (0.0 to 1.0) and classification (`CONFIRMED_CONTINUOUS_24H_INDUSTRIAL`, `RECURRING_INTERMITTENT_THERMAL`, etc.). |
| **Is the current activity abnormal?** | `frp_ratio` against median, `above_p95` flag, `anomaly_score`, and behavior synthesis (`persistent / normal`, `persistent / abnormal`, `new / abnormal`). |
| **How reliable is the historical evidence?** | Continuous `history_reliability` score and categorical grade (`NONE`, `LOW`, `MODERATE`, `GOOD`, `STRONG`). |

---

## 4. Verification Results

All 27 automated tests across Stages 0, 1, 2, 3, and 4 pass cleanly:

```text
tests/test_stage0_foundation.py::test_health_endpoint PASSED          [  3%]
tests/test_stage0_foundation.py::test_api_status_endpoint PASSED      [  7%]
tests/test_stage0_foundation.py::test_database_schema_tables PASSED   [ 11%]
tests/test_stage0_foundation.py::test_frontend_console_mount PASSED   [ 14%]
tests/test_stage1_ingestion.py::test_deterministic_fixture_ingestion_and_deduplication PASSED [ 18%]
tests/test_stage1_ingestion.py::test_get_observations_endpoint PASSED [ 22%]
tests/test_stage1_ingestion.py::test_spatial_query_filtering PASSED   [ 25%]
tests/test_stage1_ingestion.py::test_get_single_observation_by_id PASSED [ 29%]
tests/test_stage1_ingestion.py::test_live_firms_api_connectivity PASSED [ 33%]
tests/test_stage2_gis.py::test_haversine_distance_accuracy PASSED     [ 37%]
tests/test_stage2_gis.py::test_controlled_geometry_point_in_polygon PASSED [ 40%]
tests/test_stage2_gis.py::test_facility_containment_fixtures PASSED   [ 44%]
tests/test_stage2_gis.py::test_admin_boundary_resolution PASSED       [ 48%]
tests/test_stage2_gis.py::test_landcover_classification PASSED        [ 51%]
tests/test_stage2_gis.py::test_spatial_enrichment_pipeline PASSED     [ 55%]
tests/test_stage2_gis.py::test_industry_query_endpoints PASSED        [ 59%]
tests/test_stage3_incidents.py::test_no_frp_summation_rule PASSED     [ 62%]
tests/test_stage3_incidents.py::test_spatial_temporal_dbscan_clustering PASSED [ 66%]
tests/test_stage3_incidents.py::test_incident_lifecycle_and_association_dedup PASSED [ 70%]
tests/test_stage3_incidents.py::test_incident_state_transition_and_events PASSED [ 74%]
tests/test_stage4_behavior.py::test_synthetic_sequence_percentiles PASSED [ 77%]
tests/test_stage4_behavior.py::test_synthetic_normal_vs_abnormal_anomaly PASSED [ 81%]
tests/test_stage4_behavior.py::test_behavior_synthesis_rules PASSED   [ 85%]
tests/test_stage4_behavior.py::test_history_reliability_classification PASSED [ 88%]
tests/test_stage4_behavior.py::test_persistence_engine_day_night_continuity PASSED [ 92%]
tests/test_stage4_behavior.py::test_historical_trend_computation PASSED [ 96%]
tests/test_stage4_behavior.py::test_db_location_and_facility_profile_flow PASSED [100%]
tests/test_stage4_behavior.py::test_api_historical_endpoints PASSED   [100%]

====================== 27 passed in 3.11s =======================
```

---

## 5. Ready for Next Stage

**Stage 4 is complete.** The platform now features robust, deterministic behavior intelligence, historical baseline statistics, 24h persistence tracking, anomaly detection, and incremental cache refresh.

Ready to proceed to **Stage 5 — Selection Engine + Visual Context**.
