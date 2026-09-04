<p align="center">
  <img src="ce4e4a004f53657e4979565e8240e096.png" alt="FIREX Logo" width="120">
</p>

<h1 align="center">FIREX — Satellite Fire Intelligence & Real-Time Incident Command</h1>

<p align="center">
  <strong>Smart India Hackathon 2026 · Problem Statement 162</strong><br>
  Autonomous satellite thermal anomaly detection, high-resolution optical verification, multimodal Vision AI triage, and dynamic geospatial risk prioritization for India.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NASA-FIRMS-orange?style=for-the-badge&logo=nasa" alt="NASA FIRMS">
  <img src="https://img.shields.io/badge/AI-MiniMax_M3-blue?style=for-the-badge" alt="MiniMax M3">
  <img src="https://img.shields.io/badge/GIS-Leaflet.js-green?style=for-the-badge&logo=leaflet" alt="Leaflet">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Architecture-Modular_Pipeline-purple?style=for-the-badge" alt="Modular Architecture">
</p>

---

## 📋 Mission Overview

**FIREX** addresses the core operational gap in national wildfire and thermal hazard management: **NASA FIRMS detects thermal anomalies (heat spikes), NOT confirmed fires.** Emergency responders routinely face costly false alarms from gas flares, industrial smokestacks, solar farms, and slag pits.

FIREX provides a completely automated defense-grade intelligence loop:
1. **Real-Time Satellite Detection:** Ingests live thermal anomaly vectors from NASA FIRMS (VIIRS NOAA-20, Suomi-NPP, MODIS Aqua/Terra).
2. **Autonomous Imagery Retrieval:** Downloads ~1m/px resolution optical satellite crops (~1.2 km tactical radius) and draws calibrated thermal targeting reticles.
3. **Multimodal Vision AI Analysis:** Deploys reasoning-capable vision models (MiniMax M3 via OpenRouter multi-key pool) to classify anomalies into `industrial_fire`, `gas_flare`, `wildfire`, `mining_or_other_thermal_source`, or `agricultural_burn`.
4. **Section 10 Multi-Factor Risk Scorer:** Computes 0–100 composite risk scores factoring FRP, confidence, proximity to human infrastructure, and AI verdict.
5. **Interactive GIS Incident Command:** High-performance dark/light operations center with responsive spotlight navigation, incident investigation dossiers, and ambient nationwide hotspot feeds.

---

## 🏗️ Architecture & Intelligence Flow

```text
       NASA FIRMS API (637+ Hotspots Across India)
                           │
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  01_firms: Satellite Feed Ingestion (VIIRS + MODIS)         │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  02_selection: High-Fidelity Benchmark Curation             │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  03_imagery: Slippy Map Tile Retrieval & Thermal Reticle    │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  04_vision_ai: Multimodal Vision AI Classifier              │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  05_orchestrator: Autonomous End-to-End Execution Pipeline │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  06_risk_engine: Section 10 Multi-Factor Risk Engine       │
  └────────────────────────┬────────────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  dashboard: Unified Tactical GIS Command Center (Port 8000) │
  └─────────────────────────────────────────────────────────────┘
```

---

## 📂 Repository Layout

```
PS162/
├── run.py                     # Unified CLI launcher for server, pipeline, and data
├── requirements.txt           # Consolidated Python project dependencies
├── .gitignore                 # Ignore patterns & API key protection
│
├── dashboard/                 # Primary Tactical GIS Command Center (Port 8000)
│   ├── index.html             # Command platform with Spotlight Navbar & Animated Toggle
│   ├── styles/                # Modular CSS design system (tokens, map, dossier, toggle)
│   ├── js/                    # ES modules (main, map, dossier, render, data, config)
│   ├── server.py              # Self-contained HTTP server mounting satellite crops
│   ├── prepare_map_data.py    # Bundler & pipeline data synchronization script
│   └── data/                  # Live incidents & ambient nationwide FIRMS cache
│
├── pipeline/                  # Modular End-to-End Processing Stages
│   ├── 01_firms/              # Stage 1: NASA FIRMS real-time API fetcher
│   ├── 02_selection/          # Stage 2: Benchmark curation & test cases
│   ├── 03_imagery/            # Stage 3: Satellite tile fetcher & thermal annotation
│   │   └── crops/             # Generated high-resolution satellite crops
│   ├── 04_vision_ai/          # Stage 4: Vision AI prompt & evaluation engine
│   ├── 05_orchestrator/       # Stage 5: Autonomous end-to-end pipeline runner
│   └── 06_risk_engine/        # Stage 6: Section 10 multi-factor risk scoring
│
├── archive/                   # Preserved Prototype Iterations
│   └── legacy_ui/             # Initial GIS dashboard prototype (Port 8002)
│
└── docs/                      # Documentation & Architecture Specifications
    ├── PS162_FIREX_Project_Master_Brief.md
    └── assets/                # Design references & screenshots
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

# 2. Run the End-to-End Autonomous Pipeline (Section 5)
python run.py pipeline

# 3. Synchronize FIRMS datasets, AI assessments, and compute risk rankings
python run.py data

# 4. Launch the Archived Legacy Prototype (Port 8002)
python run.py legacy
```

---

## 🎯 Command Center Capabilities

| Capability | Tactical Function |
|---|---|
| **Dual Base Layer Cartography** | Instant switch between Tactical Dark Canvas and Esri High-Resolution Satellite basemaps. |
| **Pulsing Classification Markers** | Live classification colors (`#ff2d55` Wildfire, `#ff9500` Industrial Fire, `#30d158` Gas Flare, `#a2845e` Mining). |
| **Ambient Hotspots (637 Points)** | Nationwide coverage of FIRMS thermal detections with scaled visual footprint across zoom levels. |
| **Forensic Incident Dossier** | Deep-dive modal with split optical satellite view, calibrated thermal reticle, AI reasoning log, and ground truth validation. |
| **Risk Prioritization Engine** | Section 10 multi-factor risk breakdown scoring (Severity, Infrastructure, Confidence, Area Risk). |
| **Unified Navigation & Controls** | Spotlight navbar, smooth animated theme switcher, and keyboard navigation (`Esc` to close dossier). |

---

## 🤖 Benchmark AI Classification Matrix

| Case | Geolocation Target | AI Classification | Confidence | Risk Tier |
|---|---|---|---|---|
| **case_001** | Hazira Industrial Complex, Surat, Gujarat | `industrial_fire` | 62% | MEDIUM (60/100) |
| **case_002** | Talcher Coal Belt, Angul, Odisha | `mining_or_other_thermal_source` | 88% | MEDIUM (54/100) |
| **case_003** | Dhanbad-Bokaro Coal Belt, Jharkhand | `mining_or_other_thermal_source` | 72% | MEDIUM (50/100) |
| **case_004** | HMEL Guru Gobind Singh Refinery, Punjab | `gas_flare` | 92% | HIGH (80/100) |
| **case_005** | BR Hills Wildlife Sanctuary, Karnataka | `wildfire` | 62% | MEDIUM (43/100) |
| **case_006** | Kharagpur Steel / Industrial Belt, West Bengal | `industrial_fire` | 82% | MEDIUM (57/100) |
| **case_007** | Jharia Coalfield Underground Fire Zone, Jharkhand | `mining_or_other_thermal_source` | 72% | MEDIUM (41/100) |

---

## 🛡️ Competition Alignment

This project is directly built for **Smart India Hackathon (SIH) 2026 — Problem Statement 162**.
- All stages of the pipeline can be executed independently or orchestrated via `python run.py pipeline`.
- Live demonstration server is always available via `python run.py serve`.
