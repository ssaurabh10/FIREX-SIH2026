# SIH 2026 — PS 162 Project Master Brief & Operational Blueprint

## AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, Multi-Sensor Satellite Imagery & Geospatial Intelligence

> **Document Status:** Active Master Specification & Current Reality Audit  
> **Last Updated:** September 2026  
> **Target Competition:** Smart India Hackathon (SIH) 2026  
> **Problem Statement ID:** SIH26162 (PS 162)  
> **Nodal Ministry / Organization:** National Technical Research Organisation (NTRO)  
> **System Name:** **FIREX** — Fire Intelligence & Real-time EXploration  
> **Tree this brief describes:** the shipped v2 platform (`v2/backend`, `v2/frontend`), started from the repository root by `run.py`. All paths are relative to the repository root, except paths spelled `app/...`, which are relative to `v2/backend/`. The pre-v2 prototype is archived under `v1/` and is named in this brief only where it differs from v2.

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
1. Near-real-time satellite thermal anomaly detections,
2. High-resolution map/satellite visual context for incident verification,
3. Industrial infrastructure proximity datasets (GIS layers & a verified sovereign facility registry),
4. Multimodal Vision AI reasoning, and
5. Time-series persistence tracking,

to detect, segregate, classify, score, and monitor industrial fires and persistent thermal sources on interactive GIS consoles.

**The classifier's own taxonomy.** The vision model returns exactly one of six canonical classes per investigated incident (`v2/backend/app/intelligence/schemas.py:10-17`, enforced by `_normalize_taxonomy`, `app/intelligence/provider.py:251-280`): `industrial_fire`, `gas_flare`, `wildfire`, `agricultural_burning`, `mining_related`, and `uncertain`. `uncertain` is the refusal class for cloud-obscured or inconclusive scenes, not a sixth source type; the PS's "other persistent thermal emitters" is served by the closest matching class rather than a label of its own.

The value the vision path stores for the mining class is `mining_related`: that class is the only mining literal in the schema, and the provider normalises the specification's spelling into it (`v2/backend/app/intelligence/provider.py:274`, the `"mining_or_other_thermal_source": "mining_related"` alias inside `_normalize_taxonomy` at `:251-280`). **The persisted database disagrees with that code path.** In `v2/backend/data/firex_v2.db` the mining rows carry the specification spelling — 81 of 330 `incidents` and 11 of 20 `ai_investigations` — and no row in either table carries `mining_related` (`select classification, count(*) from incidents group by 1`). They were written by the shipped maintenance scripts `v2/backend/scripts/refresh_mining_incidents.py:24,36` and `v2/backend/scripts/refresh_industrial_incidents.py:32,43`, which assign `mining_or_other_thermal_source` to the row directly. The geometry-only classifier in the console feed pipeline also emits the specification spelling (`generate_console_feed_data`, `app/orchestration/pipeline.py:665`), and the frontend accepts either spelling as the same class (`v2/frontend/js/config.js:47-48`).

Per the project blueprint's claim guardrails (`v2/md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md`, §4A), this brief does not claim 24/7 continuous satellite imaging, guaranteed detection of every fire, or ground-truth confirmation from FIRMS alone. It claims continuous processing of incoming FIRMS observations followed by contextual investigation.

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

`execute_analysis_pipeline` (`v2/backend/app/orchestration/pipeline.py`) runs **twelve numbered steps** per analysis pass. Steps 8–11 repeat for each incident selected for optical investigation; step 12 sweeps the whole displayable queue before exporting. Line anchors into this file are pinned to the revision measured for this brief — **1582 lines, md5 `b4c1d265fe03a1ceb01c7ed959e6ef43`** — so if the file has changed since, the named symbol is authoritative and the line number is not.

```text
                          NASA FIRMS TELEMETRY
         (product VIIRS_NOAA20_NRT by default; MODIS rows also parse)
                                  │
                                  ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  1  RUN LOCK                         app/orchestration/lock.py │
  │  2  FIRMS INGESTION & FILTER                    app/ingestion/ │
  │  3  GIS ENRICHMENT                                    app/gis/ │
  │  4  CLUSTERING (NO FRP SUM)        app/incidents/clustering.py │
  │  5  INCIDENT ASSOCIATION          app/incidents/association.py │
  │  6  BEHAVIOR & 365-DAY BASELINES                 app/behavior/ │
  │  7  SELECTION & PRIORITY                        app/selection/ │
  │  8  VISUAL CONTEXT (IMAGERY)                      app/imagery/ │
  │  9  AI INVESTIGATION                         app/intelligence/ │
  │ 10  SEVERITY ASSESSMENT                          app/severity/ │
  │ 11  ALERT ENGINE                          app/alerts/engine.py │
  │ 12  FINALIZE & EXPORT            app/orchestration/pipeline.py │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
  ┌────────────────────────────────────────────────────────────────┐
  │ CONSOLE & SSE — one process, /console/ on port 8000            │
  │ GET /api/console/feed · GET /api/trigger-sync-stream (SSE)     │
  └────────────────────────────────────────────────────────────────┘
```

---

## 3. Current Implementation Status & Operational Reality

| # | Subsystem | Core Responsibility | State in this tree | Key Artifacts & Technologies |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Run lock | Serialise analysis passes; a second trigger is refused while one is active. | Implemented | `v2/backend/app/orchestration/lock.py` |
| **2** | Ingestion | Fetch NASA FIRMS telemetry, validate it, deduplicate on a 20-hex-character SHA-256 key, discard telemetry outside Indian sovereign territory. | Implemented | `v2/backend/app/ingestion/{firms,normalizer,validator}.py`, `app/gis/boundaries.py` |
| **3** | GIS & geodesy | Haversine distance, ray-casting point-in-polygon, land-cover and protected-area resolution, a 30-facility industrial registry and 16 major mining basins. | Implemented | `v2/backend/app/gis/{spatial,boundaries,assets,mining_basins,landcover,enrichment}.py` |
| **4** | Clustering | Spatio-temporal reachability clustering at εs = 1500 m and τ = 24 h; per-cluster max/mean/min FRP, pixel count, centroid and footprint radius. FRP is never summed. | Implemented | `v2/backend/app/incidents/clustering.py` |
| **5** | Incident association | Match clusters to tracked incidents, extend the temporal envelope, promote lifecycle state, persist observation provenance. | Implemented | `v2/backend/app/incidents/{association,state,aggregation}.py` |
| **6** | Behavior & climatology | 365-day facility and location baselines (P50/P90/P95), day/night persistence score, anomaly ratio, trends. | Implemented | `v2/backend/app/behavior/{baseline,persistence,anomaly,profile,trends}.py` |
| **7** | Selection | Dual-mode investigation priority (with history / new hotspot) plus mandatory overrides; ranks candidates. | Implemented; the per-pass optical-investigation budget is capped (default 5, `--max-ai-targets`) | `v2/backend/app/selection/{engine,scoring}.py` |
| **8** | Visual context | Dynamic viewport (500–2000 m radius tiers, zoom chosen for the incident's latitude, 640 px crop), tile stitch from the Google and Esri basemaps, tactical reticle with physical range rings. | Implemented; requires outbound HTTPS — with both tile hosts unreachable the provider returns a dark synthetic tile | `v2/backend/app/imagery/{viewport,provider,reticle,service,package}.py` |
| **9** | AI investigation | Multimodal investigation over the crop plus FIRMS/GIS/climatology context, twelve mandatory prompt rules, six-class taxonomy, key-pool rotation with cooldown. | Implemented; one remote leg (OpenRouter, model id from `AI_MODEL`, shipped as `dots-studio/dots-3-note-preview:free`) plus a deterministic offline provider. The specification's four-leg cascade (Gemini → Groq → OpenAI → mock) is **not** implemented — a documented divergence (`app/intelligence/provider.py:1-27`) | `v2/backend/app/intelligence/{provider,prompts,key_pool,schemas,service}.py` |
| **10** | Severity | Dual-mode 0–100 composite (known-hotspot 35/30/20/15; new-hotspot 50/30/20), routine-flare suppression, operational escalation overrides. | Implemented | `v2/backend/app/severity/{scoring,service,state_machine}.py` |
| **11** | Alerts | Exactly-once alert creation per incident, monotonic escalation, deduplication. | Implemented | `v2/backend/app/alerts/engine.py` |
| **12** | Orchestration & export | Twelve-step runner, severity sweep over the displayable queue, console/dashboard JSON export, SSE broadcaster. | Implemented | `v2/backend/app/orchestration/{pipeline,events,lock}.py` |
| **—** | Storage | 15 SQLAlchemy tables, including `historical_baselines` and `thermal_climatology`; SQLite by default (`v2/backend/data/firex_v2.db`), PostgreSQL/PostGIS optional. | Implemented | `v2/backend/app/storage/models.py`, `app/core/config.py` |
| **—** | Console | Static operator console served by the backend at `/console/`, with the map, incident feed and dossiers. | Implemented, with a known rendering gap — see §4.3 | `v2/frontend/` |

---

## 4. Operational Innovations

### 4.1 Physical Spatial Cluster Fusion (εs = 1500 m, τ = 24 h)
In spaceborne thermal sensors, a single physical fire or industrial complex routinely triggers several to dozens of separate sensor pixels. Instead of treating these as disconnected events:
- Observations are grouped by spatio-temporal reachability — a **1500 m spatial epsilon** and a **24-hour temporal window**, the defaults of `cluster_observations` (`v2/backend/app/incidents/clustering.py:110-113`); the pipeline calls it with exactly those values (`app/orchestration/pipeline.py:1299`). The 375 m additive buffer on the cluster's footprint radius is the sensor-pixel allowance (`app/incidents/clustering.py:81`).
- Metrics are reported per cluster: **max FRP**, **mean FRP**, **min FRP**, **pixel count**, **centroid coordinates**, and the dynamic footprint radius. FRP is never summed (Invariant INV-2), so the cluster's intensity figure is its peak pixel, not a total.
- The incident row stores that peak as `current_max_frp`; the console feed publishes it as `cluster_max_frp` beside `cluster_pixel_count` (`v2/backend/app/orchestration/pipeline.py:916-924`).
- *Example:* the Sijua coal basin cluster (Baghmara, Dhanbad, Jharkhand) — record `case_006` — holds **83 sensor pixels** with a **peak pixel FRP of 13.02 MW**. That record survives only in the committed revision: read it as `git show HEAD:v1/dashboard/data/incidents.json` (`"frp": 13.02` at line 808, `"cluster_pixel_count": 83` at line 810). The same committed record carries a summed `"cluster_total_frp": 238.3` at line 809; the v2 pipeline computes no such number.
- **The working-tree path is not a frozen v1 archive.** `export_v1_dashboard_data` writes every export pass into both `FRONTEND_DATA_DIR` and `V1_DATA_DIR` (`app/orchestration/pipeline.py:1157`; `V1_DATA_DIR` is defined at `:87`), and `execute_analysis_pipeline` calls it at the end of a run (`:1523`). So the file on disk at `v1/dashboard/data/incidents.json` is rewritten by the v2 pipeline rather than left as an archive, and in this tree it is currently an empty `[]` — 2 bytes, 0 lines — because the last export pass to touch it published no incidents (the `queue_summary.json` written beside it in the same pass records `"active_count": 0`). The committed 2,074-line revision holds the v1 record cited above. What the next export against the current database writes is v2-shaped: re-running the feed builder read-only over `v2/backend/data/firex_v2.db` returns 220 incidents, which `json.dump(..., indent=2)` serialises to 16,710 lines with 220 `cluster_max_frp` keys (`app/orchestration/pipeline.py:923`) and no key containing `total` anywhere in the payload, so `cluster_total_frp` is absent rather than zero-valued.
- The **25 km** grouping radius quoted in earlier revisions of this brief is not a v2 parameter. It is the link distance of the archived v1 dashboard clusterer (`v1/dashboard/prepare_map_data.py:366-373`, duplicated byte-for-byte at `v2/frontend/prepare_map_data.py:366-373`), which also accumulates `total_frp` by summation. That clusterer belongs to the v1 prototype; the v2 run never calls it.

### 4.2 Threat Qualification & Selection (No Arbitrary Queue Cap)
Every sovereign cluster becomes or updates a tracked incident. The qualification labels record why an incident was put forward for optical investigation; they do not gate the board. The console-feed builder (`v2/backend/app/orchestration/pipeline.py:752-760`) tags each incident with the operational triggers it meets:
1. **`SOVEREIGN_MINING_CONCESSION`**: the coordinate falls inside one of the 16 registered major mining basins (`v2/backend/app/gis/mining_basins.py`).
2. **`CRITICAL_INFRASTRUCTURE`**: the point is inside a registered facility's footprint, or within 5.0 km of it (`app/orchestration/pipeline.py:604`).
3. **`MAJOR_FIRE_SURGE`**: the incident's peak FRP is at least 50.0 MW (`app/orchestration/pipeline.py:757-758`).
4. **`24H_TEMPORAL_PERSISTENCE`**: the incident is tracked as PERSISTENT, is a known routine flare site, or sits at a metallurgical facility (`app/orchestration/pipeline.py:759-760`).

The `MONTANE_FOREST_CANOPY` trigger named in earlier revisions does not exist in the v2 pipeline — it survives only in the archived v1 clusterer duplicated at `v2/frontend/prepare_map_data.py:403`, which the v2 run never calls. Protected areas still change the outcome, through classification rather than a trigger. For incidents with no vision-model verdict, the feed applies a documented geometry-and-landcover classifier (the classification cascade at `app/orchestration/pipeline.py:638-737`, inside `generate_console_feed_data`; land cover at `resolve_landcover`, `app/gis/landcover.py:26`): a registered mining basin is labelled `mining_or_other_thermal_source`, a metallurgical facility `industrial_fire`, a flare stack or a routine site `gas_flare`, a detection inside or within 1.5 km of a facility perimeter is left honestly `uncertain` at 0.45 confidence (because process heat, an operational flare and an uncontrolled fire are indistinguishable from radiance alone), a detection inside a national park or sanctuary `wildfire`, and mapped cropland outside a protected area `agricultural_burning`. Those rules are evaluated in exactly that order.

Selection is bounded on the investigation side, not on the queue. Each pass scores at most the 500 most recently updated incidents that are not `RESOLVED` (`v2/backend/app/selection/engine.py:22,217`, status filter at `:212` — `DISMISSED` rows are still scored), keeps those at investigation priority ≥ 30 or carrying a mandatory override (`:234`), and sends the top `max_ai_targets` (default 5) for optical and AI investigation (`app/orchestration/pipeline.py:1329`). That bound exists to bound imagery and AI cost; it is configurable with `python run.py pipeline --max-ai-targets N` (flag at `v2/backend/cli.py:181`); and it does not shorten the board — the severity sweep at step 12 scores the whole displayable queue (`app/orchestration/pipeline.py:1478`).

There is no 3–5 MW agricultural-noise cutoff. The intensity tests that do exist are the selection overrides: peak FRP ≥ 150 MW with FIRMS confidence ≥ 80, persistence score ≥ 85, or a current FRP at least 3× the historical median (`v2/backend/app/selection/scoring.py:71-96`).

The ambient layer is raw telemetry, not a filtered-out class of weak detections: the console feed publishes the 200 most recent sovereign FIRMS observations as ambient points irrespective of intensity (`app/orchestration/pipeline.py:988-1002`), in a layer separate from the incident board.

### 4.3 Interactive Pipeline Streaming HUD
The console's pipeline button is labelled **"Sync Analysis"** (`v2/frontend/index.html:123-126`). Clicking it runs the handler wired by `wirePersistenceSync` (`v2/frontend/js/main.js:932-1229`), which:
- opens a modal checklist of **five stage rows** (`sync-stage-1` … `sync-stage-5`, all present in `index.html`) and connects an `EventSource` to **`GET /api/trigger-sync-stream`** (`main.js:1044`; route at `v2/backend/app/api/analysis.py:287`);
- drives a real-time progress bar, a percentage readout, a phase label, per-stage status badges and an auto-scrolling monospace log terminal from the streamed events;
- reloads the feed and refreshes the map layers, priority feed and dossiers when the run completes (`main.js:1164-1166`, the `await load(); await updatePersistenceWidget(); renderAll();` triplet; the SSE-error fallback repeats the same three calls at `main.js:1213-1215`).

The event names on the wire are the SCREAMING_SNAKE constants in `v2/backend/app/orchestration/events.py:35-46` — `ANALYSIS_STARTED`, `FIRMS_FETCHED`, `GIS_COMPLETED`, `CLUSTERING_COMPLETED`, `SELECTION_COMPLETED`, `IMAGERY_STARTED`, `AI_STARTED`, `AI_COMPLETED`, `SEVERITY_COMPLETED`, `ALERT_CREATED`, `ANALYSIS_COMPLETED`, `ANALYSIS_FAILED` — and each carries a `stage` number 0–6 from `STAGE_MAPPING` (`events.py:49-62`) that drives the five-row checklist. The pass executes twelve steps while the console renders five rows: the HUD is a coarse projection of the run, not a claim that the pipeline has five stages.

**Known gap in the shipped console.** `main.js` also looks up element ids that `index.html` does not contain: `q` and `q-clear` (the queue search box), `map-strip` (the map metric strip), `in-view` (the in-view counter), `alert-flag`, `risk-hist` and `risk-span` (the risk histogram), plus `brand-window`, `map-sub` and `rail-counts`. Every use is null-guarded (`v2/frontend/js/main.js:37-42,663-664,817-827`), so those features never render and nothing throws. The queue search box, the risk histogram, the map metric strip and the in-view counter are therefore not working features of this console.

---

## 5. Verification Runbook

```bash
# 0. Install dependencies (repository root; covers the v2 platform and the archived v1 tools)
pip install -r requirements.txt

# 1. Start the console and API (default: http://127.0.0.1:8000/console/)
python run.py serve

# 2. Run one end-to-end analysis pass (twelve steps; see --help for its flags)
python run.py pipeline

# 3. Regenerate the console data files from the persisted queue
python run.py data

# 4. Optional operational commands
python run.py severity-sweep        # score the whole queue with the severity engine
python run.py migrate               # apply pending schema migrations

# 5. Optional: the archived v1 prototype UI (port 8002)
python run.py legacy
```

`pipeline`, `data`, `severity-sweep` and `migrate` are forwarded verbatim to `v2/backend/cli.py`, which owns the v2 implementations (the `V2_CLI_COMMANDS` tuple at `run.py:50`; the delegation body is `delegate_to_v2_cli`, `run.py:89-94`, dispatched before argparse runs at `run.py:147-148`). The subcommands that execute scripts under `v1/` are the two `v1-*` entries (`V1_SCRIPTS`, `run.py:56-59`) **and** `legacy`, which launches `v1/archive/legacy_ui/server.py` (`V1_LEGACY_SERVER`, defined at `run.py:60` and used in `cmd_legacy` at `run.py:135`).

---

## 6. Summary for SIH Evaluators & Judges

> **"FIREX solves the fundamental problem of false-alarm fatigue in satellite earth observation. By processing incoming sovereign airspace telemetry, fusing multi-pixel detections into clusters without summing their radiative power, verifying each candidate against high-resolution map/satellite visual context and a verified strategic infrastructure registry, and scoring it with a deterministic multi-factor risk model, FIREX helps defense, environmental, and disaster management agencies separate routine operations from genuine catastrophic emergencies."**
