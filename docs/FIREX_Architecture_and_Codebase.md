# FIREX — Architecture & Codebase Overview

## 1. Executive Summary

**FIREX** (Satellite Thermal Intelligence & Tactical Incident Command) is a space-borne satellite AI platform designed for the Smart India Hackathon (SIH) 2026 under Problem Statement 162. 

The primary goal of FIREX is to ingest live thermal anomaly vectors from NASA FIRMS, perform physical spatial clustering to group scattered thermal hits, and evaluate them through a multi-factor threat engine. This pipeline autonomously triages critical infrastructure threats and forest fires while ignoring low-intensity background noise (e.g., routine agricultural burns), delivering an actionable, high-fidelity tactical GIS command center for responders.

## 2. Directory & Repository Structure

The project employs a modular directory structure separating the frontend command dashboard, the multi-stage backend pipeline, and utility scripts.

```text
PS162/
├── run.py                     # Unified CLI launcher for all sub-services
├── requirements.txt           # Python dependencies
├── dashboard/                 # Tactical GIS Command Center
│   ├── index.html             # The primary frontend interface
│   ├── server.py              # Local HTTP server (port 8000) providing hot-reload and data fetching API
│   ├── prepare_map_data.py    # Generates frontend-ready `incidents.json` from the pipeline data
│   ├── js/                    # JavaScript logic (map rendering, SSE updates, dossiers)
│   ├── styles/                # CSS styling (dark mode, layout, GIS components)
│   └── data/                  # Stores compiled spatial cluster JSON files
├── pipeline/                  # Modular 7-Stage End-to-End Processing Engine
│   ├── 01_firms/              # NASA FIRMS data ingestion and parsing
│   ├── 02_selection/          # Sovereign airspace filtering and region selections
│   ├── 03_imagery/            # High-res optical imagery stitching and reticle annotation
│   │   └── crops/             # Synthesized Zoom-16 optical crops (640x640)
│   ├── 04_vision_ai/          # MiniMax M3 Vision AI prompts for visual smoke/fire verification
│   ├── 05_orchestrator/       # Master orchestrator (`run_pipeline.py`) running stages 1 through 7
│   ├── 06_risk_engine/        # Section 10 multi-factor composite risk scoring (0-100)
│   └── 07_persistence/        # SQLite time-series DB for 24-hour Day/Night continuity tracking
├── archive/                   # Older legacy prototypes (Port 8002)
└── docs/                      # Technical briefs and documentation (where this file resides)
```

## 3. The 7-Stage Intelligence Pipeline

The backend data processing is split logically into stages under the `pipeline/` directory. When triggered (either manually or via the daemon), the pipeline processes live telemetry through these sequential steps:

1. **Stage 1 (FIRMS Ingestion):** Fetches active fire data (VIIRS, MODIS) from NASA API.
2. **Stage 2 (Geographic Selection):** Filters out non-sovereign/cross-border thermal noise.
3. **Stage 3 (Spatial Triage & Imagery):** Aggregates pixels within a $\le 25\text{ km}$ radius into distinct physical events and synthesizes optical map tiles (Zoom 16).
4. **Stage 4 (Vision AI):** Sends the synthesized optical crops to a vision model (MiniMax M3) to confirm the visual presence of a fire/smoke plume.
5. **Stage 5 (Orchestration):** The overarching glue that triggers these stages sequentially.
6. **Stage 6 (Risk Engine):** Computes a 0–100 risk score based on Fire Radiative Power (FRP), vision confidence, proximity to critical infrastructure, and persistence.
7. **Stage 7 (Persistence):** Logs incidents into an SQLite database (`firex_history.db`) to identify multi-day burns vs. transient fires.

## 4. Unified CLI Application (`run.py`)

`run.py` is the central command-line interface for operating FIREX. It abstracts the execution of the dashboard, data pipelines, and daemons.

**Available Commands:**
- `python run.py serve` — Starts the primary GIS Dashboard server on Port 8000. It mounts the main UI and serves `/crops/` for high-res map imagery. Includes an optional `--open` flag to launch the browser immediately.
- `python run.py daemon` — Runs an automated ingestion daemon that fetches data on a 12-hour cadence (simulating day/night satellite passes).
- `python run.py pipeline` — Manually triggers the End-to-End Vision AI pipeline (Stage 5 Orchestrator).
- `python run.py data` — Manually triggers `prepare_map_data.py` to refresh, score, and compile the GIS incidents dataset.
- `python run.py legacy` — Boots the older, legacy UI on Port 8002.

## 5. Dashboard Capabilities (`dashboard/`)

Served via `dashboard/server.py` and accessed at `http://localhost:8000/`.

### Server APIs:
- `/api/trigger-sync-stream`: Initiates the pipeline through Server-Sent Events (SSE) streaming, pushing progress updates directly to the frontend's Sync HUD.
- `/api/history-stats`: Returns database persistence stats, showing current cadence (Day vs Night pass) and historical ingest totals.
- `/crops/*`: A specialized route that securely serves imagery from the `pipeline/03_imagery/crops/` directory directly into the dashboard dossier modals.

### Frontend Flow:
- **Interactive Map:** Driven by Leaflet.js, plots pulsing classification markers (Wildfire, Industrial, Gas Flare).
- **Incident Dossiers:** Clicking a marker opens a tactical modal displaying the generated optical satellite view, AI classification, risk factors, and FRP stats.
- **5-Stage Sync HUD:** Operators can click "Sync Pass" to watch the backend pipeline ingest and process data in real-time, displaying a progress bar until completion.

## 6. Threat Qualification & Scoring

The **Multi-Factor Threat Engine (Section 10)** ensures that not all thermal spikes are treated equally. A routine 5 MW farm burn is kept visually ambient, while a 250 MW anomaly near an oil refinery is escalated. 

Factors computed:
1. **Fire Radiative Power (FRP):** Aggregated power output.
2. **Vision Certainty:** AI optical confirmation.
3. **Infrastructure Proximity:** Distance to vital assets (forests, facilities).
4. **Temporal Persistence:** Is this a continuous 24-hour burn (suggesting an industrial process or underground coal fire)?

By fusing these factors, FIREX minimizes false-alarm fatigue and maximizes operational efficiency for tactical command units.
