<p align="center">
  <img src="ce4e4a004f53657e4979565e8240e096.png" alt="FIREX Logo" width="120">
</p>

<h1 align="center">🔥 FIREX — Fire Intelligence & Real-time EXploration</h1>

<p align="center">
  <strong>SIH 2026 · Problem Statement 162</strong><br>
  AI-powered satellite fire detection, classification, and investigation platform for India
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NASA-FIRMS-orange?style=for-the-badge&logo=nasa" alt="NASA FIRMS">
  <img src="https://img.shields.io/badge/AI-MiniMax_M3-blue?style=for-the-badge" alt="MiniMax M3">
  <img src="https://img.shields.io/badge/Leaflet-GIS_Map-green?style=for-the-badge&logo=leaflet" alt="Leaflet">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge&logo=python" alt="Python">
</p>

---

## 📋 Overview

**FIREX** is an end-to-end AI-powered fire intelligence system that:

1. **Fetches real-time satellite fire detections** from NASA FIRMS (VIIRS NOAA-20, VIIRS Suomi-NPP, MODIS Aqua/Terra)
2. **Retrieves high-resolution satellite imagery** (~1 m/px) for each hotspot coordinate
3. **Classifies fire events using Vision AI** (MiniMax M3 multimodal) into categories: `industrial_fire`, `gas_flare`, `wildfire`, `mining_or_other_thermal_source`, `agricultural_burn`
4. **Visualizes results on an interactive tactical GIS map** with click-to-inspect forensic investigation screens

Built for **Smart India Hackathon (SIH) 2026 — Problem Statement 162**: *"Satellite-based real-time fire detection and AI-powered classification system for India."*

---

## 🏗️ Architecture

```text
NASA FIRMS API (637 hotspots, India-wide)
        │
        ▼
┌─── Section 1: FIRMS Data Fetcher ───────────────────────┐
│  Fetches VIIRS + MODIS detections via REST API           │
│  Validates coordinates, FRP, confidence, timestamps       │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 2: Benchmark Dataset Curation ────────────────┐
│  Selects 7 diverse test cases across India                │
│  Reverse-geocodes via OSM Nominatim + Overpass API        │
│  Categories: Industrial, Flare, Mining, Wildfire          │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 3: Satellite Imagery Retrieval ───────────────┐
│  Google Satellite tiles (zoom 16, ~1.2 km FOV)            │
│  Esri World Imagery fallback                              │
│  Tactical thermal reticle overlay + metadata banners      │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 4: Vision AI Classification ──────────────────┐
│  MiniMax M3 (multimodal, reasoning-enabled)               │
│  4-key round-robin load balancing via OpenRouter           │
│  Structured JSON output: class, confidence, evidence      │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 5: End-to-End Automated Pipeline ─────────────┐
│  Full integration: FIRMS → Imagery → AI → Dossier         │
│  Zero manual intervention                                 │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 6: Interactive GIS Map Dashboard ─────────────┐
│  Leaflet.js tactical dark-mode map                        │
│  637 ambient FIRMS dots + 7 AI-classified pulsing markers │
│  Click-to-inspect sidebar drawer                          │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─── Section 7: Forensic Investigation Screen ─────────────┐
│  Full-screen incident deep-dive dossier                   │
│  Thermal reticle ↔ Optical toggle                         │
│  AI verdict, evidence checklist, operator triage workflow  │
└──────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
PS162/
├── section1_firms/           # NASA FIRMS data fetcher
│   ├── config.py             # API key & bounding box config
│   ├── firms_fetch.py        # FIRMS REST API query engine
│   └── raw_responses/        # Raw CSV responses from FIRMS
│
├── section2_selection/       # Benchmark test case curation
│   ├── select_candidates.py  # OSM geocoding & filtering
│   └── test_detections.json  # 7 curated benchmark cases
│
├── section3_imagery/         # Satellite imagery pipeline
│   ├── fetch_satellite_crops.py  # Tile stitcher & reticle drawer
│   └── crops/                # Per-case satellite images
│       └── case_00X/
│           ├── satellite_raw.jpg
│           ├── satellite_annotated.jpg
│           └── metadata.json
│
├── section4_vision_ai/       # AI classification engine
│   ├── config.py             # OpenRouter API keys & model config
│   ├── vision_classifier.py  # Multimodal prompt + 4-key rotation
│   └── ai_classifications.json  # Full AI assessment results
│
├── section5_pipeline/        # End-to-end automated pipeline
│   ├── config.py
│   ├── key_pool.py           # API key round-robin pool
│   ├── run_pipeline.py       # Full pipeline orchestrator
│   └── incidents/            # Generated incident dossiers
│
├── section6_gis_map/         # Interactive web dashboard
│   ├── index.html            # Main dashboard layout
│   ├── style.css             # Dark-mode tactical styling
│   ├── app.js                # Leaflet map + incident interaction
│   ├── server.py             # Local HTTP server
│   ├── prepare_map_data.py   # Data bundler for frontend
│   └── data/
│       ├── incidents.json    # 7 AI-evaluated incidents
│       └── ambient_firms.json # 637 nationwide FIRMS points
│
├── .gitignore
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+**
- **pip packages**: `requests`, `Pillow`

### 1. Install dependencies

```bash
pip install requests Pillow
```

### 2. Launch the GIS Dashboard

```bash
cd section6_gis_map
python server.py
```

Then open **http://localhost:8000** in your browser.

### 3. Run the full pipeline (optional)

```bash
cd section5_pipeline
python run_pipeline.py
```

---

## 🗺️ Dashboard Features

| Feature | Description |
|---------|-------------|
| 🗺️ **Dual Basemaps** | CartoDB Dark Canvas + Esri Satellite toggle |
| 🔴 **Pulsing Markers** | Color-coded by AI classification (Flare / Industrial / Mining / Wildfire) |
| 📊 **637 Ambient Hotspots** | Nationwide FIRMS detections overlay |
| 🔍 **Click-to-Inspect** | Sidebar drawer with satellite crop, AI assessment, and FIRMS metrics |
| 🔬 **Forensic Investigation** | Full-screen dossier with thermal reticle toggle, evidence checklist |
| 🛡️ **Triage Workflow** | Operator can mark: Verified Fire / Routine Flare / Escalate / False Alarm |
| ⌨️ **Keyboard Navigation** | Arrow keys to browse cases, Esc to close |

---

## 🤖 AI Classification Results

| Case | Location | AI Classification | Confidence |
|------|----------|-------------------|------------|
| 001 | Hazira Industrial, Surat | `industrial_fire` | 62% |
| 002 | Talcher Coal Belt, Odisha | `mining_or_other_thermal_source` | 88% |
| 003 | Dhanbad-Bokaro Coal, Jharkhand | `mining_or_other_thermal_source` | 72% |
| 004 | Bathinda HMEL Refinery, Punjab | `gas_flare` | 92% |
| 005 | BR Hills Wildlife, Karnataka | `wildfire` | 62% |
| 006 | Kharagpur Steel Plant, WB | `industrial_fire` | 82% |
| 007 | Jharia Coalfield, Jharkhand | `mining_or_other_thermal_source` | 72% |

---

## 🛰️ Data Sources

- **[NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)** — Fire Information for Resource Management System
- **[Google Satellite Tiles](https://mt1.google.com/vt/lyrs=s)** — High-resolution optical basemap
- **[Esri World Imagery](https://server.arcgisonline.com/)** — Fallback satellite tiles
- **[OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/)** — Reverse geocoding
- **[MiniMax M3 via OpenRouter](https://openrouter.ai/)** — Multimodal Vision AI

---

## 📄 License

This project is developed for **SIH 2026 — Problem Statement 162**.

---

<p align="center">
  Built with 🔥 for Smart India Hackathon 2026
</p>
