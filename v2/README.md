# FIREX v2 — Space-Borne Satellite AI Industrial Thermal Intelligence Platform

Welcome to **FIREX v2**.

For the complete technical and algorithmic logic specification designed specifically for AI agents, machine learning engineers, and aerospace operators, please consult:

👉 **[FIREX v2 Logic & Algorithmic Specification](V2_LOGIC_SPECIFICATION.md)**

---

## Setup, Run and Tests

Run the commands below from this directory (`v2/`).

```bash
pip install -r backend/requirements.txt
python backend/run.py
```

`backend/requirements.txt` carries the backend's declared dependencies: fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, requests, pillow, psycopg2-binary, pytest and httpx. `backend/run.py` starts uvicorn against `app.main:app` on `127.0.0.1:8000` (`HOST` and `PORT` override the bind), and that one process serves everything:

- **Operator console:** `http://127.0.0.1:8000/console/` — the static app in `frontend/`, mounted by the backend at `backend/app/main.py:136`.
- **API docs (OpenAPI):** `http://127.0.0.1:8000/docs`
- **Health:** `http://127.0.0.1:8000/health`

Secrets and connection settings live in `backend/.env` (gitignored; the committed template is `backend/.env.example`): the NASA FIRMS key, the OpenRouter keys and the database URL. `backend/app/core/config.py:26-38` loads that file by absolute path, so a server started from any working directory reads the same settings, and a relative SQLite `DATABASE_URL` is anchored to `backend/` (`config.py:97-99`).

Operational tasks that need no browser go through the backend CLI: `python backend/cli.py --help` lists `pipeline` (one end-to-end analysis run), `data` (regenerate the console data files), `severity-sweep` and `migrate`.

Tests:

```bash
python -m pytest tests
```

17 test modules collecting 170 tests on 2026-09-17 (`python -m pytest tests --collect-only -q`; both counts move as the suite is edited). The `test_stageN_*.py` filenames use the older eleven-way subsystem grouping 0-10, which `V2_LOGIC_SPECIFICATION.md:77` records as *not* the spec's twelve-stage numbering — it merges several of those stages; the remaining modules are API-contract, climatology, export-target isolation and classifier checks. `tests/conftest.py` binds the session to a throwaway SQLite database and redirects the pipeline's data exports and the imagery cache into that same throwaway directory, so a test run does not write into `backend/data/firex_v2.db`, `frontend/data/` or `backend/data/imagery_cache/`. Verified on Python 3.14.6.

---

## Directory Structure

- **[`V2_LOGIC_SPECIFICATION.md`](V2_LOGIC_SPECIFICATION.md)**: **Master Logic Specification for AI & Systems** — complete mathematical equations, system invariants, empirical Indian climatology calibration ($P_{50}=4.05\text{ MW}$, $P_{90}=13.32\text{ MW}$, $P_{95}=20.81\text{ MW}$, $P_{99}=64.49\text{ MW}$; also the `INDIA_FRP_*` constants at `backend/app/severity/scoring.py:49-52`), the twelve-stage pipeline DAG, multimodal prompt rules, severity scoring models, alert deduplication, and database schema.
- **[`backend/`](backend)**: FastAPI backend service implementing the twelve numbered steps of `execute_analysis_pipeline` (`backend/app/orchestration/pipeline.py`). Anchor by symbol, not by line: the step comments run `# 1. Acquire Run Lock` through `# 12. Finalize & Export`, with steps 8-11 sharing one combined comment (`# 8, 9, 10, 11: Visual Context, AI Investigation, Severity, and Alerts`) whose four sub-steps are unnumbered inside the candidate loop. Measured 2026-09-17 the file was 1,582 lines (md5 `b4c1d265fe03a1ceb01c7ed959e6ef43`) and `def execute_analysis_pipeline` began at `:1180`:
  - `app/api/`: the REST and SSE route surface. The domain routers are registered both bare and under the `/api` prefix (`backend/app/main.py:70-91`), and `:109` adds `GET /crops/{incident_id}/{filename}`.
  - `app/core/`: settings, logging, TTL cache and rate-limit middleware. `app/core/config.py` is the settings module (`RATE_LIMIT_PER_MINUTE = 120` at `:90`, `DATABASE_URL` at `:49`, the AI model id at `:68`); not every spec number is a setting — the Indian FRP percentiles live in `app/severity/scoring.py`, the clustering epsilon and time window are literals at the call site, and the reticle ring fractions are in `app/imagery/reticle.py`.
  - `app/ingestion/`: FIRMS telemetry parsing, validation, and deduplication on a 20-hex-character truncated SHA-256 key (`backend/app/ingestion/normalizer.py:70-71`).
  - `app/gis/`: Spatial geodesy (Haversine, ray-casting PIP), Indian sovereign boundary checks, national industrial registry, mining basin spatial index.
  - `app/incidents/`: Adaptive spatial-temporal DBSCAN clustering at 1,500 m and 24 h (`backend/app/incidents/clustering.py:5-8`; invoked as `clusters = cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)` at `pipeline.py:1299` in the same 1,582-line revision), FRP max/mean/min aggregation under the non-summation invariant, incident association, state lifecycle.
  - `app/behavior/`: 365-day climatological baselines, diurnal night-overpass ratios, statistical anomaly ratio tables.
  - `app/selection/`: Dual-mode candidate prioritization (with history vs new hotspot), mandatory selection overrides.
  - `app/imagery/`: Dynamic optical satellite crop generation, tactical reticle HUD rendering with physical range rings (`backend/app/imagery/reticle.py:3`).
  - `app/intelligence/`: Multimodal vision AI engine, 12 prompt rules (`backend/app/intelligence/prompts.py:19-31`), key pool rotation with auto-cooldown (`backend/app/intelligence/key_pool.py:19-20`). Divergence from the spec: §6.3's four-leg cascade (Gemini → Groq → OpenAI → mock) is not implemented — `backend/app/intelligence/provider.py:1-27` ships one remote leg (OpenRouter, with the mock provider as the terminal fallback reached automatically when every key is exhausted or quarantined), because no client or credential for the middle legs exists in this tree.
  - `app/severity/`: Dual-mode severity scoring, empirical Indian climatology calibration, routine flare suppression, operational escalation overrides.
  - `app/alerts/`: Exactly-once alert deduplication, monotonic escalation engine.
  - `app/orchestration/`: Master pipeline runner, thread-safe mutex lock, real-time Server-Sent Events (SSE) broadcaster. The event names that go on the wire are the SCREAMING_SNAKE constants in `backend/app/orchestration/events.py:35-46`.
  - `app/storage/`: SQLAlchemy database models and database connections.
- **[`frontend/`](frontend)**: Tactical web map console, served by the backend at `http://127.0.0.1:8000/console/` (`backend/app/main.py:136`), with a real-time SSE listener (`frontend/js/main.js:1044`) and an incident detail drawer/dossier that shows the satellite crop. The reticle HUD and its range rings are drawn into the crop server-side (`backend/app/imagery/reticle.py`), not in the browser.
  - `frontend/server.py` is a leftover v1 standalone static server, not the console's entrypoint: it serves `frontend/` directly on port 8000 (`FIREX_PORT` overrides) and resolves `../pipeline/03_imagery/crops` and `../pipeline/07_persistence`, which do not exist under `v2/`. Run the console through the backend instead.
  - Ten element ids in the `grab()` list at `frontend/js/main.js:37-42` have no element in `frontend/index.html` — `q`, `q-clear`, `map-strip`, `in-view`, `alert-flag`, `risk-hist`, `risk-span`, `brand-window`, `map-sub` and `rail-counts` — and every use is null-guarded. The queue search box, the map metric strip, the in-view counter, the alert flag and the risk histogram therefore never render. Nothing throws.
- **[`tests/`](tests)**: Test suite of 17 modules, collecting 170 tests on 2026-09-17 (`python -m pytest tests --collect-only -q`). The `test_stageN_*.py` module names use the older eleven-way subsystem grouping 0-10, which is not the spec's twelve-stage numbering (`V2_LOGIC_SPECIFICATION.md:77`); the remaining modules are the API contract, climatology calibration, export-target isolation and classifier checks.
- **[`docs/`](docs)**: Stage verification reports for stages 1-4 of the older filename grouping (`stage1_data_foundation_and_ingestion.md`, `stage2_gis_and_industrial_context.md`, `stage3_clustering_and_incident_lifecycle.md`, `stage4_behavior_intelligence.md`) plus `v1_audit_and_stage0_notes.md`. There is no verification report numbered 5-10.
- **[`md/`](md)**: SIH 2026 Complete Project Blueprint (`FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md`).

---

## Repository Context

This tree sits beside `v1/`, which holds the superseded pipeline and dashboard (`v1/pipeline/01_firms` … `07_persistence`, `v1/dashboard/`). Two links between them are still live: `serve_crop_image` (`backend/app/main.py:110`) serves a v1 crop from `../v1/pipeline/03_imagery/crops` (`V1_CROPS_DIR` at `:100`, read at `:118`) as the *second* of three sources — after the v2 imagery cache (`:111-115`) and before on-demand rendering for a known incident (`:123-131`) — so v1 crops are a fallback, not the last resort; and every analysis export is mirrored into `../v1/dashboard/data/` so the v1 dashboard keeps reading current data — the module defines `FRONTEND_DATA_DIR` / `V1_DATA_DIR` at `pipeline.py:86-87`, and `export_v1_dashboard_data` (defined at `:1140`) writes each JSON file into both in the `for target_dir in [FRONTEND_DATA_DIR, V1_DATA_DIR]:` loop at `pipeline.py:1157` (the same 1,582-line / md5 `b4c1d265fe03a1ceb01c7ed959e6ef43` revision cited above).
