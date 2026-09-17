# FIREX v2 — Complete Defect & Conformance Report

**Scope:** every divergence between `V2_LOGIC_SPECIFICATION.md` and the shipped `v2/` implementation, plus independent defects found during adversarial review.

**How this was produced.** A dynamic multi-agent audit ran 24 agents across 11 conformance areas. Each area was first audited for spec-vs-code divergence, then handed to an independent adversarial refuter instructed to *disprove* the finding with its own file:line evidence and to default to refuted unless it could confirm the divergence firsthand. A completeness critic then swept for what the first pass missed. Every claim below is one that survived that refutation.

| | |
|---|---|
| Workflow run | `wf_d4771b72-a1f` (task `wznxolp5u`) |
| Agents | 24 completed, 0 errored, 0 empty |
| Claims audited | 98 |
| Survived refutation | **97** |
| Refuted | 1 |

> **Verification caveat — read before acting.** All ten adversarial refuters executed while the safety classifier was unavailable (inference-gateway outage). Their work was therefore not passed through that review layer. This does not affect the *reasoning* recorded here — findings cite concrete `file:line` locations and several reproduce exact arithmetic — but no finding below has been re-verified by a human. Treat each as a strong lead with traceable evidence, not as a settled fact.

---

## How to read this document

Each finding has a stable ID (`F-001` ...), a **defect class**, the **claim** made against the spec, and the **evidence** that confirmed it. Defect classes are assigned mechanically from the area and claim wording and exist only to aid navigation — the claim text is authoritative.

Defect classes present in this report:

- **LOGIC / ALGORITHM DIVERGENCE** — 18 finding(s)
- **INVARIANT VIOLATION** — 15 finding(s)
- **DOCUMENTATION DEFECT** — 13 finding(s)
- **SCHEMA / API CONTRACT DRIFT** — 11 finding(s)
- **SPEC / CODE DIVERGENCE** — 10 finding(s)
- **TEST DEFECT** — 10 finding(s)
- **STATE MACHINE / CONTRACT DEFECT** — 7 finding(s)
- **UNIT / SCALE ERROR** — 7 finding(s)
- **AI PROTOCOL / DEAD CODE** — 6 finding(s)

### Findings by subsystem

| Area | Findings |
|---|---|
| Tests & Documentation | 23 |
| System Invariants (INV-1 .. INV-6) | 14 |
| Database Schema & REST/SSE API | 11 |
| Behaviour / Baseline Modelling | 10 |
| Alerts & Imagery Reticle | 8 |
| Severity Scoring | 8 |
| Multimodal AI Protocol | 7 |
| Geodesy & Spatial Predicates | 5 |
| Candidate Selection & Prioritisation | 5 |
| Climatology Constants & Calibration | 3 |
| Spatio-Temporal Clustering | 3 |

---

## Part 1 — Critical items the primary sweep missed

Produced by a completeness critic that ran after the first pass, tasked with finding what had *not* been examined. Ordered in the source by how quickly a reviewer or judge would hit it.

FINDINGS THE PRIOR SWEEP MISSED (new, each cited). Ordered by how fast a judge hits it.

**1. FATAL: the repo cannot boot from a fresh clone.**
`C:\Users\ssaur\OneDrive\Desktop\PS162\.gitignore:24-26` ignores `config.py` and `**/config.py`. Grepping the git index directly (`C:\Users\ssaur\OneDrive\Desktop\PS162\.git\index`) matches `app/core/cache.py`, `app/core/logging.py`, `app/core/ratelimit.py`, `app/core/security.py` and **zero paths matching `*config*.py` anywhere in the repo**. `C:\Users\ssaur\OneDrive\Desktop\PS162\v2\backend\app\core\config.py` (untracked) holds every constant — `DATABASE_URL`, `FIRMS_MAP_KEY`, the AI model id, the four OpenRouter keys, rate limits — and is imported by `app\main.py:6`, `app\intelligence\provider.py:14`, `app\behavior\baseline.py:16`. A clone + `pip install -r requirements.txt` + `python run.py serve` dies at `from app.core.config import settings`. The only config artifact that IS tracked is `v2\backend\.env.example`, and it is byte-identical to `.env` (448 B) — so the live `FIRMS_MAP_KEY` is committed to the repo while the file the code actually imports is not.

**2. Nine test fixtures are live in the served queue and in the committed frontend data.**
`incidents` table: 9 rows with codes `INC-HIST-TEST-1789391301 … INC-HIST-TEST-1789581117`, all `status='ACTIVE'`, all `classification='INDUSTRIAL_FIRE'`, all `classification_confidence=0.0`, none with an `ai_investigations` row. They are published right now in `GET /api/console/feed` (measured class histogram: `'INDUSTRIAL_FIRE': 9`) and baked into the committed fallback `C:\Users\ssaur\OneDrive\Desktop\PS162\v2\frontend\data\incidents.json` (9 of 323 records), where they carry `ai_classification: "INDUSTRIAL_FIRE"`, `ai_confidence: 0.85` and `ai_reasoning: "Verified thermal source classification: INDUSTRIAL_FIRE."` despite confidence 0.0 in the DB. Two consequences: (a) `CLASSES` in `C:\...\v2\frontend\js\config.js:40-49` has no uppercase key, so `classOf()` (`config.js:53-55`) returns `UNKNOWN_CLASS` = "Not visually confirmable" with the question glyph for all 9, and `FILTERS` (`config.js:61`) tests only the lowercase id, so they are unreachable from the Industrial filter; (b) root cause is missing test isolation — `C:\...\v2\tests\conftest.py` overrides `sys.path` only and never sets `DATABASE_URL`, so a test run writes into whichever `firex_v2.db` the CWD resolves to.

**3. The severity engine's output was never persisted for the live queue, and the published factor breakdown contradicts the published score.**
Of 323 feed records: **320 have `severity_score=0`, `risk_score=0`, `severity_confidence=0`** yet are issued `risk_tier`, `action_recommendation`, `investigation_priority` (e.g. 69.5) and `priority_rank`. **All 323** have `sum(risk_factors[].score) != risk_score` (largest: 175.9 vs 42). And 7 factor entries exceed their own declared maximum — `INC-2026-0278` publishes `{"factor":"Frp Score","score":45.2,"max":25.0}`, `{"Historical Deviation Score",47.5, 20.0}`, `{"Ai Source Severity Score",50.0, 30.0}`. So the dossier's "why this score" bars overflow their own caps while the headline reads Risk 0 / LOW.

**4. The console shows zero HIGH/CRITICAL, while the alert feed fires CRITICAL alerts at incidents it cannot display.**
DB `incidents.severity_level`: CRITICAL 5, HIGH 5 — every one of them `status` in {RESOLVED, SUBSIDING}. `generate_console_feed_data` (`C:\...\v2\backend\app\orchestration\pipeline.py:74-76`) whitelists only ACTIVE/PERSISTENT/INVESTIGATING/NEW/ESCALATED, so the feed's measured tier histogram is `{LOW: 322, MEDIUM: 1}` with 0 HIGH/0 CRITICAL. Meanwhile `alert_records` holds exactly those 5 CRITICAL + 5 HIGH as `NEW`, pointing at the same incident ids — the alert panel links to incidents absent from the map and the priority queue. A "priority triage console" that shows a uniform LOW queue while holding live CRITICAL alerts is the first thing a judge clicks.

**5. `logger` used but never bound, in the pipeline's own error handler.**
`C:\...\v2\backend\app\api\analysis.py:233` — `logger.error(f"[PipelineWorker] Error during sync stream execution: {e}", exc_info=True)` inside the `except` of the background worker behind `GET /api/trigger-sync-stream` (the console's Sync button, `frontend\js\main.js:971`). A re-scan of every `app/**/*.py` for `logger.` without an `import`/assignment returns exactly this one file (`app\main.py` is fine — it imports it at line 7). Any real pipeline failure is replaced by `NameError: name 'logger' is not defined`, so the SSE terminal gets no diagnosis.

**6. A read endpoint writes to the database on every page load.**
`generate_console_feed_data` (`pipeline.py:93`) calls `get_or_create_location_baseline`, which at `C:\...\v2\backend\app\behavior\baseline.py:272` executes `db.commit()` (row insert/update) for any incident without a <24h cache row. `GET /api/console/feed` is fetched by `frontend\js\data.js:34` on load.

**7. The imagery panel — the platform's centrepiece — has no imagery for the live queue.**
`v2\backend\data\crops` contains exactly one directory, `inc_test_vis_mumbai` (a fixture, not an incident id); **0 of the 320 ACTIVE incidents** have a crop dir, and `v2\backend\data\imagery_cache` (1,293 files, ~646 ids) is keyed to ids outside the current queue. So every `/crops/<uuid>/annotated.jpg` emitted by the feed falls through to on-demand synthesis (`app\main.py:123-133`) and then `app\imagery\provider.py:60,69`, which fetches `mt1.google.com` then `server.arcgisonline.com` with 3 s timeouts; on failure `provider.py:40-45` returns a flat dark `(28,33,40)` synthetic tile. Offline (the normal hackathon venue), the "tactical reticle HUD" renders placeholder terrain for 100% of the queue. The map itself also needs `unpkg.com` (Leaflet) + arcgisonline tiles.

**8. Two of the four dead entrypoints are the ones the judge-facing runbook tells you to run.**
`C:\...\PS162\run.py`'s `pipeline`, `data`, `legacy`, `daemon` subcommands all `sys.exit(1)` (root `pipeline/`, `dashboard/`, `archive/` exist only under `v1/`), and `C:\...\PS162\docs\PS162_FIREX_Project_Master_Brief.md` §5 "Verification Runbook" instructs: `python run.py serve`, **`python run.py pipeline`**, **`python run.py data`**.

**9. The Master Brief was never audited — and it is the judge-facing document.**
`C:\...\PS162\docs\PS162_FIREX_Project_Master_Brief.md` §3 tabulates **"100% Operational"** for 8 components, each linked to `file:///c:/Users/ssaur/OneDrive/Desktop/PS162/pipeline/...` or `.../dashboard/...` paths that do not exist. §4.1 asserts **"Cluster Total FRP … 238.3 MW aggregated radiative power"**, directly contradicting INV-2 and the code (`pipeline.py:312` deliberately assigns `current_max_frp`). §4.2 declares `CRITICAL_INFRASTRUCTURE` at 35 km and `MAJOR_FIRE_SURGE` at ≥12.0 MW peak / ≥25.0 MW "cluster total"; the code uses containment-or-≤5 km (`pipeline.py:106`) and `current_max_frp >= 50.0`. §2 repeats "≤25 km" clustering; §3 stage 7 names a DB `firex_history.db` whereas code and data use `firex_v2.db`.

**10. Internal spec contradictions.** `C:\...\v2\V2_LOGIC_SPECIFICATION.md` §3 line 40: "executes **twelve** discrete stages"; its own Stage Summary Matrix lists stages **0-10 (eleven)** and its mermaid DAG has **nine** nodes.

**11. Model split brain, doc-vs-code.** `app\intelligence\provider.py:46` calls `settings.AI_MODEL`; `app\api\health.py:65` reports `settings.AI_MODEL_NAME`; `v2\backend\.env` sets only `AI_MODEL_NAME=google/gemma-4-26b-a4b-it` (and there is no `AI_MODEL` line), so `/status` names a model that is never called and the documented knob is inert, while the actual call goes to `dots-studio/dots-3-note-preview:free`. `README.md:14` (badge), `README.md:98`, `v2\README.md:21` and `docs\FIREX_Architecture_and_Codebase.md` all still name "MiniMax M3". `v2\README.md:26` also advertises the console as "(Port 8000)" while the FastAPI app defaults to 8000 too and `v2\frontend\server.py` binds 8000 as well.

**12. Documented stage coverage that does not exist.** `v2\README.md:28` calls `v2/docs` "Individual stage verification reports"; it holds 5 files — stages 1-4 plus a v1 audit — for an 11/12-stage pipeline.

**13. Climatology constants drift (beyond the sweep's list).** `v2\backend\scripts\build_thermal_climatology.py` docstring states "0.02° (~2.2 km)" and thresholds `active_days >= 30, night_ratio >= 0.30`; the code uses `ROUND(latitude, 2)` (0.01°), keys `GRID_{lat:.2f}_{lon:.2f}`, and `if active_days >= 25 and night_ratio >= 0.25`. `baseline.py:166` carries the same "pre-computed 0.02° grid" claim.

**14. DB footprint / duplicate artifacts on a synced drive.** `v2\backend\data\firex_v2.db` = 1,282,961,408 B in `journal_mode=wal` with live `-shm`/`-wal` siblings, all inside OneDrive; `firex_v2.db.bak_checkpoint` = 1,203,228,672 B plus its own `-wal`/`-shm`; a second `v2\data\firex_v2.db` (471,040 B) is what the tracked relative `DATABASE_URL=sqlite:///./data/firex_v2.db` selects when the server is started from `v2\`; and `v2\backend\data\firex.db` is a 0-byte stray.

**15. Empty module directories.** `v2\backend\app\workers\` and `v2\scripts\` contain no files (no `__init__.py`), despite `app\workers` being imported nowhere and implied by the README's component list.

CHECKED AND CLEAN (so the negative result is on record)
- Dependencies: every third-party import across `app/`, `scripts/`, `tests/` (`PIL, fastapi, pydantic, pydantic_settings, requests, sqlalchemy`; `starlette` only transitively) resolves, and `requirements.txt` covers each. No `ModuleNotFoundError`.
- Runtime: `import app.main` succeeds on the author's machine (config.py present on disk); 29 routes; `/health` 200 (0.01 s), `/api/analysis/status` 200 (0.08 s), `/api/history-stats` 200 (0.04 s), `/api/incidents?limit=3` 200, `/api/selection/candidates` 200 (0.76 s), `/api/console/feed` 200 (0.37 s, 323 incidents + 200 ambient).
- Frontend asset references: all 26 local refs in `index.html` and `js/*.js` resolve (`styles/*.css`, `js/main.js?v=17`, `data/incidents.json`, `data/ambient_firms.json` present); only external hosts are unpkg/arcgisonline/Google Fonts.
- The "redundant raw_payload JSON column" is NOT the size cause: `SUM(LENGTH(raw_payload))` = 41,710 bytes total (effectively all NULL); `COUNT(*)` on `observations` is 0.030 s and the baseline bounding-box query uses `ix_observations_longitude` (~470 rows), not a full scan.

Root-cause note tying several items together: because `.env` carries a CWD-relative `DATABASE_URL` and `tests\conftest.py` sets no override, tests, `python backend\run.py` from `v2\`, and the shipped `incidents.json` all resolve different databases — which is how 9 fixtures ended up `ACTIVE` in the 1.28 GB demo DB and in the committed feed.

---

## Part 2 — Synthesis

**A22 (continued).**
`severity/scoring.py:168-171`: `extreme_threshold = 180.0 if is_routine_flare else 150.0` / `if frp_mw >= extreme_threshold and firms_confidence >= 80.0:` / `forced_level = "CRITICAL" if frp_mw >= 250.0 or firms_confidence >= 90.0 else "HIGH"`. Spec line 251 carries only `HIGH (FRP >= 250MW => CRITICAL)` with forced min 55.0/80.0; a full-text search finds no 90%-confidence rule. Floors at `scoring.py:289`. Consequence: **150-249 MW at 90-100% FIRMS confidence is forced to CRITICAL/80.0 instead of HIGH/55.0.** The suite masks it — `tests/test_stage7_severity_alerts.py:122-134` uses frp 180.0 / conf 95.0 and asserts only `in ["HIGH","CRITICAL"]`. The sibling blueprint only says "Extreme FRP + high FIRMS confidence → minimum HIGH".

**A23. Severity's Historical Deviation carries an undocumented `max(10.0, ·)` floor.**
Spec line 234: `If r < 1.0 => 50.0 x r`, no floor. `scoring.py:89-95` `else: base_dev = round(50.0 * ratio, 2) ... return max(10.0, base_dev)` — applies only when `is_routine_flare is False`; routine flares take the min/max-0.4 branch at `:94`. No config defines 10.0 and `calculate_historical_deviation` has a single definition. Correction: the spec line number is 234, not 233, and the impact was **understated** — inflation is `0.30*(10.0 − 50r)`, up to 1.5 points at r = 0.1 and approaching the full 3.0 as r → 0; an r = 0 / frp_mw = 0 incident still receives 10.0 instead of 0.0.

**A24. Severity's Model-A selection gate (`history_reliability >= 0.4`) is unspelled.**
`scoring.py:247` `has_history = (p95_frp > 0.0 or median_frp > 0.0) and history_reliability >= 0.4`. Reachability confirmed: `behavior/baseline.py:72-87` floors reliability at 0.1 (3 obs / 3 active days → 0.17), so p95 > 0 with reliability < 0.4 is a real combination routing to `NEW_HOTSPOT_NO_HISTORY`. **This is the weakest confirmed finding**: the cited spec evidence (line 565) is the Stage-5 *priority* argument, not the severity selector, and §4.6 defines no selection criterion at all — but the sibling blueprint does condition the model on "when reliable history exists", so the code implements documented intent and only the **numeric 0.4 cutoff** is nowhere stated.

**A25. Severity's S_GIS 95.0 branch is widened by `hazard_category`.**
`scoring.py:128-134` — `high_hazard_types = {refinery, petrochemical, lng_terminal, steel_plant, chemical}`; `if any(h in f_type for h in high_hazard_types) or hazard_category == "MAJOR_ACCIDENT_HAZARD": return 95.0`. Spec lines 240-241 list only the five facility types; `hazard_category` is mentioned only as an asset column (spec 434) and its values are never defined. Consequence: 0.15\*20 = 3.0 Model-A / 0.20\*20 = 4.0 Model-B points. Impact is **understated** as first written: `storage/models.py:134` declares `hazard_category = Column(String, default="MAJOR_ACCIDENT_HAZARD")`, so **every asset persisted without an explicit category** carries the value — broadly reachable, not limited to the 3 seed assets that set it in `gis/assets.py:90,344,358`.

**A26. Severity's extra `"mining_related": 60.0` key — direction is the opposite of the claim.**
`scoring.py:102-112` includes both `"mining_or_other_thermal_source": 65.0` and `"mining_related": 60.0`; fallback `base_scores.get(classification.lower(), 50.0)` at `:112`. Spec lines 236-237 list seven ratings and name the class `mining_or_other_thermal_source` (65). Reachable: `intelligence/provider.py:313` and the provider taxonomy (`:190-201, :208`) emit `mining_related`; `intelligence/service.py:99` stores it verbatim; `orchestration/pipeline.py:133-134/148-149` remaps only a local variable, never writing back; `severity/service.py:33` reads the raw label. **Correction: relative to the spec's own taxonomy the code UNDER-scores a mining detection by 5 points (60 vs 65 = 1.5 composite points), not "10 points high vs the 50.0 fallback."** The 60-vs-50 framing only holds if the label is treated as unknown. The blueprint explicitly retains `mining_related` as canonical (blueprint 2186-2194), so spec and blueprint disagree and the code follows the blueprint.

**A27. C_sev adds an undocumented None-distance default and an outer clamp.**
Spec lines 258-260 specify only the four-term weighted sum and `C_dist = max(40.0, 100.0 - dist/50.0)`, with no None default and no floor. `scoring.py:202-206` `if distance_m is not None: dist_certainty = max(40.0, 100.0 - (distance_m / 50.0)) else: dist_certainty = 60.0`, and `:208-214` `return max(10.0, min(100.0, round(conf, 1)))`. The None path is reachable (`severity/service.py:43` sets `distance_m = None` whenever `incident.distance_to_asset_km` is None). **Correction:** 60.0 is *inside* the spec's [40, 100] range — it is exactly `C_dist` at d = 2000 m — so it is not out-of-range, merely an undocumented default 20 points above the 40.0 the spec would imply for unknown/far distance: +4.0 C_sev (0.20\*20). Conversely the `max(10.0, ·)` clamp is **not** fully benign: the spec formula's own minimum is 8.0, so it reports 10.0 where the spec yields 8.0 — though it cannot affect the <60.0 reinvestigation trigger (`scoring.py:301`).

### 2.2 Omissions — spec-mandated behavior that is absent

**B1. §6.1: the 12 mandatory rules are defined but never sent to the model.**
`intelligence/prompts.py:9-30` defines `SYSTEM_PROMPT`. A repo-wide grep for `SYSTEM_PROMPT|system_prompt` (py/ts/tsx/md/json) returns **only `prompts.py:9`** — no import anywhere. `provider.py:74-82` is the only message builder and emits a single `{"role": "user", "content": [text, image_url]}`; grep for `"system"` across `backend/*.py` returns zero matches. `provider.py:22` imports only `PROMPT_VERSION`; `vision.py:10` only `build_investigation_prompt`. `build_investigation_prompt` (`prompts.py:96-153`) contains no rule statements. `tests/test_stage6_ai_investigation.py:149-157` asserts only on the user prompt. Correction: "enforcing none of Section 6.1" is too strong — rule 6 is enforced structurally by the required `alternative` object (`prompts.py:131-134`, `schemas.py:61`), rule 10 by the `uncertain` taxonomy entry, rule 12 by "Return ONLY the raw JSON object" (`prompts.py:153`), and rule 5 implicitly by the absence of a severity field. **But the explicit rule text for rules 1, 2, 3, 4, 8, 9, 11 and the whole numbered block never reach the model.**

**B2. §6.3: no cooldown, no quarantine, no timing constants.**
Spec: HTTP 429 → 60 s quarantine; 401/403 → 1 h. `provider.py:105-109` `elif resp.status_code in [429, 401, 402, 403]:` logs and calls `key_pool.rotate_key()` with **no argument**; `rotate_key` (`key_pool.py:47-60`) only advances `current_idx` modulo `len(api_keys)` and bumps `failovers` — it has no duration/state parameter and the class stores no timestamps. Grep for `cooldown|quarantine` in `backend/` returns nothing (only spec + README). `402` is in the branch though the spec lists only 429/401/403. Consequence confirmed: `config.py:47 AI_MAX_RETRIES=4` and exactly 4 `OPENROUTER_API_KEYS` (`config.py:49-54`) means one incident attempts each key once; a 429'd key is re-selected on the very next incident with no backoff, and a revoked 401/403 key is retried at full rate. `README.md:21` advertises "auto-cooldown" which does not exist.

**B3. §6.3: three of the four cascade legs do not exist.**
Spec: Gemini 2.5 Flash/Pro → Groq Vision → OpenAI GPT-4o → Deterministic Sovereign Mock Provider. `provider.py:355-362 get_ai_provider()` returns `MockAIProvider` only when `settings.AI_PROVIDER == 'mock'`, else always `OpenRouterProvider`. `config.py:42 AI_PROVIDER = 'openrouter'` (comment enumerates only `'openrouter','mock'`), `:45 AI_API_BASE_URL='https://openrouter.ai/api/v1'`. Grep for `groq|gemini|gpt-4o|openai|cascade|fallback_chain` across `backend/` **and** `frontend/src` returns zero matches. On exhaustion `investigate()` returns `self._build_fallback_report(...)` (`provider.py:122-125`, `:216-240`, `classification='uncertain'`, `confidence=50.0`), an in-class hardcoded report that never delegates to `MockAIProvider`. Correction: "non-deterministic-shaped stub" is wrong — the fallback is fully deterministic; the real gap is that the fourth leg is OpenRouter, not Gemini, and three legs are absent.

**B4. §6.3: KeyPoolManager tracks none of the three named metrics by name.**
`key_pool.py:23-26` `self.stats[i] = {"calls": 0, "successes": 0, "failovers": 0}`. Repo-wide grep for `cooldown|quarantine|error_count|total_requests` matches **only** `V2_LOGIC_SPECIFICATION.md:348-349` and `README.md:21` — zero in backend/tests/frontend. Correction: two of the three have same-purpose analogs under different names — `calls` (`key_pool.py:68-72 record_call`, one per attempt at `provider.py:87`) **is** a per-key total-requests counter, and `failovers` (`key_pool.py:56`) is incremented on every error rotation (`provider.py:109,115,119`) and so functions as a per-key error counter. **Only `cooldown_until`/quarantine state is genuinely absent.**

**B5. §6.2: the sixth taxonomy literal is `mining_related`; the spec literal is silently coerced to `uncertain`.**
`schemas.py:10-17 TaxonomyClass` Literal contains `mining_related` (no spec literal); `provider.py:194-201 valid_classes`; `:208` alias `'mining':'mining_related'`; `prompts.py:76` and `:124`; `provider.py:313` mock returns it. `_normalize_taxonomy` (`provider.py:210-214`) lowercases/replaces, finds no alias for `mining_or_other_thermal_source`, and returns `'uncertain'` — **a spec-conformant model output IS silently downgraded.** Correction: the claim's severity note is wrong — `severity/scoring.py:106` **does** contain `"mining_or_other_thermal_source": 65.0` (the exact spec value) immediately above line 107's 60.0, and `pipeline.py:133` and `:148` remap `cls_name` before downstream use, so the spec's 65 rating *is* implemented. Also `uncertain` (50) is not the "lowest-confidence bucket" — it sits above `gas_flare` (38) and `agricultural_burning` (32). The blueprint does specify `mining_related`, so the spec/blueprint conflict is real.

**B6. §6.1 rule 4: the literal `"Unknown"` sentinel is not mandated and not checked.**
`prompts.py:21` reads `4. Never invent or hallucinate missing values. If an attribute is unknown, state so.` vs spec line 306 `...If an attribute is unknown, explicitly state "Unknown".` — both "explicitly" and the sentinel are dropped. Grep for `Unknown` in `backend/*.py` returns only two sites, neither a rule or a validator: `prompts.py:53` (the code's own facility-distance fallback) and `api/history.py:347` (a display default). Correction: "no validator can flag fabrication" implies one exists elsewhere — **none does**, on either side, so the alleged detectability was never implemented regardless of prompt wording. The claim's parenthetical that "unknown" occurs only lowercase is also inaccurate: `prompts.py:53` emits capital-U. A prompt-wording nit, not a broken contract.

**B7. §6.2: `image_quality.score` is `int` where the spec example is a float literal.**
`schemas.py:31-37` `score: int = Field(80, ge=0, le=100)`; `provider.py:173` `score=int(img_q_raw.get('score', 80))`; `prompts.py:145` asks for `<0 to 100>`; all producers are integers (`provider.py:232 score=50`, `:344 score=90`, `tests/test_stage6_ai_investigation.py:206 "score": 85`). Spec lines 336-337 show `"score": 92.0`. Correction: largely overstated — 92.0 is an integral value whose decimal point carries no fractional information, so no precision is lost for spec-conformant output; truncation only bites if a model volunteers a fraction, which the prompt does not request. All other §6.2 fields match the spec.

### 2.3 Correctness — behavior, caching and pipeline integrity

**C1. Persistence formula replaced.**
Spec line 153: `min(1.0, (active_days/45)*0.7 + min(1.0, obs/100)*0.3)` — unimplemented anywhere. `behavior/persistence.py:50-57` is verbatim: `freq_score=min(1.0, active_days/15.0)`, `density_score=min(1.0, total_obs/25.0)`, `continuous_bonus=0.35` if both day and night, `raw=(0.35*freq)+(0.30*density)+bonus`, `score=round(min(1.0,raw),2)`. Nothing else computes persistence for a location/facility (`profile.py:229` and `:425` are the only callers, both this function; `selection/engine.py:44` is a different heuristic). Consequence: **15 active days + ≥25 obs → 0.35+0.30+0.35 = 1.0 vs the spec's 0.308**, and the Stage-4 matrix test at `anomaly.py:57` (≥0.50) fires far earlier than intended.

**C2. Stage-4 statistics use a 90-day window in every production caller, not 365.**
Spec line 150. Defaults of 90 at `behavior/baseline.py:101, :298` and `behavior/profile.py:129, :308`. Production callers all pass `window_days=90`: `profile.py:513, :528`, `api/history.py:40,68,166,187`, `selection/engine.py:33,35`, `orchestration/pipeline.py:529,531`, `imagery/package.py:80,82`. `persistence.py:17` declares the parameter and it appears nowhere else in that file, so callers cannot change it. Correction: the "~1/4 of spec" estimate does **not** hold on the thermal-climatology branch (`baseline.py:172-211`), which is consulted first for any cell present and returns all-time counts with no date filter plus `active_days_365d` at `:195` — that branch is worse than 1/4. The 90-day default governs only the `HistoricalBaseline` cache path and the raw fallback (`baseline.py:218-241`).

**C3. `history_reliability` is continuous where the spec defines five discrete tiers.**
Spec lines 156-162 define 0.0/0.25/0.50/0.75/1.00. `baseline.py:72-87` implements `count_factor=min(1.0, obs/20.0)`, `days_factor=min(1.0, active_days/max(1, min(15, window_days//3)))`, `reliability=round(max(0.1, min(1.0, 0.6*count_factor+0.4*days_factor)),2)`. **No label→numeric tier map exists anywhere**: the only companion, `classify_history_reliability` (`baseline.py:52-70`), returns string labels only, and grep for `MODERATE`/`'LOW':`/`'NONE':` across backend finds no numeric table. Measured at window 90 with `active_days == obs`: obs 1 → 0.10, 2 → 0.11, 4 → 0.23, 5 → 0.28, 9 → 0.51, 10 → 0.57, 19 → 0.97, 20 → 1.00 (spec: 0.25 / 0.50 / 0.75). Multiplier confirmed at `severity/scoring.py:212` (`history_reliability * 100.0`), fed from `severity/service.py:53, :75`. Correction: 0.28-for-5-obs assumes 5 distinct days; one day gives 0.18.

**C4. R_frp pre-rounded before the table lookup.**
Spec line 165: the ratio is used directly. `behavior/anomaly.py:116` `ratio = round(current_frp / max(1.0, median_frp), 2)`, consumed at `:118` → `calculate_frp_ratio_score` → table at `anomaly.py:18-26/40-43`. Boundary behavior confirmed by the table's `if ratio <= threshold` form: true 1.254 → 1.25 → **10** where spec gives 20; 2.004 → 2.0 → **40** where spec gives 60; 1.004 → 1.0 → **0** where spec gives 10. Error direction is downward only, and impact is **bounded to ratios within 0.005 above a boundary** — interior values are unaffected.

**C5. Sparse-history short-circuit.**
Spec lines 156-162 define LOW (1-4 obs) and MODERATE (5-9) reliability tiers, and 164-176 applies the anomaly table with no minimum-observation carve-out. `behavior/anomaly.py:99-113` returns `frp_ratio 1.0`, `ratio_score_100 0.0`, `anomaly_score 0.0`, `above_p95 False`, `status INSUFFICIENT_HISTORY` and synthesis from `classify_behavior_synthesis(persistence_score, False, 1.0)` without ever reaching the table at `:118`. Consequence: the synthesis string can only ever be "new / normal" or "persistent / normal" (`anomaly.py:58-67`), so **a 1-2 observation cell with a large true ratio can never land in "new / abnormal."**

**C6. Synthesis matrix keys on an extra `above_p95` disjunct.**
Spec lines 178-190: the matrix is `persistence >= 0.5` crossed with `anomaly score >= 50`. `anomaly.py:58` `is_strong_deviation = above_p95 or (frp_ratio > 2.0)`; the `ratio > 2.0` leg does correspond to the spec boundary (table jumps 40 at `:22` to 60 at `:23`), but `above_p95` is an extra disjunct (`:117`, passed at `:132`). Correction: the claim's ratio-1.1 example requires `p95_frp < 1.1*median_frp`, which is uncommon — but the effect is wider: **any current FRP above p95 whose ratio sits in (p95/median, 2.0] returns table score ≤40 ("normal") yet is labelled abnormal** — exactly the ordinary p95-exceedance case.

**C7. Persistence 0-100 fed into a 0.50 test, making `is_high_persistence` unconditionally true on the selection path.**
`selection/engine.py:42-45` `obs_count = incident.observation_count or 1` then `persistence_score = 75.0 if is_pers else min(100.0, obs_count * 15.0)`; `:52-56` passes it into `evaluate_historical_anomaly`; `anomaly.py:57` tests `persistence_score >= 0.50`. Since `obs_count` floors at 1, the minimum is 15.0, so the "new / \*" half of the matrix (`anomaly.py:64-67`) is unreachable there. The same value is correctly scaled for the priority sum at `selection/scoring.py:133` — which is what makes the reuse as a 0-1 threshold a genuine scale collision. Correction: unreachability is specific to the selection path — `api/history.py:109` passes the real 0-1 profile value (`history.py:106`), so "new / abnormal" remains reachable through the anomaly API.

**C8. `thermal_climatology` is documented as 365-day gridded statistics; the build has no date predicate and a synthetic median.**
Spec line 442. `scripts/build_thermal_climatology.py:50-62` is `SELECT ROUND(latitude,2), ROUND(longitude,2), COUNT(*), COUNT(DISTINCT SUBSTR(acquired_at,1,10)), SUM(CASE WHEN daynight='NIGHT'...), AVG(frp_mw), MAX(frp_mw) FROM observations GROUP BY lat, lon HAVING obs_count >= {min_detections}` — **no WHERE clause at all**, so `obs_count`/`active_days`/`night_ratio` are lifetime totals. Lines 80-82 set `median_frp = round(max(0.5, mean_frp*0.80), 2)`, `p90 = min(max_frp, mean*1.60)`, `p95 = min(max_frp, mean*2.10)` — derived from AVG, never from the observed median. This synthetic median reaches the anomaly table for every climatology cell because `behavior/baseline.py:167-211` consults `ThermalClimatology` first and returns it (`:196`) as the baseline `anomaly.py:94` reads as `median_frp`; R_frp's denominator for those cells is therefore unrelated to the spec's empirical Median_FRP.

**C9. `daynight` domain is 'DAY'/'NIGHT'; the spec documents 'D'/'N'.**
Spec line 428. Writers persist words: `ingestion/normalizer.py:86` `daynight_code = "NIGHT" if str(raw.daynight).strip().upper() == "N" else "DAY"`, passed at `:99` → `firms.py:119`; `scripts/ingest_history.py:195-196` same. Every consumer compares words (`build_thermal_climatology.py:56`, `persistence.py:42-43`). Live DB: `[('DAY', 2132898), ('NIGHT', 762166)]` — **zero D/N rows**. `api/observations.py:71-72` filters `Observation.daynight == daynight.upper()`, so a spec-conformant 'D' returns HTTP 200 with an empty list and no validation error. Latent inconsistency beyond the claim: `ingestion/validator.py:21` defaults `"D"`, `orchestration/pipeline.py:365` falls back to `"D"`, `api/history.py:345` to `"N"` — and a bare D/N matches neither branch at `persistence.py:42-43`, so it is counted as neither day nor night.

**C10. Footprint buffer is 300 m where the spec says 375 m.**
Spec line 142: `R_footprint = max(500.0, max_i d_H(...) x 1000.0 + 375.0)`. `incidents/clustering.py:76` `self.radius_meters = max(500.0, round(max_dist_m + 300.0, 1))` with `max_dist_m` from `haversine_distance_meters` (`spatial.py:13-23`, `EARTH_RADIUS_METERS=6371000.0`); comment at `:69` says `'+ 300m sensor buffer'`. Grep for `375` across the repo returns only the spec and unrelated numbers. **Units resolve in the code's favour: no 1000x error** — `haversine_distance_meters` returns meters, consumed directly, so the spec's `×1000` is written assuming km. What is real: the persisted `Incident.footprint_radius_meters` (`association.py:173` new, `:121-123` expanded) is 75 m smaller than spec, and the generated GeoJSON circle (`clustering.py:79-83`) is correspondingly smaller. Corrections to the alleged impact: (a) the claim that this "narrows the footprint-overlap association tolerance" is **false in practice** — `association.py:54` uses `effective_boundary_m = max(spatial_threshold_meters, (inc.footprint_radius_meters or 500.0) + 1000.0)` with `spatial_threshold_meters` defaulting to 3000.0, so the 75 m never changes it; (b) the claim that "any downstream containment/PIP test" inherits the shrink is unevidenced — `Incident.footprint_geojson` is only written (`clustering.py:84`, `association.py:174`) and declared (`models.py:62`), and grep finds **no reader anywhere** in `backend/app`.

**C11. Clustering default eps is 2000 m; the spec says 1500.**
`clustering.py:107` `spatial_eps_meters: float = 2000.0`, used at `:140`; `api/incidents.py:139` `2000.0` passed straight through at `:153`. Spec line 129 and pseudocode line 538 fix 1500. Pipeline is conformant: `pipeline.py:510` passes `spatial_eps_meters=1500.0`. Tests use 2000.0 (`tests/test_stage3_incidents.py:62,87,92,97`). The docstring at `clustering.py:7` claims "Spatial epsilon: 1,500m (configurable)", contradicting the 2000.0 default — so this is not a docstring-reading artifact. `/incidents/cluster-sync` is 33.3% wider than spec.

**C12. `/incidents/cluster-sync` ignores the 72-hour Stage-3 window.**
Spec line 64 ("Active observations (72h)") and pseudocode 536-537. `api/incidents.py:147` `observations = db.query(Observation).all()` — no filter — fed at `:151-155`. Grep on that file for `72`/`acquired_at`/`time_cutoff` returns only the unrelated `time_window_hours=24.0` route param. The pipeline path honours it: `pipeline.py:490-491` `time_cutoff = datetime.utcnow() - timedelta(hours=72)`. Correction: the internal temporal gate (`clustering.py:133-136`, 24h) still applies, so observations years apart will **not** merge with each other. The genuine effects are (a) the unbounded full-table scan and O(n²)-ish `get_neighbors` growth, and (b) stale (>72h) observations still reach `sync_clusters_to_incidents`, where clusters >72h from any active incident (`association.py:46-48`) fall to the new-incident branch and **can mint incidents from out-of-window data** — behavior the pipeline cannot exhibit.

**C13. Frontend FRP summation — real code, but not an INV-2 breach.**
The cited sums all exist: `frontend/js/render.js:605` `const totalFrp = cases.reduce((acc, c) => acc + (c.frp || 0), 0)` rendered as "MW total" at `:645`; `:1340` `industrial.reduce((s, c) => s + c.frp, 0)` rendered at `:1350`; `:1566/:1582` "Total ... MW". **Correction: `frontend/js/data.js:128` defines `c.frp = Number(raw.frp)` = the console feed's per-incident `frp` (= `inc.current_max_frp`, `pipeline.py:311`), so all three are cross-incident aggregates of per-incident maxima, not multi-pixel cluster sums — no INV-2 violation.** The only true within-cluster sum is `frontend/prepare_map_data.py:375` (`c["total_frp"] += p["frp"]` within 25 km), and that module cannot run: it imports `history_db` from `<v2>/pipeline/07_persistence` (`prepare_map_data.py:24-28`), a directory that does not exist. **The banned operation appears nowhere in any reachable code path.**

**C14. `cluster_total_frp` is populated with `inc.current_max_frp` — naming defect only.**
`orchestration/pipeline.py:312` `"cluster_total_frp": inc.current_max_frp` — the name asserts a cluster total while the value is the incident maximum; no summation occurs. Sole reference repo-wide; never read by any frontend module (grep of `frontend/js` and `index.html` is empty); written into `frontend/data/incidents.json` by `export_v1_dashboard_data` (`pipeline.py:390-392`). The stored/computed FRP statistics remain max/mean/min, so INV-2's computational ban is not breached and no consumer misreads the field.

**C15. Model-A/B severity divergence is clean; the composite floors are not.** (Consolidated note — see A2, A3, A23.) The §4.6 coefficients themselves are exact: Model A 0.35/0.30/0.20/0.15 (`scoring.py:257-262`), Model B 0.50/0.30/0.20 (`:266-270`), the S_dev branches for r≥3.0 / r≥2.0 / r≥1.0 (`:83-88`), the routine suppression formula `min(20.0, max(5.0, S_dev*0.4))` (`:94`), all seven S_AI ratings (98/92/75/65/50/38/32) and the blend `Base*C_AI + 50.0*(1.0-C_AI)` (`:115`), the S_GIS constants and their `<=` boundaries, the four tier boundaries, the C_sev coefficients 0.25/0.35/0.20/0.20, `C_dist = max(40.0, 100.0 - dist/50.0)`, the forced minimums (CRITICAL 80.0, HIGH 55.0, MEDIUM 30.0), and the reinvestigation trigger. Scale was checked at every boundary: `ai_confidence` is persisted 0-100 and `history_reliability` is 0-1, so `ai_confidence >= 80.0` and `history_reliability*100 if <=1.0` are correct.

### 2.4 Stale documentation (spec vs code; README/docs vs repo)

**D1. §3 line 40 says the pipeline "executes twelve discrete stages"; its own Stage Summary Matrix lists stages 0-10 (eleven) and its mermaid DAG has nine nodes.** Internal contradiction in the spec itself.

**D2. §9 claims "13 normalized relational tables"; the code ships 15 and the spec's own numbered list enumerates 14.**
15 `__tablename__` in `storage/models.py` (lines 27, 54, 107, 121, 143, 157, 173, 187, 210, 223, 243, 261, 276, 290, 302); live DB `sqlite_master` has 15 app tables + `sqlite_stat1`. Spec line 407 says 13; numbered items 427-451 enumerate 14 (item 13 at `:451` names `behavior_profiles` **and** `behavior_daily_summaries`). Nuance: a tool driven off the ER diagram (line 421) would still surface `historical_baselines`, so only the data-dictionary reading omits it.

**D3. `observations.external_id` is a truncated SHA-256.**
Spec documents a "SHA-256 hash". `ingestion/normalizer.py:69-70` — `key = f"{satellite}_{instrument}_{lat:.4f}_{lon:.4f}_{strftime('%Y%m%d%H%M')}"` then `hashlib.sha256(key.encode()).hexdigest()[:20]`. Live DB: `SELECT length(external_id), count(*) FROM observations GROUP BY 1` returns exactly `[(20, 2895064)]` — **no 64-char values**. Dedup on the truncated value at `ingestion/firms.py:86-124`.

**D4. `historical_baselines` is absent from the numbered Table Definitions; `thermal_climatology` is absent from the ER diagram.**
`storage/models.py:222-239` — `class HistoricalBaseline(Base)`, `__tablename__ "historical_baselines"`, `profile_id` FK to `behavior_profiles.id`; live `PRAGMA table_info` returns 15 columns. Spec ER diagram (410-423) lists HistoricalBaseline only as an edge (`:421`) and never names `thermal_climatology`; `thermal_climatology` is numbered item 8 at `:441`. (The spec's `thermal_climatology` PK claim — `spatial_key` — is exactly correct.)

**D5. Three route rows do not match.**
- `GET /api/severity/incident/{id}` ("compute or retrieve") **does not exist**. Code has `GET /severity/{id}` (retrieve-only, 404s at `api/severity.py:39-43`; the detail string points at the undocumented `POST /api/severity/evaluate/{incident_id}`) and `POST /severity/evaluate/{id}` (`:13`). Project-wide grep for the literal matches only the spec.
- `POST /api/imagery/incident/{id}` is implemented as **GET** (`api/imagery.py:17`); the only other imagery routes are `GET /incident/{incident_id}/package` (`:36`) and `GET /cache/{incident_id}/{filename}` (`:55`); `grep -n "router.post" backend/app/api/imagery.py` returns nothing.
- `POST /api/alerts/{id}/ack` is `/{alert_id}/acknowledge` (`api/alerts.py:43`), siblings `/{alert_id}/resolve` (`:62`) and `/{alert_id}/dismiss` (`:81`) have no spec row. No `/ack` alias anywhere; `tests/test_stage7_severity_alerts.py:446` posts the implemented path.

**D6. SSE wire event names differ from the spec.**
`orchestration/events.py:27-39` defines lowercase dotted constants (`EVENT_ANALYSIS_STARTED = "analysis.started"`, …); `:88` emits `f"event: {self.event_type}\ndata: {json.dumps(payload)}\n\n"`. The spec (485-507) lists 8 SCREAMING_SNAKE names; the uppercase text exists only as Python identifiers. Publisher sites: `pipeline.py:434,477,500,512,535,582,598,612,631,648,693,710`. Four wire events are unlisted: `gis.completed`, `ai.started`, `alert.created`, `analysis.failed` (`events.py:29,33,36,38`). JSON payload keys inside those events match the spec. **A spec-conformant subscriber's dispatch table breaks.**

**D7. The "Complete REST API" table has 19 rows and the codebase exposes roughly two dozen more.**
Undocumented, all mounted (`main.py:70-91`) and exercised by tests: `GET /health/readiness` (`health.py:30`), `GET /status` (`:56`), `GET /observations/{id}` (`observations.py:116`), `GET /industries/{asset_id}` (`industries.py:114`), `POST /industries/seed` (`:131`), `POST /incidents/{id}/state` (`incidents.py:177`), `GET /incidents/{id}/{baseline,anomaly,trend}` (`history.py:65,88,121`), `GET /industries/{id}/{history,baseline,trends}` (`:163,184,205`), `POST /history/refresh` (`:245`), `GET /history/search` (`:255`), `GET /imagery/incident/{id}/package` (`imagery.py:36`), `GET /imagery/cache/{id}/{filename}` (`:55`), `GET /investigation/{id}`, `GET /{id}/history`, `POST /{id}/reinvestigate` (`investigation.py:40,57,68`), `POST /severity/evaluate/{id}`, `GET /{id}/history` (`severity.py:13,47`), `POST /alerts/{id}/{resolve,dismiss}` (`alerts.py:62,81`), `GET /analysis/{status,history}`, `POST /analysis/run`, `GET /api/trigger-sync-stream`, `POST /api/trigger-sync`, `GET /api/history-stats`, `GET /api/console/feed` (`analysis.py:37,64,199,209,244,250,270`), and `GET /crops/{incident_id}/{filename}` (`main.py:109`). Also omitted from the inventory: `GET /selection/evaluate/{incident_id}` (`selection.py:40`) and `POST /selection/score` (`:50`). Corrections: `GET /crops/{incident_id}/{filename}` **is** documented (spec row 19 differs only in path-parameter name), so it is not an undocumented route; each bare router is re-registered under `/api` at `main.py:70-91` (not 78-98); the table's own heading is "Core REST Endpoints" and "Complete REST API" is the section heading, so "presented as complete" is a slight overreach while the gap is real.

**D8. `models.py` cannot regenerate the live schema.**
Live DB `PRAGMA table_info` shows `behavior_profiles` with 22 columns including `window_days`, `day_passes_count`, `night_passes_count`, `is_continuous_24h`, and `historical_anomalies` with 11 including `anomaly_status`. `models.py` declares neither (`BehaviorProfile :186-206`, `HistoricalAnomaly :260-272`). Repo-wide grep: `day_passes_count`/`night_passes_count`/`is_continuous_24h` have **zero hits anywhere**; `window_days` appears only as a function/query parameter and a dict key; `anomaly_status` only as a local variable and response key (`behavior/anomaly.py:123-129, :161`) that no ORM column backs. No migration tooling (no `alembic/`, no `ALTER TABLE`), and `main.py:12-13` uses `Base.metadata.create_all`, which cannot add columns. Correction: "production data already depends on" these is **unsupported** — no code reads or writes them (orphaned/vestigial); the divergence is that a rebuild loses unused columns rather than depended-upon state.

**D9. `/health` promises a memory metric that does not exist.**
`api/health.py:15-28` — the body is exactly `status, service, version, timestamp, database`; `storage/database.py:36-52` returns only `status/dialect/url`. Repo-wide grep for `psutil|RSS|virtual_memory|getrusage|tracemalloc|memory` in `backend/app` finds no memory figure; `core/cache.py:39-42 cache.size()` is an entry count, used at `health.py:49` and `:73`. The adjacent undocumented endpoints expose `cache_size`, `cache_entries` and `pipeline_locked` only.

**D10. Observation-count figure is stale in both spec and code comment.**
Documented **2,896,415** (spec line 101, `severity/scoring.py:35` comment "Measured across 2,896,415 Indian Observations") vs live DB **2,895,064** — gap 1,351 (**+0.047%**). Repo-wide grep returns exactly those two hits. Percentiles recompute exactly from the same table via nearest-rank on `frp_mw` (n = 2,895,064): **P50 4.05, P90 13.32, P95 20.81, P99 64.49**, matching spec lines 104-107 and `scoring.py:36-39` verbatim — **the calibration is genuinely sound; only the workload count is wrong** (no score, weight or threshold changes). Extra data point: `firex_v2.db.bak_checkpoint` holds 2,896,417 rows, so the documented figure matches neither the shipped DB nor the backup.

**D11. Frontend calibration note omits P95 — but the claim's impact sentence is wrong.**
`frontend/js/dossier.js:146` emits `'Calibrated against Indian national satellite percentiles (P50: 4.05 MW, P90: 13.32 MW, P99: 64.49 MW).'` — P95 is indeed absent. **Correction: the claim that the omission "gives an operator no reference point for the P95 ceiling" should be dropped — P95 is surfaced twice in the same dossier view**: (1) the sibling warning at `dossier.js:145` prints it inline (`exceeds 95th percentile historical baseline (${fmt.dec(p95)} MW)`), and (2) the `Historical Heat Baseline` block (`climatologyBaseline`, `dossier.js:151-167`) renders `['Surge Alert Threshold (P95)', ...]` at `:163`, emitted into the same dossier at `:262`. The defect is only an incomplete provenance string.

**D12. Reticle model split-brain / `AI_MODEL` vs `AI_MODEL_NAME`.**
`intelligence/provider.py:46` calls `settings.AI_MODEL`; `api/health.py:65` reports `settings.AI_MODEL_NAME`; `v2/backend/.env` sets only `AI_MODEL_NAME=google/gemma-4-26b-a4b-it` and there is **no `AI_MODEL` line** — so `/status` names a model that is never called, the documented knob is inert, and the actual call goes to `dots-studio/dots-3-note-preview:free` (`config.py:43`). `README.md:14` (badge), `README.md:98`, `v2/README.md:21` and `docs/FIREX_Architecture_and_Codebase.md` all still name "MiniMax M3". `v2/README.md:26` advertises the console at Port 8000 while the FastAPI app defaults to 8000 and `v2/frontend/server.py` binds 8000 as well.

**D13. Climatology constants drift beyond the verified sweep.**
`build_thermal_climatology.py` docstring states "0.02° (~2.2 km)" and thresholds `active_days >= 30, night_ratio >= 0.30`; the code uses `ROUND(latitude, 2)` (0.01°), keys `GRID_{lat:.2f}_{lon:.2f}`, and `if active_days >= 25 and night_ratio >= 0.25`. `behavior/baseline.py:166` carries the same "pre-computed 0.02° grid" claim.

**D14–D20. README.md and the architecture doc describe a repo that no longer exists.**
- `README.md:79-109` "Repository Layout" documents root `dashboard/`, `pipeline/` (`01_firms`..`07_persistence`) and `archive/legacy_ui/` — none exist at the root; that exact tree exists under **`v1/`**. Neither README nor the architecture doc mentions `v1/` or `v2/` at all (grep returns nothing).
- `README.md:2` references `ce4e4a004f53657e4979565e8240e096.png`, absent from the root (`ls *.png` → no such file), so the landing page shows a **broken image**.
- `README.md:28` and `:148` advertise "Total FRP" / "peak and total FRP" aggregation that INV-2 forbids and the code does not compute. Correction: a field literally named `cluster_total_frp` **is** exported (`pipeline.py:312`, aliased to `current_max_frp`, present in `frontend/data/incidents.json`) — the README's language contradicts the invariant, but "a field that must never exist" is slightly overstated; what does not exist is any summed value.
- `README.md:70` and `:89` attribute `/api/trigger-sync-stream`, `/api/history-stats` and the port-8000 console to a root `dashboard/` directory. The routes live at `v2/backend/app/api/analysis.py:209` and `:250`; the console is mounted at `v2/backend/app/main.py:136`; `dashboard/server.py` exists only at `v1/dashboard/server.py`. Root `run.py:37` launches `v2/backend/run.py`, so the README describes the v2 console while naming a v1 path.
- `README.md:106-108` omits `docs/FIREX_Architecture_and_Codebase.md` (6540 B) from the docs listing — the sister architecture document is undiscoverable from the README's own tree.
- `README.md:115-121` presents `requirements.txt` (`requests>=2.31.0`, `Pillow>=10.0.0` only) as the prerequisite, but the documented server needs fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, psycopg2-binary, pytest and httpx (`v2/backend/requirements.txt`) — **`python run.py serve` fails on import in the documented environment**.
- `README.md:28, :56` and `docs/FIREX_Architecture_and_Codebase.md:43` fuse pixels within "≤25 km"; the shipped path uses 1500 m (`pipeline.py:510`) and the default 2000 m (`clustering.py:107`), with no 25 km clustering anywhere in the backend — **off by ~16-17x**.
- `docs/FIREX_Architecture_and_Codebase.md:13-35` draws the same stale root tree. Correction: its `docs/` line at `:34` reads `docs/ # Technical briefs and documentation (where this file resides)` and does **not** enumerate contents, so the claim that it "names only PS162_FIREX_Project_Master_Brief.md and assets/" is mistaken (that is `README.md:106-108`).
- `docs/...:24, :30, :37-47` teaches a 7-stage pipeline (`05_orchestrator/run_pipeline.py` running stages 1-7; Stage 2 = Geographic Selection, Stage 6 = Risk Engine) vs the spec's Stage 2 = GIS & Geodesy, Stage 7 = Severity Engine (`V2_LOGIC_SPECIFICATION.md:59-70`). The v2 code implements the 12-stage model as `app/{ingestion,gis,incidents,behavior,selection,imagery,intelligence,severity,alerts,orchestration}`; `v1/pipeline/05_orchestrator/run_pipeline.py` is the superseded runner.
- `docs/...:53-58` lists five `run.py` commands (`serve`, `daemon`, `pipeline`, `data`, `legacy`) but **only `serve` works** — the other four resolve to root paths that exist only under `v1/` and hit `sys.exit(1)` (`run.py:61-64, :73-76, :86-89, :105-108`). Only `cmd_serve` was updated, at `run.py:37`.
- `docs/...:62-67` mis-attributes routes and claims `/crops/*` serves from `pipeline/03_imagery/crops/`. Correction: the crop route **does** exist (`main.py:109`) and **does** read `V1_CROPS_DIR = .../v1/pipeline/03_imagery/crops` (`main.py:100`, served at `:117-121` as a fallback after the v2 cache at `:112-115`, before on-demand rendering at `:123-131`) — so the imagery path does exist in the running system and only the owning-file attribution is stale.

**D21. `v2/README.md` omits load-bearing packages and overstates docs coverage.**
`:14-25` enumerates eleven `app/` packages but omits `app/api/`, `app/core/` and `app/workers/`; `core/config.py` holds every spec constant (`RATE_LIMIT_PER_MINUTE` at `:64`, `DATABASE_URL` at `:28`) and `api/analysis.py` owns the SSE-style feed the same README's frontend section relies on. `:28` says `docs/` holds "Individual stage verification reports"; `ls v2/docs` returns exactly five files — stages 1-4 plus `v1_audit_and_stage0_notes.md` — for an 11/12-stage pipeline, with nothing marking the set incomplete.

### 2.5 Test-suite holes

**E1. The live-FIRMS test can never fail.**
`tests/test_stage1_ingestion.py:128` `if csv_text:` and `:133` `assert len(parsed) >= 0` — true for every possible list including `[]`. `ingestion/firms.py:45` returns `None` on HTTP != 200 and `:48` returns `None` on any exception, so an offline/quota-limited run skips the whole body and reports **PASS**. Nuance: the live-API promise is the file's own docstring at `:9`; §12 line 621 advertises the file for "SHA-256 deduplication, coordinate bounds, FIRMS parsing" and does not itself promise live coverage.

**E2. The FRP non-summation assertion is decorative, and the citations were wrong.**
The assertions are at `tests/test_stage3_incidents.py:66` `assert c.max_frp == 40.0` and `:71` `assert c.max_frp != 90.0` (**not :78 and :80**). Because 40.0 != 90.0, the second is entailed by the first under any max-preserving implementation. Real coverage is `min_frp == 20.0` (`:67`), `mean_frp == 30.0` (`:68`) and `len(c.observations) == 3` (`:69`). No test asserts the absence of a total field; the persisted model has none (`storage/models.py:66-67` defines only `current_max_frp`/`current_mean_frp`), so a summing refactor would also require a schema change — but nothing in the suite guards that.

**E3. `test_incident_lifecycle_and_association_dedup` is nondeterministic.**
`tests/test_stage3_incidents.py:108-113` (**not :120-124**): `offset = 5.0 + (int(uid,16) % 1000) * 0.02`, `test_lat = 14.0 + offset`, `test_lon = 75.0 + offset` → lat in [19.0, 38.98], lon in [80.0, 99.98]. `boundaries.py:56` rejects lat > 35.7 or lon > 97.4; `:97-109` adds six more bands (`lat>31.4 & lon>80.3`, `lat>32.2 & lon>79.0`, `lat>33.2 & lon>79.4`, `lat>34.8 & lon>78.8`, `lat>35.5 & lon>77.8`, `lon in [88.5,92.0] & lat>28.1`) plus the Nepal/Bhutan envelopes at `:86` and `:92`. `association.py:88-89` `continue`s and returns `[]`. **Corrected rate: ~0.60 rejection probability** by union analysis over the uniform offset (dominant band `offset>17.4` ≈ 0.38), not the claimed ~80% — the exact 5-failed/1-passed figure was not reproducible without executing pytest, but the nondeterminism is certain and large. `assert len(incidents_run1) == 1` fails at that rate in isolation.

**E4. A test permanently mutates live application state.**
`tests/test_stage3_incidents.py:180` `inc = db.query(Incident).first()`, `:184` `client.post(f"/incidents/{inc.id}/state", json={"new_state": "SUBSIDING", ...})`, asserted at `:186-194`, with **no finally-block restoring the prior status** (contrast the explicit cleanup at `:154-170`). `tests/conftest.py` contains no `DATABASE_URL`/dependency override (it only fixes `sys.path`); `storage/database.py:20-26` binds the engine to `settings.DATABASE_URL`, and `core/config.py:28` defaults it to `backend/data/firex_v2.db` — present at **1,282,961,408 bytes (~1.28 GB)**. The assertion is also order-dependent on whichever incident sorts first.

**E5. §12 credits `test_stage9_ui_integration.py` with "Console data feed"; no test requests it.**
Spec line 629. `grep -rn console/feed v2/tests/` returns nothing; the file's only test-side hits are `/api/history-stats` (`:186`), `/api/analysis/status` (`:194`) and `/api/history/search` (`:209`). The route exists (`analysis.py:270`) and its only caller is `frontend/js/data.js:34` — a regression in the feed route would not be caught.

**E6. §12's "Export contract" checks are presence-only, and the search-shape block is vacuous on empty results.**
`tests/test_stage9_ui_integration.py:170,172,178` are `assert 'facility_id' in profile`, `assert 'p95_frp' in profile`, `assert 'p95_frp' in base` — key presence only, so `{}` with keys mapped to `None` passes. `:217` wraps the entire row-shape block (`:218-226`) in `if payload["returned"] > 0:`; `:229-233` only asserts `returned <= 3`. Correction: `:182-198` is **not** purely presence-only — `:192` asserts `data["current_pass"] in ["DAY","NIGHT"]`, a real value constraint, so "likewise presence-only" overstates that specific test.

**E7. §12 says `test_stage4_behavior.py` covers "365d percentiles"; no 365-day window is constructed.**
Spec line 624. `:49` `seq = [10.0, 12.0, 11.0, 13.0, 12.0]` with `:56` `assert stats['p95'] >= 12.0`; the longest synthetic sequence in the file is `for i in range(10)` at `:142` (`range(6)` at `:210`). Every 365-day figure is a literal in a mock payload or an export-contract key (`test_climatology_calibration.py:74 active_days_365d: 284`, `test_industrial_facility_classification.py:111` `280`, `test_mining_basin_classification.py:90` `89`, `test_stage9_ui_integration.py:123` key presence only). The one live-data assertion, `test_climatology_calibration.py:42 bl['active_days_365d'] > 50`, reads a pre-seeded climatology row rather than exercising windowing.

**E8. §12 credits `test_stage3_incidents.py` with "DBSCAN", but every call uses the default.**
`:62, :87, :92, :97` all pass `spatial_eps_meters=2000.0`, exactly `clustering.py:107`'s default. The production call site is `pipeline.py:510` with `1500.0`, and spec line 129 mandates 1500 m. No test calls the function with 1500.0 or no override, and none places a pair 1.6 km apart — the case the shipped pipeline must not merge.

**E9. §12 credits `test_stage10_hardening.py` with "Rate limiting (120 req/min)"; the test never asserts the shipped default.**
Spec line 630. `:111` builds its own app with `requests_per_minute=5` (`:110`), asserting the 6th request is 429 at `:124-127`. The only assertion touching shipped config is `:213 assert data['hardening']['rate_limiting'] is not None` — **no numeric check**. `config.py:64 RATE_LIMIT_PER_MINUTE: int = 120`, wired at `main.py:40`, could change to any number without a test failure. The exempt-path test (`:129-143`) builds another app with `requests_per_minute=2` and only asserts 5 requests to `/console/index.html` succeed — it never proves the exempt path sits outside the limiter's accounting.

**E10. §12 credits `test_stage6_ai_investigation.py` with the "12 AI prompt rules"; no assertion checks rule count, numbering or text.**
Spec line 626. `:149-157` asserts only data substrings (`'INC-TEST-001'`, `'TATA Steel Kalinganagar'`, `'55.0 MW'`, `'11.1 MW'`, `'2.9 MW'`, three taxonomy class names). `grep -rn 'MANDATORY|OPERATIONAL RULES' v2/tests/*.py` returns nothing. Deleting or reordering the rules at `intelligence/prompts.py:17-29` would not fail any test.

---

## 3. False alarms worth knowing about

Checked and cleared — listed so the negative result is on record.

- **Reticle crosshair `gap = 12` → 24 px opening.** Not a divergence. `reticle.py:54, :57-63` matches the ordinary reticle reading (gap = centre-to-arm-start); the spec phrase is ambiguous and contains no other gap measurement. Cleared.
- **Behaviour §4.4 8-row anomaly table.** Conforms exactly — every boundary and operator (`anomaly.py:18-43`: `<=1.0→0, 1.25→10, 1.5→20, 2.0→40, 3.0→60, 4.0→75, 5.0→90, else 100`), with `max(1.0, Median_FRP)`.
- **Behaviour `history_reliability` label tiering.** Exactly NONE/LOW/MODERATE/GOOD/STRONG at 0 / 1-4 / 5-9 / 10-19 / ≥20 (`baseline.py:52-70`). Only the numeric value diverges (see C3).
- **Severity §4.6 coefficients.** All exact — see C15.
- **Selection weighted formulas.** Exact: 0.40/0.30/0.20/0.10 and 0.45/0.30/0.25, both summing to 1.00; override operators and force-to-≥90 exact; FRP input is the spec's log2 curve.
- **Clustering invariants.** FRP max/mean/min never summed; centroid is the arithmetic mean; predicates use correct inclusive operators (`dist_m <= eps`, `|Δt| <= τ`).
- **Alert dedup arithmetic.** `ALERT_ELIGIBLE_LEVELS = {"HIGH","CRITICAL"}` (`engine.py:17, :29-30`); strict `>` on `SEVERITY_RANK` (`:41`); equal severity falls to the dedup return at `:82` — **no off-by-one**.
- **Geodesy basics.** `EARTH_RADIUS_METERS = 6371000.0` ≡ 6371.0 km (km by `/1000.0`); `[lon,lat]` orientation correct (x=lon, y=lat, latitude vs ring index 1); edge enumeration `ring[0]→ring[1]…→ring[0]` correct; `2·atan2(√a, √(1−a))` algebraically identical to `2·R·arcsin(√a)` for `0 ≤ a ≤ 1`.
- **AI §6.2 schema.** All 12 required fields present with correct names and nesting, confidence bounded 0-100, and the real OpenRouter parser (`provider.py:127-191`) reads every one with sane defaults plus a validation-error fallback.
- **§5 mining-basin rule** ("never classify as gas_flare in mining pits"). Correctly enforced.
- **§12 test inventory at file level.** All 14 named files exist with the quoted names; 97 `def test_` functions, pytest collects 102, full run passes **102/102 in ~139 s**. Only the per-file *descriptions* overstate.
- **§9 column claims.** Every table the spec names exists with the named columns — and the `thermal_climatology` PK claim (`spatial_key`) is exactly correct.
- **Alert §8 escalation plumbing.** `[ESCALATED]` title prefix and `ALERT_ESCALATED` event present (`engine.py:50, :64`). The `IncidentEvent` trail **is** an accurate emission record — `ALERT_EMITTED` only on fresh emission (`engine.py:104-115`), `ALERT_ESCALATED` only on escalation (`:64`), dedup writes no event — so only the `alert_emitted` payload boolean (`severity/service.py:126`) and the severity API's `alert` block over-report.
- **Dependency closure.** Every third-party import across `app/`, `scripts/`, `tests/` (`PIL, fastapi, pydantic, pydantic_settings, requests, sqlalchemy`; `starlette` transitively) resolves and is covered by `requirements.txt`. No `ModuleNotFoundError`.
- **Runtime reachability.** `import app.main` succeeds on the author's machine (config.py present on disk); 29 routes; `/health` 200 (0.01 s), `/api/analysis/status` 200 (0.08 s), `/api/history-stats` 200 (0.04 s), `/api/incidents?limit=3` 200, `/api/selection/candidates` 200 (0.76 s), `/api/console/feed` 200 (0.37 s, 323 incidents + 200 ambient).
- **Frontend asset references.** All 26 local refs in `index.html` and `js/*.js` resolve (`styles/*.css`, `js/main.js?v=17`, `data/incidents.json`, `data/ambient_firms.json`); the only external hosts are unpkg / arcgisonline / Google Fonts.
- **The `raw_payload` JSON column is NOT the DB size cause.** `SUM(LENGTH(raw_payload))` = 41,710 bytes total (effectively all NULL); `COUNT(*)` on `observations` is 0.030 s and the baseline query uses `ix_observations_longitude` (~470 rows), not a full scan.

---

## 4. What a judge will find

Highest-risk items from the independent completeness pass, in the order a judge hits them.

**J1. FATAL — the repo cannot boot from a fresh clone.**
`.gitignore:24-26` ignores `config.py` and `**/config.py`. Grepping the git index directly (`PS162/.git/index`) matches `app/core/{cache,logging,ratelimit,security}.py` and **zero paths matching `*config*.py` anywhere in the repo**. `v2/backend/app/core/config.py` (untracked) holds every constant — `DATABASE_URL`, `FIRMS_MAP_KEY`, the AI model id, the four OpenRouter keys, rate limits — and is imported by `app/main.py:6`, `app/intelligence/provider.py:14`, `app/behavior/baseline.py:16`. A clone + `pip install -r requirements.txt` + `python run.py serve` **dies at `from app.core.config import settings`**. The only tracked config artifact is `v2/backend/.env.example`, byte-identical to `.env` (448 B) — so **the live `FIRMS_MAP_KEY` is committed while the file the code imports is not.**

**J2. Nine test fixtures are live in the served queue and in the committed frontend data.**
`incidents` holds 9 rows `INC-HIST-TEST-1789391301 … INC-HIST-TEST-1789581117`, all `status='ACTIVE'`, all `classification='INDUSTRIAL_FIRE'`, all `classification_confidence=0.0`, none with an `ai_investigations` row. They are published right now in `GET /api/console/feed` (measured class histogram `{'INDUSTRIAL_FIRE': 9}`) and baked into committed `v2/frontend/data/incidents.json` (9 of 323 records), where they carry `ai_classification: "INDUSTRIAL_FIRE"`, `ai_confidence: 0.85` and `ai_reasoning: "Verified thermal source classification: INDUSTRIAL_FIRE."` despite confidence 0.0 in the DB. Consequences: (a) `CLASSES` in `frontend/js/config.js:40-49` has no uppercase key, so `classOf()` (`:53-55`) returns `UNKNOWN_CLASS` = "Not visually confirmable" with the question glyph for all 9, and `FILTERS` (`:61`) tests only the lowercase id, making them unreachable from the Industrial filter; (b) root cause is missing test isolation — `v2/tests/conftest.py` overrides `sys.path` only and never sets `DATABASE_URL`, so a test run writes into whichever `firex_v2.db` the CWD resolves to.

**J3. The severity engine's output was never persisted for the live queue, and the published factor breakdown contradicts the published score.**
Of 323 feed records: **320 have `severity_score=0`, `risk_score=0`, `severity_confidence=0`** yet are issued `risk_tier`, `action_recommendation`, `investigation_priority` (e.g. 69.5) and `priority_rank`. **All 323** have `sum(risk_factors[].score) != risk_score` (largest: 175.9 vs 42). And **7 factor entries exceed their own declared maximum** — `INC-2026-0278` publishes `{"factor":"Frp Score","score":45.2,"max":25.0}`, `{"Historical Deviation Score",47.5,20.0}`, `{"Ai Source Severity Score",50.0,30.0}`. The dossier's "why this score" bars overflow their own caps while the headline reads Risk 0 / LOW.

**J4. The console shows zero HIGH/CRITICAL while the alert feed fires CRITICAL at incidents it cannot display.**
DB `incidents.severity_level`: **CRITICAL 5, HIGH 5** — every one `status` in {RESOLVED, SUBSIDING}. `generate_console_feed_data` (`pipeline.py:74-76`) whitelists only ACTIVE/PERSISTENT/INVESTIGATING/NEW/ESCALATED, so the feed's measured tier histogram is `{LOW: 322, MEDIUM: 1}` with **0 HIGH / 0 CRITICAL**. Meanwhile `alert_records` holds exactly those 5 CRITICAL + 5 HIGH as `NEW`, pointing at the same incident ids. A "priority triage console" showing a uniform LOW queue while holding live CRITICAL alerts is the first thing a judge clicks.

**J5. `logger` used but never bound, in the pipeline's own error handler.**
`api/analysis.py:233` — `logger.error(f"[PipelineWorker] Error during sync stream execution: {e}", exc_info=True)` inside the `except` of the background worker behind `GET /api/trigger-sync-stream` (the console's Sync button, `frontend/js/main.js:971`). A re-scan of every `app/**/*.py` for `logger.` without an import/assignment returns **exactly this one file** (`app/main.py` is fine — it imports at line 7). Any real pipeline failure becomes `NameError: name 'logger' is not defined`, so the SSE terminal gets no diagnosis.

**J6. A read endpoint writes to the database on every page load.**
`generate_console_feed_data` (`pipeline.py:93`) calls `get_or_create_location_baseline`, which at `behavior/baseline.py:272` executes `db.commit()` (row insert/update) for any incident without a <24 h cache row. `GET /api/console/feed` is fetched by `frontend/js/data.js:34` on load.

**J7. The imagery panel — the platform's centrepiece — has no imagery for the live queue.**
`v2/backend/data/crops` contains exactly one directory, `inc_test_vis_mumbai` (a fixture, not an incident id); **0 of the 320 ACTIVE incidents** have a crop dir. `v2/backend/data/imagery_cache` (1,293 files, ~646 ids) is keyed to ids outside the current queue. Every `/crops/<uuid>/annotated.jpg` emitted by the feed falls through to on-demand synthesis (`main.py:123-133`) and then `imagery/provider.py:60, :69`, which fetches `mt1.google.com` then `server.arcgisonline.com` with 3 s timeouts; on failure `provider.py:40-45` returns a flat dark `(28,33,40)` synthetic tile. Offline (the normal venue), the "tactical reticle HUD" renders **placeholder terrain for 100% of the queue**. The map itself also needs unpkg (Leaflet) + arcgisonline tiles.

**J8. Two of the four dead entrypoints are the ones the judge-facing runbook tells you to run.**
`run.py`'s `pipeline`, `data`, `legacy`, `daemon` subcommands all `sys.exit(1)` (root `pipeline/`, `dashboard/`, `archive/` exist only under `v1/`), and `docs/PS162_FIREX_Project_Master_Brief.md` §5 "Verification Runbook" instructs `python run.py serve`, **`python run.py pipeline`**, **`python run.py data`**.

**J9. The Master Brief was never audited — and it is the judge-facing document.**
`docs/PS162_FIREX_Project_Master_Brief.md` §3 tabulates **"100% Operational"** for 8 components, each linked to `file:///.../pipeline/...` or `.../dashboard/...` paths that do not exist. §4.1 asserts **"Cluster Total FRP … 238.3 MW aggregated radiative power"**, directly contradicting INV-2 and the code (`pipeline.py:312` deliberately assigns `current_max_frp`). §4.2 declares `CRITICAL_INFRASTRUCTURE` at 35 km and `MAJOR_FIRE_SURGE` at ≥12.0 MW peak / ≥25.0 MW "cluster total"; the code uses containment-or-≤5 km (`pipeline.py:106`) and `current_max_frp >= 50.0`. §2 repeats "≤25 km" clustering; §3 stage 7 names a DB `firex_history.db` whereas code and data use `firex_v2.db`.

**J10. Internal spec contradictions.** `V2_LOGIC_SPECIFICATION.md:40` — "executes **twelve** discrete stages"; its own Stage Summary Matrix lists stages **0-10 (eleven)** and its mermaid DAG has **nine** nodes.

**J11. DB footprint / duplicate artifacts on a synced drive.** `v2/backend/data/firex_v2.db` = 1,282,961,408 B in `journal_mode=wal` with live `-shm`/`-wal` siblings, all inside OneDrive; `firex_v2.db.bak_checkpoint` = 1,203,228,672 B plus its own `-wal`/`-shm`; a **second** `v2/data/firex_v2.db` (471,040 B) is what the tracked relative `DATABASE_URL=sqlite:///./data/firex_v2.db` selects when the server is started from `v2/`; and `v2/backend/data/firex.db` is a 0-byte stray.

**J12. Empty module directories.** `v2/backend/app/workers/` and `v2/scripts/` contain no files (no `__init__.py`), despite `app/workers` being imported nowhere and implied by the README's component list.

---

## 5. Recommended fixes

Ranked. Each names the file to change.

**R1 (blocker). Make the repo bootable.** Change `.gitignore:24-26` so `v2/backend/app/core/config.py` is tracked, or commit a `config.example.py` + env loader. Immediately remove the live `FIRMS_MAP_KEY` from `v2/backend/.env.example` (it is byte-identical to `.env`) and **rotate the key**. This gates every other fix.

**R2 (highest correctness severity). Stop publishing unverified classification.**
`backend/app/orchestration/pipeline.py:178-183` — delete the `cls_name = "uncontrolled_industrial_fire"` / `ai_conf = 0.88` assignment and map the geometry heuristic to `"uncertain"` with a low confidence. Either add the class to the spec's six or stop emitting it. Also add uppercase handling to `frontend/js/config.js:40-55` if any uppercase classification is retained (J2).

**R3. Fix the severity composite.**
`backend/app/severity/scoring.py:83-95` — change `elif ratio >= 1.0:` to `> 1.0` so r == 1.0 reaches the suppression branch; drop the undocumented `max(10.0, ·)` floor or write it into the spec; and either clamp the composite to ≤20.0 for `is_routine_flare and frp_mw <= p95_frp` at `:256-262`, or reword INV-4 to say "S_dev ≤ 20.0". Update `tests/test_climatology_calibration.py:143` to assert the composite.

**R4. Make FIRMS confidence real.**
`backend/app/selection/engine.py:58-63` — aggregate the member observations' real confidence (`storage/models.py:36 confidence_score`) instead of the literal `80.0`. Add a `firms_confidence` column to `Incident` (`storage/models.py:53-103`) and pass it at `backend/app/severity/service.py:67` instead of `incident.severity_confidence or 75.0`. Fixes A9 and A10 together.

**R5. Correct the anomaly scale.**
`backend/app/selection/engine.py:56` — `anomaly_score = float(...) * 100.0`, or return 0-100 from `backend/app/behavior/anomaly.py:119` and update `tests/test_stage4_behavior.py:96`. Fixes the 100x underweight.

**R6. Fix the persistence inputs.**
`backend/app/selection/engine.py:44` — call the already-imported `calculate_persistence_score` with `active_days` so PERSISTENT can clear the 85.0 override. Reconcile `backend/app/behavior/persistence.py:50-57` and `backend/app/behavior/baseline.py:72-87` with the spec, or amend spec lines 153/155-162. Same decision for the 90-vs-365-day window (`baseline.py:101, :298`).

**R7. Align the routine-flare flag.**
`backend/scripts/build_thermal_climatology.py:104-115` — threshold `>= 10`, add the P95 condition using the already-computed `p95_frp` (currently dead at `:80-82`), add an `acquired_at` predicate at `:50-62`, and move the grid to the spec's 0.02°. Make `backend/app/behavior/baseline.py:141` and `:288` agree with whichever rule survives.

**R8. Enforce a real sovereign boundary.**
`backend/app/gis/boundaries.py:56` — replace the rectangle stack with the spec envelope 68.7–97.4°E / 8.4–37.6°N plus a polygon mask, reusing the existing `backend/app/gis/spatial.py:61 point_in_geojson_geometry`. Add a per-member filter at `backend/app/incidents/association.py:88` and a 72 h cutoff at `backend/app/api/incidents.py:147`.

**R9. Send the AI rules.**
`backend/app/intelligence/provider.py:74-82` — prepend `{"role": "system", "content": SYSTEM_PROMPT}` (import from `intelligence/prompts.py`) to the message list; restore the `"Unknown"` literal at `prompts.py:21`. Add a system-message assertion to `tests/test_stage6_ai_investigation.py`.

**R10. Guard the alert lifecycle.**
`backend/app/alerts/engine.py:123-177` — add a precondition/transition table; `:38-60` — set the superseded alert to RESOLVED before inserting the escalation; `:78-82` — return `None` on dedup, or return the record with a `deduplicated: bool` flag that `backend/app/orchestration/pipeline.py:645-660` respects.

**R11. Fix the geodesy primitives.**
`backend/app/gis/spatial.py:21-22` — add the `min(1.0, ·)` clamp (and the duplicate at `backend/app/api/observations.py:107`); `:49-55` — flip to the spec's `[min, max)` latitude test and strict `x < xinters`.

**R12. Fix the reticle.**
`backend/app/imagery/reticle.py:46-51` — derive ring radii from the frame (`factor * min(w,h)//2`) and relax the guard at `:49`; `:86-93` — draw the scale bar when it fits or shrink it. `backend/app/imagery/viewport.py:29-37, :97-105` — make the crop match the declared radius (raise zoom or shrink the declared radius) and pass the correct m/px to `reticle.py:17`; fix the m/px figure at `intelligence/prompts.py:92, :102`.

**R13. Isolate the tests.**
`v2/tests/conftest.py` — set `DATABASE_URL` to a temp file or `sqlite:///:memory:` fixture. Delete the 9 `INC-HIST-TEST-*` rows from `backend/data/firex_v2.db` and regenerate `frontend/data/incidents.json`. Make `tests/test_stage3_incidents.py:180` create and tear down its own incident, and `:108-113` use fixed in-boundary coordinates. Replace `assert len(parsed) >= 0` (`test_stage1_ingestion.py:133`) with a real assertion or an explicit skip.

**R14. Repair the boot path and entrypoints.**
`run.py` — delete or repoint the `pipeline`/`data`/`legacy`/`daemon` subcommands (`:61-108`) at v2; add the v2 dependencies to the root `requirements.txt`; ship the `config.py` template from R1.

**R15. Persist severity before export.**
`backend/app/orchestration/pipeline.py:257-269` and `:390-392` — actually run the severity engine over the queue before writing `frontend/data/incidents.json`, so `risk_score` is non-zero and `sum(risk_factors[].score)` reconciles with it. Align `generate_console_feed_data`'s status whitelist (`:74-76`) with the alert feed (J4).

**R16. Reconcile the documentation.**
Rewrite `README.md` and `docs/FIREX_Architecture_and_Codebase.md` against the v2 tree, or move them under `v1/` and write fresh v2 docs; add the missing logo PNG (`README.md:2`); fix the "Total FRP" language (`README.md:28, :148`); document the v1/v2 split. Then work the spec backlog: settle `mining_related` vs `mining_or_other_thermal_source`; fix the 13-vs-15 table count (§9); align the SSE event names or document the dotted wire form; add `historical_baselines` to the numbered definitions; correct the observation count to 2,895,064; and either add the memory metric or drop the `/health` promise.

---

**Areas that matched cleanly, one line each:** §4.4's anomaly table and the reliability *labels*; §4.6's severity coefficients and override math; selection's two weighted formulas; clustering's FRP max/mean/min and temporal predicates; geodesy's earth radius, ring orientation and edge enumeration; §6.2's schema; and §12's file inventory and test count (102/102 passing). The remaining defects are concentrated in three clusters — the confidence/override plumbing (R4), the climatology-derived flags (R7), and a documentation set frozen at the v1 layout (R16).

---

## Part 3 — Confirmed findings (97)

Grouped by subsystem. Every entry survived adversarial refutation.


### Multimodal AI Protocol

#### F-001 — AI PROTOCOL / DEAD CODE

**Claim.** 6.1 rule 4: the required literal token "Unknown" is not mandated; prompts.py:21 only says 'state so', and nothing downstream checks for the sentinel.

**Evidence.** Confirmed as a text divergence. prompts.py:21 reads '4. Never invent or hallucinate missing values. If an attribute is unknown, state so.' versus spec V2_LOGIC_SPECIFICATION.md:306 '...If an attribute is unknown, explicitly state "Unknown".' — both 'explicitly' and the literal sentinel are dropped. Grep for 'Unknown' in backend/*.py returns only two sites, neither a rule or a validator: prompts.py:53 (the code itself emits "Unknown" as the facility-distance fallback value when facility_distance_m is None) and api/history.py:347 (a district display default). IMPACT CORRECTION (overstated): the claim's 'no validator can flag fabrication' implies one exists elsewhere — none does; no downstream consumer parses an 'Unknown' sentinel on either side, so the alleged detectability was never implemented regardless of the prompt wording. The claim's parenthetical that 'unknown' occurs only lowercase inside that sentence is also inaccurate: prompts.py:53 emits capital-U "Unknown". This is a prompt-wording nit, not a broken contract.

**Refuted:** no — confirmed

---

#### F-002 — AI PROTOCOL / DEAD CODE

**Claim.** 6.1: the 12 mandatory rules must be in the system prompt sent to the model; SYSTEM_PROMPT is defined but never imported or transmitted, so no model call receives the rules.

**Evidence.** Confirmed. prompts.py:9-30 defines SYSTEM_PROMPT. A repo-wide grep for 'SYSTEM_PROMPT|system_prompt' (py/ts/tsx/md/json) returns ONLY prompts.py:9 — no import anywhere. provider.py:74-82 is the only message builder in the codebase and emits a single {"role": "user", "content": [text, image_url]} entry; grep for '"system"' across backend/*.py returns zero matches. provider.py:22 imports only PROMPT_VERSION and vision.py:10 only build_investigation_prompt. build_investigation_prompt (prompts.py:96-153) contains no rule statements — only per-incident telemetry, mining/metallurgical operational notices, the 6 taxonomy choices and the JSON skeleton. tests/test_stage6_ai_investigation.py:149-157 asserts only on the user prompt, never on SYSTEM_PROMPT. IMPACT CORRECTION (overstated): 'enforcing none of Section 6.1' is too strong — rule 6 is enforced structurally by the required 'alternative' object (prompts.py:131-134, schemas.py:61), rule 10 by the 'uncertain' taxonomy entry, rule 12 by 'Return ONLY the raw JSON object' (prompts.py:153), and rule 5 implicitly by the absence of any severity field. But the explicit rule text for rules 1,2,3,4,8,9,11 and the whole numbered rule block genuinely never reach the model.

**Refuted:** no — confirmed

---

#### F-003 — UNIT / SCALE ERROR

**Claim.** 6.2: image_quality.score is a numeric 0-100 value (spec example 92.0, i.e. fractional); code declares `score: int` and truncates with int().

**Evidence.** Confirmed as a type divergence with concrete evidence: schemas.py:31-37 declares `score: int = Field(80, ge=0, le=100)`; provider.py:173 coerces `score=int(img_q_raw.get('score', 80))`; prompts.py:145 asks for '<0 to 100>'; the only other producers are provider.py:232 (score=50) and 344 (score=90), and tests/test_stage6_ai_investigation.py:206 uses "score": 85 — all integers. The spec's example at V2_LOGIC_SPECIFICATION.md:336-337 is `"score": 92.0`, a JSON float literal, so an int field cannot reproduce the spec's serialized form and `int(92.5)` would floor to 92. IMPACT CORRECTION (largely overstated): the schema search found no section-16-style typed definition — 92.0 is an integral value whose decimal point carries no fractional information, so 'i.e. fractional' is an unsupported inference and no precision is lost for spec-conformant output; truncation only bites if a model volunteers a fractional score, which the '<0 to 100>' prompt does not request. All other 6.2 schema fields do match the spec, as the claim states.

**Refuted:** no — confirmed

---

#### F-004 — AI PROTOCOL / DEAD CODE

**Claim.** 6.2: the sixth classification enum value is mining_or_other_thermal_source; code uses mining_related everywhere and coerces the spec literal to 'uncertain'.

**Evidence.** Confirmed on the core. Spec uses the literal at 4.6 (V2_LOGIC_SPECIFICATION.md:237 rating 65), 5 taxonomy (line 282), 6.2 (line 319) and 5 disambiguation matrix (line 292). Code: schemas.py:10-17 TaxonomyClass Literal contains 'mining_related' (no spec literal); provider.py:194-201 valid_classes has 'mining_related'; provider.py:208 alias 'mining':'mining_related'; prompts.py:76 and 124 use 'mining_related'; provider.py:313 mock classifier returns 'mining_related'. _normalize_taxonomy (provider.py:210-214) lowercases/replaces, finds no alias for 'mining_or_other_thermal_source', and since it is not in valid_classes returns 'uncertain' — so a spec-conformant model output IS silently downgraded. Blueprint md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md ~2185-2194 does specify mining_related, so the spec/blueprint conflict the claim notes is real. IMPACT CORRECTION (the claim's severity note is WRONG): backend/app/severity/scoring.py:106 DOES contain "mining_or_other_thermal_source": 65.0 (the exact spec value) immediately above line 107's "mining_related": 60.0, and pipeline.py:133 and 148 explicitly remap cls_name 'mining_related' -> 'mining_or_other_thermal_source' before downstream use. So the spec's 65 rating is implemented, not missing, and 'lowest-confidence bucket' is imprecise (uncertain=50 sits above gas_flare=38 and agricultural_burning=32).

**Refuted:** no — confirmed

---

#### F-005 — AI PROTOCOL / DEAD CODE

**Claim.** 6.3: On HTTP 429 quarantined 60s, on 401/403 quarantined 1 hour — code collapses all status codes into rotate_key() with no timing, and the 60s/1h constants do not exist.

**Evidence.** Confirmed at provider.py:105-109: 'elif resp.status_code in [429, 401, 402, 403]:' logs and calls key_pool.rotate_key() with no argument. rotate_key (key_pool.py:47-60) only advances current_idx modulo len(api_keys) and bumps 'failovers' — it has no time/duration/state parameter and the class stores no timestamps. Grep for 'cooldown|quarantine' in backend/ returns nothing (only spec + README). 402 is indeed in the branch though the spec lists only 429/401/403. IMPACT CONFIRMED: config.py:47 AI_MAX_RETRIES=4 and config.py:49-54 lists exactly 4 OPENROUTER_API_KEYS, so one incident attempts each key once; a 429'd key is re-selected on the very next incident with no backoff, and a revoked 401/403 key is retried at full rate. README.md:21 advertises 'auto-cooldown' which the code does not implement.

**Refuted:** no — confirmed

---

#### F-006 — AI PROTOCOL / DEAD CODE

**Claim.** 6.3: Provider fallback cascades Gemini 2.5 Flash/Pro -> Groq Vision -> OpenAI GPT-4o -> Deterministic Sovereign Mock Provider; code has only one OpenRouter provider plus an in-class hardcoded fallback report.

**Evidence.** Confirmed. provider.py:355-362: get_ai_provider() returns MockAIProvider only when settings.AI_PROVIDER == 'mock', else always OpenRouterProvider. config.py:42 AI_PROVIDER is 'openrouter' (comment enumerates only 'openrouter','mock'), config.py:45 AI_API_BASE_URL='https://openrouter.ai/api/v1', config.py:43 AI_MODEL='dots-studio/dots-3-note-preview:free'. Grep for 'groq|gemini|gpt-4o|openai|cascade|fallback_chain' across backend/ AND frontend/src returns zero matches — no Groq/OpenAI/Gemini client exists. On exhaustion investigate() returns self._build_fallback_report(...) (provider.py:122-125), an in-class hardcoded report (provider.py:216-240, classification='uncertain', confidence=50.0) that never delegates to MockAIProvider, so the mock is reachable only via the manual config switch. IMPACT CORRECTION (minor): the phrase 'non-deterministic-shaped stub' is wrong — _build_fallback_report is fully deterministic/hardcoded; the real gap is that three of the four cascade legs do not exist and the fourth (OpenRouter, not Gemini) is the only live path.

**Refuted:** no — confirmed

---

#### F-007 — AI PROTOCOL / DEAD CODE

**Claim.** 6.3: Tracks error_count, cooldown_until, and total_requests — but KeyPoolManager only tracks calls/successes/failovers.

**Evidence.** Confirmed at key_pool.py:23-26: self.stats[i] = {"calls": 0, "successes": 0, "failovers": 0}. Repo-wide grep for 'cooldown|quarantine|error_count|total_requests' returns matches ONLY in V2_LOGIC_SPECIFICATION.md:348-349 and README.md:21 — zero in backend/tests/frontend code. No cooldown_until/error_count field exists in the class (key_pool.py:12-83 read in full). IMPACT CORRECTION (partially overstated): the claim's 'only calls, which is incremented once per attempt at provider.py:87' actually concedes that 'calls' IS a functional per-key total-requests counter (record_call, key_pool.py:68-72), and 'failovers' (key_pool.py:56) is incremented on every error rotation path (provider.py:109,115,119), so it functions as a per-key error counter. Two of the three named metrics therefore have same-purpose analogs under different names; only 'cooldown_until'/quarantine state is genuinely absent at all.

**Refuted:** no — confirmed

---


### Alerts & Imagery Reticle

#### F-008 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 1. Sec 7 range rings: drawn radius comes from declared incident radius, not the frame; ring at 56% of frame radius and the 80% ring is silently skipped

**Evidence.** backend/app/imagery/reticle.py:46-51 confirmed verbatim: r_m = radius_meters*factor; r_px = int(r_m/meters_per_pixel); guard `if 15 < r_px < min(w,h)//2 - 10` (310 for a 640px crop). I re-rendered the reticle on a 640x640 black canvas at lat 22.025/zoom16 (m/px 2.214) and scanned every circle radius 20-300: for radius=1000 the ONLY ring detected is r=180 (== int(400/2.214), 180/320 = 56.3% of frame radius); 0 non-background pixels at r=128 or r=256. The 0.8 ring computes to 361 > 310 and is skipped (reticle.py:50 never executes). Same for the isolated-event tier (radius 500 @ zoom17, m/px 1.107 -> r_px 180, 0.8 ring 361 skipped). CORRECTIONS: (a) the impact framing is wrong — the amber ring sits at ~398m of real ground distance (180px x 2.214), i.e. exactly the distance its own '400m' label states; the ring is NOT at a wrong ground distance, the frame simply is not the radius the metadata declares (that is claim 2). (b) The '2000m large-cluster tier always renders a single ring' half is false as implemented: backend/app/imagery/service.py:42-48 never passes cluster_radius_meters, and no caller does (grep: only viewport.py:43/84), so viewport.py:84 yields radius = min(2000, max(1200, 0.0+500)) = 1200 at zoom 15 — rendered rings = [108, 216], i.e. BOTH rings. The 750m small-cluster tier also draws both (135 and 271). So the defect hits exactly the isolated-event (500m) and medium-cluster (1000m) tiers (plus a hypothetical true-2000m radius), not all 'primary tiers'.

**Refuted:** no — confirmed

---

#### F-009 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 2. Viewport declares radius_meters and builds bounding_box from it while the fetched 640px crop covers only 320*m/px; determine_zoom_for_radius is latitude-blind and assumes 3.125 m/px

**Evidence.** backend/app/imagery/viewport.py:97-105 builds lat_delta/lon_delta from radius_m/111320 (bbox = +/-radius_m), viewport.py:29-37 has no latitude parameter and returns 14 + int(<=2000) + int(<=1000) + int(<=500) (1000m -> 16). backend/app/imagery/provider.py:80-123 stitches 256px tiles at the given web-mercator zoom and crops 640px, so ground half-width = 320*m/px; with get_meters_per_pixel = 156543.03392*cos(lat)/2^zoom (viewport.py:21-27) that is 320*2.214 = 708.5m at lat 22.025/zoom16 versus the declared/bbox 1000m — 1000/708.5 = 1.41, the 41% overstatement is correct (even at the equator zoom16 gives 2.389 m/px -> 764m, still short). The docstring's own criterion (2*radius in 640px => 3.125 m/px at 1000m) is unreachable at zoom 16 for any latitude (cos(lat) would have to exceed 1). CORRECTIONS: (a) ImageryRecord is NOT a consumer — backend/app/storage/models.py:142-151 stores only provider/zoom_level/urls/captured_at, no bbox or radius. Real consumers are metadata.json (service.py:93-110, returned by the API at backend/app/api/imagery.py:25-34), the investigation package (imagery/package.py:131-134), and — not mentioned by the claim and the most consequential — the vision-AI prompt: backend/app/intelligence/prompts.py:92,102 renders 'Optical Scene Context: {provider} optical crop, radius ~1000m (Zoom 16)' to the model for a crop that covers +/-708m. (b) The claim misquotes viewport.py:29-37 as exposing '640x640 crop => ~1.2km tactical radius'; no such string exists anywhere in the repo (grep: none) — the docstring states the intent that the claim says is unmet. (c) '~1.2 m/px at Zoom 16' (spec line 380) is not merely unused, it is arithmetically wrong for the code's own Web Mercator formula (2.0-2.4 m/px across Indian latitudes); reticle.py:17's 1.2 default is reached only by the direct call in tests/test_stage5_selection_imagery.py:197, exactly as claimed; service.py:80 passes 2.214.

**Refuted:** no — confirmed

---

#### F-010 — UNIT / SCALE ERROR

**Claim.** 3. Sec 7 scale bar: for radius 1000 / zoom 16 scale_px (225) fails the `scale_px < w//3` (213) guard so the whole bar+label is skipped, latitude-dependently

**Evidence.** backend/app/imagery/reticle.py:84 computes 200.0 if radius<=800 else 500.0; reticle.py:86-93 draws only `if scale_px < w // 3` (640//3 = 213). Reproduced by rendering: bright (r,g>200) pixels on the bar row (y=628) = 0 for radius 1000/mpp 2.214 (Kolkata) and 0 for mpp 2.097 (Delhi, lat ~28.6), but 220 for mpp 2.365 (lat 8/Kanyakumari); 99 for radius 750 (200m bar, 90px), 189 for radius 500 (200m bar, 180px), 121 for radius 1200 @ zoom15 (500m bar, 112px). So the dropout is real, silent (no log, no metadata flag — service.py:93-110 records nothing about the bar), and latitude-dependent exactly as claimed. Minor scoping correction: it affects the radius>800 tiers at zoom 16 — the medium-cluster 1000m tier and custom radii roughly in (800, 1057] at zoom 16 — not 'the documented Zoom-16 path' wholesale (the 750m small-cluster tier also runs at zoom 16 and does render a 200m bar); 'most of India' is right (the guard clears only where cos(lat) > 0.9826, i.e. lat < ~10.7 deg).

**Refuted:** no — confirmed

---

#### F-011 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 4. Sec 8 alert state machine is unenforced: no transition table/guard, so NEW->RESOLVED, DISMISSED->ACKNOWLEDGED, RESOLVED->ACKNOWLEDGED etc. are accepted

**Evidence.** backend/app/alerts/engine.py:123-177: acknowledge_alert (line 129), resolve_alert (line 148), dismiss_alert (line 167) are bare `alert.status = "..."` assignments preceded only by a not-found check — no precondition comparing the current status. backend/app/api/alerts.py:43-97 (POST /acknowledge, /resolve, /dismiss) calls them directly with no guard. The only VALID_TRANSITIONS map in the repo is the incident one (backend/app/incidents/state.py:13-22), and even there state.py:57-61 only logger.warning's and proceeds. backend/app/severity/state_machine.py contains only determine_lifecycle_state (incident states NEW/INVESTIGATING/ACTIVE/ESCALATED/PERSISTENT/SUBSIDING/RESOLVED via app.incidents.state.VALID_STATES) and never references AlertRecord. get_active_alerts (engine.py:194) filters status in (NEW, ACKNOWLEDGED), so DISMISSED->ACKNOWLEDGED and RESOLVED->ACKNOWLEDGED do re-surface closed alerts as active, exactly as claimed.

**Refuted:** no — confirmed

---

#### F-012 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 5. Sec 8 exactly-once escalation: escalation INSERTs a second alert without closing the superseded one, and dedup only inspects the newest active row, so escalation can repeat

**Evidence.** backend/app/alerts/engine.py:38-60: on escalation the code creates a new AlertRecord (lines 47-59) and db.add()s it without touching `latest` — no status change on the superseded HIGH row — so two NEW alerts coexist; tests/test_stage7_severity_alerts.py:316 asserts count()==2, and lines 311-316 show HIGH/NEW + CRITICAL/NEW. engine.py:33-36 selects active alerts ordered by created_at.desc and engine.py:39 inspects only active_alerts[0]; engine.py:41 compares SEVERITY_RANK ranks. Once the CRITICAL row leaves the active set (resolve/dismiss) the stale HIGH/NEW row is active again, 4 > 3 holds, and another [ESCALATED] CRITICAL alert + ALERT_ESCALATED event is emitted. 'Byte-identical' is accurate except that the description embeds assessment['severity_score'] (line 53), which differs across evaluations; the title (line 50) is identical.

**Refuted:** no — confirmed

---

#### F-013 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 6. Sec 8 audit logging cannot distinguish a dispatched alert from a deduplicated one: alert_emitted is True on every HIGH/CRITICAL re-evaluation and the API reports an alert block for a suppressed evaluation

**Evidence.** backend/app/alerts/engine.py:82 returns the existing `latest` row on the dedup path and engine.py:117 returns a freshly inserted row on emission — indistinguishable to the caller. backend/app/severity/service.py:115 assigns alert_record; line 126 sets "alert_emitted": alert_record is not None (True for both paths, since the record is truthy whenever severity is HIGH/CRITICAL); lines 153-157 return "alert": {alert_id, status, title} for a suppressed evaluation too. IMPACT CORRECTION: the claim that 'the exactly-once invariant cannot be verified from incident_events' is wrong — the IncidentEvent trail does distinguish them, because ALERT_EMITTED is written only in the fresh-emission branch (engine.py:104-115, event_type at line 106) and ALERT_ESCALATED only in the escalation branch (line 64); the dedup path writes no event at all. Only the SEVERITY_ASSESSED payload flag (service.py:126) and the severity API response over-report.

**Refuted:** no — confirmed

---

#### F-014 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 8. Sec 10 route is POST /api/alerts/{id}/ack but the code implements /api/alerts/{alert_id}/acknowledge

**Evidence.** backend/app/api/alerts.py:43 `@router.post("/{alert_id}/acknowledge")` vs spec line 476 `/api/alerts/{id}/ack`. The router (prefix '/alerts', alerts.py:16) is mounted at both '' and '/api' (backend/app/main.py:88-89), so the live paths are /api/alerts/{id}/acknowledge and /alerts/{id}/acknowledge — no /ack form exists anywhere (grep for '/ack' across backend and frontend returns nothing), and the sibling /resolve (alerts.py:62) and /dismiss (alerts.py:81) have no row in the spec's route table. tests/test_stage7_severity_alerts.py:446 calls the /acknowledge path, confirming that is the implemented contract. The claim's low-operational-impact note is also right: frontend/js contains no alert-action calls (only UI text/ids such as main.js:244-246, 784).

**Refuted:** no — confirmed

---

#### F-015 — STATE MACHINE / CONTRACT DEFECT

**Claim.** 9. Sec 8 uses RESOLVED as an alert status and the code writes it, while Sec 9's data dictionary and the ORM comment list only NEW/ACKNOWLEDGED/DISMISSED

**Evidence.** backend/app/alerts/engine.py:148 `alert.status = "RESOLVED"` (and the module docstring line 6 lists RESOLVED); backend/app/storage/models.py:283 `status = Column(String, default="NEW")  # NEW, ACKNOWLEDGED, DISMISSED`; spec line 446 lists `status` (`NEW`, `ACKNOWLEDGED`, `DISMISSED`). Resolved alerts are treated as real by the query surface (backend/app/api/alerts.py:21 advertises RESOLVED as a filter value; engine.py:194 excludes it from the active set). There is no enum or CHECK constraint on any status column (all plain Column(String), models.py:58/283/305), so neither list is enforced.

**Refuted:** no — confirmed

---


### Behaviour / Baseline Modelling

#### F-016 — UNIT / SCALE ERROR

**Claim.** 1. persistence_score = min(1.0, (active_days/45)*0.7 + min(1.0, obs/100)*0.3) is unimplemented; code uses freq/15, density/25 and a 0.35 day-night bonus with weights 0.35/0.30

**Evidence.** Spec C:/Users/ssaur/OneDrive/Desktop/PS162/v2/V2_LOGIC_SPECIFICATION.md:153 gives exactly that formula. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/persistence.py:50-57 is verbatim as alleged: freq_score=min(1.0, active_days/15.0), density_score=min(1.0, total_obs/25.0), continuous_bonus=0.35 if both day and night, raw=(0.35*freq)+(0.30*density)+bonus, score=round(min(1.0,raw),2). Repo-wide grep for 45.0/obs_count/100 in behavior/ returns only anomaly.py:43 and :119 (unrelated). Nothing else computes persistence for a location/facility (profile.py:229 and profile.py:425 are the only callers, both this function; selection/engine.py:44 uses a different 0-100 heuristic). Impact is accurate: 15 active days + >=25 obs yields 0.35+0.30+0.35=1.0 vs spec 0.7*(15/45)+0.3*(25/100)=0.308, and the Stage-4 matrix test at anomaly.py:57 (>=0.50) fires far earlier than the spec intends.

**Refuted:** no — confirmed

---

#### F-017 — SPEC / CODE DIVERGENCE

**Claim.** 10. Spec documents observations.daynight as 'D'/'N' (spec:428) but the persisted domain is 'DAY'/'NIGHT'

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:428 says `daynight` ('D'/'N'). Writers persist words: C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/ingestion/normalizer.py:86 `daynight_code = "NIGHT" if str(raw.daynight).strip().upper() == "N" else "DAY"`, passed through at normalizer.py:99 -> firms.py:119, and the bulk loader backend/scripts/ingest_history.py:195-196 does the same. Every consumer compares against the words: build_thermal_climatology.py:56 `daynight = 'NIGHT'`, persistence.py:42-43 `== "DAY"` / `== "NIGHT"`. So the spec table is indeed stale. ADDITIONAL latent inconsistency beyond the claim: D/N spellings survive as defaults elsewhere — backend/app/ingestion/validator.py:21 `daynight: Optional[str] = "D"`, backend/app/orchestration/pipeline.py:365 falls back to "D", and backend/app/api/history.py:345 falls back to "N" — and a bare 'D'/'N' value matches neither branch at persistence.py:42-43, so it is counted as neither day nor night. No runtime failure occurs on the persisted domain, as the claim notes.

**Refuted:** no — confirmed

---

#### F-018 — SPEC / CODE DIVERGENCE

**Claim.** 2. Stage-4 statistics are nominally 365-day (spec:150) but every production caller uses window_days=90, and persistence.py ignores its window_days parameter

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:150 says '365-day rolling window'. Defaults are 90: C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/baseline.py:101 and :298; C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/profile.py:129 and :308. Production callers: profile.py:513 (facility refresh), profile.py:528 (location refresh), backend/app/api/history.py:40,68,166,187 (Query(90)), plus backend/app/selection/engine.py:33,35, backend/app/orchestration/pipeline.py:529,531, backend/app/imagery/package.py:80,82 all pass window_days=90. persistence.py:17 declares window_days and it appears nowhere else in that file (grep match is the signature line only), so callers cannot change it. CORRECTION to the alleged impact: the '~1/4 of the specified values' estimate does not hold on the thermal-climatology branch (baseline.py:172-211), which is consulted first for any cell present in thermal_climatology and returns all-time counts with no date filter at all (see claim 9) plus active_days_365d at baseline.py:195 — i.e. that branch is worse than 1/4, not smaller. The 90-day default only governs the HistoricalBaseline cache path and the raw-observation fallback at baseline.py:218-241.

**Refuted:** no — confirmed

---

#### F-019 — SPEC / CODE DIVERGENCE

**Claim.** 3. history_reliability is a discrete tier (0.0/0.25/0.50/0.75/1.00, spec:155-162) but the code returns a continuous 0.6*count_factor+0.4*days_factor blend clamped to [0.1,1.0]

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:156-162 defines the five discrete values. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/baseline.py:72-87 implements count_factor=min(1.0, obs/20.0), days_factor=min(1.0, active_days/max(1, min(15, window_days//3))), reliability=round(max(0.1, min(1.0, 0.6*count_factor+0.4*days_factor)),2). No label->numeric tier map exists anywhere: the only companion, classify_history_reliability (baseline.py:52-70), returns the string labels only, and grep for MODERATE/'LOW':/'NONE': across backend finds no numeric table. I re-evaluated every figure in the claim at window_days=90 (min(15,30)=15) with active_days==obs: obs=1->0.10, 2->0.11, 4->0.23, 5->0.28, 9->0.51, 10->0.57, 19->0.97, 20->1.00 — all match the claim. CORRECTION to impact: the 0.28-for-5-obs figure assumes the 5 observations fall on 5 distinct days; if they fall on one day the value is 0.18. The multiplier is confirmed at C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/severity/scoring.py:212 (`history_reliability * 100.0`), fed from backend/app/severity/service.py:53,75 which reads the continuous baseline value.

**Refuted:** no — confirmed

---

#### F-020 — SPEC / CODE DIVERGENCE

**Claim.** 4. R_frp is used as an exact quotient against the table (spec:165) but anomaly.py pre-rounds it to 2 decimals before lookup

**Evidence.** C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/anomaly.py:116 `ratio = round(current_frp / max(1.0, median_frp), 2)`; that rounded value is what index 118 -> calculate_frp_ratio_score(ratio) -> the table at anomaly.py:18-26/40-43 selects a row on. Spec V2_LOGIC_SPECIFICATION.md:165 states the ratio is used directly. Boundary behaviour confirmed by the table's `if ratio <= threshold` form: true 1.254 -> 1.25 -> returns 10 where spec row 170/171 gives 20; true 2.004 -> 2.0 -> returns 40 where spec row 173 gives 60; true 1.004 -> 1.0 -> 0 where spec row 170 gives 10. The error direction is downward only (no value rounds up across a published boundary). NOTE: this is a boundary-precision defect only — interior values are unaffected, so the impact is bounded to ratios within 0.005 above a boundary.

**Refuted:** no — confirmed

---

#### F-021 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** 5. Nothing in the spec exempts sparse history, but evaluate_historical_anomaly short-circuits at obs_count < 3 or median_frp <= 0

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:156-162 explicitly defines LOW (1-4 obs) and MODERATE (5-9 obs) reliability tiers and :164-176 applies the anomaly table to the location/facility baseline with no minimum-observation carve-out. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/anomaly.py:99-113 returns frp_ratio 1.0, ratio_score_100 0.0, anomaly_score 0.0, above_p95 False, status INSUFFICIENT_HISTORY and synthesis from classify_behavior_synthesis(persistence_score, False, 1.0) without ever reaching the table at line 118. The resulting synthesis string can only ever be 'new / normal' or 'persistent / normal' (anomaly.py:58-67 with above_p95=False and ratio=1.0), so a 1-2 observation cell with a large true ratio can never land in 'new / abnormal'. Impact is accurately stated.

**Refuted:** no — confirmed

---

#### F-022 — SPEC / CODE DIVERGENCE

**Claim.** 6. Table scores are 0-100 (spec:167-176) and feed the 0.10-weighted priority sum, but anomaly.py stores ratio_score_100/100.0 (a 0-1 fraction) which the selection engine feeds straight into 0.10*anomaly_score

**Evidence.** C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/anomaly.py:119 `anomaly_score = round(ratio_score_100 / 100.0, 2)`, returned at anomaly.py:159. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/selection/engine.py:56 `anomaly_score = float(eval_res.get("anomaly_score", 0.0))` with no rescaling, passed at engine.py:65 into compute_investigation_priority, which at C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/selection/scoring.py:135 computes `0.10 * anomaly_score` alongside 0.40*frp_score / 0.30*persistence_score / 0.20*conf_norm that are all 0-100. Spec V2_LOGIC_SPECIFICATION.md:167-176 defines the scores as 0/10/20/40/60/75/90/100 and :184 uses S_anom in the same sum. So the term maxes at 0.1 points instead of 10.0. The repo's own tests confirm the two scales coexist inconsistently: tests/test_stage4_behavior.py:96 asserts `anomaly_score >= 0.75` (0-1) while tests/test_stage5_selection_imagery.py:116 passes `anomaly_score=50.0` (0-100). Impact accurately stated.

**Refuted:** no — confirmed

---

#### F-023 — SPEC / CODE DIVERGENCE

**Claim.** 7. The synthesis matrix keys on anomaly score >= 50 (spec:178-190), but is_strong_deviation is `above_p95 or frp_ratio > 2.0`, adding a p95 disjunct the spec does not have

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:179 defines the matrix as persistence >= 0.5 crossed with anomaly score >= 50. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/behavior/anomaly.py:58 `is_strong_deviation = above_p95 or (frp_ratio > 2.0)`; the ratio>2.0 leg does correspond to the spec boundary (table jumps 40 at anomaly.py:22 to 60 at :23), but above_p95 is an extra disjunct computed at anomaly.py:117 (`current_frp > p95_frp`) and passed at anomaly.py:132. CORRECTION to the impact: the claim's ratio-1.1 example requires p95_frp < 1.1*median_frp, which is uncommon; the effect is wider than that example though — any current FRP above p95 whose ratio still sits in (p95/median, 2.0] returns table score 40 or less (spec: 'normal') yet is labelled abnormal, which is exactly the ordinary p95-exceedance case.

**Refuted:** no — confirmed

---

#### F-024 — UNIT / SCALE ERROR

**Claim.** 8. Persistence is tested against 0.50 on the 0-1 spec scale, but selection/engine.py manufactures a 0-100 persistence value (75.0 or obs_count*15.0) and feeds it into that same test, making is_high_persistence unconditionally true there

**Evidence.** C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/selection/engine.py:42-45 `obs_count = incident.observation_count or 1` then `persistence_score = 75.0 if is_pers else min(100.0, obs_count * 15.0)`; engine.py:52-56 passes it as persistence_score into evaluate_historical_anomaly; anomaly.py:57 tests `persistence_score >= 0.50`. Since obs_count floors at 1, the minimum value is 15.0, so is_high_persistence is always True on this path and the 'new / *' half of the matrix (anomaly.py:64-67) is unreachable there. The same 0-100 value is correctly scaled for the priority sum at scoring.py:133 (0.30 * persistence_score), which is what makes the reuse as a 0-1 threshold a genuine scale collision. CORRECTION to the impact's scope: the unreachability is specific to the selection path — backend/app/api/history.py:109 passes the real 0-1 profile persistence_score (history.py:106), so 'new / abnormal'/'new / normal' remain reachable through the anomaly API endpoint.

**Refuted:** no — confirmed

---

#### F-025 — SPEC / CODE DIVERGENCE

**Claim.** 9. thermal_climatology is documented as gridded 365-day statistics (spec:442) but the build query has no date predicate and Median_FRP is a synthetic 0.80*mean estimate

**Evidence.** Spec V2_LOGIC_SPECIFICATION.md:442 describes 'thermal_climatology: Gridded 365-day thermal baseline statistics'. C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/scripts/build_thermal_climatology.py:50-62 is `SELECT ROUND(latitude,2), ROUND(longitude,2), COUNT(*), COUNT(DISTINCT SUBSTR(acquired_at,1,10)), SUM(CASE WHEN daynight='NIGHT'...), AVG(frp_mw), MAX(frp_mw) FROM observations GROUP BY lat, lon HAVING obs_count >= {min_detections}` — no WHERE clause at all, so obs_count/active_days/night_ratio are lifetime totals. Lines 80-82 set `median_frp = round(max(0.5, mean_frp*0.80), 2)`, `p90 = min(max_frp, mean*1.60)`, `p95 = min(max_frp, mean*2.10)` — derived from AVG, never from the observed median. This synthetic median reaches the anomaly table for every climatology cell because backend/app/behavior/baseline.py:167-211 consults ThermalClimatology first and returns it (baseline.py:196) as the baseline that anomaly.py:94 reads as median_frp. Impact accurately stated; note the same branch also means R_frp's denominator for those cells is unrelated to the spec's empirical Median_FRP.

**Refuted:** no — confirmed

---


### Climatology Constants & Calibration

#### F-026 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Claim 1: documented observation count 2,896,415 (spec line 101, scoring.py:35) vs actual DB rows; percentile calibration itself is sound

**Evidence.** Read-only sqlite query on backend/data/firex_v2.db: SELECT COUNT(*) FROM observations => 2,895,064. Gap = 2,896,415 - 2,895,064 = 1,351 (~+0.047%), exactly as claimed. Repo-wide grep for the literal number returns exactly two hits: V2_LOGIC_SPECIFICATION.md:101 and backend/app/severity/scoring.py:35 (comment 'Measured across 2,896,415 Indian Observations'), so the 'two places' and 'code comment repeats it' assertions hold. Percentiles recompute exactly from that same table via nearest-rank on frp_mw (n=2,895,064): P50=4.05, P90=13.32, P95=20.81, P99=64.49, matching V2_LOGIC_SPECIFICATION.md:104-107 and scoring.py:36-39 verbatim - so the calibration is genuinely sound and only the workload count is wrong, as the claim states.

**Refuted:** no — confirmed

---

#### F-027 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Claim 2: a third, non-spec linear FRP normalization (FRP/64.49*25) is shipped to users in the frontend risk-factor breakdown and is the dominant path

**Evidence.** The linear form is real and shipped. backend/app/orchestration/pipeline.py:269 = {"factor": "Fire Radiative Power", "score": round(min(25.0, (inc.current_max_frp / 64.49) * 25.0), 1), "max": 25.0, "detail": f"{inc.current_max_frp:.1f} MW Calibrated"}. It sits in the else-branch (:267) guarded by the if at :257 ('if latest_sev and latest_sev.factors:'), exactly as claimed. factors_list is serialized as risk_factors at pipeline.py:349 and written to frontend/data/incidents.json by export_v1_dashboard_data (pipeline.py:390). Grep of frontend/data/incidents.json: 320 occurrences of "factor": "Fire Radiative Power" vs 3 of "India Calibrated Frp Score", so the linear fallback is the overwhelmingly dominant shipped form. The shipped numbers reproduce only from the linear map - score 1.3 at 3.4 MW (3.4/64.49*25 = 1.32) and 2.0 at 5.2 MW (5.2/64.49*25 = 2.02); spec S_FRP(3.4) = 25*log2(4.4) = 53.4 and S_FRP_calib(3.4) = 25*log2(3.4/4.05+1) = 21.98 neither match. Spec 4.2 defines only two maps (V2_LOGIC_SPECIFICATION.md:113 and :118); no linear or /64.49 scaling exists anywhere in the spec (grep for '64.49'/'log_2' hits only those lines and the four constants). The factor is user-visible: frontend/js/data.js:157-164 maps risk_factors -> c.risk.factors, and frontend/js/dossier.js:84-95 renders name/score/max/detail in the 'Risk Assessment' section (dossier.js:265).

**Refuted:** no — confirmed

---

#### F-028 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Claim 3: the frontend calibration note lists only three of the four spec percentiles, omitting P95 = 20.81 MW

**Evidence.** The literal omission is confirmed: frontend/js/dossier.js:146 emits 'Calibrated against Indian national satellite percentiles (P50: 4.05 MW, P90: 13.32 MW, P99: 64.49 MW).' - P95 is absent from that string, and the spec defines it at V2_LOGIC_SPECIFICATION.md:106. No score or threshold depends on this string, as the claim itself concedes.

**Refuted:** no — confirmed

---


### Spatio-Temporal Clustering

#### F-029 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Clustering default eps is 2000 m in code, not the spec's 1500 m; /incidents/cluster-sync mirrors 2000, pipeline uses 1500, Stage-3 tests use 2000.

**Evidence.** backend/app/incidents/clustering.py:107 `spatial_eps_meters: float = 2000.0`; used at clustering.py:140 `if dist_m <= spatial_eps_meters`. Spec line 129 states eps_s = 1500 m and line 538 canonical pseudocode passes eps_meters=1500.0. backend/app/api/incidents.py:139 `spatial_eps_meters: float = 2000.0` passed straight through at incidents.py:153. Pipeline is conformant: orchestration/pipeline.py:510 `cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)`. Tests/test_stage3_incidents.py:62, 87, 92, 97 all pass spatial_eps_meters=2000.0. Grep for 1500/2000 across backend confirms no other constant overrides these defaults. Divergence and the 2000-vs-1500 (33.3% wider) arithmetic are correct.

**Refuted:** no — confirmed

---

#### F-030 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** R_footprint additive term is 375.0 m (spec), but code uses +300.0 m, so every persisted footprint is 75 m under-sized.

**Evidence.** Spec line 142: `R_{footprint} = max(500.0, max_i d_H(...) x 1000.0 + 375.0)` where d_H in section 4.1 is kilometers (R_earth = 6371.0 km), so x1000 -> meters; requires d_m + 375.0. Code C:/Users/ssaur/OneDrive/Desktop/PS162/v2/backend/app/incidents/clustering.py:76 `self.radius_meters = max(500.0, round(max_dist_m + 300.0, 1))` with max_dist_m from haversine_distance_meters (spatial.py:13-23, EARTH_RADIUS_METERS=6371000.0), i.e. d_m + 300.0. Comment at clustering.py:69 says '+ 300m sensor buffer'. Grep for `375` across the whole repo returns only spec markdown (V2_LOGIC_SPECIFICATION.md:142) and unrelated JSON/frontend numbers -- no 375 anywhere in backend. Divergence is real: 75 m under spec, no unit error.

**Refuted:** no — confirmed

---

#### F-031 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Stage 3 must operate on the 72-hour active-observation window, but /incidents/cluster-sync clusters the entire observations table with no time cutoff.

**Evidence.** Spec line 64 (Stage-3 input 'Active observations (72h)') and lines 536-537 pseudocode `active_obs = db_session.query_observations(window_hours=72)`. backend/app/api/incidents.py:147 `observations = db.query(Observation).all()` -- no filter -- fed directly into cluster_observations at incidents.py:151-155. Grep on api/incidents.py for 72/acquired_at/time_cutoff returns only the unrelated time_window_hours=24.0 route param (lines 140/154); there is no 72h cutoff and no fallback-to-50 clause on this route. The pipeline path does honour it: orchestration/pipeline.py:490-491 `time_cutoff = datetime.utcnow() - timedelta(hours=72)` filtering `Observation.acquired_at >= time_cutoff`. Divergence between the two entry points into the same engine is real.

**Refuted:** no — confirmed

---


### Geodesy & Spatial Predicates

#### F-032 — INVARIANT VIOLATION

**Claim.** INV-3: spec envelope is 68.7°E–97.4°E, 8.4°N–37.6°N; code at boundaries.py:56 uses different bounds.

**Evidence.** V2_LOGIC_SPECIFICATION.md:31 states INV-3 as 68.7°E–97.4°E, 8.4°N–37.6°N. backend/app/gis/boundaries.py:56 is 'if lat < 6.5 or lat > 35.7 or lon < 68.0 or lon > 97.4: return False'. Executed: is_within_indian_sovereign_territory(7.0,72.0) returns True and resolve_admin_boundary(7.0,72.0) returns {'country':'India', ...}; (8.39,72.0) also True (spec floor 8.4 rejects it); (23.0,68.3) True resolving to state 'Gujarat' (west strip outside spec's 68.7 floor); (36.0,76.0) and (35.9,76.0) return False / country 'International / Foreign Territory' though INV-3 places them inside 8.4–37.6°N. All four cited consumers call this exact predicate and nothing else: backend/app/ingestion/firms.py:97 (foreign_skipped), orchestration/pipeline.py:81, :498 and :368, incidents/association.py:88.

**Refuted:** no — confirmed

---

#### F-033 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** §4.1 (spec line 86): d = 2·R·arcsin(min(1.0, √a)) — the min(1.0,·) clamp is mandated; code omits it and can raise ValueError on a>1.

**Evidence.** backend/app/gis/spatial.py:21-22 — a = sin²(dphi/2)+cos·cos·sin²(dlambda/2); c = 2.0*math.atan2(math.sqrt(a), math.sqrt(1.0-a)). No min/max clamp anywhere in the function (lines 13-23). I executed it: haversine_distance_meters(45.0,0.0,-45.0,180.0) raises ValueError('expected a nonnegative input, got -2.220446049250313e-16') from math.sqrt(1.0-a); (90,0,-90,0) and (0,0,0,180) return 20015086.796 fine. The duplicate unclamped inline copy exists verbatim at backend/app/api/observations.py:107 ('return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))', R=6371.0 at line ~101), behind the radius filter of GET /api/observations. Callers cited all exist and are unguarded: api/history.py:154, behavior/baseline.py:233, behavior/profile.py:219,415 — these call haversine_distance_km (spatial.py:29), which delegates to the same meters function, so they raise identically.

**Refuted:** no — confirmed

---

#### F-034 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** §4.1 PIP: spec requires strict λ_p < interpolation with vertical edges handled by that same expression; code uses inclusive <= plus a p1x==p2x short-circuit.

**Evidence.** backend/app/gis/spatial.py:51-55 — 'if x <= max(p1x,p2x): ... if p1x == p2x or x <= xinters: inside = not inside'. The spec expression at V2_LOGIC_SPECIFICATION.md:92 is strict '<'. I ran both implementations: right triangle [[0,0],[10,0],[10,10]] with (lat 5, lon 5) on the hypotenuse → code False / spec True; square left edge (lat 5, lon 0) → code False / spec True; right edge (lat 5, lon 10) → code True / spec False; vertex (lat 0, lon 0) → code False / spec True; vertex (lat 10, lon 10) → code True / spec False. All match the allegation exactly (note the code has no separate horizontal short-circuit — line 52 sets xinters = x for horizontal edges but it is unreachable because line 53 guards p1y != p2y, and with p1y==p2y the outer 'y>min'/'y<=max' gate cannot both hold unless min==max). Downstream wiring confirmed: spatial.py:74/77 point_in_polygon feeds point_in_geojson_geometry, assets.py:598 sets is_inside = point_in_geojson_geometry(...) and assets.py:612 returns it as is_inside_facility; scoring.py:174-176 is the CRITICAL 'INDUSTRIAL_CATASTROPHE_OVERRIDE' requiring is_inside_facility and classification=='industrial_fire'.

**Refuted:** no — confirmed

---

#### F-035 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** §4.1 PIP: spec requires the half-open (φ_i>φ_p)≠(φ_j>φ_p) latitude test, i.e. [min,max); code uses the opposite half-open convention (min,max].

**Evidence.** backend/app/gis/spatial.py:49-50 — 'if y > min(p1y, p2y): if y <= max(p1y, p2y):', i.e. strict > on min and inclusive <= on max = (min, max]. The spec (V2_LOGIC_SPECIFICATION.md:92) is (φ_i>φ_p)≠(φ_j>φ_p), which for the (min,max) endpooints toggles at y==min and not at y==max = [min, max). I ran both implementations on ring [[0,0],[10,0],[10,10],[0,10],[0,0]] (lon,lat): point (lat 0, lon 5) code False / spec True; (lat 10, lon 5) code True / spec False — exactly as alleged. For points strictly interior or exterior to the band the two agree.

**Refuted:** no — confirmed

---

#### F-036 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** §5 (spec line 294): cropland-and-not-protected → agricultural_burning, protected park/sanctuary/montane canopy → wildfire; code instead uses an FRP-then-state-name cascade with no spatial cropland/protected test.

**Evidence.** V2_LOGIC_SPECIFICATION.md:294 contains the quoted rule verbatim. backend/app/orchestration/pipeline.py:189-190 is 'elif inc.current_max_frp >= 25.0: cls_name = "wildfire"' — evaluated before any cropland/protected test — and pipeline.py:194 is 'elif inc.state in ["Punjab", "Haryana", "Uttar Pradesh"]: cls_name = "agricultural_burning"', a state-membership proxy. Grepping 'landcover|protected|is_protected|cropland|national_park|sanctuary' over pipeline.py returns zero hits, so the 'within national parks or sanctuaries → wildfire' clause has no spatial test in this cascade. The landcover module does provide the primitive — backend/app/gis/landcover.py:46 is_protected_area: True for PROTECTED_ZONES, and landcover.py:88-89 maps (25.0,80.5) into agricultural_cropland via '(24.0 <= lat <= 27.0 and 80.0 <= lon <= 88.0)' — but nothing in classification consults it. Weights confirmed at backend/app/severity/scoring.py:105 ('wildfire': 75.0) and :110 ('agricultural_burning': 32.0).

**Refuted:** no — confirmed

---


### System Invariants (INV-1 .. INV-6)

#### F-037 — INVARIANT VIOLATION

**Claim.** INV-1: evaluate_incident_severity feeds the composite C_sev into the parameter the C_firms >= 80% extreme-FRP override uses, writes it back, and can be reached with no AI investigation.

**Evidence.** CONFIRMED. backend/app/severity/service.py:67 `firms_confidence = incident.severity_confidence or 75.0  # default reasonable FIRMS confidence` is passed as the firms_confidence argument at line 70, consumed by the override gate at scoring.py:169 (`firms_confidence >= 80.0`) and simultaneously folded into C_sev at scoring.py:209 (`0.25 * firms_confidence`), then written back at service.py:99 (`incident.severity_confidence = assessment["severity_confidence"]`) — a genuine self-referential loop across passes. POST /api/severity/evaluate/{incident_id} (backend/app/api/severity.py:12-30) calls this with no AIInvestigation precondition; service.py:33 falls back to `incident.classification or "uncertain"`. Correction to impact: on a first pass the default is 75.0, which is < 80.0, so the gate is not satisfied immediately; it becomes self-satisfiable on the next pass once C_sev computes >= 80 (e.g. ai_conf 90, dist 50 m, reliability 1.0 gives C_sev ~90.05), so the force-escalation requires at least one prior evaluation pass.

**Refuted:** no — confirmed

---

#### F-038 — INVARIANT VIOLATION

**Claim.** INV-1: raw FIRMS observation classified 'uncontrolled_industrial_fire' at ai_conf 0.88 / low uncertainty with no multimodal verification, reached when no AIInvestigation exists or AI returned 'uncertain'.

**Evidence.** CONFIRMED. backend/app/orchestration/pipeline.py:178-183 is a pure geometry+FRP heuristic: `elif is_near and (is_inside_fac or dist_km <= 1.5): if inc.current_max_frp >= 25.0 and inc.status == "ACTIVE" and not is_routine: cls_name = "uncontrolled_industrial_fire"; ai_conf = 0.88; ai_unc = "low"`. Lines 131 and 146 both gate on `!= "uncertain"`, so an explicit AI 'uncertain' verdict falls through to 178 (intelligence/service.py:99 writes incident.classification = report.classification, so both the latest_inv and the incident-level branches are excluded). Incidents are born status="ACTIVE" with zero AI at app/incidents/association.py:170, and /api/console/feed (app/api/analysis.py:270-277) returns those rows through generate_console_feed_data untouched. frontend/js/config.js:41 maps the class to label 'Uncontrolled industrial fire', group 'critical'. Two corrections to scope, neither weakening the finding: (a) the branch also requires the facility NOT be a registered flaring or metallurgical asset (lines 167-171) and NOT be a mining basin, so 'uncontrolled_industrial_fire' is never emitted for a flare/steel/coalfield site; (b) it requires containment or <=1.5 km proximity. Note also that 'uncontrolled_industrial_fire' is not one of the six canonical classes in spec 5/6.2 (which permits only industrial_fire|gas_flare|wildfire|agricultural_burning|mining_or_other_thermal_source|uncertain), so the console publishes a class the vision AI can never emit.

**Refuted:** no — confirmed

---

#### F-039 — INVARIANT VIOLATION

**Claim.** INV-2: FRP across multi-pixel clusters must never be summed; the backend complies but the frontend sums FRP as 'MW total' / 'Combined radiative power', and prepare_map_data.py:375 sums within clusters.

**Evidence.** CONFIRMED as literal code facts, with a large correction to significance. Backend compliance verified: backend/app/incidents/clustering.py:55-57 computes max/min/mean only; backend/app/incidents/association.py:109-115 uses max() for current_max_frp and a count-weighted mean; a repo-wide grep of backend/app for sum/aggregate/SUM over frp finds only mean computations (behavior/profile.py:96, behavior/trends.py:45,59-60) — no accumulation. The cited frontend sums all exist: frontend/js/render.js:605 `const totalFrp = cases.reduce((acc, c) => acc + (c.frp || 0), 0)` rendered as 'MW total' at line 645; render.js:1340 `industrial.reduce((s, c) => s + c.frp, 0)` rendered as 'Total Thermal Radiance / Combined radiative power across sites' at line 1350; render.js:1566/1582 'Total ... MW' from stats(). Correction: frontend/js/data.js:128 defines `c.frp = Number(raw.frp)` = the console feed's per-incident `frp` (= inc.current_max_frp, pipeline.py:311), so all three render.js figures are cross-incident aggregates of per-incident maxima, not multi-pixel cluster sums, and therefore do not violate INV-2's specific prohibition. The only true within-cluster FRP sum is frontend/prepare_map_data.py:375 (`c["total_frp"] += p["frp"]` for points within 25 km), and that module cannot run: it imports history_db from <v2>/pipeline/07_persistence (prepare_map_data.py:24-28), a directory that does not exist. So the banned operation appears nowhere in any reachable code path.

**Refuted:** no — confirmed

---

#### F-040 — INVARIANT VIOLATION

**Claim.** INV-3: out-of-boundary telemetry is discarded; incident association tests only the cluster centroid, so clusters can carry foreign pixels into incidents.

**Evidence.** CONFIRMED as a code fact, but the cited path is wrong and the real path is a different one. backend/app/incidents/association.py:88 is indeed centroid-only: `if not is_within_indian_sovereign_territory(cluster.center_lat, cluster.center_lon): continue`, with no per-member filter, and members are linked wholesale at association.py:206-234. However the pipeline the claim cites (pipeline.py:510, eps 1500 m) pre-filters every observation at pipeline.py:498, so no out-of-boundary member can exist there. The reachable path is POST /api/incidents/cluster-sync (backend/app/api/incidents.py:139-156), which loads `db.query(Observation).all()` with no sovereign filter, clusters at eps 2000 m, and relies solely on the centroid test. Out-of-boundary rows do exist to feed it: ingest_history.py:178 admits the spec box 8.4-37.6N, which includes the 35.7-37.6N band the runtime gate rejects. So the impact stands (foreign pixels can enter incident_observations, max FRP, severity and imagery) but via /api/incidents/cluster-sync, not the pipeline.

**Refuted:** no — confirmed

---

#### F-041 — INVARIANT VIOLATION

**Claim.** INV-3: outside 68.7E-97.4E / 8.4N-37.6N plus a polygon mask is quarantined; the runtime gate is instead a loose hand-written rectangle stack with two other conflicting envelopes.

**Evidence.** CONFIRMED, live-verified by importing the real function. backend/app/gis/boundaries.py:56 is `if lat < 6.5 or lat > 35.7 or lon < 68.0 or lon > 97.4: return False`, followed by ~20 ad-hoc border boxes (lines 60-125). Executed against the live module: (6.9, 69.0) -> True, (23.0, 68.4) -> True (both outside the spec envelope, admitted), (36.5, 76.0) -> False, (37.0, 78.0) -> False (both inside the spec envelope, rejected). The two other envelopes exist exactly as cited: backend/app/core/config.py:33 `FIRMS_REGION = "68.1,8.0,97.4,35.7"` (bounds the NASA request) and backend/scripts/ingest_history.py:34-37 MIN_LAT 8.4 / MAX_LAT 37.6 / MIN_LON 68.7 / MAX_LON 97.4, enforced at ingest_history.py:178 for the historical corpus. Correction to impact: the discarded 35.7-37.6N band is predominantly Aksai Chin / Gilgit-Baltistan (the code's own comment at boundaries.py:54-55 justifies the 35.7 cut), so 'genuine Indian territory discarded' overstates the geographic loss; the split-corpus claim (baselines admit rows that live filtering rejects) is exact.

**Refuted:** no — confirmed

---

#### F-042 — INVARIANT VIOLATION

**Claim.** INV-3: the sovereign filter is envelope PLUS a high-fidelity polygon mask; no polygon mask exists.

**Evidence.** CONFIRMED. backend/app/gis/boundaries.py contains only rectangles — INDIAN_STATE_REGIONS boxes at lines 10-46, border envelopes at 56-126, INDIAN_DISTRICT_SUBREGIONS boxes at 131-164 — and resolve_admin_boundary unconditionally returns `{country: "India", state: "Indian National Territory", district: "Maritime / Border Sector"}` at lines 195-199 for any point that survives the rectangles, including open ocean. A search of the whole tree for *.geojson or an India polygon asset returns nothing. A correct ray-casting implementation does exist (backend/app/gis/spatial.py:31 point_in_polygon, :61 point_in_geojson_geometry) but a repo-wide grep shows its only caller is backend/app/gis/assets.py:598 for facility polygon_geojson containment; it is never invoked from the sovereignty test. Impact is accurate.

**Refuted:** no — confirmed

---

#### F-043 — INVARIANT VIOLATION

**Claim.** INV-4 / 4.6.2: suppression applies while r <= 1.0; at r == 1.0 the code returns 50.0 instead of the clamped <= 20.0.

**Evidence.** CONFIRMED, reproduces exactly. backend/app/severity/scoring.py:83-88 orders the branches so `elif ratio >= 1.0:` precedes the suppression block at 92-95, so at r == 1.0 the function returns `round(50.0 + (1.0-1.0)*30.0, 2)` = 50.0 and never reaches the clamp. Ran the real function: calculate_historical_deviation(20.0, 4.0, 20.0, is_routine_flare=True) -> 50.0. Spec line 235 says the clamp applies whenever r <= 1.0, giving min(20, max(5, 20.0)) = 20.0. The docstring at scoring.py:74 states the same wrong guarantee ('If is_routine_flare=True and current FRP <= P95, clamps score to <= 20.0'). Correction to impact: the divergence is confined to the exact boundary r == 1.0 (measure-zero but reachable, since P95 = min(max_frp, mean_frp*2.10) can equal the current max), where the composite moves by 0.30*(50-20) = 9.0 points; and spec 4.6.2 bullet 3 itself yields 50.0 at r == 1.0, so the spec is internally ambiguous at that single point rather than unambiguously violated.

**Refuted:** no — confirmed

---

#### F-044 — INVARIANT VIOLATION

**Claim.** INV-4 / INV-2: stored cluster/incident FRP stats must be max/mean/min, never a total; the console feed key 'cluster_total_frp' is populated with inc.current_max_frp.

**Evidence.** CONFIRMED. backend/app/orchestration/pipeline.py:312 `"cluster_total_frp": inc.current_max_frp,` — the field name asserts a cluster total while the value is the incident maximum; no summation occurs. It is the only reference in code (repo-wide grep: pipeline.py:312 only), it is never read by any frontend module (grep of frontend/js and index.html is empty), and it is written into frontend/data/incidents.json by export_v1_dashboard_data (pipeline.py:390-392). Correction to impact: this is a naming defect only. The stored/computed FRP statistics themselves remain max/mean/min, so INV-2's computational ban is not breached by this field and no consumer currently misreads it.

**Refuted:** no — confirmed

---

#### F-045 — INVARIANT VIOLATION

**Claim.** INV-4: ROUTINE_FLARE is applied to flares with >= 10 active days/year within their 365-day P95 envelope.

**Evidence.** CONFIRMED. backend/scripts/build_thermal_climatology.py:104-115: the routine flag is set only inside the flare branch, and line 110 is `if active_days >= 25 and night_ratio >= 0.25: is_routine_flare = True`. Threshold is 25 (not 10), an extra night_ratio >= 0.25 gate exists, and neither p95_frp/median_frp nor max_frp is consulted anywhere in the decision (the percentiles computed at lines 80-82 are stored but never tested). Cells failing the test fall to hint 'EPISODIC_THERMAL' (line 115) or 'PERSISTENT_INDUSTRIAL' at >=15 active days (line 118). The two migration scripts (backend/scripts/migrate_climatology_industrial.py:40, migrate_climatology_mining.py:30) only clear the flag to 0, they never set it True, so no second path sets it. Impact stands (under-suppression of 10-24 active-day flares) but note the opposite-direction over-suppression described in claim 4 also exists, so the net effect is not uniformly 'under-suppression'.

**Refuted:** no — confirmed

---

#### F-046 — INVARIANT VIOLATION

**Claim.** INV-4: routine flag is keyed to >=10 active days and the empirical P95; instead a cached HistoricalBaseline path uses 3 active days, the fresh path hard-codes False, and the P95 is a synthetic mean-scaled estimate on a 0.01 deg grid with no date filter.

**Evidence.** CONFIRMED on every sub-point. (a) backend/app/behavior/baseline.py:141 `is_routine = bool(existing_bl.is_persistent)` where is_persistent = `(len(matching_obs) >= 5 and active_days >= 3)` (baseline.py:242, computed over window_days=90) — 3 active days, not 10. (b) The freshly-computed path ends with the literal `"is_routine_flare": False` at baseline.py:288, so a persistent refinery flare at a coordinate with no ThermalClimatology cell is never suppressed. (c) The P95 is synthesized, not empirical: build_thermal_climatology.py:57-58 selects SQL AVG/MAX only, and lines 80-82 derive `median_frp = max(0.5, mean_frp*0.80)`, `p90_frp = min(max_frp, mean_frp*1.60)`, `p95_frp = min(max_frp, mean_frp*2.10)`. (d) The aggregation query (build_thermal_climatology.py:50-62) has no WHERE on acquired_at, and grids at `ROUND(latitude, 2)` = 0.01 deg vs spec 4.4's 0.02 deg cell (the file's own docstring claims 0.02 deg). Two scope corrections: sub-point (a) additionally requires is_flare_fac (baseline.py:140) and a cache row younger than 86400s (line 132); and the missing date filter is partly compensated because the corpus is ingest-bounded to 365 days (backend/scripts/ingest_history.py MIN_ACQ_DATE = '2025-09-14'). Empirical percentiles do exist — but in baseline.py:18-50 (compute_percentiles), which serves only the fresh path, not the climatology table the invariant names.

**Refuted:** no — confirmed

---

#### F-047 — INVARIANT VIOLATION

**Claim.** INV-4: routine-flare clamp is applied only to S_dev, never to the composite; a confirmed routine refinery flare scores 26.4/MEDIUM (and 38.3 at 8 MW), so the composite can never be <= 20.0.

**Evidence.** CONFIRMED, arithmetic reproduced exactly. Calculate_historical_deviation clamps only the sub-factor at backend/app/severity/scoring.py:92-95 (`min(20.0, max(5.0, round(base_dev*0.4, 2)))`); the composite weights at scoring.py:256-262 apply 0.30 to dev_score and are never clamped. Ran the real function: compute_incident_severity(frp=1.0, firms_conf=80.0, gas_flare, ai_conf=90.0, median=4.0, p95=20.0, history_rel=1.0, dist=0.0, refinery, inside=True, routine=True) -> 26.4 MEDIUM (base 26.38, dev 5.0); FRP 8.0 -> 38.3 MEDIUM. With dev pinned at its 5.0 floor, ai gas_flare 38*1.0 -> 7.6 and gis 95 -> 14.25, the composite minimum is ~23.4, i.e. MEDIUM is unreachable-below only by construction. Correction to the framing: spec 4.6.2 line 235 prescribes exactly this S_dev-only clamp, so the code matches 4.6.2 and the divergence is against INV-4's own headline wording ('clamped to low severity scores (<= 20.0)'). tests/test_climatology_calibration.py:143 encodes the weaker contract (asserts only `historical_deviation_score <= 20.0` and level in [LOW, MEDIUM]), confirming the <=20 composite is not delivered or tested.

**Refuted:** no — confirmed

---

#### F-048 — INVARIANT VIOLATION

**Claim.** INV-5 / 4.5: selection weights C_firms, but evaluate_incident_selection hard-codes confidence_val = 80.0, so the extreme-FRP override's `confidence >= 80.0` test is always satisfied.

**Evidence.** CONFIRMED. backend/app/selection/engine.py:58-59 `# 5. FIRMS confidence approximation (default 80 if aggregate)` / `confidence_val = 80.0`, passed as confidence_score at line 63. That flows through scoring.py:117 map_firms_confidence -> 80.0 and into the override at scoring.py:85 `if frp_mw >= 150.0 and confidence >= 80.0`. Verified by running the real function: compute_investigation_priority(frp_mw=160.0, confidence_score=0.8, has_history=False) returns is_override_triggered True, so the override degenerates to an FRP-only test and force-elevates priority to >= 90 (scoring.py:147). The real per-observation confidence exists and is normalized (backend/app/ingestion/normalizer.py:30 normalize_confidence, :95 confidence_score) and is not consulted here. Spec 4.5 line 206 requires C_firms >= 80.0%. Impact accurate; one nuance: map_firms_confidence would also read an aggregate 80.0 as 80.0, so the constant is indistinguishable from a genuine high-confidence aggregate even in principle.

**Refuted:** no — confirmed

---

#### F-049 — INVARIANT VIOLATION

**Claim.** INV-5 / spec 11: selection-side has_history must be baseline_p95 > 0; engine.py instead sets has_history whenever observation_count > 0, routing 1-2-detection sites into the with-history model with a zero anomaly term and lower weights (60.5 vs 69.5).

**Evidence.** CONFIRMED. backend/app/selection/engine.py:37-39 `if baseline_data and baseline_data.get("observation_count", 0) > 0: has_history = True` — spec line 565 states `has_history=(inc.baseline_p95 > 0)`. backend/app/behavior/anomaly.py:99 short-circuits on `obs_count < 3 or median_frp <= 0.0` and returns `"status": "INSUFFICIENT_HISTORY"` with `anomaly_score: 0.0` (line 108), so such incidents get a zero anomaly term. Weight shift verified by running the real function: compute_investigation_priority(frp=30.0, confidence_score=0.8, persistence_score=15.0, anomaly_score=0.0) -> has_history=True 60.5, has_history=False 69.5 (backend/app/selection/scoring.py:130-147: 0.40/0.30/0.20/0.10 vs 0.45/0.30/0.25). Both 60.5 and 69.5 sit above the pipeline min_priority of 30.0 (pipeline.py:534) but the 9.0-point penalty is real and the with-history score is provably never higher when anomaly_score = 0 (difference = -0.05*frp_score - 0.05*confidence), so INV-5's 'NEVER penalized' is violated. One correction: at FRP 30 MW both modes still clear the pipeline's 30.0 cut, so the claim's 'can fall below the min_priority 30/40 cut' is only reachable at lower FRP/persistence, not in the measured case.

**Refuted:** no — confirmed

---

#### F-050 — INVARIANT VIOLATION

**Claim.** INV-6: an alert is emitted only once per incident unless severity strictly escalates; the dedup path returns the existing record so the pipeline still counts and republishes it.

**Evidence.** CONFIRMED. backend/app/alerts/engine.py:78-82 returns `latest` (the existing AlertRecord) instead of None on the same-or-higher-severity dedup path, and tests/test_stage7_severity_alerts.py:281 codifies it (`assert alert2.id == alert1.id`). backend/app/severity/service.py:153-157 therefore returns a non-None `"alert"` object, and backend/app/orchestration/pipeline.py:645-660 increments `alerts_emitted` and publishes EVENT_ALERT_CREATED for it, so run_record.alerts_count (pipeline.py:672) and the run summary's alerts_emitted are inflated per pass. The record-level contract is otherwise exact as the claim states: SEVERITY_RANK LOW..CRITICAL at engine.py:18, strict `>` at engine.py:41, eligibility {HIGH, CRITICAL} at engine.py:17. Correction to impact: the dedup path creates neither a duplicate AlertRecord nor an ALERT_EMITTED IncidentEvent, so the alert table and incident_events audit stay clean; the over-reporting is confined to the SSE ALERT_CREATED stream and run counters, and the frontend consumes it only as a line in the sync-progress log (frontend/js/main.js:974, :1114), not as an operator-facing notification.

**Refuted:** no — confirmed

---


### Database Schema & REST/SSE API

#### F-051 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec documents observations.daynight as ('D'/'N'); the code writes the full words 'DAY'/'NIGHT', so a spec-conformant 'D' filter returns nothing.

**Evidence.** backend/app/ingestion/normalizer.py:86 `daynight_code = "NIGHT" if str(raw.daynight).strip().upper() == "N" else "DAY"`, assigned at :99 and persisted at backend/app/ingestion/firms.py:119. Live DB: SELECT daynight, count(*) FROM observations GROUP BY 1 → [('DAY', 2132898), ('NIGHT', 762166)]; zero 'D'/'N' rows. Filter at backend/app/api/observations.py:71-72 is `Observation.daynight == daynight.upper()`, so 'D'→'D' matches nothing (returns HTTP 200 with an empty list, no validation error).

**Refuted:** no — confirmed

---

#### F-052 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec documents observations.external_id as a "SHA-256 hash"; the code stores a SHA-256 digest truncated to 20 hex chars (80 bits).

**Evidence.** backend/app/ingestion/normalizer.py:69-70 — key = f"{satellite}_{instrument}_{lat:.4f}_{lon:.4f}_{strftime('%Y%m%d%H%M')}" then hashlib.sha256(key.encode()).hexdigest()[:20]. Live DB: SELECT length(external_id), count(*) FROM observations GROUP BY 1 returns exactly [(20, 2895064)] — no 64-char values. Dedup on the truncated value at backend/app/ingestion/firms.py:86-124.

**Refuted:** no — confirmed

---

#### F-053 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec presents the REST table as "Complete REST API" (19 rows); the codebase exposes roughly two dozen additional undocumented routes.

**Evidence.** Spec table has 19 rows (V2_LOGIC_SPECIFICATION.md:459-479). Decorator grep of backend/app/api/*.py plus main.py yields dozens of routes not in that table, e.g. health.py:30 /health/readiness and :56 /status; observations.py:116 /observations/{id}; industries.py:114 /industries/{asset_id} and :131 POST /industries/seed; incidents.py:177 POST /incidents/{id}/state; history.py:65/:88/:121 /incidents/{id}/baseline|anomaly|trend and :163/:184/:205 /industries/{id}/history|baseline|trends, :245 POST /history/refresh, :255 /history/search; imagery.py:36 /imagery/incident/{id}/package, :55 /imagery/cache/{id}/{filename}; investigation.py:40 GET /{id}, :57 /{id}/history, :68 POST /{id}/reinvestigate; severity.py:13 POST /evaluate/{id}, :47 /{id}/history; alerts.py:62 /resolve, :81 /dismiss; analysis.py:37 /analysis/status, :64 /analysis/history, :199 POST /analysis/run (top_router), :209 /api/trigger-sync-stream, :244 POST /api/trigger-sync, :250 /api/history-stats, :270 /api/console/feed; main.py:56 GET /, :109 /crops, :136 /console mount. Every router is actually mounted (main.py:70-91) and the tests exercise the extras (tests/test_stage9_ui_integration.py:167,175,186,194,209,229; tests/test_stage10_hardening.py:173,197).

**Refuted:** no — confirmed

---

#### F-054 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec §9 says "13 normalized relational tables" but the code ships 15, and the spec's own numbered list is internally inconsistent (items 1-12 + item 13's two tables = 14 enumerated; historical_baselines appears only in the ER diagram).

**Evidence.** Spec C:/Users/ssaur/OneDrive/Desktop/PS162/v2/V2_LOGIC_SPECIFICATION.md:407 ("13 normalized relational tables"), numbered items at lines 427-451 (item 13 at :451 names `behavior_profiles` & `behavior_daily_summaries`). Code: grep of `__tablename__` in backend/app/storage/models.py returns exactly 15 (lines 27, 54, 107, 121, 143, 157, 173, 187, 210, 223, 243, 261, 276, 290, 302). Live DB backend/data/firex_v2.db sqlite_master has 16 rows, 15 tables + sqlite_stat1.

**Refuted:** no — confirmed

---

#### F-055 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec's SSE event names are uppercase (ANALYSIS_STARTED, FIRMS_FETCHED, CLUSTERING_COMPLETED, ...); the wire emits dotted lowercase names (analysis.started, firms.fetched, ...), plus four unlisted event types.

**Evidence.** backend/app/orchestration/events.py:27-39 defines dotted string constants (EVENT_ANALYSIS_STARTED = "analysis.started", ... EVENT_ANALYSIS_FAILED = "analysis.failed"); :88 returns f"event: {self.event_type}\ndata: {json.dumps(payload)}\n\n" — the `event:` line is the string value, and the uppercase text exists only as Python identifiers. Publisher sites confirmed by grep: pipeline.py:434,477,500,512,535,582,598,612,631,648,693,710. Tests assert the dotted wire form (tests/test_stage8_orchestration.py:159 `msg.startswith(f"event: {EVENT_FIRMS_FETCHED}\n")`, :231). Spec lists 8 uppercase names at V2_LOGIC_SPECIFICATION.md:485-507. Four wire events unlisted in the spec: gis.completed, ai.started, alert.created, analysis.failed (events.py:29,33,36,38). JSON payload keys match the spec (e.g. summary with status/duration_seconds at pipeline.py:676-694), so only the dispatch key diverges.

**Refuted:** no — confirmed

---

#### F-056 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec's `GET /api/severity/incident/{id}` ("compute or retrieve") does not exist; the code exposes GET /severity/{id} (retrieve-only, 404s) and POST /severity/evaluate/{id}.

**Evidence.** backend/app/api/severity.py:11 `APIRouter(prefix="/severity")`; :13 `@router.post("/evaluate/{incident_id}")`; :30 `@router.get("/{incident_id}")`; :47 `@router.get("/{incident_id}/history")`. Mounted at backend/app/main.py:86-87. Project-wide grep for the literal 'api/severity/incident' matches only the spec file (V2_LOGIC_SPECIFICATION.md:474). GET handler 404s when no assessment exists (severity.py:39-43) and its detail string points at the undocumented POST /api/severity/evaluate/{incident_id}.

**Refuted:** no — confirmed

---

#### F-057 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec's `GET /health` / `/api/health` promises "database status, memory metrics"; the handler reports DB status but no memory metric exists anywhere in the API.

**Evidence.** backend/app/api/health.py:15-28 — response body is exactly status, service, version, timestamp, database (database from check_db_connection(), health.py:20). backend/app/storage/database.py:36-52 returns only status/dialect/url. Repo-wide grep for psutil/RSS/virtual_memory/getrusage/tracemalloc/memory in backend/app finds no memory figure; cache.size() (backend/app/core/cache.py:39-42) is an entry count, used at health.py:49 and health.py:73. The adjacent undocumented endpoints (/status at health.py:56, /health/readiness at :30) expose cache_size, cache_entries and pipeline_locked only.

**Refuted:** no — confirmed

---

#### F-058 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec's `POST /api/alerts/{id}/ack` is implemented as `/{alert_id}/acknowledge`, with no /ack alias.

**Evidence.** backend/app/api/alerts.py:16 `APIRouter(prefix="/alerts")`; :43 `@router.post("/{alert_id}/acknowledge")`; siblings :62 `/{alert_id}/resolve`, :81 `/{alert_id}/dismiss`. Repo-wide grep for a literal '/ack' alias returns no match. The project's own test posts the code path: tests/test_stage7_severity_alerts.py:446 `client.post(f"/api/alerts/{alert_id}/acknowledge", ...)`. Notes are recorded only in acknowledge_alert (backend/app/alerts/engine.py:123-139, IncidentEvent payload {"notes": notes}).

**Refuted:** no — confirmed

---

#### F-059 — SCHEMA / API CONTRACT DRIFT

**Claim.** Spec's `POST /api/imagery/incident/{id}` is implemented as GET, with no POST variant anywhere.

**Evidence.** backend/app/api/imagery.py:15 `APIRouter(prefix="/imagery")`; :17 `@router.get("/incident/{incident_id}", ...)`. The only other imagery routes are :36 GET /incident/{incident_id}/package and :55 GET /cache/{incident_id}/{filename}. `grep -rn "router.post" backend/app/api/imagery.py` returns nothing; repo-wide grep for 'imagery/incident' returns nothing literal (the prefix lives on the router), confirming no second registration path.

**Refuted:** no — confirmed

---

#### F-060 — SCHEMA / API CONTRACT DRIFT

**Claim.** historical_baselines is absent from the numbered Table Definitions (only an ER-diagram edge), yet is a first-class created, FK-referencing table; conversely thermal_climatology (numbered item 8) is absent from the ER diagram.

**Evidence.** backend/app/storage/models.py:222-239 — `class HistoricalBaseline(Base)`, __tablename__ "historical_baselines", profile_id FK to behavior_profiles.id. Spec ER diagram (V2_LOGIC_SPECIFICATION.md:410-423) lists HistoricalBaseline only as an edge (:421) and never names thermal_climatology; thermal_climatology is numbered item 8 at spec:441. Live DB PRAGMA table_info(historical_baselines) returns 15 columns matching the claim; PRAGMA table_info(thermal_climatology) also exists.

**Refuted:** no — confirmed

---

#### F-061 — SCHEMA / API CONTRACT DRIFT

**Claim.** models.py is not a complete description of the live schema: the DB carries behavior_profiles.window_days/day_passes_count/night_passes_count/is_continuous_24h and historical_anomalies.anomaly_status with no ORM counterpart, so a rebuild from models.py cannot reproduce the running DB.

**Evidence.** PRAGMA table_info on backend/data/firex_v2.db: behavior_profiles has 22 columns including window_days, day_passes_count, night_passes_count, is_continuous_24h; historical_anomalies has 11 including anomaly_status. models.py BehaviorProfile (:186-206) and HistoricalAnomaly (:260-272) declare neither. Repo-wide grep: day_passes_count/night_passes_count/is_continuous_24h have zero hits anywhere in the repo; window_days appears only as a function/query parameter (e.g. backend/app/behavior/baseline.py:101, api/history.py:40) and a dict key; anomaly_status appears only as a local variable and response key (backend/app/behavior/anomaly.py:123-129, :161) that no ORM column backs. No migration tooling exists (no alembic/, no ALTER TABLE anywhere; backend/scripts/*.py only backfill thermal_climatology), and main.py:12-13 uses Base.metadata.create_all, which cannot add columns to an existing table.

**Refuted:** no — confirmed

---


### Candidate Selection & Prioritisation

#### F-062 — UNIT / SCALE ERROR

**Claim.** C_firms should be the incident's FIRMS confidence (0-100, override requires >= 80.0%), but engine.py:59 hardcodes 80.0 for every incident

**Evidence.** CONFIRMED. backend/app/selection/engine.py:58-63: comment '# 5. FIRMS confidence approximation (default 80 if aggregate)' then `confidence_val = 80.0` passed as `confidence_score=confidence_val`. The Incident ORM class (backend/app/storage/models.py:53-103) has only classification_confidence (line 77) and severity_confidence (line 73) — no FIRMS confidence column, and the engine never reads Observation.confidence_score/confidence_raw (models.py:35-36), where the real FIRMS value lives. scoring.py:35-38 maps 80.0 through unchanged, so weighting is `0.20 * 80.0 = 16.0` (scoring.py:134) or `0.25 * 80.0 = 20.0` (scoring.py:142) for every incident. Impact (b) also holds: scoring.py:85 `if frp_mw >= 150.0 and confidence >= 80.0` is trivially true whenever the engine is the caller, so the documented two-condition EXTREME_FRP override degenerates to FRP>=150.0 in the automated pipeline. One caveat on scope: the manual POST /api/selection/score endpoint (api/selection.py:51-61) does forward a real confidence_raw, so the two-condition collapse is specific to the pipeline/engine path — which is the path that drives automatic promotion.

**Refuted:** no — confirmed

---

#### F-063 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** R_frp should be FRP_current / max(1.0, Median_FRP), but selection/scoring.py:119-121 omits the max(1.0, ...) clamp

**Evidence.** CONFIRMED. backend/app/selection/scoring.py:119-121: `frp_ratio = 1.0` / `if has_history and historical_median_frp and historical_median_frp > 0.0: frp_ratio = round(frp_mw / historical_median_frp, 2)` — the denominator is unclamped, against spec line 165. The sibling module does clamp (backend/app/behavior/anomaly.py:116 `ratio = round(current_frp / max(1.0, median_frp), 2)`), so the two modules genuinely disagree. Sub-1.0 medians are reachable: baselines have no floor (backend/app/behavior/baseline.py:253/264 store compute_percentiles output directly, engine.py:39 takes it verbatim). Arithmetic in the claim checks out: median 0.5, FRP 1.6 -> code 3.2 vs spec 1.6, and 3.2 >= 3.0 fires STRONG_HISTORICAL_ANOMALY (scoring.py:91) which floors priority at 90.0 (scoring.py:147). Direction of error is always over-triggering since max(1.0,m) >= m implies code ratio >= spec ratio. Minor citation nit only: the clamping line in anomaly.py is 116, not 118.

**Refuted:** no — confirmed

---

#### F-064 — UNIT / SCALE ERROR

**Claim.** S_anom in the 0.10*S_anom term should be the 0-100 anomaly-table score (§4.4), but engine.py feeds a 0-1 value, underweighting by 100x

**Evidence.** CONFIRMED. spec lines 169-176 give the anomaly table 0/10/20/40/60/75/90/100 and line 187 uses 'Anomaly >= 50'. backend/app/selection/engine.py:56 does `anomaly_score = float(eval_res.get("anomaly_score", 0.0))` with no rescaling, and that key is produced at backend/app/behavior/anomaly.py:119 `anomaly_score = round(ratio_score_100 / 100.0, 2)` — max 1.0 (ratio 5.5 -> calculate_frp_ratio_score falls through the loop at anomaly.py:40-43 -> 100 -> 1.0). backend/app/selection/scoring.py:135 then applies `0.10 * anomaly_score`, so the max contribution is 0.1 instead of the spec's 10.0. Internal inconsistency is real: persistence_score in the same sum is 0-100 (engine.py:44), so the anomaly term is 100x smaller relative to its peers. No second path rescales it — grep over v2 shows engine.py:56 is the only production consumer, and tests/test_stage5_selection_imagery.py:116 confirms the function's contract is 0-100 by passing anomaly_score=50.0. Impact statement is accurate; only nuance is that the priority difference is bounded at ~10 points, so only incidents within 10 points of the floor flip.

**Refuted:** no — confirmed

---

#### F-065 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** S_pers should be the §4.4 formula min(1.0, active_days/45*0.7 + min(1,obs/100)*0.3), but engine.py:44 uses 75.0-for-PERSISTENT / min(100, obs*15), making HIGH_PERSISTENCE unreachable for PERSISTENT incidents

**Evidence.** CONFIRMED. backend/app/selection/engine.py:44 `persistence_score = 75.0 if is_pers else min(100.0, obs_count * 15.0)` — no active_days, no 45.0 divisor, no obs_count/100 term (spec line 153). The spec's formula family does exist at backend/app/behavior/persistence.py:15-57 (returns 0-1; asserted >= 0.70 at tests/test_stage4_behavior.py:159), and engine.py:11 imports calculate_persistence_score but the 138-line file never calls it (only behavior/profile.py:229 and :425 use it). Impact holds: scoring.py:88 `if persistence_score >= 85.0` cannot fire on the 75.0 branch, and status PERSISTENT is genuinely reachable (app/severity/state_machine.py:33-34, pipeline.py:225), so the 'multi-day persistent industrial combustion' override is reachable only for non-PERSISTENT incidents with observation_count >= 6 (6*15=90) — e.g. a PERSISTENT incident with 20 observations scores 75.0 while a non-persistent one with 6 scores 90.0. Caveat: the spec is itself self-inconsistent on this term (its own line 153 formula yields 0-1 while line 207 requires S_pers >= 85.0), so the 0-100 interpretation is arguably forced by the spec; the formula divergence and the override dead-zone are still real.

**Refuted:** no — confirmed

---

#### F-066 — SPEC / CODE DIVERGENCE

**Claim.** Spec §11 documents no pool cap beyond candidates[:5], but engine.py:121 silently limits the scored pool to the 100 most-recently-updated incidents

**Evidence.** CONFIRMED. backend/app/selection/engine.py:121 `incidents = query.order_by(Incident.updated_at.desc()).limit(100).all()` — the spec contains no such cap: grep for 'limit|LIMIT|max_ai_targets' across V2_LOGIC_SPECIFICATION.md returns no hits, and the §11 pseudocode (lines 559-572) scores every incident before `top_candidates = candidates[:5]`. This function is the live pipeline path: orchestration/pipeline.py:534 `select_investigation_candidates(db, min_priority=30.0, limit=max_ai_targets, status=None)` and api/selection.py:33. The cap is self-reinforcing and silent: evaluate_incident_selection commits changed priorities (engine.py:75-76) and Incident.updated_at has onupdate=datetime.utcnow (models.py:87), so freshly-scored rows stay 'recent', and neither engine.py (no logger calls at all) nor the response exposes the truncation. Impact is correctly stated but conditional — it only bites when more than 100 open incidents exist simultaneously (e.g. a mass ag-burning burst), which is exactly the scenario the claim names.

**Refuted:** no — confirmed

---


### Severity Scoring

#### F-067 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** C_sev adds two unspecified behaviours: `else: dist_certainty = 60.0` when distance_m is None, and an outer `max(10.0, min(100.0, ...))` clamp.

**Evidence.** backend/app/severity/scoring.py:202-206 (`if distance_m is not None: dist_certainty = max(40.0, 100.0 - (distance_m / 50.0)) else: dist_certainty = 60.0`) and scoring.py:208-214 (`return max(10.0, min(100.0, round(conf, 1)))`). V2_LOGIC_SPECIFICATION.md:258-260 specifies only the four-term weighted sum and `C_dist = max(40.0, 100.0 - dist_meters/50.0)`, with no None-distance default and no floor; blueprint §19 (blueprint:2318-2331) lists inputs generically with no constants. The None path is reachable: backend/app/severity/service.py:43 sets distance_m = None whenever incident.distance_to_asset_km is None. Note the spec's own minimum for the formula is 8.0 (0.25*0 + 0.35*0 + 0.20*40.0 + 0.20*0), so the 10.0 floor does bind for near-zero-confidence inputs.

**Refuted:** no — confirmed

---

#### F-068 — UNIT / SCALE ERROR

**Claim.** Extreme Thermal Radiance override contains an extra `or firms_confidence >= 90.0` disjunct that the spec table (line 251) does not contain, forcing 150-249 MW detections at 90-100% FIRMS confidence to CRITICAL/80.0 instead of HIGH/55.0.

**Evidence.** backend/app/severity/scoring.py:168-171 — `extreme_threshold = 180.0 if is_routine_flare else 150.0` / `if frp_mw >= extreme_threshold and firms_confidence >= 80.0:` / `forced_level = "CRITICAL" if frp_mw >= 250.0 or firms_confidence >= 90.0 else "HIGH"`. V2_LOGIC_SPECIFICATION.md:251 says only `HIGH (FRP >= 250MW => CRITICAL)` with forced min 55.0/80.0; a full-text search for 90/>=90 confidence-CRITICAL rules finds none (only coincidental hits at spec:65,105,175,205,442,631). The sibling blueprint (md/FIREX_SIH2026_Complete_Project_Blueprint_REVISED2.md:2276-2290, §18 'Escalation rules') only says 'Extreme FRP + high FIRMS confidence -> minimum HIGH' and never mentions 250 MW or 90%. Floors confirmed at backend/app/severity/scoring.py:289 (`tier_min_scores = {"LOW": 10.0, "MEDIUM": 30.0, "HIGH": 55.0, "CRITICAL": 80.0}`). Masking test confirmed: tests/test_stage7_severity_alerts.py:122-134 uses frp_mw=180.0, firms_confidence=95.0 and asserts only `res["severity_level"] in ["HIGH", "CRITICAL"]` (line 132), which the CRITICAL branch satisfies. Impact as stated is accurate.

**Refuted:** no — confirmed

---

#### F-069 — SPEC / CODE DIVERGENCE

**Claim.** Historical Deviation for r < 1.0 is exactly 50.0 * r per spec 4.6, but the code adds an undocumented `max(10.0, base_dev)` floor.

**Evidence.** backend/app/severity/scoring.py:89-95 — `else: base_dev = round(50.0 * ratio, 2) ... return max(10.0, base_dev)` (the floor applies only when is_routine_flare is False; routine flares take the min/max-0.4 branch at line 94). V2_LOGIC_SPECIFICATION.md:234 states 'If r < 1.0 => 50.0 x r' with no floor; the only stated clamp is the routine-flare one at spec:235, and blueprint §18 (2232-2250) specifies no S_dev piecewise at all. No config/env defines a 10.0 floor (single implementation — the only definition of calculate_historical_deviation is scoring.py:65).

**Refuted:** no — confirmed

---

#### F-070 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** Model A selection is gated by an unspelled `history_reliability >= 0.4` threshold (scoring.py:247) in addition to baseline presence.

**Evidence.** backend/app/severity/scoring.py:247 `has_history = (p95_frp > 0.0 or median_frp > 0.0) and history_reliability >= 0.4`; the V2 spec's §4.6 (V2_LOGIC_SPECIFICATION.md:220-262) labels Model A only '(Known Hotspot With History)' / '(With Historical Baseline)' and never states a selection trigger or reliability threshold — reliability appears only in the C_sev formula (spec:258). Reachability confirmed: backend/app/behavior/baseline.py:72-87 computes a continuous reliability with a `max(0.1, ...)` floor (e.g. 3 observations / 3 active days -> 0.17), so p95_frp > 0 with reliability < 0.4 is a real, reachable combination routing the incident to NEW_HOTSPOT_NO_HISTORY.

**Refuted:** no — confirmed

---

#### F-071 — SPEC / CODE DIVERGENCE

**Claim.** Routine Flare Suppression applies at r <= 1.0 per spec 4.6 line 235, but the code's suppression branch sits in the `else` of `elif ratio >= 1.0`, so r == 1.0 exactly returns 50.0 without suppression.

**Evidence.** backend/app/severity/scoring.py:87-95: `elif ratio >= 1.0: return round(50.0 + (ratio - 1.0) * 30.0, 2)` is evaluated before the `else` that contains the routine-flare clamp at line 92-94; with ratio == 1.0 the >= branch returns 50.0 and the suppression code is unreachable. V2_LOGIC_SPECIFICATION.md:235 specifies suppression for `r <= 1.0` (min(20.0, max(5.0, 50.0*0.4)) = 20.0), and the invariants table at spec:32 says flares 'within their empirical 365-day P95 baseline envelope' are clamped to <= 20.0 — 'within' includes the ceiling. The 0.4 factor / max(5.0,..) / min(20.0,..) math itself is implemented correctly (line 94).

**Refuted:** no — confirmed

---

#### F-072 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** S_GIS's 95.0 branch fires on `hazard_category == "MAJOR_ACCIDENT_HAZARD"` regardless of facility_type, widening the spec's five named high-hazard types.

**Evidence.** backend/app/severity/scoring.py:128-134 — `high_hazard_types = {"refinery", "petrochemical", "lng_terminal", "steel_plant", "chemical"}`; `if is_inside: if any(h in f_type for h in high_hazard_types) or hazard_category == "MAJOR_ACCIDENT_HAZARD": return 95.0` / otherwise 75.0. V2_LOGIC_SPECIFICATION.md:240-241 lists only the facility types ('Inside High Hazard Facility (Refinery, Petrochem, Steel, LNG, Chemical): 95.0' / 'Inside General Facility: 75.0'); hazard_category is only mentioned as an asset column (spec:434) and its values are never defined, and neither the spec nor blueprint §14.4 (blueprint:1915-1925) contains the MAJOR_ACCIDENT_HAZARD condition. Impact arithmetic is correct: 0.15*20 = 3.0 Model A points, 0.20*20 = 4.0 Model B points.

**Refuted:** no — confirmed

---

#### F-073 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** The `firms_confidence` fed into the severity engine is `incident.severity_confidence or 75.0` (service.py:67), i.e. the incident's own previously-computed severity confidence, overwritten at service.py:99 — not a NASA FIRMS confidence, producing a self-referential loop.

**Evidence.** backend/app/severity/service.py:67 `firms_confidence = incident.severity_confidence or 75.0` and service.py:99 `incident.severity_confidence = assessment["severity_confidence"]`; scoring.py:293-298 re-injects it as `firms_confidence` into calculate_severity_confidence (scoring.py:209-212, `0.25 * firms_confidence`). backend/app/storage/models.py:53-103 (Incident) has no FIRMS/observation confidence column; the observation-level confidence does exist (models.py:36 `confidence_score`, mapped by backend/app/selection/scoring.py:23-38 map_firms_confidence) but gateway/entry points never pass it to the severity engine: backend/app/api/severity.py:23 and backend/app/orchestration/pipeline.py:630 both call evaluate_incident_severity(incident_id, db) with no confidence argument, and no other caller of compute_incident_severity exists (grep). Spec V2_LOGIC_SPECIFICATION.md:588 hands the engine `firms_confidence=target.confidence`, and blueprint §19 (line 2318-2331) lists 'FIRMS confidence' as an input to severity confidence.

**Refuted:** no — confirmed

---

#### F-074 — LOGIC / ALGORITHM DIVERGENCE

**Claim.** base_scores contains an extra key `"mining_related": 60.0` absent from the spec's seven canonical classes, scoring that label 60.0 instead of the 50.0 unspecified-label fallback.

**Evidence.** backend/app/severity/scoring.py:102-112 — dict includes `"mining_or_other_thermal_source": 65.0, "mining_related": 60.0`; fallback `base_scores.get(classification.lower(), 50.0)` at line 112. V2_LOGIC_SPECIFICATION.md:236-237 lists exactly seven base ratings and names the class `mining_or_other_thermal_source` (65), and the spec's JSON schema (spec:319) and canonical taxonomy diagram (spec:282) use the same name — `mining_related` appears nowhere in the spec. The label does reach this dict on the live path: backend/app/intelligence/provider.py:313 and schemas/provider taxonomy (provider.py:190-201, 208) emit 'mining_related'; backend/app/intelligence/service.py:99 stores it verbatim as incident.classification; backend/app/orchestration/pipeline.py:133-134/148-149 remap it only in a local variable (cls_name), never writing back to the AIInvestigation row; backend/app/severity/service.py:33 reads latest_inv.classification raw, so the extra key is hit for real mining detections.

**Refuted:** no — confirmed

---


### Tests & Documentation

#### F-075 — DOCUMENTATION DEFECT

**Claim.** README.md (and the architecture doc) fuse pixels within a '<= 25 km' physical radius into one cluster, but nothing in the code uses 25 km.

**Evidence.** Confirmed. README.md:28 'Aggregates multi-pixel satellite hits within a physical radius ($\le 25\text{ km}$)' and README.md:56 'Clusters pixels (<=25km)'; the same figure appears at docs/FIREX_Architecture_and_Codebase.md:43. The shipped path uses 1500 m — v2/backend/app/orchestration/pipeline.py:510 `spatial_eps_meters=1500.0` — and the clustering default is 2000 m (v2/backend/app/incidents/clustering.py:107). Spec V2_LOGIC_SPECIFICATION.md:129 fixes epsilon_s = 1500 m. `grep '25 km|25km'` over the backend returns no clustering use, so the docs are off by roughly 16-17x.

**Refuted:** no — confirmed

---

#### F-076 — DOCUMENTATION DEFECT

**Claim.** README.md advertises a 'Total FRP' aggregation that spec Invariant 2 forbids and the code does not compute.

**Evidence.** Confirmed in substance. README.md:28 'computing aggregated radiative output (Total FRP), peak pixel intensity, and pixel count' and README.md:148 'grouped into unified physical fire events with peak and total FRP'. Spec V2_LOGIC_SPECIFICATION.md:30 (INV-2) states FRP 'MUST NEVER BE SUMMED' and mandates only max/mean/min; v2/backend/app/incidents/association.py:109-115 and clustering.py:96-98 keep max/mean/min only. Correction to the alleged impact: a field literally named `cluster_total_frp` does exist in the export — v2/backend/app/orchestration/pipeline.py:312 `"cluster_total_frp": inc.current_max_frp` (aliased to max, never a sum) and it appears in v2/frontend/data/incidents.json. So the README's 'Total FRP' language contradicts the invariant, but 'a field that must never exist' is slightly overstated: the misleading name is emitted.

**Refuted:** no — confirmed

---

#### F-077 — DOCUMENTATION DEFECT

**Claim.** README.md attributes /api/trigger-sync-stream and /api/history-stats, and the port-8000 console, to a root dashboard/ directory, but v2/backend owns them and dashboard/server.py exists only under v1/.

**Evidence.** Confirmed. README.md:70 'dashboard: Unified Tactical Command Center (Port 8000)' and :89 'server.py # Server with /api/trigger-sync-stream and /api/history-stats'. The routes are defined at v2/backend/app/api/analysis.py:209 (`/api/trigger-sync-stream`) and :250 (`/api/history-stats`); the console is mounted at v2/backend/app/main.py:136 `app.mount('/console', StaticFiles(directory=FRONTEND_DIR), html=True)`. `dashboard/` does not exist at the root; v1/dashboard/server.py does. Root run.py:37 launches v2/backend/run.py for `serve`, so the README describes the v2 console while naming a v1 path.

**Refuted:** no — confirmed

---

#### F-078 — DOCUMENTATION DEFECT

**Claim.** README.md's 'Dependencies: requests, Pillow' + `pip install -r requirements.txt` cannot install or run the v2 FastAPI product the README documents.

**Evidence.** Confirmed. Root requirements.txt contains only `requests>=2.31.0` and `Pillow>=10.0.0` (with comments). The documented server is launched by run.py:37 -> v2/backend/run.py, and v2/backend/requirements.txt requires fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, psycopg2-binary, pytest and httpx. README.md:115-121 presents only the root requirements as the prerequisite, so `python run.py serve` fails on import in the documented environment.

**Refuted:** no — confirmed

---

#### F-079 — DOCUMENTATION DEFECT

**Claim.** README.md's 'Repository Layout' documents dashboard/, pipeline/ and archive/ at the repo root, but none exist there (they exist only under v1/), and neither README nor the architecture doc mentions v1/v2.

**Evidence.** Confirmed. README.md:79-109 draws PS162/ with run.py, requirements.txt, .gitignore, dashboard/ (index.html, styles/, js/, server.py, prepare_map_data.py, data/), pipeline/ (01_firms..07_persistence) and archive/legacy_ui/. `ls C:/Users/ssaur/OneDrive/Desktop/PS162` returns only .agents, .git, .gitignore, .pytest_cache, 'History data', README.md, __pycache__, docs, requirements.txt, run.py, run_firex.bat, v1, v2 — and that exact tree exists under v1/ (v1/dashboard/{index.html,js,styles,data,prepare_map_data.py,server.py}, v1/pipeline/{01_firms..07_persistence}, v1/archive/legacy_ui/). `grep -n 'v1|v2' README.md` and the same grep on docs/FIREX_Architecture_and_Codebase.md both return nothing.

**Refuted:** no — confirmed

---

#### F-080 — DOCUMENTATION DEFECT

**Claim.** README.md's docs/ listing omits docs/FIREX_Architecture_and_Codebase.md.

**Evidence.** Confirmed. README.md:106-108 lists only `PS162_FIREX_Project_Master_Brief.md` and `assets/`. `ls docs/` returns FIREX_Architecture_and_Codebase.md (6540 bytes), PS162_FIREX_Project_Master_Brief.md (12669 bytes) and assets/. The omitted file is the sister architecture document, and it is undiscoverable from the README's own tree.

**Refuted:** no — confirmed

---

#### F-081 — DOCUMENTATION DEFECT

**Claim.** README.md:2 references ce4e4a004f53657e4979565e8240e096.png, which does not exist at the repo root, so the landing page shows a broken image.

**Evidence.** Confirmed. README.md:2 `<img src="ce4e4a004f53657e4979565e8240e096.png" alt="FIREX Logo" width="120">`; `ls C:/Users/ssaur/OneDrive/Desktop/PS162/*.png` returns 'No such file or directory', and the root listing contains no .png at all.

**Refuted:** no — confirmed

---

#### F-082 — TEST DEFECT

**Claim.** The FRP non-summation assertion in test_stage3_incidents.py is decorative: `assert c.max_frp != 90.0` is implied by the preceding `assert c.max_frp == 40.0`, and nothing asserts a summed/total FRP field is absent.

**Evidence.** Substance confirmed; the cited lines are wrong. The assertions are at v2/tests/test_stage3_incidents.py:66 `assert c.max_frp == 40.0` and :71 `assert c.max_frp != 90.0` (the claim cited :78 and :80). Because 40.0 != 90.0, the second assertion is entailed by the first under any max-preserving implementation. The real non-summation coverage is `min_frp == 20.0` (:67), `mean_frp == 30.0` (:68) and `len(c.observations) == 3` (:69). No test asserts the absence of a total field, and the persisted model has none — v2/backend/app/storage/models.py:66-67 defines only current_max_frp/current_mean_frp — so a summing refactor would also require a schema change, but nothing in the suite guards that.

**Refuted:** no — confirmed

---

#### F-083 — DOCUMENTATION DEFECT

**Claim.** docs §3 teaches a 7-stage pipeline (05_orchestrator/run_pipeline.py running stages 1-7) with stage numbering that conflicts with the spec's 12 stages.

**Evidence.** Confirmed. docs/FIREX_Architecture_and_Codebase.md:24 'Modular 7-Stage End-to-End Processing Engine', :30 '05_orchestrator/ Master orchestrator (run_pipeline.py) running stages 1 through 7', :37-47 enumerating Stage 2 = Geographic Selection and Stage 6 = Risk Engine. The authoritative spec's Stage Summary Matrix (V2_LOGIC_SPECIFICATION.md:59-70) defines stages 0-10 with Stage 2 = GIS & Geodesy and Stage 7 = Severity Engine. The v2 code implements the 12-stage model as app/{ingestion,gis,incidents,behavior,selection,imagery,intelligence,severity,alerts,orchestration} (ls of v2/backend/app). v1/pipeline/05_orchestrator/run_pipeline.py is the superseded 7-stage runner.

**Refuted:** no — confirmed

---

#### F-084 — DOCUMENTATION DEFECT

**Claim.** docs §4 lists five run.py commands (serve, daemon, pipeline, data, legacy) but only `serve` works; the other four resolve to paths that exist only under v1/ and exit(1).

**Evidence.** Confirmed. run.py:61 `pipeline` -> BASE_DIR/pipeline/05_orchestrator/run_pipeline.py; :73 `data` -> BASE_DIR/dashboard/prepare_map_data.py; :86 `legacy` -> BASE_DIR/archive/legacy_ui/server.py; :105 `daemon` -> BASE_DIR/pipeline/07_persistence/daemon.py; each is guarded by `os.path.exists` and calls `sys.exit(1)` (run.py:62-64, :74-76, :87-89, :106-108) since none of those root directories exist. The targets do exist under v1/ (v1/pipeline/05_orchestrator/run_pipeline.py, v1/pipeline/07_persistence/daemon.py, v1/dashboard/prepare_map_data.py, v1/archive/legacy_ui/server.py). Only cmd_serve was updated, at run.py:37 -> v2/backend/run.py. Doc cite: docs/FIREX_Architecture_and_Codebase.md:53-58.

**Refuted:** no — confirmed

---

#### F-085 — DOCUMENTATION DEFECT

**Claim.** docs §5 attributes /api/trigger-sync-stream, /api/history-stats and '/crops/*: serves imagery from pipeline/03_imagery/crops/' to dashboard/server.py, documenting an imagery-serving path that does not exist in the running system.

**Evidence.** Mis-attribution confirmed; the stated impact is wrong. docs/FIREX_Architecture_and_Codebase.md:62-67 says 'Served via dashboard/server.py' and that `/crops/*` serves from `pipeline/03_imagery/crops/`. dashboard/server.py exists only at v1/dashboard/server.py, while v2 defines the routes at v2/backend/app/api/analysis.py:209/:250 and the crops route at v2/backend/app/main.py:109 `@app.get("/crops/{incident_id}/{filename}")`. However the alleged reality's sentence 'Nothing in the v2 serving path reads v1/pipeline/03_imagery/crops/' is false: main.py:100 sets `V1_CROPS_DIR = .../v1/pipeline/03_imagery/crops` and :117-121 serve from it as a fallback (after the v2 cache at :112-115, before on-demand rendering at :123-131). So the imagery-serving route does exist in the running system; only the owning-file attribution is stale.

**Refuted:** no — confirmed

---

#### F-086 — DOCUMENTATION DEFECT

**Claim.** docs/FIREX_Architecture_and_Codebase.md §2 draws the same stale root tree (dashboard/, pipeline/, archive/), which exists only under v1/.

**Evidence.** Confirmed for the stale tree. docs/FIREX_Architecture_and_Codebase.md:13-35 draws PS162/ with dashboard/ (index.html, server.py port 8000, prepare_map_data.py, js/, styles/, data/), pipeline/ (01_firms..07_persistence), archive/ and docs/; those directories exist only under v1/. Correction to one sub-claim: the doc's tree does NOT enumerate files under docs/ — its docs/ line at :34 reads `docs/ # Technical briefs and documentation (where this file resides)` — so the assertion that the tree 'names only PS162_FIREX_Project_Master_Brief.md and assets/' is mistaken (that is README.md:106-108's tree). The core divergence stands.

**Refuted:** no — confirmed

---

#### F-087 — TEST DEFECT

**Claim.** test_incident_lifecycle_and_association_dedup is nondeterministic: its coordinates are derived from a random uuid, and the resulting lat/lon are frequently outside the sovereign-territory predicate, so `assert len(incidents_run1) == 1` fails at a high rate in isolation.

**Evidence.** Confirmed, with a corrected rate. v2/tests/test_stage3_incidents.py:110-111 `offset = 5.0 + (int(uid,16) % 1000) * 0.02`, `test_lat = 14.0 + offset`, `test_lon = 75.0 + offset` gives lat in [19.0,38.98], lon in [80.0,99.98]. v2/backend/app/gis/boundaries.py:56 rejects lat>35.7 or lon>97.4; :97-109 additionally reject lat>31.4 & lon>80.3, lat>32.2 & lon>79.0, lat>33.2 & lon>79.4, lat>34.8 & lon>78.8, lat>35.5 & lon>77.8, lon in [88.5,92.0] & lat>28.1, plus the Nepal/Bhutan envelopes at :86 and :92. v2/backend/app/incidents/association.py:88-89 `continue`s on rejection and returns []. Analysing the union of these test bands over the uniform offset distribution gives a rejection probability of roughly 0.60 (dominant band: offset>17.4 -> ~0.38). The cited range :120-124 is also wrong (actual :108-113). I could not execute pytest to reproduce the claimed '5 failed / 1 passed' (the Bash classifier was unavailable), so the exact 80% figure is unverified, but the nondeterminism is certain and large.

**Refuted:** no — confirmed

---

#### F-088 — TEST DEFECT

**Claim.** test_incident_state_transition_and_events picks an arbitrary incident (`db.query(Incident).first()`), POSTs a SUBSIDING transition it never reverts, against the real SessionLocal bound to the default sqlite file — i.e. the suite writes to live application state.

**Evidence.** Confirmed. v2/tests/test_stage3_incidents.py:180 `inc = db.query(Incident).first()`, :184 `client.post(f"/incidents/{inc.id}/state", json={"new_state": "SUBSIDING", ...})`, :186-194 assert the change; no finally-block restores the prior status (contrast the explicit cleanup in test_incident_lifecycle_and_association_dedup at :154-170 and test_dashboard_data_export_contract's finally). v2/tests/conftest.py contains no DATABASE_URL/dependency override (it only fixes sys.path), v2/backend/app/storage/database.py:20-26 binds the engine to settings.DATABASE_URL, and v2/backend/app/core/config.py:28 defaults it to backend/data/firex_v2.db — that file is present at 1,282,961,408 bytes (~1.28 GB). The assertion is also order-dependent on whichever incident sorts first.

**Refuted:** no — confirmed

---

#### F-089 — TEST DEFECT

**Claim.** test_stage1_ingestion.py's live-FIRMS test (docstring item 6, 'Real NASA FIRMS API live access test') can never fail: the body is gated on `if csv_text:` and contains the tautology `assert len(parsed) >= 0`.

**Evidence.** Confirmed. v2/tests/test_stage1_ingestion.py:128 `if csv_text:` and :133 `assert len(parsed) >= 0` — `>= 0` is true for every possible list, including []. v2/backend/app/ingestion/firms.py:45 returns None on HTTP != 200 and :48 returns None on any exception, so an offline/quota-limited run skips the whole body and the test reports PASS. Only nuance: spec §12/V2_LOGIC_SPECIFICATION.md:621 advertises this file as 'SHA-256 deduplication, coordinate bounds, FIRMS parsing' and does not itself promise live-API coverage — the live-API promise is the file's own docstring at :9. The defect is real; cite is exact.

**Refuted:** no — confirmed

---

#### F-090 — TEST DEFECT

**Claim.** test_stage9_ui_integration.py's 'Export contract' checks are presence-only (facility_id, p95_frp, median_frp), and the search-response shape block is vacuous on an empty result set.

**Evidence.** Substance confirmed; one sub-assertion is slightly overstated. v2/tests/test_stage9_ui_integration.py:170,172,178 are `assert 'facility_id' in profile`, `assert 'p95_frp' in profile`, `assert 'p95_frp' in base` — key presence only, so `{}` with keys mapped to None passes. :217 `if payload["returned"] > 0:` wraps the entire row-shape block (:218-226), so on an empty Odisha result set none of the row contract is checked; the :229-233 block likewise only asserts `returned <= 3`. Correction: :182-198 is not purely presence-only — :192 asserts `data["current_pass"] in ["DAY","NIGHT"]`, which is a real value constraint.

**Refuted:** no — confirmed

---

#### F-091 — DOCUMENTATION DEFECT

**Claim.** v2/README.md says docs/ holds 'Individual stage verification reports', but v2/docs contains only stages 1-4 plus stage 0 notes.

**Evidence.** Confirmed. v2/README.md:28 '`docs/`: Individual stage verification reports and historical migration audits.' `ls v2/docs` returns exactly stage1_data_foundation_and_ingestion.md, stage2_gis_and_industrial_context.md, stage3_clustering_and_incident_lifecycle.md, stage4_behavior_intelligence.md and v1_audit_and_stage0_notes.md — stages 1-4 of the twelve the README's own spec advertises, with nothing marking the set as incomplete.

**Refuted:** no — confirmed

---

#### F-092 — DOCUMENTATION DEFECT

**Claim.** v2/README.md's backend/ listing omits app/api/, app/core/ and app/workers/, including config constants and the API surface.

**Evidence.** Confirmed. v2/README.md:14-25 enumerates app/ingestion, gis, incidents, behavior, selection, imagery, intelligence, severity, alerts, orchestration, storage — eleven packages. `ls v2/backend/app` shows those eleven plus api/, core/ and workers/. The omitted packages are load-bearing: v2/backend/app/core/config.py holds every spec constant (e.g. RATE_LIMIT_PER_MINUTE at :64, DATABASE_URL at :28), and app/api/analysis.py owns the SSE-style feed and the routes the same README's frontend description relies on.

**Refuted:** no — confirmed

---

#### F-093 — TEST DEFECT

**Claim.** §12 credits test_stage10_hardening.py with 'Rate limiting (120 req/min)', but the test builds its own app with requests_per_minute=5 and never asserts the shipped default of 120.

**Evidence.** Confirmed. V2_LOGIC_SPECIFICATION.md:630 advertises 'Rate limiting (120 req/min)'. v2/tests/test_stage10_hardening.py:111 `test_app.add_middleware(RateLimitMiddleware, requests_per_minute=5)` on a locally constructed FastAPI app (:110), asserting the 6th request is 429 at :124-127. The only assertion touching the shipped configuration is :213 `assert data['hardening']['rate_limiting'] is not None` — no numeric check. The real value lives at v2/backend/app/core/config.py:64 `RATE_LIMIT_PER_MINUTE: int = 120` and is wired at v2/backend/app/main.py:40, so it could be changed to any number without a test failure. The exempt-path test (:129-143) builds another app with requests_per_minute=2 and only asserts 5 requests to /console/index.html succeed — it never proves the exempt path is outside the limiter's accounting.

**Refuted:** no — confirmed

---

#### F-094 — TEST DEFECT

**Claim.** §12 credits test_stage3_incidents.py with 'DBSCAN', but every call passes spatial_eps_meters=2000.0 (the function default); the shipped pipeline uses 1500.0 and no test exercises the 1.5 km reachability boundary.

**Evidence.** Confirmed. v2/tests/test_stage3_incidents.py:62, :87, :92, :97 all pass `spatial_eps_meters=2000.0`, which is exactly the default at v2/backend/app/incidents/clustering.py:107. The production call site is v2/backend/app/orchestration/pipeline.py:510 `cluster_observations(active_obs, spatial_eps_meters=1500.0, time_window_hours=24.0)`, and spec V2_LOGIC_SPECIFICATION.md:129 mandates epsilon_s = 1500 meters. No test calls the function with 1500.0 or with no override, and none places a pair 1.6 km apart (the case the shipped pipeline must not merge).

**Refuted:** no — confirmed

---

#### F-095 — TEST DEFECT

**Claim.** §12 credits test_stage6_ai_investigation.py with the '12 AI prompt rules', but no assertion checks rule count, numbering, or rule text.

**Evidence.** Confirmed. V2_LOGIC_SPECIFICATION.md:626 advertises '12 AI prompt rules'. v2/tests/test_stage6_ai_investigation.py:149-157 asserts only data substrings: 'INC-TEST-001', 'TATA Steel Kalinganagar', '55.0 MW', '11.1 MW', '2.9 MW', and three taxonomy class names. `grep -rn 'MANDATORY|OPERATIONAL RULES' v2/tests/*.py` returns nothing, and no test asserts rule numbering or count. The actual rules live in v2/backend/app/intelligence/prompts.py:17-29 (SYSTEM_PROMPT block) matching spec §6.1 at V2_LOGIC_SPECIFICATION.md:300-315. Deleting or reordering them would not fail any test.

**Refuted:** no — confirmed

---

#### F-096 — TEST DEFECT

**Claim.** §12 credits test_stage9_ui_integration.py with 'Console data feed', but no test in the suite ever requests /api/console/feed.

**Evidence.** Confirmed. Spec V2_LOGIC_SPECIFICATION.md:629 lists 'test_stage9_ui_integration.py  # Console data feed, backward-compatible dashboard sync'. `grep -rn console/feed v2/tests/` returns nothing; the only test-side hits in the file are /api/history-stats (:186), /api/analysis/status (:194) and /api/history/search (:209). The route exists at v2/backend/app/api/analysis.py:270 and its only caller is the frontend at v2/frontend/js/data.js:34. A regression in the feed route would not be caught by the suite.

**Refuted:** no — confirmed

---

#### F-097 — TEST DEFECT

**Claim.** §12 says test_stage4_behavior.py covers '365d percentiles', but no test constructs or asserts a 365-day window — the percentile test uses a 5-element list.

**Evidence.** Confirmed. v2/tests/test_stage4_behavior.py:49 `seq = [10.0, 12.0, 11.0, 13.0, 12.0]` with :56 `assert stats['p95'] >= 12.0`; the longest synthetic sequence anywhere in the file is `for i in range(10)` at :142 (and `range(6)` at :210). Every 365-day figure in the suite is a literal in a mock payload or an export-contract key: test_climatology_calibration.py:74 `active_days_365d: 284`, test_industrial_facility_classification.py:111 `280`, test_mining_basin_classification.py:90 `89`, test_stage9_ui_integration.py:123 key-presence only. The one live-data assertion, test_climatology_calibration.py:42 `bl['active_days_365d'] > 50`, reads a pre-seeded climatology row rather than exercising 365 days of windowing. Spec: V2_LOGIC_SPECIFICATION.md:624.

**Refuted:** no — confirmed

---

## Part 4 — Claims that did NOT survive refutation (1)

Recorded so the audit's negative results are not lost. These should **not** be treated as defects.

### 7. Sec 7 crosshair `gap = 12` is used as offset from centre, giving a 24px opening (2x the specified 12px gap)

The code geometry is exactly as described — backend/app/imagery/reticle.py:54 gap = 12, lines 57-61 draw arms from cx-40/cx-12 and cx+12/cx+40, line 63 draws a 4px dot — so the tip-to-tip opening is 24px and 20px clear of the dot, and the 2px width and (255,50,50) crimson (line 37) do match. But no divergence is established: '12px central targeting gap' is satisfied under the ordinary reticle reading of gap = distance from centre to the start of each arm, which is precisely what the code implements; the claim's 24px figure is an inference from the competing (total-opening) reading of an ambiguous spec phrase, and the claim itself concedes it is 'not verifiable from code alone'. Sec 7 contains no other gap measurement to appeal to.

---

## Provenance

- Run ID: `wf_d4771b72-a1f`
- Raw machine-readable result: `C:\Users\ssaur\AppData\Local\Temp\claude\C--WINDOWS-system32\e07b814c-ab5e-4b30-867c-14ccd758efe1\tasks\wznxolp5u.output`
- Per-agent full return values: `...\subagents\workflows\wf_d4771b72-a1f\journal.jsonl`
- This document was generated mechanically from that JSON. Claim and evidence strings are verbatim; no finding was summarised, merged, or dropped.
