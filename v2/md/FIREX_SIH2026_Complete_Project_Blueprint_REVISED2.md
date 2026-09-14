# FIREX-SIH2026
## AI-Enabled Geospatial Industrial Fire & Persistent Thermal Source Intelligence Platform

**Implementation Blueprint • SIH Problem Mapping • Vibe-Coding Roadmap**

---

# 1. Project Overview

## Project Name

**FIREX-SIH2026**

Suggested expansion:

> **FIREX — Fire & Industrial Thermal Anomaly Intelligence Explorer**

The exact expansion can be changed later; the architecture does not depend on the acronym.

## One-Line Product Definition

> **FIREX converts satellite thermal anomaly detections into explainable, trackable industrial incidents by combining NASA FIRMS, GIS context, industrial infrastructure data, satellite imagery, multimodal AI, historical behavior, severity assessment, and continuous monitoring.**

## Core Principle

```text
DETECT
  ↓
ENRICH
  ↓
GROUP
  ↓
SELECT
  ↓
INVESTIGATE
  ↓
CLASSIFY
  ↓
ASSESS
  ↓
TRACK
  ↓
ALERT
  ↓
VISUALIZE
  ↓
MONITOR
```

---

# 2. SIH Problem Statement

## Background

Industrial facilities generate thermal signatures that can be observed from space, but current satellite-based monitoring systems like NASA FIRMS cannot distinguish between different types of thermal anomalies. To address this, there is a challenge to develop an AI-enabled geospatial system that integrates thermal data, land-cover information, industrial databases, and satellite imagery to automatically identify, classify, and monitor industrial fires and persistent thermal sources.

## Description

Industrial facilities such as oil refineries, petrochemical complexes, thermal power plants, steel industries, mining areas, and LNG terminals generate thermal signatures that can be observed from space. In addition, accidental industrial fires, gas leaks, explosions, and abnormal thermal events pose significant risks to critical infrastructure, public safety, and the environment.

Current satellite-based fire monitoring systems such as NASA FIRMS provide thermal anomaly detections but do not distinguish between industrial fires, gas flares, agricultural burning, mining activity, and wildfires.

The challenge is to develop an AI-enabled geospatial system that can automatically identify, classify, and monitor industrial fires and persistent thermal sources by integrating thermal anomaly data, land-cover information, industrial infrastructure databases, and satellite imagery.

## Expected Solution / Deliverables

### i. Classification and segregation of Industrial fires from forest fires and other natural fires.

### ii. GIS based solution for data storage, visualization of the output as an overlay over maps

## FIREX Interpretation of the PS

The implementation must stay faithful to the PS above.

The industrial contexts explicitly named by the PS are:

- Oil refineries
- Petrochemical complexes
- Thermal power plants
- Steel industries
- Mining areas
- LNG terminals

The PS explicitly mentions distinguishing industrial fires and gas flares from:

- Forest fires / wildfires
- Agricultural burning
- Mining activity as a competing thermal source

The PS does **not** explicitly require a separate other thermal source class. Do not make other thermal source a headline classification or major feature in the SIH solution.

The PS's reference to satellite imagery does not require FIREX to claim live high-resolution satellite imaging. FIREX uses the existing high-resolution Google Maps / map-satellite visual-context workflow from the prototype for visual verification around FIRMS detections.

Use this wording in project documentation:

> **High-resolution map/satellite visual context for incident verification**

rather than claiming continuous live satellite imaging.

# 3. What FIREX Must Solve

The project must answer five major questions:

### Question 1 — Where is thermal activity happening?

Use:

- NASA FIRMS
- Geospatial processing
- Spatial-temporal clustering

### Question 2 — What is around that thermal activity?

Use:

- Land-cover data
- Industrial databases
- Administrative boundaries
- Environmental / protected-area layers

### Question 3 — What is the anomaly likely to be?

Use:

- Current satellite imagery
- FIRMS metadata
- GIS context
- Multimodal AI

### Question 4 — How serious is it?

Use:

- Current thermal intensity
- Historical deviation
- AI source classification
- GIS context
- Escalation rules

### Question 5 — Is this a one-off event, a persistent source, or abnormal facility behavior?

Use:

- Historical FIRMS data
- Persistence analysis
- Historical baseline
- P95 / percentile analysis
- Trend analysis
- Incident tracking

---

# 4. Critical Architecture Rules

These rules should be treated as project-wide invariants.

## Rule 1 — FIRMS observation is not a confirmed fire

NASA FIRMS provides thermal anomaly detections.

FIREX performs interpretation.

Never label a raw FIRMS point as a confirmed fire before investigation.

## Rule 2 — Observation and incident are different

Many observations may belong to one physical event.

```text
FIRMS observations
      ↓
Spatial-temporal clustering
      ↓
Incident candidate
```

## Rule 3 — Selection and severity are different

### Selection asks:

> Should we investigate this incident?

### Severity asks:

> How serious does the current evidence indicate that the incident is?

Never merge them into one generic "risk" value.

## Rule 4 — FIRMS confidence and AI confidence are different

- FIRMS confidence = reliability of the satellite detection/product
- AI confidence = confidence in the classification

## Rule 5 — Severity and severity confidence are different

Example:

```text
Severity = CRITICAL
Severity Score = 88
Severity Confidence = 47
```

This means the evidence suggests potentially severe activity, but confidence is limited.

## Rule 6 — New incidents must not be penalized for having no history

No history means:

```text
Historical = N/A
```

not:

```text
Historical = 0
```

Use the new-incident selection/severity model.

## Rule 7 — Persistence does not mean danger

A persistent gas flare can be normal.

Therefore:

```text
Persistent + normal
```

and

```text
Persistent + abnormal
```

must be distinguishable.

## Rule 8 — Store all current FIRMS observations

Do not delete low-priority observations.

An event that is insignificant today can become a persistent source later.

## Rule 9 — GIS is context first

Do not blindly assign points such as:

```text
near refinery = +15
near forest = +15
```

GIS should provide structured context which is interpreted by downstream logic.

## Rule 10 — Avoid double counting

FRP, persistence, historical anomaly, observation count, and related derivatives can overlap.

Do not feed the same information repeatedly into multiple scoring systems without documenting the relationship.

---

# 4A. PS Scope and Claim Guardrails

These rules should be followed in the implementation, README, pitch, and SIH presentation.

## Do not claim

- 24/7 continuous satellite imaging
- guaranteed detection of every industrial fire
- ground-truth fire confirmation from FIRMS alone
- that AI classification is always correct
- that every industrial facility is present in the infrastructure database
- that a persistent source is automatically dangerous

## Prefer

- continuous automated processing of incoming FIRMS observations
- thermal anomaly detection followed by contextual investigation
- high-resolution map/satellite visual context for verification
- explainable AI classification with uncertainty
- industrial-context matching using available GIS/asset data
- historical behavioral analysis for persistence and abnormality

## PS-to-FIREX mapping

| SIH requirement | FIREX implementation |
|---|---|
| Thermal anomaly data | NASA FIRMS ingestion |
| Land-cover information | GIS enrichment |
| Industrial databases | Industrial asset layer |
| Satellite imagery | Existing high-resolution Google Maps / map-satellite visual context |
| Industrial fire classification | Multimodal AI investigation |
| Forest/natural fire segregation | GIS + visual context + AI |
| Persistent thermal sources | Behavior Intelligence / persistence engine |
| GIS storage | PostgreSQL + PostGIS |
| GIS visualization | Existing FIREX map UI |
| Monitoring | Incremental FIRMS processing + incident tracking + alerts |

# 5. Final End-to-End Pipeline

```text
                         NASA FIRMS
                             │
                             ▼
                 ┌──────────────────────┐
                 │ 1. INGESTION         │
                 │ Fetch latest data    │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 2. VALIDATE &        │
                 │ NORMALIZE            │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 3. STORE RAW DATA    │
                 │ Preserve provenance  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 4. GIS ENRICHMENT    │
                 │ Land cover           │
                 │ Industrial assets    │
                 │ Protected areas      │
                 │ Admin context        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 5. SPATIAL-TEMPORAL  │
                 │ CLUSTERING           │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 6. INCIDENT          │
                 │ ASSOCIATION          │
                 │ New / existing       │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 7. BEHAVIOR          │
                 │ INTELLIGENCE         │
                 │ Persistence          │
                 │ Historical baseline  │
                 │ P95 / anomaly        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 8. SELECTION ENGINE  │
                 │ Investigation        │
                 │ Priority             │
                 └──────────┬───────────┘
                            │
                     selected incidents
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 9. CURRENT IMAGERY   │
                 │ Dynamic radius       │
                 └──────────┬───────────┘
                            │
                            ▼
              ┌──────────────────────────────┐
              │ 10. MULTIMODAL AI           │
              │ Image + FIRMS + GIS         │
              │ + industrial context        │
              └─────────────┬────────────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 11. CLASSIFICATION   │
                 │ + Evidence           │
                 │ + Alternatives       │
                 │ + Uncertainty        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 12. SEVERITY ENGINE  │
                 │ Weighted score       │
                 │ + escalation rules   │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 13. INCIDENT STATE   │
                 │ New / Active /       │
                 │ Persistent / etc.    │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 14. ALERT ENGINE     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 15. DATABASE UPDATE  │
                 │ Incident + evidence  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ 16. DASHBOARD / SSE  │
                 │ Live visualization   │
                 └──────────┬───────────┘
                            │
                            ▼
                       NEW DATA LOOP
```

---

# 6. Data Flow Philosophy

## Raw Evidence

```text
FIRMS
Satellite imagery
GIS datasets
Industrial database
```

## Derived Intelligence

```text
Cluster
Incident
Persistence
Historical baseline
Historical anomaly
AI classification
Severity
State
Alert
```

Never mix raw source data with derived values in a way that destroys traceability.

---

# 7. Existing Project Reuse Strategy

The project already has a working frontend/UI direction and a first-generation backend in the `ssaurabh10/FIREX-SIH2026` repository. The current README describes the Tactical GIS Command Center, Leaflet map UI, SSE sync HUD, dossier/incident view, and high-resolution visual verification flow.

### Reuse the UI

**Do not rebuild the frontend from zero.**

Keep the existing visual language, layout, map experience, incident dossier, and overall interaction model.

Make only targeted edits required by the new backend:

- new incident fields
- selection explanation
- persistence/history values
- severity vs investigation priority
- industry search page
- historical industry charts
- improved run/refresh flow
- new SSE event names if required

### Rewrite the backend

Treat the current backend as a prototype/reference implementation, not as the final architecture. Use v1 as a reference at the relevant stage, not as something to duplicate wholesale.

The repository currently contains separate stages for FIRMS, selection, imagery, Vision AI, orchestration, risk scoring, and persistence. The new backend should consolidate overlapping responsibilities into clearer services while preserving useful working integrations.

### Existing AI integration worth preserving

The current `pipeline/04_vision_ai/vision_classifier.py` is a **v1 reference implementation**, not a provider lock-in. It already:

- sends satellite image + FIRMS metadata to MiniMax through OpenRouter
- uses strict allowed classifications
- tells the model that FIRMS is a thermal anomaly rather than proof of fire
- supports `uncertain`
- uses an API-key pool/failover approach

Use this as the starting point for the refactored `intelligence/vision.py`, rather than recreating the integration from scratch.

### Migration principle

```text
Existing UI
   │
   │ preserve
   ▼
NEW CLEAN BACKEND
   │
   ├── reuse FIRMS client
   ├── reuse Google-map/tile visual logic
   ├── reuse MiniMax/OpenRouter integration
   └── replace tangled orchestration/persistence/scoring
```

Do not make the frontend depend directly on the old pipeline folders.

---


### Current project status

The team already has a working UI and a first-generation backend.

**The UI is intentionally not being rebuilt from scratch.**

Keep the existing visual language, map interaction, incident/dossier style, blur/morphism treatment, and overall dashboard structure. Make targeted edits only where the new backend requires additional fields or workflows.

The primary rework is the backend:

```text
EXISTING UI
    │
    │ keep similar
    ▼
NEW CLEAN BACKEND
    ├── new data model
    ├── incident-centric pipeline
    ├── NEW Behavior Intelligence
    ├── selection
    ├── imagery/context
    ├── AI
    ├── severity
    ├── alerts
    └── Industry Intelligence APIs
```

The existing FIRMS integration, Google Maps/high-resolution tile visual workflow, and MiniMax/OpenRouter integration should be reused where they are already working. Do not duplicate these integrations in the new backend.


# 8. Core Modules

Recommended backend structure:

```text
firex-backend/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── incidents.py
│   │   ├── observations.py
│   │   ├── industries.py
│   │   ├── dashboard.py
│   │   ├── analysis.py
│   │   ├── history.py
│   │   └── stream.py
│   │
│   ├── ingestion/
│   │   ├── firms.py
│   │   ├── normalizer.py
│   │   └── validator.py
│   │
│   ├── gis/
│   │   ├── enrichment.py
│   │   ├── landcover.py
│   │   ├── assets.py
│   │   ├── boundaries.py
│   │   └── spatial.py
│   │
│   ├── incidents/
│   │   ├── clustering.py
│   │   ├── association.py
│   │   └── state.py
│   │
│   ├── behavior/
│   │   ├── persistence.py
│   │   ├── baseline.py
│   │   ├── anomaly.py
│   │   └── trends.py
│   │
│   ├── selection/
│   │   ├── score.py
│   │   ├── thresholds.py
│   │   └── rules.py
│   │
│   ├── imagery/
│   │   ├── provider.py
│   │   ├── radius.py
│   │   └── quality.py
│   │
│   ├── intelligence/
│   │   ├── vision.py
│   │   ├── prompts.py
│   │   ├── schemas.py
│   │   └── evidence.py
│   │
│   ├── severity/
│   │   ├── score.py
│   │   ├── models.py
│   │   └── escalation.py
│   │
│   ├── alerts/
│   │   └── engine.py
│   │
│   ├── storage/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   ├── workers/
│   │   ├── analysis_worker.py
│   │   ├── ingestion_worker.py
│   │   └── ai_worker.py
│   │
│   └── core/
│       ├── config.py
│       ├── logging.py
│       ├── events.py
│       └── errors.py
│
├── tests/
├── migrations/
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```

---

# 9. Recommended Technology Stack

## Backend

Preferred:

- Python
- FastAPI
- Pydantic
- SQLAlchemy / SQLModel
- PostgreSQL
- PostGIS

## Frontend

Preferred:

- React
- TypeScript
- Existing FIREX dashboard UI if already available
- MapLibre GL JS / compatible map library
- Recharts / ECharts / equivalent charting library

## Live updates

Use:

- Server-Sent Events (SSE) initially

Optional later:

- WebSockets

## Queue / cache

Start without a complicated distributed system.

Optional:

- Redis

Avoid adding Kafka/Kubernetes/Celery/RabbitMQ unless the actual load requires them.

## AI

The AI provider/model must be configurable and replaceable through an internal AI interface. Existing MiniMax/OpenRouter capability may be reused from v1 where it is still useful, but the architecture must not depend on one specific model or provider.

---

# 10. Database Design

Preferred database:

> PostgreSQL + PostGIS

## 10.1 observations

Stores every normalized FIRMS observation.

Suggested fields:

```text
id
source
external_id
latitude
longitude
geom
frp_mw
confidence_raw
confidence_score
satellite
sensor
product
acquired_at
ingested_at
raw_payload
```

## 10.2 incidents

Central business object.

```text
id
incident_code
status
center_geom
first_detected_at
last_detected_at
observation_count
current_max_frp
current_mean_frp
investigation_priority
severity_score
severity_level
severity_confidence
classification
classification_confidence
created_at
updated_at
```

## 10.3 incident_observations

Join table:

```text
incident_id
observation_id
association_method
association_score
created_at
```

## 10.4 industrial_assets

```text
asset_id
facility_name
facility_type
operator
industry
state
district
geom
hazard_category
source
source_updated_at
```

## 10.5 gis_context

Can be materialized/cached or generated dynamically.

```text
incident_id
land_cover
state
district
protected_area
forest_context
mining_context
industrial_context
nearby_asset_count
nearest_asset_distance_m
```

## 10.6 imagery

```text
id
incident_id
provider
image_uri
bbox
center_lat
center_lon
radius_m
acquired_at
time_difference_from_firms
cloud_score
quality_score
created_at
```

## 10.7 ai_investigations

```text
id
incident_id
model
prompt_version
image_id
classification
confidence
alternative_classification
alternative_confidence
visual_evidence
contextual_evidence
uncertainties
image_quality
raw_response
created_at
```

## 10.8 historical_baselines

```text
id
spatial_reference
window_start
window_end
observation_count
median_frp
mean_frp
p90_frp
p95_frp
min_frp
max_frp
detection_frequency
history_reliability
updated_at
```

## 10.9 severity_assessments

```text
id
incident_id
model_version
frp_component
history_component
ai_component
gis_component
base_score
escalation_adjustment
final_score
severity_level
confidence
created_at
```

## 10.10 alerts

```text
id
incident_id
alert_type
severity
message
created_at
acknowledged_at
resolved_at
```

## 10.11 incident_events

Audit / timeline:

```text
id
incident_id
event_type
payload
created_at
```

Examples:

```text
incident.created
investigation.started
investigation.completed
severity.changed
incident.updated
alert.created
incident.resolved
```

---

# 11. GIS Strategy

## 11.1 Use geometry, not string matching

Do not determine proximity using names/keywords.

Bad:

```text
if "refinery" in nearby_text:
    risk += ...
```

Good:

```text
point within facility polygon
```

or:

```text
distance(point, facility) < threshold
```

## 11.2 Context to compute

For each observation/incident:

```text
land_cover
industrial_asset
distance_to_asset
inside_asset
protected_area
forest_context
mining_context
state
district
```

## 11.3 Spatial operations

Use PostGIS concepts such as:

- point-in-polygon
- distance queries
- spatial joins
- indexed geographic searches

The system should be designed so spatial analysis remains fast as data grows.

---

# 12. Clustering Design

## Goal

Turn:

```text
FIRMS point
FIRMS point
FIRMS point
...
```

into:

```text
Incident candidate
```

## Initial method

Use DBSCAN with spatial and time constraints.

## Inputs

- Latitude / longitude
- Acquisition time
- Optional FRP-aware checks

## Output

```json
{
  "cluster_id": "cluster-123",
  "observation_count": 7,
  "center": {
    "lat": 25.000,
    "lon": 86.000
  },
  "radius_m": 650,
  "max_frp_mw": 82.4,
  "mean_frp_mw": 41.5,
  "time_start": "...",
  "time_end": "..."
}
```

## Edge case

Adjacent events can accidentally merge.

To reduce false merges:

- Keep time windows explicit
- Do not use one giant spatial radius
- Use industrial boundaries as contextual constraints
- Preserve cluster membership evidence
- Allow manual/debug visualization of clusters

---

# 13. NEW Behavior Intelligence / Historical Pipeline

The historical system is **not a rewrite of the old SQLite persistence module**.

Build it from scratch around the new incident-centric architecture.

Its job is to answer:

> **What has historically happened at or around this location/facility, what is normal here, and is the current activity persistent or abnormal?**

It must serve both:

```text
LIVE MONITORING
        +
INDUSTRY INTELLIGENCE
```

without creating two separate history systems.

---

## 13.1 Historical Pipeline Overview

```text
                         ALL STORED FIRMS
                               │
                               ▼
                  NORMALIZED OBSERVATIONS DB
                               │
                               ▼
                    SPATIAL/TEMPORAL MATCH
                               │
               ┌───────────────┴───────────────┐
               │                               │
               ▼                               ▼
        INCIDENT HISTORY                 FACILITY HISTORY
               │                               │
               └───────────────┬───────────────┘
                               ▼
                     BEHAVIOR FEATURES
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
     Persistence           Baseline             Trends
          │                    │                    │
          ▼                    ▼                    ▼
    Detection rate         Median/P95        Activity change
    Active periods         FRP distribution  Recurrence
    Spatial consistency    History quality   Seasonality later
          │                    │                    │
          └────────────────────┼────────────────────┘
                               ▼
                    HISTORICAL INTELLIGENCE
                               │
             ┌─────────────────┴─────────────────┐
             ▼                                   ▼
       Selection Engine                    Severity Engine
             │                                   │
             ▼                                   ▼
      Investigation                       Current seriousness
        decision                              assessment
```

---

## 13.2 Store First, Analyze Second

Every valid FIRMS observation is stored before historical analysis.

```text
FIRMS
 ↓
Validate
 ↓
Normalize
 ↓
Store
 ↓
Historical feature generation
```

This means a low-FRP event that is not selected today can become important later.

Example:

```text
Day 1  → 7 MW
Day 2  → 8 MW
Day 3  → 7 MW
Day 5  → 9 MW
Day 7  → 8 MW
```

The individual observations may have been low priority initially, but together they form a persistent source.

---

# 13.3 Spatial Matching for History

Historical observations should not require an exact latitude/longitude match.

Use a spatial relationship based on:

- incident footprint
- facility polygon
- configurable radius around incident/facility
- spatial consistency of repeated observations

Conceptually:

```text
             historical points
              • • •
             •     •
              • • •

                  ↓

             current incident
                   ●
```

If repeated observations fall within the same spatial region, they can contribute to the same behavior profile.

Use PostGIS spatial queries for this.

---

# 13.4 Two Historical Profiles

FIREX should support two related but distinct historical profiles.

## A. Incident / Location Profile

Used for a thermal source at a particular geographic region.

Useful when:

- there is no known industrial facility
- the source is in a forest/mining/agricultural area
- a new incident is developing

Profile:

```text
location_id / spatial_reference
observation_count
active_days
median_frp
p90_frp
p95_frp
min_frp
max_frp
detection_frequency
persistence_score
history_reliability
```

## B. Industrial Facility Profile

Used by the Industry Intelligence page.

Profile:

```text
facility_id
observation_count
active_days
median_frp
p90_frp
p95_frp
min_frp
max_frp
detection_frequency
persistence_score
normal_activity_range
historical_incident_count
abnormal_event_count
history_reliability
```

This lets the user search a petrochemical/refinery/plant/mining facility and inspect its previous FIRMS behavior.

---

# 13.5 History Window

Start with:

```text
Last 30 days
Last 90 days
Last 365 days
```

But the engine should not hard-code one window everywhere.

Expose:

```text
history_window
comparison_window
```

as configuration.

For the first implementation:

- **30 days** → short-term behavior
- **90 days** → primary baseline
- **365 days** → longer-term facility view where data exists

Later versions can add:

- same month comparison
- season-aware comparison
- time-of-day comparison
- day/night behavior

Do not add those complexities to v1 unless the data supports them.

---

# 13.6 Historical Baseline

The baseline represents:

> **Normal thermal behavior for this specific location/facility over the selected historical window.**

Do not define the baseline as one previous observation.

Example:

```text
Historical FRP:

18
21
20
23
19
22
25
21
24
20

Median ≈ 21.5 MW
P95 ≈ upper historical range
```

The baseline object should contain:

```json
{
  "observation_count": 43,
  "median_frp": 21.5,
  "mean_frp": 22.8,
  "p90_frp": 28.4,
  "p95_frp": 31.2,
  "min_frp": 8.1,
  "max_frp": 42.7,
  "typical_detection_frequency": 6.2,
  "history_reliability": "strong"
}
```

Median is the main representation of typical FRP because it is less sensitive to extreme outliers.

P95 represents the upper historical range.

---

# 13.7 History Reliability

Do not pretend every baseline is equally trustworthy.

Use:

```text
0 observations      → NONE
1–4                 → LOW
5–9                 → MODERATE
10–19               → GOOD
20+                 → STRONG
```

This should primarily affect:

```text
Severity Confidence
Historical Confidence
```

It should NOT automatically reduce actual current severity.

A new 100 MW fire is still potentially severe even if the site has no historical data.

---

# 13.8 Persistence Engine

Persistence answers:

> **Does thermal activity repeatedly occur in approximately the same location over time?**

Do not reduce persistence to raw detection count alone.

Use multiple evidence dimensions:

### 1. Detection frequency

How often is the area detected?

### 2. Active periods

How many distinct dates/observation periods contain detections?

### 3. Temporal consistency

Are detections spread across multiple periods rather than concentrated in one satellite overpass?

### 4. Spatial consistency

Are detections close enough to represent the same source?

### 5. Recency

Is the source still being observed recently?

Produce:

```text
persistence_score = 0–100
```

The exact formula should be configurable.

For v1, avoid arbitrary complex ML. Use transparent deterministic rules.

Example feature object:

```json
{
  "detection_count": 18,
  "active_days": 12,
  "observation_span_days": 28,
  "spatial_radius_m": 180,
  "recent_detection": true,
  "persistence_score": 91
}
```

---

# 13.9 Distinguish Persistence From Normality

This is one of the most important historical rules.

```text
Persistence = repeated activity
Normality    = whether repeated activity is expected
```

Therefore:

```text
HIGH persistence
+
FRP near historical median
+
FRP below historical P95
=
Persistent / Normal
```

Whereas:

```text
HIGH persistence
+
FRP far above historical P95
=
Persistent / Abnormal
```

A refinery flare can therefore be persistent without automatically becoming a dangerous incident.

---

# 13.10 Historical Anomaly

Historical anomaly answers:

> **How unusual is the current thermal activity compared with this location's historical behavior?**

Use current FRP against:

- historical median
- historical P95

Simple first metric:

```text
FRP Ratio = Current FRP / Historical Median FRP
```

Engineering starting score:

```text
≤1.0×          → 0
>1.0–1.25×    → 10
>1.25–1.5×    → 20
>1.5–2×        → 40
>2–3×          → 60
>3–4×          → 75
>4–5×          → 90
>5×            → 100
```

Also flag:

```text
Current FRP > Historical P95
```

as an important abnormality indicator.

These thresholds are starting engineering values and should later be calibrated with real data.

---

# 13.11 Historical Trend Engine

Once enough observations exist, calculate trends such as:

```text
FRP increasing
FRP decreasing
Detection frequency increasing
Detection frequency decreasing
Stable activity
New persistent source
Recurring source
Recent surge
```

For v1, use simple deterministic trend calculations.

Example:

```text
Previous 30-day median = 12 MW
Recent 7-day median     = 24 MW

Trend = increasing
```

Do not build a forecasting model initially.

The PS requires monitoring and analysis, not long-range prediction.

---

# 13.12 Historical Incident Linking

The history system should also link historical FIRMS behavior to FIREX incidents.

Example:

```text
Facility A

Incident #021
Gas flare
LOW

Incident #044
Industrial fire
HIGH

Incident #081
Thermal anomaly
MEDIUM
```

The facility profile can then show:

```text
Total incidents
High/Critical incidents
Classification distribution
Persistent sources
Abnormal events
```

This creates the historical incident timeline for Industry Intelligence.

---

# 13.13 Historical Data Refresh

History should update incrementally after every ingestion cycle.

Do not rebuild an entire year's history every time the operator presses:

```text
RUN FIREX ANALYSIS
```

Instead:

```text
New FIRMS observations
        ↓
Identify affected spatial profiles
        ↓
Update only affected behavior profiles
        ↓
Recalculate relevant metrics
```

For example:

```text
100,000 historical observations
5 new observations
```

should not require recomputing unrelated facilities.

---

# 13.14 Historical Cache / Materialized Features

For dashboard speed, maintain computed feature records.

Example:

```text
behavior_profiles
behavior_daily_summary
historical_baselines
historical_incident_summary
```

The raw observations remain the source of truth.

Derived behavior tables are rebuildable.

This gives:

```text
RAW DATA
   ↓
DERIVED FEATURES
   ↓
FAST DASHBOARD
```

---

# 13.15 Recommended New Historical Tables

Instead of the old persistence-only SQLite design, use the new PostgreSQL/PostGIS model.

### `behavior_profiles`

```text
id
profile_type
facility_id
spatial_reference
window_start
window_end
observation_count
active_days
median_frp
mean_frp
p90_frp
p95_frp
min_frp
max_frp
detection_frequency
persistence_score
history_reliability
updated_at
```

### `behavior_daily_summary`

```text
id
profile_id
date
observation_count
max_frp
mean_frp
median_frp
active
```

### `historical_baselines`

```text
id
profile_id
window_start
window_end
median_frp
p90_frp
p95_frp
observation_count
history_reliability
updated_at
```

### `historical_anomalies`

```text
id
profile_id
incident_id
current_frp
historical_median
historical_p95
frp_ratio
anomaly_score
above_p95
created_at
```

### `historical_incident_summary`

```text
facility_id / spatial_reference
incident_count
low_count
medium_count
high_count
critical_count
persistent_count
abnormal_count
last_incident_at
```

---

# 13.16 Historical Pipeline API

For Live Monitoring:

```text
GET /incidents/{id}/history
GET /incidents/{id}/behavior
GET /incidents/{id}/baseline
GET /incidents/{id}/trend
```

For Industry Intelligence:

```text
GET /industries/{id}/firms
GET /industries/{id}/history
GET /industries/{id}/baseline
GET /industries/{id}/persistence
GET /industries/{id}/trends
GET /industries/{id}/incidents
```

---

# 13.17 Historical Pipeline Execution

Recommended internal flow:

```python
def update_behavior_for_observations(new_observations):

    affected_profiles = find_affected_profiles(
        observations=new_observations
    )

    for profile in affected_profiles:

        history = load_history(
            profile=profile,
            window="90d"
        )

        daily = build_daily_summary(history)

        baseline = calculate_baseline(history)

        persistence = calculate_persistence(history)

        trend = calculate_trend(daily)

        anomaly = calculate_current_anomaly(
            profile=profile,
            baseline=baseline
        )

        save_behavior_features(
            profile=profile,
            baseline=baseline,
            persistence=persistence,
            trend=trend,
            anomaly=anomaly
        )
```

This is conceptual pseudocode.

---

# 13.18 Where Historical Intelligence Is Used

The historical engine should expose features to other modules.

## Selection

Consumes:

```text
persistence_score
historical_anomaly_score
history_reliability
```

## Severity

Consumes:

```text
historical_deviation
historical_baseline
historical_p95
```

## Industry Intelligence

Consumes:

```text
full behavior profile
full time series
historical incidents
trends
```

## Dashboard

Displays:

```text
Persistence
Historical baseline
P95
Anomaly
Trends
```

The historical engine itself should **not** make the final severity or selection decision.

---

# 13.19 Final Historical Intelligence Flow

```text
                         ALL FIRMS DATA
                               │
                               ▼
                        POSTGRES / POSTGIS
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ SPATIAL PROFILE MATCH   │
                  │ Incident / Facility    │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ HISTORICAL WINDOW       │
                  │ 30d / 90d / 365d       │
                  └────────────┬────────────┘
                               │
             ┌─────────────────┼──────────────────┐
             ▼                 ▼                  ▼
       DAILY SUMMARY      PERSISTENCE        BASELINE
             │                 │                  │
             │                 │            Median / P95
             │                 │                  │
             └─────────────────┼──────────────────┘
                               ▼
                        TREND ANALYSIS
                               │
                               ▼
                     HISTORICAL ANOMALY
                               │
                               ▼
                     BEHAVIOR PROFILE
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
      SELECTION             SEVERITY          INDUSTRY PAGE
      Priority              Context           Historical view
```

---

# 13.20 Important Separation

The final system should conceptually maintain:

```text
CURRENT DATA
    ↓
What is happening now?

HISTORICAL DATA
    ↓
What normally happens here?

AI
    ↓
What is it probably?

SEVERITY
    ↓
How serious is it?

INDUSTRY INTELLIGENCE
    ↓
How has this facility behaved over time?
```

This avoids turning the historical module into another duplicate "risk engine."

---

# 14. Selection Engine

## Purpose

Selection asks:

> Which incident candidates deserve current detailed investigation?

It happens before expensive imagery/AI analysis.

## Recommended weighted model

### When history exists

```text
Current Thermal Intensity / FRP   40%
Persistence                       30%
FIRMS Confidence                  20%
Historical Anomaly                10%
--------------------------------------
                                  100%
```

Formula:

```text
Investigation Priority =
    0.40 × FRP Score
  + 0.30 × Persistence Score
  + 0.20 × FIRMS Confidence
  + 0.10 × Historical Anomaly
```
#### 14.1 FRP Normalization
Define how raw FRP (MW) maps to a 0‑100 score.

``FRP_Score = min(100, 25 × log2(frp_mw + 1))``

- 4 MW → ~50
- 8 MW → ~75
- 16 MW → ~100

Tune with real data as needed.

#### 14.2 FIRMS Confidence Mapping
Map FIRMS confidence values to numeric scores (0‑100).

| Source | Category | Score |
|--------|----------|-------|
| MODIS  | low      | 25 |
| MODIS  | nominal  | 65 |
| MODIS  | high     | 95 |
| VIIRS  | 0‑100 raw| use raw value |

#### 14.3 Selection Override Thresholds
Starting thresholds for mandatory overrides:

- **Extreme FRP**: FRP > 150 MW **and** FIRMS confidence > 80.
- **High Persistence**: Persistence score > 85.
- **Strong Historical Anomaly**: Current FRP > 3 × historical median FRP.

These thresholds can be tuned during experimentation.

#### 14.4 GIS Context Scoring (Severity Engine)
A preliminary rubric (to be refined in Stage 7):

| GIS Context | Score |
|-------------|-------|
| Inside petro‑chemical facility | 30 |
| Within 500 m of a forest reserve | 20 |
| Agricultural land | 10 |
| Urban area | 5 |
| Default (no special context) | 0 |

#### 14.5 AI Source Severity Scoring (Severity Engine)
Map AI classification to a base severity contribution (0‑100).

| Classification | Severity Score |
|----------------|----------------|
| industrial_fire | 85 |
| gas_flare       | 60 |
| wildfire        | 70 |
| agricultural_burning | 40 |
| unknown / uncertain | 50 |

#### 14.6 Incident Temporal Gap (Clustering Design)
Initial rule for associating observations into the same incident:

- Observations within **24 hours** and within a **5 km** radius are considered temporally compatible and may belong to the same incident.

#### 14.7 Incident Merge / Split (v2 consideration)
For version 1 the system will **not** merge or split incidents after creation. This capability is planned for a future release where incident trajectories can be reconciled.
### When history does not exist

```text
Current Thermal Intensity / FRP   45%
Persistence                       30%
FIRMS Confidence                  25%
Historical Anomaly                 N/A
--------------------------------------
                                  100%
```

Formula:

```text
Investigation Priority =
    0.45 × FRP Score
  + 0.30 × Persistence Score
  + 0.25 × FIRMS Confidence
```

> **Note on no-history persistence:** "No history" means no historical baseline data exists for this location, not necessarily that the incident is brand new. Persistence can still be meaningful if multiple observations have been recorded within the current ingestion window or recent cycles. For a truly first-ever single observation, persistence will be near zero, effectively limiting the score to FRP + FIRMS Confidence (~70% of range). The mandatory selection overrides below ensure that extreme new events are still selected regardless of the weighted score.

## Mandatory selection overrides

### Extreme current event

```text
Very high FRP
+
high FIRMS confidence
→ immediate investigation
```

### Persistent source

```text
high persistence
→ investigation
```

### Strong historical anomaly

```text
current behavior far above local historical baseline
→ investigation
```

These overrides prevent a low-FRP but highly persistent source from being ignored.

## Example

```text
FRP Score = 25
Persistence = 95
FIRMS Confidence = 90
Historical Anomaly = 30

Priority =
0.40×25 + 0.30×95 + 0.20×90 + 0.10×30
= 59.5
```

The incident can still be selected due to the persistence trigger.

---

# 15. Current Visual Verification — Existing Google Maps / Map-Satellite Logic

The existing FIREX prototype already uses a high-resolution map/satellite-tile approach rather than relying on a blurry "live satellite image" as the main AI input. Preserve that direction in the backend rewrite.

### Important wording

Do **not** describe this as "live satellite imagery."

Describe it as:

> **Current high-resolution map/satellite visual context centered on the FIRMS incident.**

The purpose is to provide a clearer visual view of the physical surroundings of the thermal anomaly.

### Existing-repo direction to preserve

The current repository describes a dynamic high-resolution optical tile synthesis workflow and a calibrated thermal reticle centered on the FIRMS location. The existing AI module also expects `satellite_annotated.jpg` / `satellite_raw.jpg` crops and explicitly asks the model to inspect the visible surroundings of the marked detection.

For the rewritten backend:

```text
Selected Incident
      ↓
Calculate incident footprint
      ↓
Generate map/satellite viewport
      ↓
Fetch/stitch high-resolution tiles
      ↓
Place calibrated FIRMS reticle
      ↓
Crop around the incident
      ↓
Basic image availability/validity check
      ↓
AI Investigation
```

### Dynamic viewport/radius

Starting values can remain configurable:

```text
isolated event       ≈ 500 m
small cluster        ≈ 750 m
medium cluster       ≈ 1 km
large cluster        ≈ 1.5–2 km
```

General idea:

```text
visual_radius =
max(min_radius, cluster_radius + buffer)
```

with an upper cap.

These are engineering starting values, not scientific constants.

### Visual verification metadata

Store:

- imagery/map provider
- tile/viewport zoom
- acquisition/access timestamp where available
- center coordinates
- bounding box
- radius
- image dimensions
- reticle coordinates
- imagery metadata and acquisition timestamp
- source URL/template identifier where appropriate
- relationship to FIRMS timestamp

### Provider abstraction

Do not hard-code Google Maps logic throughout the application.

Create:

```python
class VisualMapProvider:
    def fetch_context(self, request):
        ...
```

Then implement the current Google Maps/tile approach behind that interface.

This lets FIREX switch or add another imagery/map provider later without rewriting the AI or incident pipeline.

### API / licensing note

Use only imagery access methods and credentials permitted by the relevant Google Maps Platform products and project terms. Keep provider credentials server-side.


---

---

# 16. Multimodal AI Investigation

AI is an **investigator**, not the initial detector.

## Input

### FIRMS

```text
frp_mw
frp_percentile
firms_confidence
satellite
sensor/product
acquisition_time
```

### Cluster

```text
observation_count
cluster_radius
time_span
```

### GIS

```text
land_cover
state
district
industrial_context
nearby_assets
protected_area
```

### Image

Current satellite image.

## AI output schema

```json
{
  "classification": "industrial_fire",
  "confidence": 91,
  "alternative": {
    "classification": "gas_flare",
    "confidence": 6
  },
  "visual_evidence": [
    "Thermal activity appears spatially associated with industrial structures"
  ],
  "contextual_evidence": [
    "Incident lies within a mapped industrial facility"
  ],
  "uncertainties": [
    "Smoke partially obscures the eastern section"
  ],
  "image_quality": {
    "score": 82,
    "cloud_cover": "low",
    "visibility": "good"
  },
  "needs_reinvestigation": false
}
```

## AI classifications

### PS-focused classification taxonomy

Keep the first-version taxonomy tightly aligned with the PS:

```text
industrial_fire
gas_flare
wildfire
agricultural_burning
mining_related
uncertain
```

`mining_related` is retained because the PS explicitly names mining areas and lists mining activity as a competing thermal source.

Use `uncertain` whenever the available FIRMS, GIS, or visual evidence is insufficient.

If an observation does not fit the above categories, preserve the raw evidence and classify it as `uncertain` rather than expanding the taxonomy prematurely.

# 17. AI Prompt Rules

The system prompt should explicitly instruct:

1. FIRMS is a thermal anomaly source, not proof of fire.
2. Inspect the image rather than relying only on metadata.
3. Use GIS and FIRMS as context.
4. Never invent missing values.
5. Do not calculate final severity.
6. Provide primary and alternative hypotheses.
7. Explain visual evidence.
8. Explain contextual evidence.
9. State uncertainty.
10. Use `uncertain` when evidence is insufficient.
11. Never claim ground truth from satellite imagery alone.
12. Return strict JSON matching the schema.

---

# 18. Severity Engine

## Purpose

Severity answers:

> How serious does the current evidence indicate this incident is?

It is after AI investigation.

## Known hotspot model

When reliable history exists:

```text
FRP / Thermal Intensity    35%
Historical Deviation       30%
AI Source Severity         20%
GIS Context                15%
--------------------------------
                           100%
```

Formula:

```text
Severity =
    0.35 × FRP
  + 0.30 × HistoricalDeviation
  + 0.20 × AISourceSeverity
  + 0.15 × GISContext
```

## New hotspot model

When reliable history does not exist:

```text
FRP / Thermal Intensity    50%
AI Source Severity         30%
GIS Context                20%
--------------------------------
                           100%
```

Formula:

```text
Severity =
    0.50 × FRP
  + 0.30 × AISourceSeverity
  + 0.20 × GISContext
```

## Severity levels

Recommended first version:

```text
0–24    LOW
25–49   MEDIUM
50–74   HIGH
75–100  CRITICAL
```

## Escalation rules

Keep explicit operational rules outside the weights.

Examples:

```text
Extreme FRP + high FIRMS confidence
→ minimum HIGH
```

```text
Strong industrial-fire evidence
+
hazardous/critical asset nearby
→ escalate
```

```text
Wildfire
+
protected-area overlap
→ escalate
```

```text
Current activity far above historical P95
→ flag ABNORMAL ACTIVITY
```

The weighted score provides the base. Rules handle exceptional conditions.

---

# 19. Severity Confidence

Keep separate from severity.

Potential confidence inputs:

- FIRMS confidence
- AI confidence
- GIS certainty
- Historical sample size
- Evidence consistency

Output:

```text
severity_score: 84
severity_level: CRITICAL
severity_confidence: 76
```

---

# 20. Incident State Machine

Severity and state are separate.

Recommended states:

```text
NEW
  ↓
INVESTIGATING
  ↓
ACTIVE
  ↓
PERSISTENT / ESCALATED
  ↓
SUBSIDING
  ↓
RESOLVED
```

An incident can be:

```text
State: PERSISTENT
Severity: LOW
```

or:

```text
State: ACTIVE
Severity: CRITICAL
```

---

# 21. Alert Engine

Recommended initial behavior:

```text
LOW      → dashboard
MEDIUM   → monitor
HIGH     → alert
CRITICAL → immediate alert
```

Additional logic:

```text
high severity + low confidence
→ re-investigate
```

```text
extreme current FRP + high confidence
→ immediate escalation
```

Alert channels can initially be:

- dashboard
- notification panel
- webhook

Email/SMS can be added later.

---

# 22. Re-Investigation

FIREX should support iterative investigation.

Trigger when:

- AI confidence is low
- new FIRMS observations arrive
- FRP changes significantly
- incident severity changes
- event expands spatially
- current activity becomes historically abnormal

Example:

```text
AI confidence 42%
        ↓
re-investigation
        ↓
new image / crop
        ↓
AI
        ↓
confidence 88%
```

---

# 23. Live Monitoring Page

This page answers:

> What is happening now?

## Main controls

### Primary button

```text
[ 🔄 RUN FIREX ANALYSIS ]
```

This is an analysis trigger, not a browser refresh.

Backend endpoint:

```text
POST /analysis/run
```

## What the button does

```text
Fetch latest FIRMS
      ↓
Validate / deduplicate
      ↓
GIS enrichment
      ↓
Clustering
      ↓
Incident association
      ↓
Behavior feature refresh
      ↓
Selection
      ↓
Current imagery
      ↓
AI
      ↓
Severity
      ↓
History update
      ↓
Alert evaluation
      ↓
Database update
      ↓
Dashboard update
```

## Prevent duplicate runs

While analysis is active:

```text
[ ⟳ ANALYSIS RUNNING... ]
```

Disable repeated clicks.

Use backend run locks / idempotency.

## Incremental refresh

Do not re-run expensive AI for every old observation.

Example:

```text
Previous DB: 100 observations
New FIRMS:   105 observations

Only 5 new observations
→ process affected/new incidents
```

All observations remain stored.

## Auto monitoring

Optional setting:

```text
Auto Monitoring: ON
[ RUN NOW ]
```

Automatic monitoring and manual analysis should share the same backend analysis pipeline.

---

# 24. Live Monitoring UI

Suggested layout:

```text
┌─────────────────────────────────────────────────────┐
│ FIREX LIVE MONITORING                     ● ACTIVE  │
│                                                     │
│ Last analysis: 13 Sep 2026 • 18:47 IST             │
│                                                     │
│ [ 🔄 RUN FIREX ANALYSIS ]     Auto Monitoring: ON  │
└─────────────────────────────────────────────────────┘

┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│   124    │ │    18    │ │     4    │ │     2    │
│ Anomalies│ │  Active  │ │   High   │ │ Critical │
└──────────┘ └──────────┘ └──────────┘ └──────────┘

                    GIS MAP

        Incident markers
        Industrial assets
        Context layers

                 INCIDENT LIST
```

---

# 25. Analysis Progress UI

During a run:

```text
✓ FIRMS data fetched
✓ Validation completed
✓ GIS enrichment
✓ Clustering
✓ Incident selection
◉ Image acquisition
○ AI investigation
○ Severity assessment
○ History update
○ Alert evaluation
✓ Dashboard update
```

At completion:

```text
ANALYSIS COMPLETE

12 new observations
4 incidents updated
2 new incidents
1 high-priority investigation
1 persistent source detected
```

---

# 26. Industry Intelligence Page

This is an important additional feature.

The page answers:

> What has happened at this industrial facility in the past?

It should **reuse the same FIRMS database and behavior engine**.

Do NOT create a second ingestion pipeline.

## Flow

```text
Search industry
      ↓
Find industrial asset
      ↓
Load historical FIRMS
      ↓
Behavior Intelligence
      ↓
Baseline / P95 / persistence
      ↓
Historical incidents
      ↓
Trends / anomaly analysis
      ↓
Facility intelligence view
```

## Search by

- Facility name
- Facility type
- State
- District
- Operator
- Map selection

## Example

```text
🔎 Search industrial facility...

Barauni Refinery
```

---

# 27. Industry Intelligence UI

Recommended sections:

## 27.1 Facility Overview

```text
BARAUNI REFINERY

Type: Oil Refinery
State: Bihar

FIRMS detections: 127
Active days: 43
Persistent source: YES

Current status: NORMAL
```

## 27.2 Thermal Activity

Charts:

- FRP over time
- daily detections
- activity frequency
- satellite breakdown

## 27.3 Historical Baseline

```text
Historical Median: 16.2 MW
Historical P95:    31.8 MW
Current:            82.0 MW

Historical status: VERY HIGH
```

## 27.4 Incident History

```text
Incident #142
Industrial Fire
Severity: CRITICAL
Date: ...

Incident #117
Gas Flare
Severity: LOW
Date: ...

Incident #089
Thermal Anomaly
Severity: MEDIUM
Date: ...
```

## 27.5 Trend / Pattern

Examples:

```text
Persistent but normal
Persistent and abnormal
New event
Increasing activity
Decreasing activity
Recurring pattern
```

---

# 28. Relationship Between the Two Main Pages

## Live Monitoring

```text
What is happening now?
```

## Industry Intelligence

```text
What normally happens here?
What happened here before?
Is current behavior abnormal?
```

They share:

```text
FIRMS database
GIS database
Industrial asset database
Incident database
Behavior Intelligence engine
```

---

# 29. Dashboard Incident Detail

When a user clicks an incident:

```text
┌─────────────────────────────────────────────┐
│ FIREX-00142                                │
├─────────────────────────────────────────────┤
│ Classification: INDUSTRIAL FIRE            │
│ AI Confidence: 91%                         │
│ Severity: CRITICAL                         │
│ Severity Score: 87/100                     │
│ Severity Confidence: 82%                   │
│                                             │
│ Current FRP: 94.2 MW                       │
│ FIRMS Confidence: HIGH                     │
│ Satellite: NOAA-21                         │
│                                             │
│ Persistence: HIGH                          │
│ Historical Anomaly: VERY HIGH              │
│ State: ACTIVE                              │
│                                             │
│ Facility: Petrochemical Complex            │
│ State: ...                                 │
│ District: ...                              │
│                                             │
│ [Current Satellite Image]                  │
│                                             │
│ Evidence                                   │
│ • Thermal activity near facility           │
│ • Current FRP above historical P95         │
│ • Multiple clustered observations          │
└─────────────────────────────────────────────┘
```

---

# 30. Explainability Requirements

Never show only:

```text
Severity = CRITICAL
```

Show:

```text
WHY?

FRP: 94.2 MW
Historical median: 21.5 MW
Historical P95: 31.2 MW
AI classification: Industrial Fire
AI confidence: 91%
GIS context: Petrochemical facility
State: Active
```

Then summarize:

> Current thermal intensity is substantially above the site's historical range, and available image/GIS evidence favors an industrial fire classification.

---

# 31. Evidence Provenance

Every final conclusion should be traceable.

```text
FIRMS observation
      ↓
cluster
      ↓
GIS enrichment
      ↓
satellite imagery
      ↓
AI investigation
      ↓
severity assessment
      ↓
alert
```

Store:

- source
- timestamp
- model
- prompt version
- image ID
- calculation version
- threshold/weight version

This is essential for explainability and debugging.

---

# 32. API Design

## Analysis

```text
POST /analysis/run
GET  /analysis/runs/{run_id}
GET  /analysis/runs/{run_id}/events
```

## Incidents

```text
GET  /incidents
GET  /incidents/{id}
GET  /incidents/{id}/history
GET  /incidents/{id}/imagery
POST /incidents/{id}/reinvestigate
```

## Observations

```text
GET /observations
GET /observations/{id}
```

## Industry

```text
GET /industries
GET /industries/search?q=
GET /industries/{id}
GET /industries/{id}/firms
GET /industries/{id}/history
GET /industries/{id}/incidents
GET /industries/{id}/trends
```

## Dashboard

```text
GET /dashboard/summary
GET /dashboard/map
GET /dashboard/alerts
```

## Live events

```text
GET /events
```

SSE events:

```text
incident.created
incident.updated
investigation.started
investigation.completed
severity.changed
alert.created
analysis.completed
```

---

# 33. Recommended Backend Run Flow

```python
def run_firex_analysis():
    raw = firms.fetch_latest()

    observations = validator.validate_and_normalize(raw)

    storage.save_observations(observations)

    enriched = gis.enrich(observations)

    clusters = clustering.build_clusters(enriched)

    incidents = incident_service.associate(clusters)

    behavior = behavior_engine.update_features(incidents)

    selected = selection_engine.select(
        incidents=incidents,
        behavior=behavior
    )

    for incident in selected:
        image = imagery.fetch_current(incident)

        quality = imagery.check_quality(image)

        ai_result = ai.investigate(
            incident=incident,
            image=image,
            quality=quality
        )

        incident_behavior = behavior.for_incident(incident)

        severity = severity_engine.calculate(
            incident=incident,
            ai_result=ai_result,
            behavior=incident_behavior
        )

        state = incident_state.update(
            incident=incident,
            severity=severity
        )

        storage.save_results(
            incident=incident,
            ai_result=ai_result,
            severity=severity,
            state=state
        )

        alerts.evaluate(incident)

        events.publish(incident)

    return run_summary()
```

This is pseudocode, not production code.

---

# 34. Vibe-Coding Strategy

Do NOT ask an AI coding agent:

> "Build the entire FIREX system."

It will likely create tightly coupled code, fake data paths, duplicated logic, and hard-to-debug integrations.

Instead, build in **vertical, testable sections**.

**MANDATORY MANUAL VERIFICATION:** After every stage, stop implementation and manually verify the actual running system. Automated tests are necessary but are not sufficient. Saurabh must explicitly mark the stage **PASS** before the coding agent starts the next stage.

The coding agent must provide a short manual checklist after each stage:

```text
MANUAL VERIFICATION — STAGE X

1. Start/run:
2. Click/request:
3. Expected result:
4. PASS condition:
5. FAIL condition:
6. What to inspect (UI/API/logs/database):
7. V1 comparison required? YES/NO
8. Result: PASS / FAIL
9. Verified by: Saurabh
10. Notes:
```

**Do not continue after FAIL.** Fix the current stage, rerun automated tests, repeat the manual checklist, and only then continue.

Every section should have:

```text
1. Goal
2. Inputs
3. Outputs
4. Files to create
5. API contract
6. Database tables
7. Test cases
8. Demo condition
9. Stop point
```

Do not begin the next section until the previous section works.

---

# 35. Staged Build Roadmap

The implementation should be completed in **large, testable stages**, not as dozens of independent sections.

The purpose of this roadmap is to let a coding agent complete one coherent stage, test it, compare it with the working **v1 repository where useful**, and only then continue.

## Stage 0 — V1 Audit + Project Foundation

### Goal

Understand and preserve the working parts of v1 before writing the new backend.

### First inspect v1

Use the existing FIREX-SIH2026 repository as a **reference implementation**, especially for:

- existing frontend/UI and interaction patterns
- FIRMS ingestion/client behavior
- Google Maps / high-resolution map-satellite visual workflow
- MiniMax/OpenRouter AI integration where still applicable
- existing API/data assumptions
- working map markers, dossier/incident views, SSE behavior, and visual states

Do not blindly copy v1 architecture. Reuse proven integrations and UX patterns, while replacing tangled backend responsibilities with the new incident-centric design.

### Build

Create the clean project structure:

```text
backend/
frontend/
data/
scripts/
tests/
docs/
```

Configure:

- Python environment
- FastAPI
- TypeScript
- PostgreSQL/PostGIS connection
- `.env`
- `.env.example`
- logging
- health endpoint

### V1 checkpoint

Before continuing, run v1 and record:

```text
what already works
what should be reused
what should be replaced
what should not be touched
```

### Done when

```text
GET /health → 200
frontend loads
database connects
v1 reference notes are documented
```

---

## Stage 1 — Data Foundation + FIRMS Ingestion

### Goal

Create the source-of-truth data layer and reliably ingest FIRMS observations.

### Build

Implement:

- PostgreSQL/PostGIS schema
- observations
- incidents
- incident_observations
- industrial_assets
- imagery
- ai_investigations
- historical_baselines
- severity_assessments
- alerts
- incident_events
- FIRMS client
- validation
- normalization
- deduplication
- persistence

### Test

Start with deterministic fixtures:

```text
known CSV → validate → normalize → store → retrieve
```

Then test real FIRMS API access.

Every valid FIRMS observation must be stored before downstream analysis.

### V1 reference checkpoint

Compare the new FIRMS client with the v1 implementation. Reuse its working authentication/request/parsing logic where appropriate, but keep the new database model authoritative.

### Done when

```text
GET /observations
```

returns normalized observations and spatial queries work.

---

## Stage 2 — GIS + Industrial Context

### Goal

Attach geospatial and industrial context to observations.

### Build

Implement:

- point-in-polygon
- nearest industrial asset
- facility containment checks
- land-cover lookup
- protected-area lookup
- state/district lookup
- spatial indexes
- industrial facility importer
- industry/facility search
- spatial lookup APIs

### Test

Use controlled geometry fixtures:

```text
point inside polygon
point near polygon
point outside polygon
```

Also verify searches by:

```text
name
type
industry
state
district
```

### V1 reference checkpoint

Reuse v1's useful map/context conventions and existing facility-data assumptions where they are valid. Do not reintroduce string-based proximity logic.

### Done when

An observation can be enriched with structured GIS context and related industrial assets.

---

## Stage 3 — Clustering + Incident Lifecycle

### Critical clustering invariants

**Never sum the FRP values of all observations in a cluster and treat the sum as the incident FRP.** Every FIRMS observation is an independent raw observation and keeps its own FRP.

The lifecycle is strictly:

```text
ONE FIRMS OBSERVATION
        ↓
SPATIAL + TEMPORAL CLUSTER
        ↓
CLUSTER CANDIDATE
        ↓
INCIDENT ASSOCIATION
        ↓
NEW OR EXISTING INCIDENT
```

A cluster may expose `max_frp`, `mean_frp`, `min_frp`, observation count, footprint, and time span, but these are derived statistics—not a summed thermal-power value.

**Hard rule:**

```text
FRP1 + FRP2 + FRP3 = incident FRP  ❌

incident.current_max_frp       = appropriate current maximum ✓
incident.current_mean_frp      = appropriate current mean ✓
incident.observation_count     = number of linked observations ✓
individual observation FRPs    = always preserved ✓
```

Manually verify at minimum:

```text
Case A: 3 nearby observations at nearly the same time
→ one cluster / candidate incident
→ individual FRPs preserved

Case B: distant observations
→ separate clusters

Case C: same place but clearly separated in time
→ separate clusters unless incident association rules intentionally link them

Case D: adjacent industrial sources
→ do not merge just because they are geographically close

Case E: multiple FRPs inside one cluster
→ NO FRP summation as incident intensity
→ max/mean/statistical fields remain traceable to observations
```


### Goal

Convert raw FIRMS observations into persistent incident objects.

### Incident spatial representation

Every incident should maintain both a center and a spatial footprint:

```text
center_geom
footprint_geom
footprint_radius_m
```

The footprint is used for:

- incident association
- map rendering
- imagery viewport/radius
- historical spatial matching
- detecting incident expansion or contraction

Do not use a single fixed-radius circle as the permanent representation when the observed cluster geometry provides better evidence.

### Build

Implement:

- spatial-temporal clustering
- DBSCAN or equivalent deterministic clustering
- cluster geometry/statistics
- new incident creation
- existing incident matching
- incident-observation association
- incident state transitions
- incident timeline events

### Incident association rules

A cluster becoming an incident is **not** automatic purely because points are nearby. Association to an existing incident should consider:

```text
1. Spatial compatibility
   - cluster overlaps/is within the existing incident footprint
   - distance remains within a configurable threshold

2. Temporal compatibility
   - cluster is temporally continuous or within a configured gap

3. Source compatibility
   - evidence does not indicate a distinct nearby source

4. Facility/context compatibility
   - industrial boundaries/assets may help distinguish adjacent sources
```

Create a **new incident** when the spatial/temporal relationship indicates a distinct event.

**Never associate an observation to an existing incident solely because it is geographically close.**

The association decision must be explainable and store an association method/score.

### Test

```text
3 close points → one cluster
2 far points → two clusters
same area + distant time → separate clusters
run 1 → new incident
run 2 → same incident updated
run 3 → another incident
```

### V1 reference checkpoint

Inspect v1 incident grouping, marker/dossier behavior, and any existing incident identifiers. Preserve useful semantics, but the new backend must treat the **incident** as the central business object.

### Done when

Repeated ingestion updates the correct incident rather than creating duplicates.

### Provenance requirement

Every derived object must remain traceable through the complete evidence chain:

```text
FIRMS observation
    ↓
cluster_id
    ↓
incident_id
    ↓
behavior profile / historical features
    ↓
selection result
    ↓
imagery record
    ↓
AI investigation
    ↓
severity assessment
    ↓
alert
```

Persist enough identifiers and timestamps to answer: **"Which raw observations and evidence produced this incident result?"**

Do not overwrite or destroy the raw evidence when calculating derived values.

---

## Stage 4 — Behavior Intelligence / Historical System

### Goal

Build the new history system from scratch around the incident/facility model.

### Build

Implement:

- location history profile
- facility history profile
- 30d / 90d / 365d windows
- daily summaries
- historical baseline
- median / P90 / P95
- history reliability
- persistence score
- historical anomaly
- trend calculation
- historical incident summaries
- incremental feature refresh
- behavior cache/materialized features

Use deterministic rules for v1 of the behavior engine.

### Test

Use synthetic sequences such as:

```text
10, 12, 11, 13, 12
```

Then compare current values such as:

```text
12  → normal
40  → abnormal
```

Also verify:

```text
high persistence + normal historical range
    → persistent / normal

high persistence + strong historical deviation
    → persistent / abnormal
```

### V1 reference checkpoint

Only use v1's persistence/history logic as a **reference for migration decisions**. Do not rebuild the old SQLite persistence module as the new system.

The new PostgreSQL/PostGIS behavior system is authoritative.

### Done when

The history engine can answer:

```text
What is normal here?
How often does activity recur?
Is the source persistent?
Is the current activity abnormal?
How reliable is the historical evidence?
```

---

## Stage 5 — Selection + Visual Context

### Goal

Select incidents for expensive investigation and prepare the existing visual verification workflow.

### Build

Implement:

- normalized FRP score
- persistence score
- FIRMS confidence
- historical anomaly score
- investigation-priority model
- new-incident model
- mandatory selection overrides
- visual map provider interface
- dynamic incident viewport/radius
- image/tile retrieval
- caching
- provenance metadata
- basic image availability/validity check

Selection must happen **before** expensive AI analysis.

### V1 reference checkpoint

This stage should explicitly reuse the existing v1 visual workflow where it already works:

```text
incident
→ centered map/satellite context
→ calibrated FIRMS reticle
→ crop
→ AI input
```

Do not create a completely new imagery experience.

**Do not create a separate mandatory Image Quality Intelligence subsystem in v1.** The requirement here is only to verify that the retrieved image/context is available and usable enough to send to the configured AI model. Keep optional metadata such as dimensions or provider timestamp when available, but do not build a separate scoring pipeline unless later testing proves it is necessary.

Use the wording:

> High-resolution map/satellite visual context for incident verification

Do not claim continuous live satellite imaging.

### Done when

A selected incident produces a deterministic investigation package containing:

```text
incident data
GIS context
historical features
visual context
provenance metadata
```

---

## Stage 6 — AI Investigation

### Goal

Add the multimodal AI investigator after the upstream evidence pipeline is stable.

### Important model rule

The AI provider/model is **configurable**, not hard-coded as a project architecture dependency.

The implementation must support:

```text
AI_PROVIDER
AI_MODEL
AI_API_BASE_URL
AI_API_KEY
```

through environment/configuration.

The current or future model may change without requiring changes to:

- FIRMS ingestion
- GIS
- clustering
- incident association
- history
- selection
- severity
- UI

### V1 reference checkpoint

Use the working v1 `vision_classifier.py` integration as the starting reference for:

- multimodal request construction
- image + FIRMS metadata input
- allowed classification handling
- API-key pool/failover where useful
- uncertainty handling
- response parsing

Refactor it behind:

```text
intelligence/
├── vision.py
├── prompts.py
├── schemas.py
└── evidence.py
```

Do not copy v1's provider-specific logic throughout the application.

### Build

Add:

- provider abstraction
- configurable model name
- strict JSON schema validation
- prompt versioning
- retry handling
- timeout handling
- primary + alternative hypothesis
- visual evidence
- contextual evidence
- uncertainty
- re-investigation flag

Keep the PS-focused taxonomy:

```text
industrial_fire
gas_flare
wildfire
agricultural_burning
mining_related
uncertain
```

### Test

At minimum:

```text
industrial fire
gas flare
wildfire
agricultural burning
mining
uncertain/cloud-obscured
provider/API failure
invalid model/provider response
```

### Done when

The configured AI model returns valid structured output without changing the rest of the pipeline when the model/provider is swapped.

---

## Stage 7 — Severity + Alerts

### Goal

Turn structured evidence into operational severity and alerts.

### Build

Implement:

- known-hotspot severity model
- new-hotspot severity model
- normalization
- escalation rules
- severity confidence
- alert thresholds
- alert deduplication
- acknowledgment
- resolution

Keep these concepts separate:

```text
investigation_priority
severity_score
severity_level
severity_confidence
```

### Test

Use deterministic fixtures and verify:

```text
same input → same output
extreme FRP → override works
historical anomaly → escalation works
high severity + low confidence → re-investigation
```

### Done when

The system can reliably produce final severity and exactly-once alert transitions.

---

## Stage 8 — End-to-End Orchestration + SSE

### Goal

Connect all backend stages into one reliable analysis run.

### Build

Implement:

```text
POST /analysis/run
```

Pipeline:

```text
FIRMS
→ validation
→ GIS
→ clustering
→ incident association
→ behavior
→ selection
→ visual context
→ AI
→ severity
→ alerts
→ database update
```

Add SSE events such as:

```text
analysis.started
firms.fetched
gis.completed
clustering.completed
selection.completed
imagery.started
ai.started
ai.completed
severity.completed
alert.created
analysis.completed
```

Prevent duplicate runs with:

- backend run locks
- idempotency
- incremental processing
- affected-profile updates only

### V1 reference checkpoint

Compare the complete run against the v1 orchestration flow and preserve any working operational behavior that does not conflict with the new architecture.

### Done when

One backend run can complete end-to-end and stream progress to the frontend without repeated polling.

---

## Stage 9 — Existing UI Integration + Industry Intelligence

### Goal

Connect the new backend to the **existing v1 UI** rather than creating a new frontend.

### Hard rule

> **DO NOT CREATE A NEW UI.**

Keep the same:

- visual language
- layout
- dashboard structure
- map experience
- blur/morphism treatment
- incident cards
- dossier/detail presentation
- navigation style
- interaction patterns

Only make targeted changes required by the new backend.

### Allowed UI changes

Add or update only what is necessary for:

```text
new incident fields
investigation priority explanation
severity vs priority
persistence/history
historical anomaly
AI evidence/uncertainty
new API states
analysis progress
industry search
historical facility charts
```

Do not redesign the page structure merely because the backend has changed.

### Live Monitoring

Integrate:

- existing map
- existing incident cards
- existing filters
- existing summary cards
- existing dossier/detail experience
- `RUN FIREX ANALYSIS`
- analysis progress
- SSE live updates
- last updated timestamp

### Industry Intelligence

Add the new industry/facility workflow **inside the same visual system**:

```text
search facility
→ facility context
→ thermal activity
→ historical baseline / P95
→ persistence
→ incidents
→ trends
```

### V1 reference checkpoint

Before changing any visual component, inspect the v1 implementation and modify the smallest possible layer needed to connect the new API.

### Done when

A judge can use the existing FIREX UI to:

```text
run analysis
view incidents
inspect evidence
see severity
see historical behavior
search industries/facilities
```

without feeling that the application has been replaced with a different product.

---

## Stage 10 — Hardening, Testing, Performance

### Goal

Make the system reliable enough for deployment and SIH demonstration.

### Add

- authentication if needed
- rate limits
- retries
- timeouts
- structured logs
- database indexes
- configuration validation
- cache
- background workers
- health checks
- error boundaries
- provider/API failure handling
- regression tests

### Test sequence

```text
unit tests
→ integration tests
→ end-to-end test
→ real FIRMS run
→ UI/SSE verification
→ failure injection
```

### V1 regression checkpoint

Re-run the v1 reference workflow and verify that the new architecture has not broken the working UI or useful integrations being intentionally preserved.

### Done when

The application survives external API/model failures without taking down the whole analysis pipeline.

---

## Stage Completion Rule

A stage is complete only when:

```text
BUILD
 ↓
TEST
 ↓
COMPARE WITH V1 WHERE RELEVANT
 ↓
FIX
 ↓
FREEZE INTERFACE
 ↓
NEXT STAGE
```

### Mandatory human verification gate

Immediately after **FIX** and before **FREEZE INTERFACE**, Saurabh must manually run the stage in the real application and record the result.

```text
BUILD
 ↓
AUTOMATED TESTS
 ↓
REAL RUN
 ↓
MANUAL CHECK BY SAURABH
 ↓
V1 COMPARISON (when relevant)
 ↓
PASS? ── NO → FIX CURRENT STAGE → TEST AGAIN
   │
  YES
   ↓
FREEZE INTERFACE
 ↓
NEXT STAGE
```

### Manual verification record

Every stage must leave behind a simple verification record, for example:

```text
Stage: 3 — Clustering + Incident Lifecycle
Automated tests: PASS
Real run: PASS
Manual verification: PASS
V1 comparison: PASS
Verified by: Saurabh
Notes: 3 nearby same-time observations formed one cluster; time-separated and distant observations remained separate. No FRP values were summed into a fake total.
```

The coding agent must **never self-approve a stage**. It may report that implementation and automated tests pass, but the stage remains pending until Saurabh performs the manual check.

Do not allow a coding agent to implement multiple unfinished stages at once.

---

## Recommended Stage Dependencies

```text
STAGE 0
V1 audit + foundation
        ↓
STAGE 1
Data + FIRMS
        ↓
STAGE 2
GIS + industry context
        ↓
STAGE 3
Clustering + incidents
        ↓
STAGE 4
Behavior intelligence
        ↓
STAGE 5
Selection + visual context
        ↓
STAGE 6
AI investigation
        ↓
STAGE 7
Severity + alerts
        ↓
STAGE 8
Orchestration + SSE
        ↓
STAGE 9
EXISTING UI integration + Industry Intelligence
        ↓
STAGE 10
Hardening + final testing
```

This order intentionally delays expensive AI work until the evidence pipeline is reliable and makes the UI integration a controlled final integration step rather than a frontend rewrite.

---

# 36. Vibe-Coding Prompt Template

Use this structure every time you ask a coding agent to implement a section.

```text
You are implementing SECTION X of FIREX-SIH2026.

PROJECT CONTEXT:
FIREX is an AI-enabled geospatial industrial thermal anomaly
monitoring system.

CORE RULES:
- FIRMS observation is not confirmed fire.
- Observation != incident.
- Selection != severity.
- FIRMS confidence != AI confidence.
- Severity != severity confidence.
- Store all valid observations.
- Avoid duplicate logic.
- Do not invent data.
- Keep business logic in backend services.
- Keep thresholds/weights configurable.
- Do not expose API keys to frontend.

CURRENT ARCHITECTURE:
[Paste the relevant architecture section.]

THIS SECTION'S GOAL:
[One clear goal.]

INPUTS:
[List exact inputs.]

OUTPUTS:
[List exact outputs.]

FILES TO CREATE/MODIFY:
[List explicit files.]

DATABASE TABLES:
[List affected tables.]

API CONTRACT:
[List endpoint + request + response.]

IMPLEMENTATION RULES:
[Specific rules.]

TEST CASES:
[Specific test cases.]

DEFINITION OF DONE:
[Exact observable completion criteria.]

IMPORTANT:
Do not implement future sections.
Do not refactor unrelated modules.
Do not replace real integrations with fake data unless
explicitly instructed.
Return changed files and explain how to run the tests.
```

---

# 37. Vibe-Coding Rules

## Rule A — Build one section at a time

Do not combine:

```text
FIRMS + GIS + AI + frontend
```

in one prompt.

## Rule B — Always give the coding agent the architecture

AI coding agents otherwise invent different interpretations.

## Rule C — Require tests

Every backend module must have at least:

- happy-path test
- edge case
- invalid input test where appropriate

## Rule D — Use real data only after fixtures work

Recommended:

```text
Synthetic fixture
    ↓
Unit tests
    ↓
Recorded sample data
    ↓
Real API
```

## Rule E — Do not let agents change formulas casually

Selection and severity weights are part of the project design.

Any formula change should be explicit.

## Rule F — Keep integrations behind interfaces

Example:

```python
class ImageryProvider:
    def fetch(self, request):
        ...
```

Then you can switch image providers without rewriting the incident pipeline.

Same concept for:

- FIRMS
- AI
- industrial data
- land cover

---

# 38. Golden Regression Dataset

Create a small fixed, version-controlled test dataset used by every backend revision. It must contain enough cases to catch regressions in clustering, incident association, history, selection, AI handling, and severity.

Minimum cases:

```text
CASE A — isolated thermal observation
CASE B — 3 nearby observations at nearly the same time → one cluster
CASE C — distant observations → separate clusters
CASE D — same location but clearly separated in time → separate clusters unless association rules intentionally link them
CASE E — adjacent independent industrial sources → must not blindly merge
CASE F — persistent low-FRP source → persistence retained
CASE G — high-FRP new incident with no history → not penalized for missing history
CASE H — current FRP above historical P95 → abnormality detected
CASE I — uncertain/cloud-obscured visual case → AI may return uncertain
CASE J — AI provider/model failure → pipeline handles failure safely
```

For clustering cases, assert that individual FRPs remain preserved and **no FRP summation is used as incident intensity**.

The golden dataset should be usable for:

```text
unit tests
integration tests
regression tests
manual verification
final end-to-end demonstration
```

Changes to expected outputs must be intentional and documented.

---

# 39. Final End-to-End Acceptance Test

Before SIH demonstration, run one complete realistic scenario through the actual backend and existing UI.

```text
FIRMS
  ↓
validation / normalization
  ↓
GIS enrichment
  ↓
clustering
  ↓
incident association
  ↓
behavior / history
  ↓
selection
  ↓
visual context
  ↓
configured AI model
  ↓
severity
  ↓
alert evaluation
  ↓
database update
  ↓
SSE / UI
```

The manual acceptance check must verify at least:

```text
[ ] raw observations are stored
[ ] cluster membership is sensible
[ ] no FRPs were incorrectly summed
[ ] incident identity is stable across a second run
[ ] history is linked to the correct location/facility
[ ] selection rationale is visible
[ ] visual context is centered correctly
[ ] AI classification/evidence/uncertainty are stored
[ ] configured model/provider is recorded
[ ] severity and severity confidence are separate
[ ] alerts are not duplicated
[ ] existing UI still looks/behaves like v1
[ ] SSE progress completes successfully
```

This acceptance run is a human sign-off point. Automated tests passing does not replace the manual check.

---

# 40. Testing Strategy

## Unit tests

Test individually:

- FIRMS parsing
- normalization
- deduplication
- clustering
- persistence
- baseline
- P95
- selection
- severity
- escalation
- incident association

## Integration tests

Test:

```text
FIRMS fixture
→ DB
→ GIS
→ cluster
→ incident
→ selection
```

Then:

```text
selected incident
→ imagery fixture
→ AI fixture
→ severity
```

## End-to-end test

```text
POST /analysis/run
```

Expected:

```text
observations created
incidents created/updated
selected incidents processed
AI result stored
severity stored
alerts evaluated
analysis completed
```

---

# 41. Common Failure Modes to Avoid

## Failure 1 — Treating every FIRMS point as a fire

Fix:

```text
observation → cluster → incident
```

## Failure 2 — Dropping low-FRP observations

Fix:

Store everything. Selection is selective; storage is not.

## Failure 3 — Ignoring persistent low-FRP sources

Fix:

Persistence is a major selection factor and trigger.

## Failure 4 — Persistence automatically increasing severity

Fix:

Persistence describes behavior. Severity describes seriousness.

## Failure 5 — Missing history = zero

Fix:

Use N/A and switch to new-event model.

## Failure 6 — AI sees image and hallucinates certainty

Fix:

Image-quality layer + strict evidence/uncertainty schema.

## Failure 7 — Industrial database miss means non-industrial

Fix:

Use:

```text
CONFIRMED
POSSIBLE
NOT_IDENTIFIED
```

## Failure 8 — Re-running AI for everything

Fix:

Only investigate selected/new/changed incidents.

## Failure 9 — Duplicated history logic

Fix:

Single Behavior Intelligence Engine.

## Failure 10 — Duplicate "risk" scores

Fix:

Keep:

```text
Investigation Priority
Incident Severity
Severity Confidence
Historical Anomaly
```

as separate concepts.

## Failure 11 — Claiming 24/7 satellite imaging

Fix:

Use:

> Continuous automated monitoring of incoming satellite thermal observations.

## Failure 12 — Frontend contains secrets

Fix:

All API keys stay server-side.

---

# 42. Performance Strategy

Start simple.

## First version

```text
FastAPI
PostgreSQL/PostGIS
background worker
SSE
Redis optional
```

## Optimization priorities

1. Database indexing
2. Deduplication
3. Incremental processing
4. Image caching
5. AI only for selected incidents
6. Async API clients
7. Background tasks

Do not prematurely introduce a large distributed architecture.

---

# 43. Recommended Spatial Indexes

At minimum index:

```text
observations.geom
observations.acquired_at
incidents.center_geom
incidents.last_detected_at
industrial_assets.geom
```

Composite/time indexes should be added where query patterns justify them.

---

# 44. Security

Never commit:

```text
NASA/API keys
AI keys
database passwords
```

Use:

```text
.env
.env.example
```

Backend only.

Frontend should call FIREX APIs, not external AI providers directly.

---

# 45. Observability

Every analysis run should have:

```text
run_id
started_at
completed_at
status
observations_fetched
observations_new
clusters_created
incidents_created
incidents_updated
incidents_selected
images_fetched
ai_success
ai_failed
alerts_created
```

This makes debugging and SIH demos easier.

---

# 46. Final Product UX

FIREX should have at least two primary modes.

# MODE 1 — LIVE MONITORING

Purpose:

> What is happening now?

Includes:

- current FIRMS anomalies
- current incidents
- selection
- satellite images
- AI classification
- severity
- alerts
- live refresh button
- auto monitoring
- map

# MODE 2 — INDUSTRY INTELLIGENCE

Purpose:

> What has happened at this facility over time?

Includes:

- industry search
- facility profile
- historical FIRMS
- persistent sources
- baseline
- P95
- trends
- historical incidents
- current-vs-normal comparison

---

# 47. Final Conceptual Architecture

```text
                    ┌───────────────────┐
                    │     NASA FIRMS    │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ DATA FOUNDATION   │
                    │ Ingestion + GIS   │
                    │ PostgreSQL/PostGIS│
                    └─────────┬─────────┘
                              │
                ┌─────────────┴─────────────┐
                │                           │
                ▼                           ▼
      BEHAVIOR INTELLIGENCE          LIVE INCIDENT PIPELINE
                │                           │
         Persistence                 Clustering
         Baseline                    Association
         P95                         Selection
         Trends                      Imagery
         Anomaly                     AI
                │                     Severity
                │                     Alerts
                │                           │
                └──────────────┬────────────┘
                               │
                               ▼
                        FIREX DASHBOARD
                         /             \
                        /               \
                       ▼                 ▼
               LIVE MONITORING    INDUSTRY INTELLIGENCE
```

---

# 48. Final Development Order

Build exactly in this order:

```text
01. Project skeleton
02. Database + PostGIS
03. FIRMS ingestion
04. GIS enrichment
05. Industrial assets
06. Clustering
07. Incident association
08. Behavior Intelligence
09. Selection Engine
10. Imagery
11. AI Investigation
12. Severity Engine
13. Alert Engine
14. End-to-end orchestrator
15. SSE / live events
16. Live Monitoring UI edits / backend integration
17. Industry Intelligence UI
18. Testing
19. Hardening + deployment
```

Do not start by building the complete dashboard.

The backend intelligence must become stable first.

---

# 49. Definition of Done for the Full Project

FIREX is ready for SIH demonstration when all of these work:

## Detection

- [ ] Real FIRMS data can be ingested
- [ ] Raw observations are stored
- [ ] Duplicates are controlled

## GIS

- [ ] Land-cover context works
- [ ] Industrial asset matching works
- [ ] Protected/environmental context works
- [ ] Map overlays work

## Incident creation

- [ ] FIRMS observations cluster into incidents
- [ ] Existing incidents can be updated
- [ ] New incidents can be created

## Selection

- [ ] High-FRP incidents are selected
- [ ] Persistent low-FRP incidents can be selected
- [ ] New incidents are not penalized for missing history
- [ ] Extreme FRP override exists
- [ ] Weights are configurable

## AI

- [ ] AI receives image + FIRMS + GIS context
- [ ] AI produces strict JSON
- [ ] AI outputs evidence
- [ ] AI outputs alternatives
- [ ] AI reports uncertainty
- [ ] Uncertain events are allowed

## Severity

- [ ] Known-hotspot and new-hotspot models exist
- [ ] Escalation rules exist
- [ ] Severity confidence exists
- [ ] Severity is separate from selection

## Monitoring

- [ ] Persistent sources are tracked
- [ ] Historical baseline is available
- [ ] P95 is available
- [ ] Historical anomaly works
- [ ] Incident state updates

## Dashboard

- [ ] Live map works
- [ ] Run Analysis button works
- [ ] Progress events work
- [ ] Incident details work
- [ ] Alerts appear
- [ ] Industry search works
- [ ] Historical facility analysis works

## Reliability

- [ ] Errors are handled
- [ ] API keys are secret
- [ ] Tests exist
- [ ] Demo fixtures exist
- [ ] System works even when an external provider fails

---

# 50. SIH Demonstration Story

The ideal 3–5 minute demo:

### Step 1

Open **Live Monitoring**.

Show current thermal anomalies on the map.

### Step 2

Click:

> **RUN FIREX ANALYSIS**

Show live progress.

### Step 3

Show an incident that has:

```text
FIRMS anomaly
+
industrial context
+
satellite image
```

### Step 4

Run AI investigation.

Show:

```text
Industrial Fire — 91%
Alternative: Gas Flare — 6%
Evidence: ...
Uncertainty: ...
```

### Step 5

Show severity:

```text
Severity: CRITICAL
Score: 87
Confidence: 82
```

Explain why.

### Step 6

Open historical information.

Show:

```text
Median = 21.5 MW
P95 = 31.2 MW
Current = 94.2 MW
```

and:

> Abnormally high relative to historical behavior.

### Step 7

Show a low-FRP persistent source.

Explain:

> It was still selected because persistence indicates repeated thermal activity.

### Step 8

Open **Industry Intelligence**.

Search a refinery.

Show:

- previous FIRMS activity
- persistent patterns
- baseline
- P95
- historical incidents
- current anomaly

### Step 9

Finish with:

> FIREX does not simply display satellite hotspots. It converts raw thermal anomalies into explainable, monitored industrial incidents.

---

# 51. Suggested Final Pitch

> **FIREX is an AI-enabled geospatial thermal intelligence platform designed to bridge the gap between satellite anomaly detection and actionable industrial incident understanding.**
>
> NASA FIRMS provides the initial thermal evidence. FIREX enriches that evidence with land cover and industrial infrastructure, groups observations into incidents, selects important incidents using current intensity and behavioral evidence, investigates selected incidents using current satellite imagery and multimodal AI, assesses incident severity, tracks persistence and historical abnormalities, and continuously presents the results through a GIS dashboard.
>
> The platform has two complementary workflows:
>
> **Live Monitoring** for current incidents and alerts, and
>
> **Industry Intelligence** for facility-level historical analysis and persistent thermal behavior.
>
> This turns a raw thermal hotspot feed into an explainable, continuously monitored industrial intelligence system.

---

# 52. Immediate Build Checklist

Start with only these first five milestones:

```text
MILESTONE 1
Backend starts
Database works
Frontend starts

MILESTONE 2
Real FIRMS data → database

MILESTONE 3
FIRMS → GIS enrichment → clusters → incidents

MILESTONE 4
Behavior Intelligence → Selection

MILESTONE 5
Selected incident → image → AI → severity
```

After milestone 5 works reliably, build:

```text
Alerts
SSE
Live Monitoring UI
Industry Intelligence UI
Hardening
```

This sequencing minimizes rework and makes the project highly compatible with AI-assisted / vibe-coded development.


---

# 53. Final Team Decision — What Is In Scope

The first SIH-focused FIREX release should prioritize the following:

### Core PS classes

```text
Petrochemical / refinery-related industrial fire
Industrial fire
Gas flare
Thermal-power / steel / industrial context
Mining-related activity
Wildfire / forest fire
Agricultural burning
Uncertain
```

### Core visual approach

```text
FIRMS thermal anomaly
        +
Google Maps / high-resolution map-satellite context
        +
GIS industrial/land-cover context
        +
Multimodal AI
```

The imagery layer is **visual verification/context**, not a claim of live satellite capture.

### Core pages

```text
1. Live Monitoring
2. Industry Intelligence
3. Incident Detail / Dossier
```

### Core rewrite boundary

```text
KEEP:
- Existing UI look & feel
- Existing map interaction
- Existing useful FIRMS integration
- Existing Google-map/tile visual workflow
- Existing MiniMax/OpenRouter capability

REBUILD:
- Backend architecture
- Data model
- Incident model
- Selection engine
- NEW Behavior Intelligence / Historical pipeline
- Severity engine
- API layer
- Incremental refresh
- Industry Intelligence backend
```

This keeps the team's working visual investment while replacing the backend with the cleaner incident-centric architecture defined in this document.
