<h1 align="center">FIREX — Satellite Thermal Intelligence & Tactical Incident Command</h1>

<p align="center">
  <strong>Smart India Hackathon 2026 · Problem Statement 162 (NTRO Mandate)</strong><br>
  Autonomous satellite thermal anomaly detection, physical spatial cluster triage, sovereign airspace filtering, high-resolution optical verification, and multi-factor threat risk prioritization for India.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NASA-FIRMS-orange?style=for-the-badge&logo=nasa" alt="NASA FIRMS">
  <img src="https://img.shields.io/badge/AI-OpenRouter_Multimodal_Vision-blue?style=for-the-badge" alt="OpenRouter multimodal vision">
  <img src="https://img.shields.io/badge/GIS-Leaflet.js-green?style=for-the-badge&logo=leaflet" alt="Leaflet">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Architecture-Spatial_Clustering_Engine-purple?style=for-the-badge" alt="Spatial Clustering">
</p>

---

## 🗂️ The v1 / v2 Split

This repository holds two trees, and only one of them is the product.

| Tree | Status | Entry point |
|---|---|---|
| `v2/` | **The live platform.** FastAPI backend, the operator console, the test suite, the logic specification. | `python run.py serve`, `pipeline`, `data`, `severity-sweep`, `migrate` |
| `v1/` | **Archived prototype.** The original script-per-stage pipeline, its own GIS dashboard, and an even older UI. Kept for reference and demo history. | `python run.py legacy`, `v1-pipeline`, `v1-daemon` |

`run.py` at the repository root is a dispatcher. `pipeline`, `data`, `severity-sweep` and `migrate` are forwarded verbatim to `v2/backend/cli.py` (`run.py`, `V2_CLI_COMMANDS`, which the dispatcher does not parse itself). `serve` does not delegate: `cmd_serve` launches `v2/backend/run.py`, the uvicorn entrypoint, as a subprocess with `PORT` and `HOST` in the environment. `legacy`, `v1-pipeline` and `v1-daemon` run scripts under `v1/` by explicit name (`V1_SCRIPTS`, `V1_LEGACY_SERVER`). The two trees do not share a database: v2 writes `v2/backend/data/firex_v2.db`, v1 wrote `v1/pipeline/07_persistence/firex_history.db`.

---

## 📋 Mission Overview & Scientific Foundation

**FIREX** addresses the core operational gap in national thermal hazard and defense surveillance: **NASA FIRMS detects thermal radiance anomalies (infrared heat spikes), NOT confirmed fires.** Emergency responders, forest departments, and defense analysts routinely face severe false-alarm fatigue from operational refinery flare stacks, metallurgical blast furnaces, slag pits, and small routine agricultural burns.

FIREX provides an automated intelligence loop:

1. **Real-Time Sovereign Telemetry Ingestion:** Ingests thermal anomaly vectors from NASA FIRMS — the live path requests one product, `VIIRS_NOAA20_NRT`, the head of `FIRMS_DEFAULT_PRODUCTS` (`live_product = settings.FIRMS_DEFAULT_PRODUCTS[0]` and then `live_csv = firms_client.fetch_live_csv(live_product, days=1)` in `execute_analysis_pipeline`, which `fetch_live_csv` in `app/ingestion/firms.py` interpolates straight into the area/csv URL), i.e. the 375 m VIIRS product — and confines them to the sovereign Indian bounding box 68.7°E–97.4°E, 8.4°N–37.6°N plus a boundary polygon, discarding foreign and cross-border telemetry (INV-3; `app/core/config.py:54`, `app/gis/boundaries.py`). The multi-product list `FIRMS_DEFAULT_PRODUCTS` (`VIIRS_NOAA20_NRT` / `VIIRS_SNPP_NRT` / `MODIS_NRT`, `app/core/config.py:56-60`) is read only through its first entry, by the live call above, so the live fetch names one of the three rather than the set. MODIS and NOAA-21 observations are in the committed database (satellites N20, N21, SNPP, Aqua, Terra), but they arrived through `--firms-csv` / `--file` ingestion rather than the live call.
2. **Physical Spatial Cluster Triage:** Groups satellite hits that are mutually reachable within $\epsilon_s = 1500\text{ m}$ and $\tau = 24\text{ h}$ into physical incident clusters (the stage-4 comment in `execute_analysis_pipeline`, `app/orchestration/pipeline.py`, reads `# 4. Spatial-Temporal Clustering & Non-Summing Invariant`; the call is `cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)`), aggregating **max FRP, mean FRP, min FRP and pixel count**. FRP is **never summed** (INV-2, `V2_LOGIC_SPECIFICATION.md` §2); the console feed carries the cluster maximum as `frp` / `cluster_max_frp` (`generate_console_feed_data` in `app/orchestration/pipeline.py`).
3. **Operational Threat Qualification:** The selection engine scores open (non-`RESOLVED`) incidents with a dual-mode priority model and three mandatory overrides — `EXTREME_FRP` (≥ 150 MW at ≥ 80 % FIRMS confidence), `HIGH_PERSISTENCE` (persistence score ≥ 85) and `STRONG_HISTORICAL_ANOMALY` (current FRP ≥ 3× the 365-day median) (`app/selection/scoring.py:71-96`) — but only the newest-updated `CANDIDATE_POOL_LIMIT = 500` of them per pass: incidents beyond that bound are not scored at all, and the engine logs the count it dropped (`app/selection/engine.py:22`, `:217`, `:221`). A run sends the highest-priority candidates for optical investigation — five by default (`--max-ai-targets`, the default of `max_ai_targets` in `execute_analysis_pipeline` and of the flag in `v2/backend/cli.py`). Routine, low-intensity agricultural burns remain ambient dots on the map instead of entering the priority queue.
4. **Time-Series Persistence & Diurnal Profiles:** Persists incidents and their history in SQLite at `v2/backend/data/firex_v2.db` (the default `DATABASE_URL`; a relative SQLite path is resolved against `v2/backend/`, not the working directory — `app/core/config.py:49`, `:97-115`; PostgreSQL/PostGIS is the documented alternative). The 365-day baselines live in the `historical_baselines` table (`app/storage/models.py:238`), and the day/night overpass ratio separates continuous combustion (refineries, coal-seam fires) from transient diurnal burns.
5. **High-Res Optical Satellite Tile Synthesis:** Fetches and stitches a 640×640 optical crop, requesting a radius from the cluster's size — 500 m (isolated), 750 m (2–3 points), 1000 m (4–8 points), 1200–2000 m (larger clusters) — and derives the zoom from that request *and the incident's own latitude*, because Web Mercator ground resolution scales with cos(lat) (`calculate_incident_viewport` and `determine_zoom_for_radius`, `app/imagery/viewport.py`; `get_stitched_crop`, `app/imagery/provider.py:80-86`). The radius tiers are fixed; the zooms are not: the 500 m → zoom 17 tier holds only down to about 29.3° N, while 750 m → 16 and 1200 m → 15 hold across the whole sovereign envelope, so at Amritsar (31.6° N) a 500 m request resolves to zoom 16 and a 2000 m request to zoom 14 — as the docstring's own table concedes in qualifying the first row "~500 m radius -> Zoom 17 (Indian latitudes; coverage shrinks with cos(lat))". The crop is then annotated with a reticle whose rings sit at 40 % and 80 % of the frame, measured from the crop's *actual* ground coverage (`app/imagery/reticle.py:11`, `:44-63`).
6. **Multi-Factor Severity Engine (spec §4.6):** Computes a deterministic, auditable 0–100 score. With history the weights are FRP 0.35, Historical Deviation 0.30, Vision AI Source Severity 0.20, GIS Context 0.15; a new hotspot without a usable baseline drops the deviation term and redistributes its weight to FRP — FRP 0.50, Vision AI 0.30, GIS Context 0.20 — so it is never penalised for lacking history (INV-5; `app/severity/scoring.py`, `compute_incident_severity`). Deterministic operational escalation rows are added on top, and a persistent flare inside its own 365-day P95 envelope is clamped to ≤ 20 (INV-4).
7. **Interactive Pipeline HUD & Live Console:** Operators press **"Sync Analysis"** in the console (`v2/frontend/index.html:123-126`) and watch a modal stream five progress groups over Server-Sent Events from `/api/trigger-sync-stream` (`v2/frontend/js/main.js:1044`, `v2/backend/app/api/analysis.py:287`). On completion the console reloads the queue and the persistence widget (`js/main.js:1163-1166`).

---

## 🏗️ Architecture & Intelligence Flow

One analysis run is the twelve ordered stages of `execute_analysis_pipeline` (`v2/backend/app/orchestration/pipeline.py`). The comments in that function enumerate them 1–12 — numbered one by one through stage 7 (`# 1. Acquire Run Lock`, `# 2. FIRMS Telemetry Fetch & Normalization`, `# 3. GIS Enrichment`, `# 4. Spatial-Temporal Clustering & Non-Summing Invariant`, `# 5. Incident Association & Lifecycle Promotion`, `# 6. Refresh Behavior Profiles & 365d Baselines for Affected Assets`, `# 7. Selection & Priority Ranking`), then stages 8–11 in a single grouped comment (`# 8, 9, 10, 11: Visual Context, AI Investigation, Severity, and Alerts`), then stage 12 (`# 12. Finalize & Export`) — which is also the count the specification states in prose ("executes twelve discrete stages", `V2_LOGIC_SPECIFICATION.md` §3). The specification's "Stage Summary Matrix" table numbers the subsystems 1–12, and its section headings carry that same numbering (§4.3 clustering is "Stage 4", §4.6 severity is "Stage 10"). The 0–10 numbering that appears around the repository is a different, older grouping: the specification's own note that `tests/test_stageN_*.py` filenames "use an older eleven-way subsystem grouping (0 foundation … 10 hardening)". The twelve steps below are the numbering the pipeline implements. The console HUD does **not** report into that numbering: its five rows carry fixed labels `Stage 1`–`Stage 5` in the markup, and the stage number the HUD prints comes from `STAGE_MAPPING` in `app/orchestration/events.py`, a separate 0–6 scale (`ANALYSIS_STARTED` → 0; `CLUSTERING_COMPLETED` and `SELECTION_COMPLETED` both → 3; the last four events → 6) — so HUD "Stage 3" spans twelve-steps 4+5+7 and HUD "Stage 5" spans 9–12 (`events.py:49-62`, `frontend/js/main.js:1050`, `frontend/index.html:432`).

```text
             NASA FIRMS SATELLITE CONSTELLATION
     (VIIRS NOAA-20 / Suomi-NPP [375 m] · MODIS [1 km])
                            │
                            ▼
  execute_analysis_pipeline  —  one run, twelve ordered stages
  ┌───────────────────────────────────────────────────────────────────────┐
  │  1  Acquire the run lock (single-flight; a concurrent run is refused) │
  │  2  Ingest FIRMS telemetry (live API, --firms-csv or --file)          │
  │     · SHA-256 deduplication                                           │
  │  3  GIS enrichment + sovereign India filter (bbox + polygon mask)     │
  │  4  Spatial-temporal clustering — 1500 m / 24 h, max/mean/min FRP     │
  │  5  Incident association & lifecycle state promotion                  │
  │  6  Refresh the 365-day behavior baseline for each affected asset     │
  │  7  Selection: priority ranking + mandatory overrides → top N targets │
  │  ── per selected candidate ─────────────────────────────────────────  │
  │  8  Optical crop synthesis + calibrated thermal reticle               │
  │  9  Multimodal vision-AI investigation (cached verdict reused)        │
  │ 10  Severity assessment                                                │
  │ 11  Alert emission (exactly once per incident, INV-6)                 │
  │  ───────────────────────────────────────────────────────────────────  │
  │ 12  Severity sweep over the displayable queue → console feed export   │
  └───────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  Console  http://127.0.0.1:8000/console/
  · reads GET /api/console/feed (falls back to static JSON)
  · subscribes to the SSE stream for the run HUD
```

The SSE event names on the wire are the constants in `v2/backend/app/orchestration/events.py:35-46` — `ANALYSIS_STARTED`, `FIRMS_FETCHED`, `GIS_COMPLETED`, `CLUSTERING_COMPLETED`, `SELECTION_COMPLETED`, `IMAGERY_STARTED`, `AI_STARTED`, `AI_COMPLETED`, `SEVERITY_COMPLETED`, `ALERT_CREATED`, `ANALYSIS_COMPLETED`, `ANALYSIS_FAILED` — each written literally on the stream's `event:` line (`events.py:96`).

---

## 📂 Repository Layout

```text
PS162/
├── run.py                     # Dispatcher: v2 subcommands + named archived v1 entrypoints
├── requirements.txt           # Union dependency list for both trees
├── run_firex.bat              # Windows helper: `python run.py serve --open`
├── .gitignore                 # Runtime cache and secret exclusions (.env, *.db, imagery_cache/)
│
├── docs/                      # Repository-level documentation
│   ├── FIREX_Architecture_and_Codebase.md
│   ├── PS162_FIREX_Project_Master_Brief.md
│   └── assets/Inspiration/    # Reference image + pixel-accurate dashboard spec
│
├── History data/              # Downloaded FIRMS archives (gitignored)
│
├── v1/                        # ARCHIVED prototype — not the product
│   ├── dashboard/             # v1 GIS command UI + its own static server.py
│   ├── pipeline/              # 01_firms … 07_persistence (script-per-stage)
│   │   └── 07_persistence/firex_history.db
│   ├── archive/legacy_ui/     # Earliest prototype UI (port 8002)
│   └── scratch/
│
└── v2/                        # LIVE platform
    ├── V2_LOGIC_SPECIFICATION.md    # Master logic & algorithmic specification
    ├── README.md                    # v2-scoped notes
    ├── md/                          # SIH 2026 complete project blueprint (REVISED2)
    ├── backend/
    │   ├── run.py                   # uvicorn entrypoint (reads PORT / HOST)
    │   ├── cli.py                   # pipeline · data · severity-sweep · migrate
    │   ├── requirements.txt         # Authoritative v2 backend dependency list
    │   ├── .env.example             # Committed template; copy to .env for real keys
    │   ├── app/
    │   │   ├── main.py              # FastAPI app; mounts frontend at /console
    │   │   ├── api/                 # health, observations, industries, incidents, history,
    │   │   │                        # selection, imagery, investigation, severity, alerts, analysis
    │   │   ├── core/                # config.py (every spec constant), cache, clock, logging,
    │   │   │                        # ratelimit, security
    │   │   ├── ingestion/           # FIRMS parsing, validation, SHA-256 dedup
    │   │   ├── gis/                 # Geodesy, boundaries, industrial assets, mining basins
    │   │   ├── incidents/           # Clustering, incident association, lifecycle state
    │   │   ├── behavior/            # 365-day baselines, diurnal ratios, anomaly tables
    │   │   ├── selection/           # Dual-mode priority model + mandatory overrides
    │   │   ├── imagery/             # Crop synthesis, viewport selection, reticle rendering
    │   │   ├── intelligence/        # Vision-AI provider, prompt rules, key pool
    │   │   ├── severity/            # Scoring engine, operational overrides, state machine
    │   │   ├── alerts/              # Exactly-once dedup and escalation
    │   │   ├── orchestration/       # Pipeline runner, run lock, SSE broadcaster
    │   │   └── storage/             # SQLAlchemy models and database session
    │   ├── data/                    # firex_v2.db, imagery_cache/, crops/
    │   └── scripts/                 # ingest_history.py, migrate_schema.py, repair utilities
    │
    ├── frontend/                    # Console, served by the backend at /console/
    │   ├── index.html
    │   ├── js/                      # main, map, render, dossier, data, config (ES modules)
    │   ├── styles/                  # tokens, base, layout, components, map, dossier, cards…
    │   ├── data/                    # Generated incidents.json, ambient_firms.json, queue_summary.json
    │   └── server.py, prepare_map_data.py   # v1-era static server; the CLI does not use them
    │
    ├── tests/                       # 17 pytest modules + conftest.py
    └── docs/                        # Stage 1–4 verification reports + stage 0 / v1 audit notes
```

---

## 🚀 Quick Start & CLI Usage

### Prerequisites
- **Python 3.10+**
- Dependencies — install the repository-root list, which is the union of both trees:

```bash
pip install -r requirements.txt
```

That file installs the v2 stack (fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy), the test stack (pytest, httpx), and the shared ingestion/imagery libraries (requests, pillow). `psycopg2-binary` is listed as a commented optional extra for the PostgreSQL/PostGIS path. `v2/backend/requirements.txt` is the authoritative list for the v2 backend alone.

### Configuration
Copy the committed template and fill in your own keys:

```bash
cp v2/backend/.env.example v2/backend/.env
```

- `FIRMS_MAP_KEY` — a NASA FIRMS map key. Without one no live payload is fetched, and the run proceeds on the observations already in the database (`execute_analysis_pipeline` logs `[Pipeline] No live FIRMS payload fetched; proceeding with existing active observations.`).
- `OPENROUTER_API_KEYS` — one or more OpenRouter keys, rotated with the spec §6.3 cooldown/quarantine policy. If every key is unusable, the provider answers with the deterministic mock report, capped at 50 % confidence and flagged `needs_reinvestigation` (`app/intelligence/provider.py`, `_build_fallback_report`; the ceiling is `FALLBACK_CONFIDENCE_CEILING = 50.0`).
- `AI_MODEL` — the vision model id. The default is `dots-studio/dots-3-note-preview:free`; `/status` reports whatever `AI_MODEL` holds (`app/core/config.py:62-68`, `:117-124`).

The committed `app/core/config.py` holds no credentials; secrets live only in the gitignored `.env` (`config.py:4-17`).

### Unified CLI (`run.py`)
Run every command from the repository root:

```bash
# Start the v2 console + API (default port 8000) and open a browser
python run.py
python run.py serve
python run.py serve --port 8080 --open

# One end-to-end analysis run
python run.py pipeline
python run.py pipeline --firms-csv path/to/firms.csv    # ingest a downloaded CSV
python run.py pipeline --force --max-ai-targets 8       # re-investigate, widen the target set

# Regenerate the console data files from the persisted queue
python run.py data
python run.py data --force-sweep

# Score the whole displayable queue with the severity engine
python run.py severity-sweep [--force]

# Apply pending schema migrations
python run.py migrate [--dry-run]

# Archived v1 prototype (the legacy server binds its own FIREX_LEGACY_PORT, default 8002)
python run.py legacy [--port 8002] [--open]
python run.py v1-pipeline
python run.py v1-daemon
```

With the server running, the console is at `http://127.0.0.1:8000/console/`, the OpenAPI docs at `/docs`, and the health probe at `/health`. `python run.py data` writes generated data to both `v2/frontend/data/` and `v1/dashboard/data/` (`FRONTEND_DATA_DIR` and `V1_DATA_DIR` in `v2/backend/app/orchestration/pipeline.py`).

---

## 🎯 Command Center Capabilities

| Capability | What the shipped console does |
|---|---|
| **Run HUD (five progress groups)** | The **"Sync Analysis"** button opens a modal with five stage rows — Satellite Thermal Feed, History & Baseline Matching, Hotspot Grouping & Priority Ranking, Satellite Imagery Preparation, AI Vision & Risk Assessment — plus a progress bar, elapsed timer, per-target sub-progress and a live log (`frontend/index.html:391`, `:429-479`). The twelve pipeline stages report into those five rows (`frontend/js/main.js:1073-1105`). |
| **Cluster aggregation** | Each case carries its cluster's **max FRP** as `frp` and `cluster_max_frp`, and its detection count as `cluster_pixel_count`. There is no mean-FRP key in the published case: the clustering engine computes `mean_frp` and the `Incident` row stores it as `current_mean_frp`, but neither reaches the console case (`generate_console_feed_data` in `v2/backend/app/orchestration/pipeline.py`). FRP is never summed (INV-2). |
| **Base layers** | Two Leaflet base layers from Esri: **Canvas** (Dark Gray Canvas with a reference overlay) and **Imagery** (World Imagery), switched from the map controls (`frontend/js/map.js:7-11`, `:69-75`). |
| **Map markers** | Incidents are glyph markers: the icon carries the classification (factory, flare, mining, wildfire, crop, warning, question) and the colour ramp carries the risk tier (`frontend/js/config.js:43-52`, `frontend/styles/tokens.css:64-67`). The top-ranked case pulses; the rest are static (`frontend/styles/map.css:171-184`). |
| **Ambient detections** | Raw FIRMS points plot as circle markers with an FRP-scaled radius and a toggle to show or hide them (`frontend/js/map.js:196-221`). |
| **Incident dossier** | Drawer and full modal with the annotated and raw optical crops, AI classification/confidence/evidence, the 365-day baseline, the weighted risk breakdown, and reviewer triage buttons (Confirmed / Routine / Escalated / Dismissed) (`frontend/js/dossier.js:287-350`). |
| **Risk breakdown** | The published `risk_factors` are the spec §4.6 weighted contributions and sum to the `risk_score` beside them, with explicit Operational Escalation and Routine Flare Suppression rows when those apply (`_weighted_risk_factors` and `_reconciliation_row` in `v2/backend/app/orchestration/pipeline.py`). |
| **Pass / persistence widget** | Shows the current day or night pass, the stored hotspot count and the last run time, read from `GET /api/history-stats` (`frontend/js/main.js:845-857`, `v2/backend/app/api/analysis.py:311-328`). |
| **Live feed** | `GET /api/console/feed` returns incidents and ambient detections straight from the database; when that request fails the console reads the static files under `frontend/data/` instead (`frontend/js/data.js:41`, `:68-88`; `v2/backend/app/api/analysis.py:331-338`). |
| **Published queue roll-up** | The feed also carries a roll-up over the queue it just published — active count, tier histogram and the HIGH + CRITICAL attention count (`queue_summary`, built by `generate_console_feed_data` in `v2/backend/app/orchestration/pipeline.py`). The console renders it as a strip and hides the strip when an older or static payload has no summary, rather than drawing a zero that reads like a finding (`frontend/js/main.js:871-916`, `frontend/index.html:137-144`). |

**Not wired in the shipped console.** Ten element ids that `frontend/js/main.js` registers — `brand-window`, `map-sub`, `rail-counts`, `risk-hist`, `risk-span`, `map-strip`, `in-view`, `alert-flag`, `q` and `q-clear` — have no element in `frontend/index.html` (`frontend/js/main.js:38-43`). The consequences are that the queue search box (`q` / `q-clear`), the risk histogram (`risk-hist` / `risk-span`), the map metric strip (`map-strip`), the in-view counter (`in-view`) and the alert flag (`alert-flag`) never render, and the map header and rail labels (`brand-window`, `map-sub`, `rail-counts`) stay empty. Two further direct lookups, `btn-alerts` (`frontend/js/main.js:246`) and `btn-trigger-sync` (`:933`), are unmatched in `frontend/index.html` and are the only two with no element anywhere at all; the run HUD still opens because `wirePersistenceSync` listens on both names and `btn-run-analysis` does exist. Four more literals, `hist-input-query`, `hist-select-state`, `hist-input-start` and `hist-input-end` (`:341-344`), are likewise absent from `frontend/index.html`, but unlike the two above their elements are rendered at runtime by `frontend/js/render.js`, so the history search does work. Every unmatched use is null-guarded, so nothing throws and the rest of the console works; these features are simply absent until the markup is added.

---

## 🛡️ Competition Alignment

This project is built for **Smart India Hackathon (SIH) 2026 — Problem Statement 162 (NTRO)**.
- Adheres strictly to the sovereign Indian geographical boundary (INV-3) and to physical cluster aggregation without FRP summation (INV-2).
- No pre-baked verdicts: each incident's classification, severity and risk score come from its own detections, its 365-day baseline and a vision-AI investigation; when the AI provider is unreachable the report is a deterministic fallback capped at 50 % confidence and marked for reinvestigation (`v2/backend/app/intelligence/provider.py:48-57`).
- The console is served at `http://127.0.0.1:8000/console/` once `python run.py serve` is running (default port 8000, overridable with `--port`).
