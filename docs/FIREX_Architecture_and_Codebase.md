# FIREX — Architecture & Codebase Overview

## 1. Executive Summary

**FIREX** (Satellite Thermal Intelligence & Tactical Incident Command) is a satellite thermal anomaly intelligence platform built for the Smart India Hackathon (SIH) 2026, Problem Statement 162 (NTRO mandate).

The platform ingests live thermal anomaly vectors from NASA FIRMS, groups detections into incidents by spatial-temporal reachability, enriches each incident with sovereign geospatial context and a 365-day climatological baseline, renders an optical satellite crop for the cases worth inspecting, and runs a multimodal vision model over that crop. A dual-mode severity engine converts the result into an explainable 0–100 risk score, an exactly-once alert engine raises operator alerts for the cases that warrant them, and the same backend process serves the operator console.

Two rules from the specification shape the code throughout:

- **INV-2, FRP is never summed.** A cluster's thermal output is reported as max, mean and min FRP (`v2/backend/app/incidents/clustering.py:54-57`). The console feed publishes the incident's peak value as `cluster_max_frp`, on the line that reads `"cluster_max_frp": inc.current_max_frp,` (`v2/backend/app/orchestration/pipeline.py:923`). No path the v2 run takes sums a cluster's pixels — a cluster's FRP reaches the console as its maximum. (The superseded v1 routine carried along at `v2/frontend/prepare_map_data.py:375` does sum within a cluster, but nothing in v2's startup path launches it — see §3.) The sums the console does display are cross-incident aggregates of those per-incident maxima, not cluster sums: `renderOverview` totals the queue's `frp` into a tile labelled "MW total" (`v2/frontend/js/render.js:605`, `:645-646`) and `renderIndustrial` totals it again as "Total Thermal Radiance" (`:1340`, `:1350`).
- **INV-1, radiance is not a disaster.** A raw FIRMS detection is an infrared anomaly vector, not a confirmed fire. Where only geometry is known — a detection inside a facility perimeter that the vision model has not verified — the published classification is `uncertain`, not a fire class (`pipeline.py:702-710`, the gate `elif is_near and (is_inside_fac or dist_km <= 1.5):` whose body sets `cls_name = "uncertain"`).

## 2. Directory & Repository Structure

The repository root holds the dispatcher, the two trees it can launch, and the documentation.

```text
PS162/
├── run.py                    # Top-level CLI: starts the v2 server, forwards v2 commands to v2/backend/cli.py
├── README.md                 # Repository overview and the v1/v2 split
├── requirements.txt          # Union of both trees (v2/backend/requirements.txt is the v2 list)
├── docs/                     # Architecture and project briefs (where this file resides)
│   ├── FIREX_Architecture_and_Codebase.md
│   ├── PS162_FIREX_Project_Master_Brief.md
│   └── assets/
├── v1/                       # Superseded v1 prototype, frozen; reachable via run.py's v1-* commands
│   ├── pipeline/             # 01_firms … 07_persistence — the seven-stage script chain
│   ├── dashboard/            # v1 console: static HTTP server with its own js/, styles/ and data/
│   ├── archive/legacy_ui/    # Earlier prototype UI (port 8002)
│   └── scratch/
└── v2/                       # The shipped platform
    ├── README.md
    ├── V2_LOGIC_SPECIFICATION.md    # System logic and algorithmic specification
    ├── V2_DEFECT_REPORT.md          # Audit: 97 confirmed code findings, 16 ranked recommended fixes
    ├── backend/
    │   ├── run.py            # uvicorn entrypoint: app.main:app on 127.0.0.1:8000
    │   ├── cli.py            # Browser-free operations: pipeline, data, severity-sweep, migrate
    │   ├── app/              # The twelve-stage service packages (see §3)
    │   ├── scripts/          # Schema migration, climatology build, data-repair scripts
    │   └── data/             # firex_v2.db (SQLite by default), imagery_cache/ and crops/
    ├── frontend/             # Console SPA, mounted by the backend at /console
    ├── docs/                 # Stage verification reports: stages 1–4 plus a v1 audit
    ├── md/                   # SIH 2026 project blueprint
    └── tests/                # Pytest suite
```

Three things about the tree are easy to get wrong:

- **The v1 tree is not inert.** The v2 backend reads one directory out of it. `GET /crops/{incident_id}/{filename}` falls back to `v1/pipeline/03_imagery/crops` when the v2 imagery cache holds no file for that incident (`v2/backend/app/main.py:100`, `:118`), and every analysis export is mirrored into `v1/dashboard/data/` so the v1 dashboard keeps reading current data (`v2/backend/app/orchestration/pipeline.py:86-87` define `FRONTEND_DATA_DIR` and `V1_DATA_DIR`; the export loop at `:1157` writes both).
- **`v2/frontend/server.py` is not the console's entrypoint.** It is a v1-era static server carried along by the directory copy: it resolves `../pipeline/03_imagery/crops` and `../pipeline/07_persistence` (`v2/frontend/server.py:23`, `:68`), neither of which exists under `v2/`, and nothing in the v2 startup path launches it. The console is served by the FastAPI backend.
- **Requirements are split by tree.** The root `requirements.txt` is the union of both — every active dependency of either tree — with one exception: the optional PostgreSQL driver `psycopg2-binary` is commented out there and left active in `v2/backend/requirements.txt`, the list the backend alone needs.

## 3. The Twelve-Stage Intelligence Pipeline

The runner is `execute_analysis_pipeline` (`v2/backend/app/orchestration/pipeline.py:1180`). Its module docstring (`:1-16`) lays the pipeline out as a twelve-step chain from FIRMS to persistence and SSE emission, and the inline comments in the function run from step 1 to step 12 (`:1196` through `:1470`). The comments are not one-per-step, though: steps 8 to 11 share a single combined heading, `# 8, 9, 10, 11: Visual Context, AI Investigation, Severity, and Alerts` (`:1344`), so nine numbered comment sites cover the twelve steps. The docstring and the runner agree on the count and on items 3–12. They differ at the head: the docstring counts ingestion as two items (FIRMS, then validation and deduplication) and does not count the run lock, while the runner counts lock acquisition as step 1 and ingestion as step 2.

Every `pipeline.py` line number in this section is against the file as measured for this revision: 1,582 lines, md5 `b4c1d265fe03a1ceb01c7ed959e6ef43`.

| Step | Subsystem | What the step does |
| :---: | :--- | :--- |
| 1 | `app/orchestration/lock.py` | Acquires the single-run lock (`pipeline.py:1196-1202`). A second concurrent run is refused rather than interleaved. |
| 2 | `app/ingestion/` | Fetches FIRMS telemetry (VIIRS NOAA-20, VIIRS Suomi-NPP, MODIS — `app/core/config.py:56-60`), validates it, filters to the sovereign envelope, and deduplicates on a truncated SHA-256 key (`app/ingestion/normalizer.py:70`). Accepts a CSV string, a file path, or a live fetch (`pipeline.py:1227-1264`). |
| 3 | `app/gis/` | Loads the run's scope and nothing more: every observation from the last 72 hours (`pipeline.py:1279`), falling back to the 50 most recent when that set is empty (`:1283-1284`), then keeps only those inside the sovereign Indian envelope (`:1287`) and publishes `GIS_COMPLETED` (`:1289-1296`). No per-observation geometry is resolved here — see the note below the table. |
| 4 | `app/incidents/clustering.py` | Groups observations by spatial-temporal reachability: epsilon_s = 1500 m, tau = 24 h (`pipeline.py:1299`; specification §4.3). Cluster FRP is aggregated as max, mean and min — never summed (INV-2). |
| 5 | `app/incidents/` | Associates clusters with existing incidents and advances the incident lifecycle state machine (`pipeline.py:1310-1313`). |
| 6 | `app/behavior/` | Recomputes behavior profiles and the 365-day per-facility or per-location baseline for every affected incident (`pipeline.py:1315-1326`). 365 days is the window INV-4's routine-flare test compares against. |
| 7 | `app/selection/` | Ranks the queue and picks the cases to send for optical investigation: at most `max_ai_targets`, five by default (`pipeline.py:1328-1338`). |
| 8 | `app/imagery/` | Fetches the optical crop for each selected incident and renders the reticle over it (`pipeline.py:1376-1389`). |
| 9 | `app/intelligence/` | Runs the multimodal vision investigation over the crop and its context, producing a classification, a confidence and evidence points (`pipeline.py:1391-1422`). |
| 10 | `app/severity/` | Scores the incident with the dual-mode severity model and persists the assessment (`pipeline.py:1424-1437`; see §6). |
| 11 | `app/alerts/` | Evaluates the alert rules and emits at most one alert per incident unless severity strictly escalates (INV-6) (`pipeline.py:1439-1468`). |
| 12 | `pipeline.py`, `app/storage/` | Sweeps the severity engine over the whole displayable queue so every published row carries a score, writes the run record, exports the console data files, and emits the completion event (`pipeline.py:1470-1532`). |

**The GIS step's name is broader than its body.** The pipeline module imports `enrich_coordinate_gis_context` (`pipeline.py:35`), and that helper does resolve administrative unit, nearest asset and landcover in one call (`app/gis/enrichment.py:16-69`) — but the pipeline never calls it. A grep for the name over `v2/backend` returns two imports (`app/orchestration/pipeline.py:35`, `app/api/industries.py:18`), the definition, and one caller, `GET /gis/enrich` (`app/api/industries.py:139-148`), which is not in the run. What the run actually resolves, and where: administrative hierarchy and nearest industrial asset per incident, at incident creation inside the clustering/association layer (`app/incidents/association.py:189-190`); landcover in the console-feed builder (`pipeline.py:631`) and in the severity service (`app/severity/service.py:63`).

Two numbers belong to this section and are frequently confused:

- **The 25 km figure is a v1 grouping radius, not the v2 clustering epsilon.** The superseded v1 cluster routine grouped detections within 25 km (`v2/frontend/prepare_map_data.py:366`, the test `if d <= 25.0:` at `:373`; the same file ships as `v1/dashboard/prepare_map_data.py`), and that routine is reachable only through `v2/frontend/server.py:127-149`, the v1-era static server nothing in v2's startup path launches. The v2 reachability parameters are epsilon_s = 1500 m (the distance at which two detections are the same physical event) with tau = 24 h (`app/incidents/clustering.py:110-113`, called at `pipeline.py:1299`). The two numbers measure different quantities.
- **The optical crop is not fixed at Zoom 16.** The zoom is chosen from the cluster's ground radius: an isolated detection is requested at ~500 m (zoom 17), a 2–3 point cluster at ~750 m and a 4–8 point cluster at ~1000 m (zoom 16), and a larger cluster scales up to 2000 m (zoom 15) (`app/imagery/viewport.py:64-135`). The radius reported back is the ground half-width the 640 px crop actually covers at the chosen zoom (`viewport.py:36-42`).

## 4. Unified CLI Application (`run.py`)

`run.py` at the repository root is the dispatcher. It serves the v2 platform itself and forwards the operational v2 commands, arguments and all, to `v2/backend/cli.py`, which owns their implementations (`run.py:50`, `:89-94`). The archived v1 entrypoints stay reachable, but only under names that make running one a deliberate act (`run.py:56-60`).

**Available commands:**

- `python run.py serve [--port N] [--open]` — starts the v2 platform: uvicorn against `app.main:app` on port 8000 (`run.py:63-86` → `v2/backend/run.py`). One process serves the console at `/console/` and the API.
- `python run.py pipeline` — runs one end-to-end analysis pass (forwarded to `v2/backend/cli.py`, `cmd_pipeline`).
- `python run.py data` — runs the severity sweep over unassessed incidents and regenerates the console and v1 dashboard data files (`v2/backend/cli.py:90-122`).
- `python run.py severity-sweep [--force]` — scores the whole displayable queue with the severity engine (`v2/backend/cli.py:125-146`).
- `python run.py migrate [--dry-run]` — applies pending schema migrations by delegating to `v2/backend/scripts/migrate_schema.py` (`v2/backend/cli.py:149-164`).
- `python run.py legacy [--port 8002] [--open]` — boots the archived v1 prototype UI on port 8002 (`run.py:112-139` → `v1/archive/legacy_ui/server.py`).
- `python run.py v1-pipeline` — runs the archived v1 vision pipeline (`v1/pipeline/05_orchestrator/run_pipeline.py`).
- `python run.py v1-daemon` — runs the archived v1 ingestion daemon, which ingests on a 12-hour (twice-daily) cadence (`v1/pipeline/07_persistence/daemon.py:172`).

There is no `daemon` subcommand: `python run.py daemon` is rejected by the argument parser, because the daemon belongs to v1 and is named accordingly.

## 5. Console Capabilities (`v2/frontend/`)

The console is served by the FastAPI backend and mounted at `http://127.0.0.1:8000/console/` (`v2/backend/app/main.py:136`). `http://127.0.0.1:8000/` itself returns a JSON service index, not the console.

### Server APIs

Ten of the twelve routers are mounted twice — bare and again under `/api` (`v2/backend/app/main.py:70-89`, twenty `include_router` calls for ten routers, e.g. `/alerts` and `/api/alerts`; the twelve are those ten plus a pair in `analysis.py`). The analysis module is the exception: its two routers carry their own prefixes instead of a mount prefix, so `analysis.router` (`prefix="/api/analysis"`, `analysis.py:34`) is mounted once at `main.py:90` and `analysis.top_router` (no prefix, hardcoded `/api/...` paths, `analysis.py:36`) once at `main.py:91`; there is no bare `/analysis/stream`. The endpoints the console actually calls:

- `GET /api/trigger-sync-stream` — if the pipeline lock is free, starts an analysis run in a background worker thread with its own database session and streams the run's events (`v2/backend/app/api/analysis.py:287-302`). The console's sync modal subscribes to this endpoint (`v2/frontend/js/main.js:1044`).
- `GET /api/analysis/stream` — the raw Server-Sent Events route the endpoint above serves (`analysis.py:95-96`). The console subscribes to `/api/trigger-sync-stream`, which calls this same generator, not to the raw path.
- `GET /api/console/feed` — the live queue of active sovereign incidents plus ambient FIRMS points, read from the database rather than from a static file (`analysis.py:331-338`; consumed at `v2/frontend/js/data.js:41`).
- `GET /api/history-stats` — run totals, hotspot totals, and the current overpass (DAY or NIGHT, computed in IST) for the console's persistence widget (`analysis.py:311-328`; consumed at `main.js:847`).
- `GET /api/history/search` — the historical observation archive search (`v2/backend/app/api/history.py:255`; consumed at `main.js:364`).
- `GET /crops/{incident_id}/{filename}` — serves the raw or annotated satellite crop. It checks the v2 imagery cache first, then `v1/pipeline/03_imagery/crops`, then renders the crop on demand if the incident exists in the database (`main.py:109-133`).

### SSE event names on the wire

The event type that lands on the `event:` line is the constant value in `v2/backend/app/orchestration/events.py:35-46`, and those are SCREAMING_SNAKE names: `ANALYSIS_STARTED`, `FIRMS_FETCHED`, `GIS_COMPLETED`, `CLUSTERING_COMPLETED`, `SELECTION_COMPLETED`, `IMAGERY_STARTED`, `AI_STARTED`, `AI_COMPLETED`, `SEVERITY_COMPLETED`, `ALERT_CREATED`, `ANALYSIS_COMPLETED`, `ANALYSIS_FAILED`. No dotted (for example `analysis.started`) form is emitted. That dotted form was the wire form until F-055: the constants then held dotted lowercase names, so a subscriber written against the spec's table matched nothing (`events.py:28-34`). The console now registers both spellings on its `EventSource`, one pair per blueprint event, so it reads the stream either side of that change (`v2/frontend/js/main.js:1184-1198`).

Each event also carries a compatibility block built from `STAGE_MAPPING` (`events.py:49-62`), which maps the twelve event types onto seven stage numbers (0–6) and percentages. The console's sync modal is a five-step operator checklist (`v2/frontend/index.html:427-480`) driven by those stage numbers and percentages.

### Frontend flow

- **Interactive map:** driven by Leaflet 1.9.4 (`v2/frontend/index.html:499-501`). Each incident is one marker carrying the classification as a glyph and the risk tier as its ring colour; a dashed ring means the vision model could not confirm the source (`v2/frontend/js/map.js:102-124`). Only the top-ranked case pulses (`v2/frontend/styles/map.css:171-199`).
- **Incident dossier:** clicking a marker opens the detail drawer, showing the annotated or raw satellite crop, the classification and its reasoning, detection details, the 365-day baseline, the weighted risk-factor breakdown and the recommended action (`v2/frontend/js/dossier.js:240-282`). The "Full Details & Evidence" button in the drawer opens the full-screen modal.
- **Sync HUD:** the "Sync Analysis" button (`index.html:123`) opens a modal with a five-step checklist, a progress bar and a live log stream fed by the SSE events above.

### Known gap in the shipped console

Ten element ids that `v2/frontend/js/main.js:37-43` looks up have no matching element anywhere under `v2/frontend/` — not in `index.html`, and not in any string `render.js` injects: `brand-window`, `map-sub`, `rail-counts`, `risk-hist`, `risk-span`, `map-strip`, `in-view`, `alert-flag`, `q` and `q-clear`. Every use is null-guarded, so nothing throws. What that leaves missing in the shipped console is the **queue search box**, the **map metric strip**, the **in-view counter**, the **alert flag**, the **map sub-line**, the **rail counts** and the **brand status line** — `renderStrip` (`render.js:284`) has no caller other than the guarded lookup at `main.js:602`, the search wiring at `main.js:817-829` has no input to attach to, and the guarded writes behind `brand-window`, `map-sub` and `rail-counts` (`main.js:577-581`, `:585-595`, `:597`) have no element to land in. The risk histogram is the one feature on the list that still reaches the operator, because the Overview tab supplies its own container rather than the absent `el["risk-hist"]`: `renderOverview` emits `<div id="ov-hist"></div>` (`render.js:698`) and calls `renderRiskHist` on it at the end of the render (`render.js:743`), so the Overview tab does draw a ten-bin 0-100 risk distribution; the Analytics tab draws its own ten-bin "Risk score distribution" panel (`render.js:1597-1598`). Dead is the rail instance, the guarded `el["risk-hist"]`/`risk-span` pair at `main.js:598`. The same is true of the direct lookups for `btn-alerts` (`main.js:246`) and `btn-trigger-sync` (`main.js:933`), each of which is guarded or has a working alternative: `updateAlerts` returns at `main.js:247` when the button is absent, and `wirePersistenceSync` builds its trigger list from `[syncBtn, runBtn].filter(Boolean)` and returns at `:939` when it is empty, leaving the `btn-run-analysis` button (`index.html:123`) as the working path.

The three `hist-input-*` fields are **not** part of that gap, and an earlier draft of this list was wrong to file them there. They are built at runtime rather than declared in `index.html` — `render.js:1782`, `:1792` and `:1796` emit `hist-input-query`, `hist-input-start` and `hist-input-end` into the history panel — and `main.js:341-344` reads them straight back to drive `GET /api/history/search` (`main.js:364`, `:354-364`). History search works.

## 6. Threat Qualification & Scoring

The severity model is the specification's §4.6 dual-mode engine, implemented in `v2/backend/app/severity/scoring.py`. A routine 5 MW farm burn and a 250 MW anomaly differ by the score it produces, not by a separate triage list.

Every `scoring.py` line number in this section is against the file as measured for this revision: 422 lines, md5 `f9bfc7f4d406ae3d7aa44c3f8360b926`.

It assigns one of four canonical tiers: LOW [0.0, 24.9], MEDIUM [25.0, 49.9], HIGH [50.0, 74.9], CRITICAL [75.0, 100.0] (`scoring.py:16-32`).

**Two weight sets, chosen by whether the site has history:**

- Known hotspot with history: `0.35 * FRP + 0.30 * historical deviation + 0.20 * vision AI + 0.15 * GIS context` (`scoring.py:310-313`).
- New hotspot without history: `0.50 * FRP + 0.30 * vision AI + 0.20 * GIS context` (`scoring.py:319-321`). A new site is not penalised for the baseline it does not have (INV-5).

**Component scores:**

1. **Effective FRP score:** one of two log2 normalisations of the incident's peak FRP — the raw map `25 * log2(FRP + 1)`, or the Indian-calibrated `25 * log2(FRP / P50 + 1)` with P50 = 4.05 MW, which is used for routine flare sites (`scoring.py:49`, `:55-75`, `:304`).
2. **Historical deviation score:** the ratio of current FRP to the site's 365-day P95, banded from 0 to 100, and suppressed for a confirmed routine flare inside its own envelope (`scoring.py:78-118`).
3. **Vision AI source severity:** a per-class base rating scaled by the model's own confidence (`scoring.py:121-144`). Both spellings of the sixth class — `mining_related` and the specification's `mining_or_other_thermal_source` — rate the same 65.0 (`scoring.py:129`, `:136`).
4. **GIS context score:** whether the detection is inside a high-hazard facility, inside a general facility, in a protected reserve, or merely within a proximity buffer (`scoring.py:147-182`).

**INV-4 routine flare suppression:** when the site is a routine flare and its FRP sits within its own P95 envelope, the composite is clamped to at most 20.0 (`scoring.py:370-376`).

**Four deterministic overrides** raise the level above the weighted score, never below it (`scoring.py:185-230`): extreme FRP at high FIRMS confidence (minimum HIGH, CRITICAL at 250 MW); a confirmed `industrial_fire` at AI confidence 80% or more inside a facility boundary (CRITICAL); an abnormal spike at three times the P95 ceiling (minimum HIGH); and a `wildfire` inside a protected area (minimum MEDIUM).

**Severity confidence** is computed independently of the score — `0.25 * FIRMS + 0.35 * AI + 0.20 * distance + 0.20 * history reliability` (`scoring.py:233-266`) — and an incident at HIGH or CRITICAL with confidence below 60% is flagged for re-investigation on the next pass.

By fusing these components, FIREX separates the thermal signatures that matter to a responder from the ones that recur harmlessly every night.
