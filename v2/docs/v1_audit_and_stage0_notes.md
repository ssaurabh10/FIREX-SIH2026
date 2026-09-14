# V1 Audit & Reference Assessment for FIREX v2
**Document Version:** 1.0  
**Stage:** Stage 0 — V1 Audit + Project Foundation  
**Reference Blueprint:** [FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md](file:///c:/Users/ssaur/OneDrive/Desktop/PS162/v2/md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md)

---

## 1. V1 Architecture Audit Summary

The v1 repository (`ssaurabh10/FIREX-SIH2026`) was inspected thoroughly across the following components:
1. `dashboard/`: Tactical GIS Command Center, Leaflet map, dossier view, SSE updates, `prepare_map_data.py`.
2. `pipeline/01_firms`: NASA FIRMS API fetcher (`firms_fetch.py`) using `area/csv` endpoint.
3. `pipeline/02_selection`: Known facilities registry (`facilities_registry.py`) with ~200 curated Indian industrial coordinates (refineries, steel complexes, power plants, coalfields).
4. `pipeline/03_imagery`: Slippy-map tile fetcher (`fetch_satellite_crops.py`) using Google Satellite tiles with Esri World Imagery fallback and thermal reticle annotation.
5. `pipeline/04_vision_ai`: MiniMax/Gemma OpenRouter multi-key pool vision classifier (`vision_classifier.py`).
6. `pipeline/06_risk_engine`: Deterministic risk scoring matrix (`risk_scorer.py`).
7. `pipeline/07_persistence`: SQLite time-series daemon and historical persistence engine (`history_db.py`, `daemon.py`).

---

## 2. Categorization Checklist

### A. What Already Works
- **NASA FIRMS Ingestion:** Proven parameter formatting (`area/csv`), bounding box for sovereign India (`68.7, 8.4, 97.4, 37.6`), and parsing of VIIRS (NOAA-20, SNPP) and MODIS feeds.
- **Satellite Tile Cropping:** Zero-cost Slippy-map Web Mercator tile fetcher from Google Maps satellite tiles + Esri fallback, generating 256x256 and stitched crops with thermal reticle overlays.
- **OpenRouter Multi-Key Vision AI:** Gemma/MiniMax prompt formulation instructing the AI that FIRMS is a thermal detection (not confirmed fire) and requesting structured classification.
- **Command UI & Dossier View:** Leaflet-based dark tactical theme with incident dossier slide-out, hotspot list, time-window toggles, and incident metrics.
- **Facilities Registry:** Curated coordinates for Indian oil refineries, petrochemical complexes, thermal power stations, steel smelters, and mining clusters.

### B. What Should Be Reused in v2
- **UI Assets & Styling:** The tokens, CSS layout, and interaction design from `v1/dashboard` are preserved directly into `v2/frontend`.
- **Satellite Imagery Engine:** Reuse the tile retrieval math (`deg2num`), caching, and crop stitching logic inside `v2/backend/app/imagery`.
- **Vision AI Prompt Structure & Key Pool:** Adapt the 4-key load-balanced pool and strict schema prompting into `v2/backend/app/intelligence`.
- **Facilities Database:** Ingest the verified facility coordinates from `facilities_registry.py` into the new `industrial_assets` SQL table.
- **FIRMS Fetch Logic:** Refactor `firms_fetch.py` into `v2/backend/app/ingestion/firms.py` with Pydantic validation and direct DB persistence.

### C. What Should Be Replaced in v2
- **Tangled File-Based State:** Replace ad-hoc JSON file outputs (`incidents.json`, `ambient_firms.json`, `ai_classifications.json`) with the unified relational database schema (`observations`, `incidents`, `incident_observations`, `ai_investigations`).
- **Ad-Hoc Script Orchestration:** Replace the serial script chaining (`run_pipeline.py`, `prepare_map_data.py`) with a clean FastAPI service architecture and background worker tasks.
- **Overloaded Risk Concept:** Disentangle Investigation Selection (Should we investigate?) from Severity Assessment (How serious is it?) as mandated by Critical Architecture Rule 3.
- **Basic SQLite Time-Series:** Upgrade persistence to the structured Historical Behavior & Baseline Pipeline (30d/90d/365d baselines, persistence scoring, anomaly detection, P95 FRP).

### D. What Should Not Be Touched
- The core problem statement scope (distinguishing industrial thermal sources from wildfires/crop burning).
- The high-resolution map-satellite visual context verification approach (do not attempt to replace with live optical satellite feeds which do not exist at sub-daily cadences).

---

## 3. Stage 0 Milestone Verification Status

| Requirement | Status | Evidence |
|---|---|---|
| Project structure (`backend`, `frontend`, `data`, `scripts`, `tests`, `docs`) | Completed | Created under `/v2/` |
| FastAPI Application Setup | Completed | `/v2/backend/app/main.py` |
| Database Connection & Schema | Completed | 10 Tables created in SQLite / PostgreSQL ready |
| Environment Configuration (`.env`, `.env.example`) | Completed | Configured with Pydantic settings |
| `/health` endpoint returns 200 OK | Verified | Tested via `pytest` (200 OK, DB connected) |
| Frontend UI loads | Verified | Mounted at `/console/` returning 200 OK |
| Docker logic handling | Omitted | Docker logic deliberately bypassed as requested |
