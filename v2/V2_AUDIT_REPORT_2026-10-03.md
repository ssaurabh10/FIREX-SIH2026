# FIREX v2 — Independent Audit Report

**Date:** 2026-10-03
**Target:** `v2/` (backend `app/` — 6,592 LOC across imagery/behavior/selection/incidents/gis/ingestion/intelligence; tests; frontend; deploy config)
**Basis:** Independent, from-scratch audit. `v2/V2_DEFECT_REPORT.md` was **not** used as a source; it is stale (see "Starting state").
**Method:** Line-by-line reading of the modules listed under "Coverage", plus targeted verification of every claim below against source. The shipped test suite was run. Where a finding came from a delegated reading pass rather than my own read of the file, that is stated in the finding.

---

## Starting state (why this report differs from the old one)

The tree has been **heavily remediated** since `V2_DEFECT_REPORT.md` was written. 59 of that report's 137 finding IDs now carry remediation comments in the code, and several formerly-fatal items are fixed and verified:

- `v2/backend/app/core/config.py` is tracked in git (`.gitignore:26-42` explicitly keeps it; verified via `git ls-files`).
- `logger` is bound in `analysis.py` (`analysis.py:32`) — the `NameError`-in-handler is gone.
- Test fixtures are out of the committed `frontend/data/incidents.json`; `tests/conftest.py` now binds the suite to a throwaway DB and **asserts** all five in-repo write targets are redirected (`conftest.py:182-188`).
- `v2/backend/app/imagery/*` — the reticle/zoom/scale-bar defects (old F-008/F-009/F-010/F-103/F-104/F-105) are genuinely fixed; I hand-verified the Web Mercator arithmetic (see "Verified clean").

**Test suite: 181 passed, 39.54s, exit 0** (`python -m pytest tests/ -q`; `--timeout` is unavailable — `pytest-timeout` is not installed, so the suite is run without it).

So this report lists **what is still wrong**, not what the old one listed.

---

## Severity summary

| # | Finding | Severity | Verification |
|---|---|---|---|
| H-1 | INV-4 chronic-source clamp is inert on the pipeline's own severity path | High | Confirmed (all lines read) |
| H-2 | The chronic clamp can demote a spec-mandated forced CRITICAL to LOW/20 | High | Confirmed (reproduced arithmetically) |
| H-3 | `S_FRP_eff` uses the calibrated curve unconditionally; spec §4.6.1 forbids it | High | Confirmed (spec text quoted) |
| H-4 | Every mutating endpoint is unauthenticated; `verify_api_key` is dead code | High | Confirmed (grep + read) |
| H-5 | Caller-controlled server-side file path is opened without containment | High | Confirmed, impact bounded (see finding) |
| H-6 | GET endpoints write to the DB (class already fixed for `/console/feed`) | High | Confirmed |
| H-7 | `/crops` is rate-limiter-exempt while it renders, fetches tiles, and writes | High | Confirmed |
| M-1 | `max_frp` / `mean_frp` published from the wrong columns; branches disagree | Medium | Confirmed |
| M-2 | Severity-driven lifecycle transitions bypass the transition table and are unaudited | Medium | Confirmed |
| M-3 | In-memory cache is unbounded with attacker-controlled keys | Medium | Confirmed (cache.py) |
| M-4 | Rate limiter collapses to one global bucket on the deployed platform | Medium | Confirmed (launch config) |
| M-5 | Selection override tests a *rounded* ratio | Medium | Confirmed |
| M-6 | Severity sweep emits alerts never published or counted | Medium | Confirmed |
| M-7 | Wall-clock windows where `data_reference_time()` is required | Medium | Confirmed (pipeline) |
| M-8 | Unbounded `COUNT(*)` / offset over the 2.9M-row table | Medium | Partly delegated |
| L-1 | `LIKE` wildcards unescaped in query filters | Low | Delegated |
| L-2 | Path containment is a prefix test without a separator | Low (Suspected) | Confirmed pattern, not exploitable as-is |
| L-3 | GET seeds the asset registry on an unseeded install | Low | Confirmed |
| L-4 | `current_max_frp` nullable in the model, unguarded in arithmetic/formatting | Low | Confirmed (latent) |
| L-5 | Dead code, deprecated APIs, stub statistics | Low | Confirmed |
| H-8 | INV-3 sovereign mask rejects large tracts of real Indian territory | High | Confirmed (predicate executed) |
| M-9 | Cluster→incident mean FRP double-counts and is non-idempotent | Medium | Confirmed |
| M-10 | `incident.updated` audit events appended on every pass | Medium | Confirmed |
| M-11 | `external_id` not unique; dedup is a racy read-then-insert | Medium | Confirmed |
| M-12 | State machine accepts arbitrary status strings | Medium | Confirmed |
| M-13 | `frontend/server.py` cannot serve 4 of the 6 endpoints the console calls | Medium | Confirmed |
| M-14 | Destructive maintenance scripts run with no guard or confirmation | Medium | Confirmed |
| L-6 | Stored-XSS sinks in `render.js` / `dossier.js` (latent) | Low | Confirmed sink, untainted path |
| L-7 | Dead UI element ids; features silently never render | Low | Confirmed |
| L-8 | Frontend presents summed FRP as a "Total", contradicting its own INV-2 rule | Low | Confirmed |
| L-9 | Continuous 24 h sites counted only as day passes | Low | Confirmed |
| L-10 | Undefined CSS custom properties; dead rules | Low | Confirmed |
| L-11 | Backend roll-ups parsed then never rendered | Low | Confirmed |
| L-12 | Vacuous test assertions; tests perform live network I/O; fixture leaks | Low | Confirmed |

---

## High

### H-1 — INV-4's chronic-source clamp never fires on the path the pipeline actually uses

`severity/scoring.py:441-444` gates chronic suppression on `active_days_365 >= 90`. The value arrives from `severity/service.py:65`:

```python
active_days = base_dict.get("active_days_365d", base_dict.get("active_days", 0)) or 0
```

`behavior/baseline.py` has **three** return paths and they do not agree on this key:

| Path | Returns `active_days`? | Line |
|---|---|---|
| `ThermalClimatology` cell | `active_days_365d` | `baseline.py:288` |
| Fresh observation scan | `active_days` | `baseline.py:398` |
| `HistoricalBaseline` 24 h cache shortcut | **neither** | `baseline.py:233-251` |

The cache-shortcut dict contains `spatial_key, window_days, observation_count, median_frp, p90_frp, p95_frp, mean_frp, min_frp, max_frp, history_reliability, history_reliability_label, is_persistent, is_routine_flare, site_classification_hint, is_mining_basin, is_metallurgical_facility, nearest_asset` — **no active-day count of any name**. So `service.py:65` yields `0`, `is_chronic` is `False`, and the clamp is skipped.

The shortcut is guarded by `and not is_flare_fac` (`baseline.py:211-213`). That guard protects the *flare* path — but the chronic clamp was written for **non-flare** chronic sources (steel plants, coal basins), which is exactly the set that *does* take the shortcut.

And the pipeline warms that cache before scoring: `orchestration/pipeline.py:1639-1643` calls `get_or_create_facility_baseline(...)/get_or_create_location_baseline(..., window_days=365)` for every synced incident (Stage 6), then Stage 10 (`pipeline.py:1805`) calls the same helper for the same incidents. The second call hits the `< 86400 s` shortcut for any non-flare site, so `active_days` arrives as 0.

**Impact.** The `CHRONIC_SOURCE_SUPPRESSION` clamp — whose justification comment (`scoring.py:42-72`) states it was written because "12 of the 19 CRITICAL incidents sat BELOW their own cell's P95 … India's largest steel plants, each publishing 'IMMEDIATE EMERGENCY DISPATCH' against a blast furnace" — is inert for those very incidents. It is reachable only on cold-cache evaluations (`run_severity_sweep`, or `POST /api/severity/evaluate/{id}` after 24 h). The same incident can score differently depending on whether a cache row happens to be fresh.

Note also that the mitigation comment at `service.py:59-64` diagnoses the **opposite** failure direction ("Reading only one would silently disable suppression whenever the cache is cold"). Both named keys are read; the path that returns *neither* is the one that was missed.

**Fix.** Have the cache branch return the stored active-day count (or read `BehaviorProfile.active_days` / recompute), and give `service.py` a fallback rather than defaulting to 0.

---

### H-2 — The chronic clamp can demote a spec-mandated forced CRITICAL to LOW

`severity/scoring.py` computes overrides (406-415), applies them as a forced **minimum** with tier floors (417-423), and *then* applies the composite clamp (448-470), which sets `forced_level = None` and re-bands the level:

```python
if routine_suppressed:
    ...
    final_score = min(20.0, final_score)
    final_level = score_to_level(final_score)
    forced_level = None
```

Worked case (arithmetic reproduced against `scoring.py`):

- FRP 50 MW, P95 100 MW, median 40 MW, `industrial_fire` at `C_AI` 90 %, inside a high-hazard facility, cell active 200 days with 500 observations.
- `S_FRP_calib = 25·log2(50/4.05+1) = 93.45`; `S_dev = 50·0.5 = 25.0`; `S_AI = 92·0.9 + 50·0.1 = 87.8`; `S_GIS = 95.0`
- `S_raw = 0.35·93.45 + 0.30·25.0 + 0.20·87.8 + 0.15·95.0 = 72.02` → HIGH
- Override "Industrial Catastrophe" (`scoring.py:250-252`) fires → `final_score = max(72.02, 80.0) = 80.0`, level CRITICAL
- `is_chronic = True` (200 ≥ 90, 500 ≥ 30); `spike_bar = 3.0`; `50 >= 300` is False → not anomalous → `routine_suppressed = True`
- **`final_score = min(20.0, 80.0) = 20.0` → published LOW**

Spec `V2_LOGIC_SPECIFICATION.md:296` mandates CRITICAL/80.0 for that trigger. The code's own comment at `scoring.py:388-401` states the contract it breaks: *"Operational overrides raise the level, they never lower it."* INV-4 is scoped to persistent **flares**; the `is_chronic` disjunct has no counterpart in the specification (the comment at `scoring.py:435-440` acknowledges the widening as deliberate, but does not consider its interaction with overrides).

Secondary reporting defect in the same block: `override_reasons` still contains `"INDUSTRIAL_CATASTROPHE_OVERRIDE … -> CRITICAL"` while the published level is LOW, so `has_override` is `True` with a reason string that contradicts the record.

**Fix.** Restrict the composite clamp to `is_routine_flare` per §4.6/INV-4, or at minimum exempt forced-CRITICAL / `industrial_fire` assessments.

---

### H-3 — `S_FRP_eff` uses the calibrated curve unconditionally; the spec says otherwise

`severity/scoring.py:368`:

```python
effective_frp_score = india_calibrated_frp
```

Spec `V2_LOGIC_SPECIFICATION.md:273`, verbatim:

> 1. **Effective FRP Score ($S_{FRP\_eff}$):** Uses $S_{FRP\_calib}$ for routine flaring facilities; uses $S_{FRP}$ otherwise.

`calculate_frp_severity` is still computed (`scoring.py:326`) and persisted as `frp_score`, but never enters `raw_score`. Magnitude at FRP 10 MW: raw `25·log2(11) = 86.45` vs calibrated `25·log2(10/4.05+1) = 44.74` — 41.7 points of a term weighted 0.35, i.e. 14.6 composite points, applied to **every non-routine assessment**.

The code comment at `scoring.py:341-368` argues at length for the unconditional choice (consistent absolute curve across Models A and B) but **never addresses §4.6.1's explicit rule**, which names the gate it removes. Either the spec must be amended or the code reverted; as it stands the implementation contradicts its authoritative document on a factor weight of 0.35, and the divergence is invisible from the spec.

---

### H-4 — Every mutating endpoint is unauthenticated; the auth helper is dead code

`app/core/security.py:13-28` defines `verify_api_key`. A grep across `app/` for `verify_api_key` returns **only** `security.py` itself — no router imports it, no route declares `Depends(verify_api_key)`. `API_KEY_AUTH_ENABLED` (default `False`) is therefore inert: setting it to `True` changes nothing.

Every state-changing route is publicly reachable:

| Route | Effect |
|---|---|
| `POST /api/analysis/run`, `POST /analysis/run` | full pipeline run; up to `max_ai_targets` billed OpenRouter calls |
| `GET /api/trigger-sync-stream` | spawns a full pipeline run in a background thread |
| `POST /api/trigger-sync` | full pipeline run |
| `POST /api/observations/ingest` | ingest from a server-side path (see H-5) |
| `POST /api/industries/seed` | registry write |
| `POST /api/history/refresh` | history rebuild |
| `POST /api/incidents/{id}/state` | incident lifecycle mutation |
| `POST /api/incidents/cluster-sync` | cluster/incident rebuild |
| `POST /api/severity/evaluate/{id}`, `POST /api/investigation/{id}` | re-scoring / re-investigation (billed) |
| `POST /api/alerts/{id}/{ack,acknowledge,resolve,dismiss}` | alert lifecycle mutation |

This compounds with CORS: `main.py:31-37` sets `allow_origins=settings.CORS_ORIGINS` with `allow_credentials=True`, and `config.py:83` defaults `CORS_ORIGINS = ["*"]`. Starlette echoes the request `Origin` (rather than `*`) when credentials are allowed, so **any web page a visitor loads can drive these endpoints cross-origin from their browser**.

**Impact.** Cost (each run makes billed vision calls), state mutation, and a publicly-defacable demo. On the shipped Render deployment (`render.yaml:8`) this is live.

**Fix.** Declare `dependencies=[Depends(verify_api_key)]` on the mutating routers, default `API_KEY_AUTH_ENABLED=True`, and restrict `CORS_ORIGINS`.

---

### H-5 — Caller-controlled server-side file path is opened without containment

`app/api/observations.py:141-148` → `app/ingestion/firms.py:137-144`:

```python
if payload.file_path:
    stats = client.ingest_from_file(db, payload.file_path, ...)
# firms.py:141
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()
```

The same parameter reaches the pipeline from `AnalysisRunRequest.file_path` (`api/analysis.py:40`) → `execute_analysis_pipeline(..., file_path=...)` → `pipeline.py:1557-1558` (`if os.path.exists(file_path)`). There is no allow-list, no containment under a fixtures directory, and (per H-4) no authentication.

**Impact — stated precisely.** The process will **open and read any path the process can read** (`backend/.env`, `backend/data/firex_v2.db`, `/etc/passwd`, `C:/Windows/win.ini`). The content reaches the caller **only** if it parses as FIRMS CSV: `RawFIRMSObservation` (`ingestion/validator.py:8-27`) requires `latitude`, `longitude`, `acq_date`, `acq_time`, `satellite`; coordinates must be in range and pass the India filter (`firms.py:97`); and `ObservationResponse` (`api/observations.py:23-38`) does **not** expose `raw_payload`, so arbitrary CSV columns are not returned either. This is therefore an arbitrary-file **read** primitive, not general file disclosure — a naive "exfiltrate `/etc/passwd`" exploit does not work, and it should not be reported as though it does. It is still a defect worth fixing: it is a read primitive on an unauthenticated route, and it is one parse-format bug away from being a disclosure.

**Fix.** `os.path.realpath` containment under a configured fixtures directory, plus the auth gate from H-4.

---

### H-6 — GET endpoints write to the database

`_read_cached_location_baseline` (`pipeline.py:150-165`) exists specifically because `GET /api/console/feed` must not write — that fix was applied to the feed. **The same defect class is still live on the history, selection and imagery GETs:**

| GET | Write |
|---|---|
| `/api/incidents/{id}/history` (`api/history.py:59`) | `get_or_create_location_profile` → `db.commit()` (`behavior/profile.py:286`, `:307`) |
| `/api/incidents/{id}/baseline` (`api/history.py:83`) | `get_or_create_location_baseline` → `db.commit()` (`behavior/baseline.py:392`) |
| `/api/incidents/{id}/anomaly` (`api/history.py:113`) | `evaluate_historical_anomaly` → `db.add(HistoricalAnomaly(...)); db.commit()` (`behavior/anomaly.py:168-186`) — **one new row per GET** |
| `/api/industries/{id}/history`, `/baseline` (`api/history.py:182`, `:203`) | profile/baseline commits |
| `/api/selection/candidates` (`api/selection.py:33`) | `select_investigation_candidates` → `get_or_create_*` + `evaluate_historical_anomaly` (`selection/engine.py:88-92`, `:129`) |
| `/api/imagery/incident/{id}` (`api/imagery.py:25`), `GET /crops/...` (`main.py:145`) | render + cache write + tile fetch |
| `/api/industries`, `/api/industries/search` | `seed_industrial_assets` when the table is empty (`gis/assets.py:596`) |

**Impact.** (a) Unbounded row growth driven by unauthenticated read traffic — the anomaly endpoint appends a `HistoricalAnomaly` row every time it is called. (b) GET is neither safe nor idempotent, so any proxy/CDN/browser prefetch can write. (c) On SQLite, every such GET takes a write lock, serialising concurrent readers.

**Fix.** Split each endpoint into a pure-read path plus an explicit `POST .../refresh`, mirroring `_read_cached_location_baseline`; move `seed_industrial_assets` off the read path.

---

### H-7 — `/crops` is exempt from the rate limiter while it renders, fetches tiles and writes

`core/ratelimit.py:29` returns early for `path.startswith(("/console", "/crops", "/docs", "/redoc", "/openapi.json"))`. But `/crops/{incident_id}/{filename}` (`main.py:123-151`) is not a static route: on a cache miss it calls `get_or_create_incident_imagery(inc.id, db)` (`main.py:145`), which fetches map tiles from Google/Esri (`imagery/provider.py`) and writes files + a DB row.

**Impact.** A cache-miss flood is entirely unmetered on the only deployed target: unlimited outbound tile fetches, unlimited PNG rendering, unlimited disk writes — from an unauthenticated endpoint. (The `/console` exemption is benign; `/crops` is not.)

**Fix.** Rate-limit `/crops` (at minimum the dynamic-synthesis branch); exempt only genuinely static prefixes.

---

## Medium

### M-1 — `max_frp` and `mean_frp` are published from the wrong columns, and the branches disagree

`behavior/models.py` does not carry the columns these readers assume:

- `HistoricalBaseline` (`storage/models.py:237-255`) has `median_frp, p90_frp, p95_frp, mean_frp` — **no `max_frp`**.
- `ThermalClimatology` (`storage/models.py:257-272`) has `median_frp, p90_frp, p95_frp, max_frp` — **no `mean_frp`**.

Both readers paper over the gap by substituting a different statistic under the missing key:

```python
# behavior/baseline.py:242  (HistoricalBaseline cache path)
"max_frp": existing_bl.p95_frp or 0.0,          # p95 published as max
# behavior/baseline.py:292  (ThermalClimatology path)
"mean_frp": clim.median_frp or 0.0,             # median published as mean
# orchestration/pipeline.py:181 / :204       (console feed repeats both)
"mean_frp": clim.median_frp or 0.0,
"max_frp": cached.p95_frp or 0.0,
```

Consequences: the **same nominal field means different things depending on which row type the cell has** — `max_frp` is the true max on the climatology path (`baseline.py:294`) and P95 on the cache path; `mean_frp` is the median on both climatology readers. These keys are consumed by the console (`frontend/js/data.js`). A `max_frp` used for display is understated for cache-path cells.

**Fix.** Omit the key rather than aliasing a different statistic, or derive it from the producer; do not publish one column under another's name.

---

### M-2 — Severity-driven lifecycle transitions bypass the transition table and are unaudited

`severity/state_machine.py:23-40` can return `RESOLVED`, `SUBSIDING`, `ESCALATED`, `PERSISTENT`. `incidents/state.py:13-22` does not permit most of those from the states they occur in:

- `VALID_TRANSITIONS["NEW"] = ["INVESTIGATING", "ACTIVE", "RESOLVED"]` — no `PERSISTENT`, `ESCALATED`, or `SUBSIDING`, yet a NEW incident with CRITICAL severity returns `ESCALATED` (`state_machine.py:29-30`) and one 24-48 h stale returns `SUBSIDING` (`:25-26`).
- `VALID_TRANSITIONS["RESOLVED"] = ["ACTIVE", "REOPENED"]` — but a resolved incident with recent detections and CRITICAL severity returns `ESCALATED`.

`severity/service.py:129` assigns directly:

```python
incident.status = next_status
```

It never calls `transition_incident_state`, so no `incident.state_changed` event is written. The `SEVERITY_ASSESSED` payload (`service.py:174-187`) carries `score, level, confidence, model_used, alert_emitted, alert_deduplicated, overrides` — **no status field**. Lifecycle changes therefore leave **no audit trail** on this path, for a platform whose INV-1 is about provenance. (Separately, `transition_incident_state` itself only *warns* on a disallowed transition — `incidents/state.py:59-62` — so the table is advisory even where it is used.)

**Reachable impact.** `POST /api/severity/evaluate/{id}` applies no status filter (`api/severity.py:13-27`), so a RESOLVED incident can be re-evaluated straight to ESCALATED, an undocumented transition, with no event.

---

### M-3 — In-memory cache is unbounded, with attacker-controlled keys

`core/cache.py:10-46`: `_store` is a plain dict with **no maximum size and no eviction sweep**. `get` pops only the key it was asked for (`:23-24`); `set` always inserts (`:33`). A key that is never requested again is retained forever.

Keys are built from free-form query parameters — `industries.py:54` (`facility_type`, `state`, `category`), `industries.py:86` (`q`), `history.py:177/198` (`window_days`, which has **no `le=` bound**). Each unique value is a permanent addition; on the facility endpoints each novel key is also an expensive observation scan to compute.

**Impact.** Memory exhaustion with no authentication required. `cache.size()` is O(n) and is called by `/status`, so a bloated cache also degrades that route.

*(Verification: `cache.py` read in full by me. The key-construction line numbers come from a delegated pass and were not individually re-read.)*

**Fix.** Bound the store (LRU/`maxsize`), sweep expired entries periodically, and constrain key components (`window_days` needs `le=`).

---

### M-4 — The rate limiter collapses to a single global bucket on the deployed platform

`core/ratelimit.py:33` identifies clients solely by `request.client.host`; `X-Forwarded-For` is never read. The app is launched without proxy-header trust:

```
render.yaml:8      python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
Dockerfile:23      ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", ...]
```

uvicorn's default `forwarded_allow_ips` is `127.0.0.1`, which does not include the hosting platform's proxy address, so `request.client.host` is the **proxy's** address for every request — identical for all users.

**Impact.** The documented "per IP address" limiting degenerates into a **single shared 120 req/min budget for the entire deployment**: one abusive client throttles every legitimate operator, while no individual attacker is bounded. This inverts the stated Stage-10 hardening intent. (Note: the fix is not simply to trust the header — with `forwarded_allow_ips="*"` the limiter becomes trivially bypassable. The header must be trusted only from the platform proxy's known range.)

*(Verification: middleware and launch commands read. The uvicorn default is from documented behaviour, not executed here.)*

---

### M-5 — Selection override tests a rounded ratio

`selection/scoring.py:131` rounds before the comparison at `:92`:

```python
frp_ratio = round(frp_mw / max(1.0, historical_median_frp), 2)   # :131
...
if frp_ratio >= 3.0:                                             # :92 → STRONG_HISTORICAL_ANOMALY
```

Any true ratio in `[2.995, 3.0)` rounds to 3.0 and fires the override, forcing `final_priority >= 90.0`. Spec §4.5:242 requires the raw quotient.

This is the **same defect class that `behavior/anomaly.py:135-141` explicitly fixed and documents** ("Rounding it to 2 decimals *before* the lookup made the classification depend on presentation rounding: 1.254 collapsed to 1.25 and scored 10 where the spec's '> 1.25 - 1.5x' row gives 20"). The fix was not propagated to the sibling module. Low harm, but it demonstrates an incomplete remediation of a known defect.

---

### M-6 — Severity sweep emits alerts that are never published or counted

`pipeline.py:1858` calls `run_severity_sweep(db)` outside the Stage-11 alert loop. Each swept incident reaches `evaluate_and_emit_alert` (`severity/service.py:161`), which can create a real `AlertRecord`. Only the Stage-11 loop (`pipeline.py:1827-1848`) publishes `EVENT_ALERT_CREATED` and increments `alerts_emitted`.

**Impact.** Alerts created during the sweep are absent from the operator's SSE feed and from `AnalysisRun.alerts_count` / `summary.alerts_emitted` — the stream under-reports dispatched alerts, which is the opposite of what §10's exactly-once contract is for.

---

### M-7 — Wall-clock windows where the archive clock is required

`core/clock.py` provides `data_reference_time(db)` and documents that callers must not re-derive the reference instant; `severity/service.py:113-116` uses it correctly. But:

```python
# orchestration/pipeline.py:1596-1601   (Stage 3, "active observations (72 h)")
time_cutoff = datetime.utcnow() - timedelta(hours=72)
active_obs = db.query(Observation).filter(Observation.acquired_at >= time_cutoff).all()
if not active_obs:
    active_obs = db.query(Observation).order_by(Observation.acquired_at.desc()).limit(50).all()
```

The same wall-clock cut-off appears at `api/incidents.py:159` (cluster-sync) and `api/history.py:139-140` (trend window).

**Impact on the shipped archive.** Against a stored archive whose newest detection is days or weeks behind the wall clock, the 72 h query returns nothing and the code **silently substitutes the newest 50 observations** — an unrelated sample. Stage 3/4 then cluster a different detection set than the specification's "Active observations (72h)" describes, without logging the substitution.

*(Verification: `pipeline.py:1596-1604` read by me — confirmed. The `clock.py` contract and the specific newest-detection date come from a delegated pass.)*

**Fix.** Derive the cut-off from `data_reference_time(db)` in all three sites.

---

### M-8 — Unbounded `COUNT(*)` and offset over the 2.9M-row table

- `api/analysis.py:314-315` (`GET /api/history-stats`): `db.query(Observation).count()` on every call — an unindexed full scan of the 1.2 GB table, unauthenticated. *(Read by me — confirmed.)*
- `api/history.py:364-401` (`GET /api/history/search`): unconditional `q.count()`, an unbounded `offset` (`Query(0, ge=0)`), `max_scan_limit = max(offset + limit * 5, 2000)` which scales with the caller's offset, and a per-row `find_nearest_asset` call. *(Delegated pass; not re-read by me.)*

**Fix.** Cache/maintain the observation count; bound `offset`; make `count()` opt-in; batch the per-row enrichment.

---

## Low

**L-1 — `LIKE` wildcards unescaped.** `observations.py:71`, `industries.py:65-67/94-105`, `incidents.py:98` interpolate caller strings into `ilike(f"%{value}%")`. Not SQL injection (values are bound), but `%` and `_` act as wildcards: `?satellite=%` matches every row, turning a targeted filter into a full scan. *Delegated pass.*

**L-2 — Path containment is a prefix test without a separator.** `main.py:126-127` and `api/imagery.py:86-88` test `file_path.startswith(V2_CROPS_DIR)`. Since no trailing separator is required, a sibling directory whose name extends the cache directory name (`imagery_cache_x`) would pass. Plain `../` traversal is correctly blocked (`abspath` collapses it, then the test fails). **Suspected**, not exploitable on a stock tree — no such sibling exists. Fix: compare against `os.path.join(root, "")` or use `os.path.commonpath`.

**L-3 — GET seeds the asset registry on an unseeded install.** `gis/assets.py:593-597` calls `seed_industrial_assets(db)` (which commits, `:571`) from `get_cached_assets`, reached from `find_nearest_asset` on read paths. Only fires when the table is empty. Move it behind the existing `POST /industries/seed`.

**L-4 — `current_max_frp` is nullable in the model but used unguarded.** `storage/models.py:66` declares no `nullable=False`; it is consumed unguarded in arithmetic (`scoring.py:96`, `:109` via `severity/service.py:88`) and in f-string formatting (`alerts/engine.py:112`, `:161`). A NULL row raises `TypeError` and aborts the severity pass. In practice ORM inserts apply `default=0.0`, so this is latent — it requires a row written by migration or raw SQL. Adding an explicit `None → 0.0` coercion at the read points would close it.

**L-5 — Hygiene.**
- Dead imports: `calculate_frp_severity`, `IndustrialAsset` in `pipeline.py:51`; `SEVERITY_LEVELS` unused (`scoring.py:16-21`); `hazard_category` is an unused parameter of `calculate_gis_context_severity` (`scoring.py:186-198`).
- `RATE_LIMIT_BURST` (`config.py:91`) is never read — the limiter is a flat fixed-window count.
- `orchestration/events.py:3-4` docstring says "11 blueprint event types"; the module defines and emits 12.
- `GET /api/history-stats` returns hardcoded `"unique_dates": 365`, `"cadence"`, `"overpass_times"` (`analysis.py:323-327`) as though measured — stub data presented as statistics.
- `@app.on_event("startup"/"shutdown")` (`main.py:174`, `:186`) is deprecated in current FastAPI; use the lifespan context.
- `datetime.utcnow()` throughout (~2,900 `DeprecationWarning`s in one suite run).
- The pipeline lock (`orchestration/lock.py`) is a process-local singleton: under multiple uvicorn workers, concurrent `POST /api/analysis/run` runs are possible. Correct within one process (verified: `acquire` raises on contention, `release(run_id)` refuses a mismatched id, released in `finally` on every exit path).

---

## Spec-conformance divergences (summary)

| Spec | Implementation | Finding |
|---|---|---|
| §4.6.1 line 273: `S_FRP_calib` only for routine flaring facilities | calibrated curve used unconditionally (`scoring.py:368`) | H-3 |
| §4.6 line 303 + code comment: overrides raise, never lower | chronic clamp demotes a forced CRITICAL (`scoring.py:448-470`) | H-2 |
| §4.5 line 242: `R_frp >= 3.0` on the raw quotient | rounded to 2 dp first (`selection/scoring.py:131`) | M-5 |
| INV-4 scoped to persistent flares | widened to any chronic source, and inert on the pipeline path | H-1, H-2 |
| §3 stage 3 "Active observations (72h)" | wall clock, silent 50-row fallback | M-7 |

---

## Verified clean (checked and found sound)

These were examined specifically and are **not** defects — listed so the audit's coverage is legible and so these are not re-reported:

- **No SQL injection.** The only raw SQL is `text("SELECT 1")` (`storage/database.py:61`); every filter is an ORM expression with bound parameters.
- **INV-2 (no FRP summation).** The pipeline reads `incident.current_max_frp` only; no total-FRP key is published anywhere.
- **Imagery geometry.** Hand-verified: at lat 22.025°/zoom 16, `m/px = 156543.03392·cos(22.025°)/2^16 = 2.2145`; a 640 px crop covers 708.7 m; reticle rings at 0.4/0.8 × frame radius land at 283.5 m / 566.9 m — 40 %/80 % of true coverage; the 200 m scale bar is 90 px against a 398 px budget. `determine_zoom_for_radius` minimises |coverage − request| and reports `radius_m` from the *derived* coverage, not the nominal request (`imagery/viewport.py:28-104`).
- **Concurrency in the pipeline.** `KeyPoolManager` is fully lock-guarded — every mutator takes `self.lock` (`intelligence/key_pool.py:100-242`). The `ThreadPoolExecutor` (`pipeline.py:1750-1769`) parallelises **AI calls only**, with `max_workers = min(len(tasks), pool_size)`, and each worker uses the provider, not a DB session. Severity and alert evaluation run **serially** in the main thread (`pipeline.py:1805`), so INV-6's read-then-insert is not raced. I looked for this specifically and found no defect.
- **Alert engine.** Eligibility (`engine.py:17`, `:80`), the escalation-close of the superseded alert (`:119-126`, fixing F-012), the dedup path writing no row and marking `is_new=False` (`:151-152`), and the transition table with both terminal states (`:36-41`) are sound.
- **Factor reconciliation.** `_weighted_risk_factors` (`pipeline.py:405-529`) reads the engine's own `frp_curve` marker and reproduces the curve choice exactly; legacy records without the marker fall back to the old `is_routine_flare` rule, which matches the pre-change engine (`:473-477`). Rows are apportioned to the published (1-dp) score so they sum exactly.
- **Weights and bands.** Severity Models A/B (`0.35/0.30/0.20/0.15`, `0.50/0.30/0.20`) and selection models (`0.40/0.30/0.20/0.10`, `0.45/0.30/0.25`) each sum to 1.00 and match §4.5/§4.6; `score_to_level` boundaries (25/50/75) and tier floors (10/30/55/80) match; the level is re-banded from the *rounded* published score so a record cannot contradict itself (`scoring.py:480`).
- **Secrets.** `/health` and `/status` expose only booleans and a key *count*; `check_db_connection` strips credentials via `split("@")[-1]`; key identifiers log only a 14-char prefix. No secret material is served.
- **Test isolation.** `tests/conftest.py` binds a throwaway DB before any `app.*` import, refuses to run against the live DB, redirects all five in-repo write targets, and **asserts** each rebind took.
- **Two suspicions I withdrew after checking** (recorded so they are not "re-found" later):
  - `pipeline.py:1629` `(datetime.utcnow() - (i.created_at or i.first_detected_at))` **cannot** raise: `first_detected_at` is `nullable=False` (`storage/models.py:63`), so the `or` always yields a datetime.
  - `evaluate_severity_overrides` matching only `industrial_fire` (not `uncontrolled_industrial_fire`) is **not** a defect: spec `V2_LOGIC_SPECIFICATION.md:282` states that key is unreachable in this tree.

---

## Part 2 — Subsystem passes (ingestion/GIS/incidents, frontend, tests/scripts/deploy)

### H-8 — INV-3's sovereign polygon mask rejects large tracts of real Indian territory

`gis/boundaries.py:236` gates every detection on `point_in_geojson_geometry(lat, lon, INDIA_SOVEREIGN_MASK)`, whose ring is the hand-traced `INDIA_MAINLAND_RING` (`boundaries.py:85-122`). The docstring calls it the "high-fidelity polygon mask", but several chords cut well inland of the real border and coastline.

**Verified by executing the shipped predicate** (`python -c "from app.gis.boundaries import is_within_indian_sovereign_territory as f; ..."`):

| Location | Result | Expected |
|---|---|---|
| Lachen, North Sikkim (27.72, 88.56) | **False** | True |
| Lachung (27.69, 88.75) | **False** | True |
| Chungthang (27.60, 88.65) | **False** | True |
| Tawang, Arunachal (27.59, 91.86) | **False** | True |
| Ziro (27.59, 93.83) | **False** | True |
| Daporijo (27.99, 94.22) | **False** | True |
| **Hazira ONGC / AM-NS Steel — the code's own registry entry (21.103, 72.649)** | **False** | True |
| Paradip / IOCL refinery (20.26, 86.66) | **False** | True |
| Kakinada (16.99, 82.25) | **False** | True |
| Machilipatnam (16.17, 81.13) | **False** | True |
| Kannur (11.87, 75.37), Alappuzha (9.50, 76.34), Kozhikode (11.25, 75.78) | **False** | True |
| Gangtok, Surat, Delhi, Mumbai, Kolkata/Haldia | True | True |

The ring vertices that cause it: the Sikkim segment `[88.15, 27.9] → [88.9, 27.3]` (`:96`) drops below 27.6 N east of 88.3 E; the Arunachal chord `[92.5, 27.5] → [94.0, 27.5]` (`:99`) sits ~50–90 km south of the McMahon line; the Gujarat coast chord `[72.75, 19.0] → [72.55, 20.6] → [72.9, 21.4]` (`:113`) runs east of the Surat/Hazira shoreline.

**Blast radius.** The predicate is load-bearing at six sites, so a detection in any of these places is dropped at *every* layer:
`ingestion/firms.py:97` (never stored), `orchestration/pipeline.py:1604` (`active_obs`), `:675` (console export), `:1306` and `:1357` (queue), `:1411` (severity sweep), `incidents/association.py:116` (cluster membership).

**Impact.** No incident or alert can ever be raised for a fire in North Sikkim, most of Tawang/Ziro/Daporijo, or the Hazira–Surat industrial belt — and Hazira is in the platform's own industrial registry (`gis/assets.py`), so the code carries an asset it can never associate. Whole districts are silently outside the mandate.

**Correction to a delegated claim.** The delegated pass also reported that the ring "admits open sea inside its chords (e.g. `(13.0,80.3)` ~25 km off Chennai)". I tested five genuinely offshore points — Bay of Bengal off Paradip (20.0, 87.2), off Chennai (13.0, 80.9), Arabian Sea off Kochi (9.5, 75.5), off Gujarat (21.0, 71.5), Bay off Kolkata (21.5, 88.3) — and **all five return `False`**. The mask does **not** admit open sea; the defect is one-directional (false negatives only). The single reported sea point sits on the Chennai shoreline.

**Fix.** Re-trace the Sikkim, Arunachal and west-coast vertices onto the real border/coastline and add the towns above as regression points; the mask is the sole enforcement of INV-3, so its errors are the platform's errors.

---

### M-9 — Cluster→incident mean FRP double-counts already-linked observations and is non-idempotent

`incidents/association.py:148-155`:

```python
matched_inc.current_max_frp = max(matched_inc.current_max_frp, cluster.max_frp)
old_count = matched_inc.observation_count or 1
new_count = len(cluster.observations)
total_count = old_count + new_count
matched_inc.current_mean_frp = round(
    (matched_inc.current_mean_frp * old_count + cluster.mean_frp * new_count) / max(1, total_count), 2
)
```

`old_count` is the incident's *total* linked observations, while `new_count`/`cluster.mean_frp` describe **all** cluster members — including ones already linked to this incident (skipped by the `exists` check at `:248-256`) and any member belonging to a different incident. Line 114 further shows the cluster is filtered to `sovereign_members` for the incident, but `:151` still counts the unfiltered `cluster.observations`.

The pipeline re-clusters the entire 72 h window every run (`pipeline.py:1597,1616`) and `POST /api/incidents/cluster-sync` does the same, so this runs even when nothing new is linked.

**Arithmetic, verified:** incident with member A = 100 MW (mean 100, count 1); next pass cluster = {A = 100, B = 10} (cluster mean 55) → stored mean `(100·1 + 55·2)/3 = 70.0`, true member mean 55.0. A following no-op pass gives 62.5, then 58.75 — `current_mean_frp` is both wrong and non-idempotent, and it feeds selection, severity and the console.

### M-10 — `incident.updated` audit events are appended on every pass

`association.py:168-178` writes the event unconditionally for every matched cluster, whether or not an `IncidentObservation` row was created (the link loop at `:246-265` skips duplicates, but the event is already queued). Repeated runs over an idle 72 h window append one row per incident per run; `incident_events` grows without bound and `GET /api/incidents/{id}` returns an ever-longer timeline of identical "updated" events. Emit only when at least one link was inserted.

### M-11 — `observations.external_id` has no unique constraint; dedup is a racy read-then-insert

`storage/models.py:31`: `external_id = Column(String, nullable=True, index=True)` — indexed, **not** unique. SHA-256 dedup (spec stage 2) is enforced only in Python (`ingestion/firms.py:86-106`: read the existing id set, then insert the ones not present). The pipeline holds `pipeline_lock`, but `POST /api/observations/ingest` (`api/observations.py:134-158`) and `POST /api/incidents/cluster-sync` take no lock, so two ingests — or an ingest racing a pipeline run — can both read "not present" and both insert the same `external_id`. Duplicates then double-count in cluster `observation_count`, inflate `mean_frp`, and double-weight one pixel in `firms_confidence`. Add `unique=True` and handle `IntegrityError`.

### M-12 — The state machine accepts arbitrary status strings

`incidents/state.py:58-65` (and see M-2): `new_state` is unvalidated (`StateTransitionRequest.new_state: str`, `api/incidents.py:72-74`). `POST /api/incidents/{id}/state {"new_state":"GARBAGE"}` persists `status="GARBAGE"`; `VALID_TRANSITIONS.get("GARBAGE", [])` is `[]`, so every later transition on that incident is flagged "unusual", and console/severity queries filtering on the enum silently miss it. Reject a `new_state` not in `VALID_STATES` with 422.

### M-13 — `frontend/server.py` cannot serve four of the six endpoints the console calls

`frontend/server.py:55-177`'s `do_GET` handles only `/api/health`, `/api/history-stats`, `/api/trigger-sync-stream`, `/api/trigger-sync`. The console calls `/api/console/feed` (`data.js:52`), `/api/industries?limit=500` (`data.js:116`), `/api/industries/{id}/history` (`main.js:439`) and `/api/history/search` (`main.js:498`); none are handled, so each falls through to the static handler and 404s. Yet `server.py`'s own banner and the console's error text (`main.js:737`: *"Start the console through server.py, then reload"*) both direct the operator to it. Following that instruction demotes the console to the stale committed JSON (`data.js:79-108`), leaves the industrial register empty, and makes history search always fail. Either add the routes or correct the launcher instruction to `backend/run.py`.

### M-14 — Destructive maintenance scripts run with no guard or confirmation

All confirmed by reading the scripts:

| Script | Hazard |
|---|---|
| `scripts/seed_cloud_db.py:96` | `TRUNCATE TABLE "{table}" CASCADE` against the DSN defaulted from `DATABASE_URL` (`:203`), with `--wipe` needing no confirmation or backup. `SEED_TABLES` omits `historical_anomalies`, which has FKs to truncated tables, so `CASCADE` empties it permanently and the seeder never repopulates it. |
| `scripts/build_thermal_climatology.py:281-290` | `DELETE FROM thermal_climatology` against the live DB, then bulk insert, with no `--yes`/dry-run — and no guard against `aggregate_thermal_cells` returning `{}`, which would commit an empty climatology table that every suppression rule reads. |
| `scripts/clean_foreign_and_refresh.py:38` | `Observation.latitude > 35.7` deletes valid Ladakh/J&K/Himachal detections; the sovereign envelope is 8.4–37.6 N (`boundaries.py:229` explicitly notes the former 35.7 N gate "rejected the 35.7-37.6N band the spec places inside it"). The same script uses the correct predicate for incidents at `:23`. |
| `scripts/refresh_{industrial,mining}_incidents.py` | Overwrite `classification` and `AIInvestigation.reasoning` on production rows, then commit, with no report-only default — unlike `withdraw_unverified_confidence.py`, which defaults to dry-run. |
| `scripts/ingest_history.py:94,108-114,268-274` | Six `DROP INDEX` statements on the 1.28 GB live DB with **no `try/finally`**; an interrupt leaves the DB unindexed until a full re-run completes. |
| `scripts/migrate_climatology_{industrial,mining}.py:15-16` | `sqlite3.connect(settings.DATABASE_URL.replace(...))` with no SQLite guard (the sibling `migrate_schema.py:59-63` raises `SystemExit`). With a Postgres URL it opens a junk local file, sees zero rows, and prints a **false success**. |
| `scripts/inspect_incident.py:1-11`, `check_stage5_coords.py:1-11` | No `if __name__ == "__main__"` guard: importing either executes DB work and prints; the relative path only resolves from the monorepo root. |

### Low — frontend

- **L-6 Stored-XSS sinks (latent).** `render.js:15`'s `set()` assigns `innerHTML`; `render.js:43` interpolates `c.severity?.level` unescaped, and `:228` repeats it inside a `title="…"` attribute. `data.js:290` sources it from the raw `raw.severity_level`. `dossier.js:39` emits values verbatim, and `:220` passes `p.daysActive`/`p.detections`, which `data.js:309-311` do **not** `Number()`-coerce (every other value in that block is). **Caveat:** the current producers constrain these fields — `severity_level` comes from `score_to_level`'s fixed set, and `days_active`/`persistence_detections` are ints — so the sink is real but I found no tainted path to it. Fix by escaping/whitelisting anyway.
- **L-7 Dead UI ids.** `main.js:39-44` grabs `brand-window`, `map-sub`, `rail-counts`, `risk-hist`, `risk-span`, `map-strip`, `in-view`, `q`, `q-clear`, and `:1018` grabs `btn-trigger-sync`. A grep for those ids across `frontend/` returns matches **only** in `main.js` (plus `layout.css:266,270` styling the nonexistent `#rail-counts`) — no `index.html` definition. Every lookup is null-guarded, so nothing throws, but the rail metric tiles, risk histogram, bottom strip, "N in view" readout and the global search box never render. *(I confirmed the absence; the "silently dead, never throws" conclusion follows from the guards at `main.js:726,746,747,758`.)*
- **L-8 FRP presented as a "Total".** `render.js:1926` renders `Total ${fmt.dec(frp.sum)} MW` and `:1942` says `total ${fmt.dec(frp.sum)} megawatts`, where `frp.sum` (`data.js:401`) adds per-incident FRP *maxima*. The same file states the opposite three times — `:589` "INV-2: peak, not a sum", and further at `:1778/1785`. The analytics tab presents a meaningless aggregation the console elsewhere forbids.
- **L-9 Continuous sites counted only as day.** `render.js:596-604` tests `includes("DAY")` then `else if includes("NIGHT")`, so the backend's `"DAY + NIGHT (Continuous 24h)"` (`pipeline.py:1250`) increments only `dayPasses`; a fully continuous window reports 0 night passes. `dayNightOf` (`:23-33`) handles the same string as both.
- **L-10 CSS.** `--signal-fade` (`map.css:619`, `components.css:1292`) and `--line-active` (`components.css:1328`) are used but defined nowhere in `styles/` (grep finds only the three usages) — those declarations are invalid at computed-value time. Plus dead selectors: `#rail-counts` (`layout.css:266,270`), `.mapkey__pop` (`map.css:832`; markup uses `.mapkey__panel`), and `.mapview` grid rules (`layout.css:409`) on a container that is never `display:grid`.
- **L-11 Roll-ups parsed but never rendered.** `data.js:68-73,105-106` populate `store.closedAttention` from `feed.closed_attention`, which the pipeline publishes deliberately (`pipeline.py:1330-1370`) so the console can warn when closed HIGH/CRITICAL incidents still carry open alerts. No reader exists, so the warning never appears.

### Low — tests, scripts and deploy

- **L-12 Vacuous assertions.** `test_stage8_orchestration.py:267` asserts `duration_seconds >= 0.0` (a wall-clock delta that cannot be negative); `:42` imports `EVENT_ALERT_CREATED` but never asserts on it while the docstring claims "all 11 SSE events" (10 are checked); `test_stage6_ai_investigation.py:541-545` asserts `status_code in [200, 404]` against a hard-coded incident the throwaway DB never seeds (an always-404 route passes); `test_stage6:177-190`'s "concurrent threads" key-pool test gives each worker a *distinct* `preferred_idx`, so it passes even with `self.lock` removed; `test_stage10_hardening.py:229,239` assert `is not None` on fields that are plain booleans. Coverage docstrings in `test_industrial_facility_classification.py:8` and `test_mining_basin_classification.py:6-8` claim assertions the bodies do not make (`enrich_coordinate_gis_context` and `build_investigation_package` are imported and never called).
- **Non-hermetic tests.** `test_stage8_orchestration.py:250-261,340-380`, `test_stage10_hardening.py:270-284` run the real pipeline, which fetches Google/Esri tiles (`imagery/provider.py:62,71`) and, at `test_stage8:378` (`POST /api/trigger-sync` with no body), issues a live `requests.get` to NASA FIRMS (`firms.py:41`). Pass/fail depends on external hosts and the local `.env`.
- **Fixture leaks.** `test_stage4_behavior.py:362-377` commits an `ACTIVE` `INC-HIST-TEST-*` incident and its `finally` only closes the session — the same leak class `conftest.py:15-20` documents; `:307-353` persists `BehaviorProfile` rows that cleanup never deletes. `test_stage5_selection_imagery.py:309,446,501` uses second/millisecond-resolution timestamps as primary keys (collision risk; other tests use `uuid.uuid4()`).
- **Deploy.** `v2/render.yaml` is a divergent duplicate of the authoritative root blueprint with **no `rootDir`** (so `pip install -r backend/requirements.txt` resolves to a nonexistent path if selected) and **no `databases:` block** (`DATABASE_URL` is `sync: false`), so the SQLite-default app would run on Render's ephemeral filesystem and lose the 1.4 GB DB on restart. `backend/run.py:22` hardcodes `uvicorn.run(..., reload=True)`, and the README documents it as the start command — a production run gets the file-watcher. `config.py:43-44` defaults `ENV="development"`/`DEBUG=True` and neither blueprint overrides them, so the deployed service logs at DEBUG and serves `/docs`. Runtime pins are lower-bound-only with no lockfile; the root `requirements.txt` comments out `psycopg2-binary`, which `scripts/seed_cloud_db.py:23-24` imports.
- **Secret-adjacent.** `archive/v1/pipeline/04_vision_ai/ai_classifications.json` and the `case_00*/incident_dossier.json` files carry `key_used` values containing the first five characters after `sk-or-v1-` of the four OpenRouter keys (I verified the prefixes match the live key set **without reproducing them**). Not usable secrets, but they leak key count, rotation order and prefixes to anyone with repo read access. `v2/backend/.env` itself is correctly untracked.

---

## Coverage and method limits

- **Read in full by me:** `severity/scoring.py`, `severity/service.py`, `severity/state_machine.py`, `alerts/engine.py`, `intelligence/provider.py`, `intelligence/key_pool.py`, `core/ratelimit.py`, `core/security.py`, `core/cache.py`, `storage/database.py`, `storage/models.py` (structural), `api/analysis.py`, `api/observations.py` (targeted), `imagery/{viewport,reticle,provider,service}.py`, `behavior/{anomaly,trends}.py`, `behavior/baseline.py` (targeted), `selection/{engine,scoring}.py` (targeted), `incidents/state.py`, `ingestion/firms.py`, `ingestion/validator.py`, `gis/assets.py` (targeted), `api/history.py` (targeted), `main.py`, `tests/conftest.py`.
- **Delegated reading passes, now folded in:** ingestion/GIS/incidents, frontend console JS, backend scripts, and the test/deploy surfaces (Part 2). Load-bearing claims from those passes were spot-verified against source before inclusion — the sovereign-predicate results, the `association.py` mean-FRP arithmetic, `render.js`/`data.js` sinks, the missing element ids, the CSS tokens, `seed_cloud_db.py`'s `TRUNCATE`, `clean_foreign_and_refresh.py`'s 35.7 N cutoff, `v2/render.yaml` and `run.py`. **One delegated claim was disproved and is corrected in place** (the "admits open sea" assertion at H-8); a second was narrowed (arbitrary-file-read vs exfiltration, H-5); two of my own suspicions were withdrawn and are recorded under "Verified clean". Claims not individually re-read by me are labelled as delegated in their finding.
- **Still outstanding:** the stage-by-stage test-suite passes (stages 0-4, 5-7, 8-10) and the imagery-module re-cover. Four delegated passes failed with a provider-side error (`400 Content Exists Risk`) on the imagery, behavior and intelligence modules; rather than retry, I audited those modules **directly** — that is why they appear in the "read in full" list above.
- **Not executed:** the live server against the production database, and the AI provider paths (no credentials). Runtime claims are derived from code and configuration, not observed traffic. The one exception is the INV-3 predicate (H-8), which I ran directly against the shipped code.
