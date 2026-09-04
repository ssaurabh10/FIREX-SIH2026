# SIH 2026 — PS 162 Project Master Brief & Operational Blueprint

## AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, Multi-Sensor Satellite Imagery & Geospatial Intelligence

> **Document Status:** Active Master Specification & Current Reality Audit  
> **Last Updated:** September 2026  
> **Target Competition:** Smart India Hackathon (SIH) 2026  
> **Problem Statement ID:** SIH26162 (PS 162)  
> **Nodal Ministry / Organization:** National Technical Research Organisation (NTRO)  
> **System Name:** **FIREX** — Fire Intelligence & Real-time EXploration

---

## 1. Executive Summary & Problem Context

### 1.1 The Official Problem Statement
* **Category:** Software
* **Theme:** Space & Defense Technology / Homeland Security
* **Organization:** National Technical Research Organisation (NTRO)
* **Official Statement:** Industrial facilities generate significant thermal signatures visible from space. Existing satellite fire-monitoring systems, such as NASA FIRMS, detect thermal anomalies but cannot reliably differentiate between:
  1. Uncontrolled industrial and structural fires
  2. Routine operational gas flaring
  3. Agricultural stubble burning
  4. Open-cast coal mine fires & overburden heat anomalies
  5. Forest canopy wildfires
  6. Other persistent thermal emitters (smelters, steel plants, power plants)

The mandate is to build an **AI-enabled geospatial system** that fuses:
1. Real-time satellite thermal anomaly detections,
2. High-resolution optical satellite imagery,
3. Industrial infrastructure proximity databases (GIS layers & verified sovereign facility registries),
4. Multimodal Vision AI reasoning, and
5. Time-series persistence tracking,

to detect, segregate, classify, score, and monitor industrial fires and persistent thermal sources on interactive GIS consoles.

### 1.2 Core Scientific Tenet
```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      THE SCIENTIFIC GOLDEN RULE                         │
│                                                                         │
│   NASA FIRMS detects THERMAL ANOMALIES (infrared radiance),            │
│   NOT confirmed "industrial fires".                                     │
│                                                                         │
│   FIREX performs the multi-sensor forensic investigation:               │
│   "Given this thermal spike, optical ground features, and spatial       │
│   proximity, what is this emitter, how severe is it, and why?"          │
└─────────────────────────────────────────────────────────────────────────┘
```
A high Fire Radiative Power (FRP) detection inside a refinery is typically a **routine gas flare**, not an emergency. A moderate FRP detection in a chemical storage yard is a **critical disaster**. Treating all thermal dots identically produces massive false-alarm fatigue. FIREX resolves this by generating evidence-backed forensic dossiers.

---

## 2. End-to-End System Architecture

```text
               NASA FIRMS SATELLITE CONSTELLATION
       (VIIRS NOAA-20/21 [375m] · VIIRS Suomi-NPP · MODIS [1km])
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 1: FIRMS Ingestion & Sovereign Indian Airspace Filter │
  │  pipeline/01_firms · Discards foreign/cross-border telemetry │
  │  Retains verified domestic Indian thermal coordinates       │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 2: Time-Series Persistence & Diurnal Profiles (DB)   │
  │  pipeline/07_persistence · SQLite historical archive         │
  │  Tracks 12h overpass cadence (Day vs Night 24h continuity)  │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 3: Physical Spatial Clustering & Threat Qualification│
  │  Aggregates adjacent pixels (≤25km) into fire clusters      │
  │  Strict operational qualification (Infrastructure, Canopy,  │
  │  Surge); filters out minor 3-5 MW agricultural noise        │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 4: High-Res Optical Tile Synthesis & Thermal Reticle │
  │  pipeline/03_imagery · Zoom-16 optical scenes (640x640)     │
  │  Calibrated targeting crosshairs with 0 coordinate mismatch  │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 5: Section 10 Multi-Factor Threat Risk Engine        │
  │  pipeline/06_risk_engine · Deterministic 0-100 scoring      │
  │  Vision certainty, FRP, confidence, proximity, hazard level │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  dashboard: Unified Tactical Command Center (Port 8000)     │
  │  Real-time SSE Sync Modal · Interactive GIS Map · Dossiers   │
  └─────────────────────────────────────────────────────────────┘
```

---

## 3. Current Implementation Status & Operational Reality

| Pipeline Stage | Core Responsibility | Current State | Key Artifacts & Technologies |
| :--- | :--- | :--- | :--- |
| **01_firms** | Query NASA FIRMS API across Indian airspace; filter to sovereign boundaries. | **100% Operational** | [`pipeline/01_firms/firms_fetch.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/01_firms/firms_fetch.py), raw CSV archives in `raw_responses/` |
| **02_selection** | Ground truth registries: critical refineries, steel mills, power plants, coalfields. | **100% Operational** | [`dashboard/prepare_map_data.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/dashboard/prepare_map_data.py) verified sovereign registry |
| **03_imagery** | High-res optical tile stitcher (Zoom 16, ~1.2 km FOV), thermal targeting reticles. | **100% Operational** | [`pipeline/03_imagery/fetch_satellite_crops.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/03_imagery/fetch_satellite_crops.py), session tile caching |
| **04_vision_ai** | MiniMax M3 Vision AI pool via OpenRouter with reasoning and key load balancing. | **100% Operational** | [`pipeline/04_vision_ai/vision_classifier.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/04_vision_ai/vision_classifier.py), 4-key rotation pool |
| **05_orchestrator** | Headless automated pipeline runner: telemetry → crops → AI → incident dossiers. | **100% Operational** | [`pipeline/05_orchestrator/run_pipeline.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/05_orchestrator/run_pipeline.py) |
| **06_risk_engine** | Section 10 multi-factor threat scoring engine (0–100 auditable composite score). | **100% Operational** | [`pipeline/06_risk_engine/risk_scorer.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/06_risk_engine/risk_scorer.py) |
| **07_persistence** | SQLite time-series database tracking 12-hour cadence, day/night persistence. | **100% Operational** | [`pipeline/07_persistence/history_db.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/07_persistence/history_db.py), `firex_history.db` |
| **dashboard** | Unified Tactical Command Center (Port 8000) with 5-stage real-time streaming HUD. | **100% Operational** | [`dashboard/server.py`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/dashboard/server.py), [`index.html`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/dashboard/index.html), [`main.js`](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/dashboard/js/main.js) |

---

## 4. Operational Innovations

### 4.1 Physical Spatial Cluster Aggregation ($\le 25\text{ km}$)
In spaceborne thermal sensors (VIIRS 375m and MODIS 1km), a single physical fire or industrial complex routinely triggers 5 to 80 separate sensor pixels. Instead of treating these as disconnected events:
- Pixels are clustered within physical geographic boundaries.
- Metrics are aggregated: **Cluster Total FRP**, **Peak Pixel FRP**, **Pixel Count**, and **Centroid Coordinates**.
- *Example:* The Sijua/Jharia coalfield fire previously generated 83 disconnected dots; FIREX unifies them into **1 strategic incident cluster** with **238.3 MW aggregated radiative power**.

### 4.2 Threat Qualification Engine (No Arbitrary Caps)
Arbitrary cutoffs (e.g. "Top 20") are unscientific. FIREX evaluates every cluster against tactical intelligence triggers:
1. **`CRITICAL_INFRASTRUCTURE`**: Within 35 km of registered strategic assets (refineries, petrochemical hubs, steel complexes, power plants, active mines).
2. **`MONTANE_FOREST_CANOPY`**: Active canopy wildfires in dense forest reserves or border sectors ($\ge 7.0\text{ MW}$).
3. **`MAJOR_FIRE_SURGE`**: Severe expanding fire fronts ($\ge 12.0\text{ MW}$ peak or $\ge 25.0\text{ MW}$ cluster total across $\ge 3$ pixels).
4. **`24H_TEMPORAL_PERSISTENCE`**: Verified continuous day-and-night industrial combustion.

Routine, low-intensity (3–5 MW) agricultural burns remain as **ambient dots on the map**, but do not clutter the operator's response queue.

### 4.3 Interactive 5-Stage Mission Pipeline Streaming HUD
When an operator clicks **"Sync Pass"**:
- An SSE connection streams live execution across stages 1 through 5 (`/api/trigger-sync-stream`).
- Real-time progress bar (0% $\rightarrow$ 100%), pulsing stage badges, and an auto-scrolling monospace telemetry terminal inform the operator of raw counts, filtered noise, cluster formations, and risk rankings.
- Upon completion, the console auto-refreshes the map layers, priority feed, and persistence widget seamlessly.

---

## 5. Verification Runbook

```bash
# 1. Start Primary Tactical GIS Command Center (Default: http://localhost:8000)
python run.py serve

# 2. Run Headless Pipeline End-to-End
python run.py pipeline

# 3. Synchronize Satellite Pass Data & Update SQLite DB
python run.py data
```

---

## 6. Summary for SIH Evaluators & Judges

> **"FIREX solves the fundamental problem of false-alarm fatigue in satellite earth observation. By orchestrating sovereign airspace telemetry, physical cluster aggregation, high-resolution optical imagery, verified strategic infrastructure registries, and deterministic multi-factor risk scoring, FIREX empowers defense, environmental, and disaster management agencies to distinguish routine operations from genuine catastrophic emergencies in real time."**
