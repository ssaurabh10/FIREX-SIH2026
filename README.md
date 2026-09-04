<p align="center">
  <img src="ce4e4a004f53657e4979565e8240e096.png" alt="FIREX Logo" width="120">
</p>

<h1 align="center">FIREX — Satellite Thermal Intelligence & Tactical Incident Command</h1>

<p align="center">
  <strong>Smart India Hackathon 2026 · Problem Statement 162 (NTRO Mandate)</strong><br>
  Autonomous satellite thermal anomaly detection, physical spatial cluster triage, sovereign airspace filtering, high-resolution optical verification, and multi-factor threat risk prioritization for India.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NASA-FIRMS-orange?style=for-the-badge&logo=nasa" alt="NASA FIRMS">
  <img src="https://img.shields.io/badge/AI-MiniMax_M3-blue?style=for-the-badge" alt="MiniMax M3">
  <img src="https://img.shields.io/badge/GIS-Leaflet.js-green?style=for-the-badge&logo=leaflet" alt="Leaflet">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Architecture-Spatial_Clustering_Engine-purple?style=for-the-badge" alt="Spatial Clustering">
</p>

---

## 📋 Mission Overview & Scientific Foundation

**FIREX** addresses the core operational gap in national thermal hazard and defense surveillance: **NASA FIRMS detects thermal radiance anomalies (infrared heat spikes), NOT confirmed fires.** Emergency responders, forest departments, and defense analysts routinely face severe false-alarm fatigue from operational refinery flare stacks, metallurgical blast furnaces, slag pits, and small routine agricultural burns.

FIREX provides a fully automated, defense-grade intelligence loop:
1. **Real-Time Sovereign Telemetry Ingestion:** Ingests live thermal anomaly vectors from NASA FIRMS (VIIRS NOAA-20, Suomi-NPP, MODIS Aqua/Terra) and enforces strict sovereign Indian geographical bounds, discarding foreign/cross-border telemetry noise.
2. **Physical Spatial Cluster Triage:** Aggregates multi-pixel satellite hits within a physical radius ($\le 25\text{ km}$) into unified physical fire incident clusters, computing aggregated radiative output (Total FRP), peak pixel intensity, and pixel count.
3. **Operational Threat Qualification (No Arbitrary Caps):** Replaces arbitrary "Top N" cutoffs with tactical threat qualification criteria (`CRITICAL_INFRASTRUCTURE`, `MONTANE_FOREST_CANOPY`, `MAJOR_FIRE_SURGE`, `24H_TEMPORAL_PERSISTENCE`). Routine, low-intensity (3–5 MW) agricultural burns remain as ambient dots on the map without cluttering the priority command feed.
4. **Time-Series Persistence & Diurnal Profiles:** Ingests into an SQLite time-series database (`pipeline/07_persistence/firex_history.db`) to distinguish 24-hour continuous combustion (refineries, underground coal seam fires) from transient diurnal burns.
5. **High-Res Optical Satellite Tile Synthesis:** Dynamically fetches Zoom-16 optical satellite imagery (~1.2 km tactical radius) and draws calibrated thermal reticles with zero coordinate mismatches.
6. **Section 10 Multi-Factor Threat Engine:** Computes deterministic, auditable 0–100 composite risk scores across 5 balanced vectors (Vision certainty, Fire Radiative Power, Satellite confidence, Infrastructure proximity, Hazard multiplier).
7. **Interactive 5-Stage Mission Pipeline Streaming HUD:** Operators clicking **"Sync Pass"** observe a real-time Server-Sent Events (SSE) progress HUD streaming every pipeline stage with live telemetry logs, auto-deploying the fresh dossiers to the feed upon completion.

---

## 🏗️ Architecture & Intelligence Flow

```text
               NASA FIRMS SATELLITE CONSTELLATION
       (VIIRS NOAA-20/21 [375m] · VIIRS Suomi-NPP · MODIS [1km])
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 1: FIRMS Ingestion & Sovereign Indian Airspace Filter │
  │  Discards cross-border noise · Retains sovereign hotspots   │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 2: Time-Series Persistence & Diurnal Profiles (DB)   │
  │  SQLite time-series archive · 24h Day+Night continuity      │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 3: Spatial Cluster Triage & Threat Qualification     │
  │  Clusters pixels (≤25km) · Qualifies infrastructure/forests  │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 4: High-Res Optical Tile Synthesis & Thermal Reticle │
  │  Zoom-16 optical crops (640x640) with calibrated reticles   │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  Stage 5: Section 10 Multi-Factor Threat Risk Engine        │
  │  Deterministic 5-factor scoring (0-100) & Priority Dossiers │
  └────────────────────────────┬────────────────────────────────┘
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  dashboard: Unified Tactical Command Center (Port 8000)     │
  │  Real-time SSE Sync Modal · Interactive GIS Map · Dossiers   │
  └─────────────────────────────────────────────────────────────┘
```

---

## 📂 Repository Layout

```
PS162/
├── run.py                     # Unified CLI launcher for server, pipeline, and data sync
├── requirements.txt           # Consolidated Python project dependencies
├── .gitignore                 # Protected keys and runtime cache exclusions
│
├── dashboard/                 # Primary Tactical GIS Command Center (Port 8000)
│   ├── index.html             # Command platform with Spotlight Navbar, 5-Stage Sync Modal
│   ├── styles/                # Modular CSS design system (tokens, map, surfaces, components)
│   ├── js/                    # ES modules (main, map, dossier, render, data, config)
│   ├── server.py              # Server with /api/trigger-sync-stream and /api/history-stats
│   ├── prepare_map_data.py    # Spatial cluster aggregation & operational threat qualification
│   └── data/                  # Live incidents.json & ambient nationwide FIRMS cache
│
├── pipeline/                  # Modular End-to-End Processing Stages
│   ├── 01_firms/              # Stage 1: NASA FIRMS real-time API fetcher & raw CSV archives
│   ├── 02_selection/          # Stage 2: Geographic reference registries
│   ├── 03_imagery/            # Stage 3: High-res tile stitcher, reticle annotator & crops
│   │   └── crops/             # Synthesized Zoom-16 optical imagery folders
│   ├── 04_vision_ai/          # Stage 4: MiniMax M3 Vision AI pool & prompt engine
│   ├── 05_orchestrator/       # Stage 5: Autonomous end-to-end pipeline runner
│   ├── 06_risk_engine/        # Stage 6: Section 10 multi-factor risk scoring engine
│   └── 07_persistence/        # Stage 7: SQLite time-series historical database
│
├── archive/                   # Preserved Prototype Iterations
│   └── legacy_ui/             # Initial GIS dashboard prototype (Port 8002)
│
└── docs/                      # Documentation & Architecture Specifications
    ├── PS162_FIREX_Project_Master_Brief.md
    └── assets/                # Design specifications & reference documentation
```

---

## 🚀 Quick Start & CLI Usage

### Prerequisites
- **Python 3.10+**
- Dependencies: `requests`, `Pillow`

```bash
pip install -r requirements.txt
```

### Unified CLI (`run.py`)

FIREX provides a unified command-line runner at the root:

```bash
# 1. Start Primary Tactical GIS Command Center (Default: http://localhost:8000)
python run.py serve

# Start on a custom port and automatically launch browser:
python run.py serve --port 8080 --open

# 2. Run the End-to-End Autonomous Pipeline
python run.py pipeline

# 3. Synchronize FIRMS datasets, physical clusters, and compute risk rankings
python run.py data
```

---

## 🎯 Command Center Capabilities

| Capability | Tactical Function |
|---|---|
| **Real-Time 5-Stage Sync HUD** | Interactive modal streaming stages 1 to 5 with live telemetry logs and progress bar upon clicking "Sync Pass". |
| **Physical Cluster Aggregation** | Multi-pixel satellite detections grouped into unified physical fire events with peak and total FRP. |
| **Dual Base Layer Cartography** | Instant switch between Tactical Dark Canvas and Esri High-Resolution Satellite basemaps. |
| **Pulsing Classification Markers** | Live classification colors (`#ff2d55` Wildfire, `#ff9500` Industrial Fire, `#30d158` Gas Flare, `#a2845e` Mining, `#f59e0b` Stubble). |
| **Ambient Nationwide Points** | All raw FIRMS thermal points plotted on the map; only qualified threats elevated to the response queue. |
| **Forensic Incident Dossier** | Deep-dive modal with split optical satellite view, calibrated thermal reticle, and ground truth validation. |
| **Multi-Factor Threat Engine** | Section 10 multi-factor risk breakdown scoring (Severity, Infrastructure, Confidence, Area Risk). |
| **12-Hour Persistence Monitor** | Live persistence widget tracking Day vs Night overpass cycles and historical database volume. |

---

## 🛡️ Competition Alignment

This project is built for **Smart India Hackathon (SIH) 2026 — Problem Statement 162 (NTRO)**.
- Adheres strictly to the sovereign Indian geographical boundary and physical cluster aggregation doctrine.
- Completely dynamic: zero hardcoded static benchmark injection.
- Live demonstration server is always available at `http://localhost:8000`.
