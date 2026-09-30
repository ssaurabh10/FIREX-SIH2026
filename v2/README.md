# FIREX v2 — AI-Powered Satellite Fire & Thermal Intelligence Platform

> **Smart India Hackathon 2026 · Problem Statement 162 (NTRO)**

## What Is FIREX?

NASA satellites detect thousands of heat sources over India every day — but **most of them are not emergencies**. Refinery flares, steel furnaces, coal mine fires, and crop burning all look the same from space as an actual industrial disaster.

**FIREX v2** is an autonomous intelligence platform that takes those raw satellite heat detections and determines which ones are real emergencies worth acting on. It does this through a 12-stage pipeline that:

1. 🛰️ Pulls live thermal data from NASA FIRMS (VIIRS & MODIS satellites)
2. 🗺️ Identifies where each detection is — which facility, district, or forest it's near
3. 📊 Compares against a full year of historical data for that exact location
4. 🖼️ Fetches satellite imagery and overlays a tactical analysis HUD
5. 🤖 Sends the image to an AI vision model that classifies what it sees
6. ⚡ Computes a composite danger score (0–100) from multiple factors
7. 🚨 Alerts human operators only when the danger is genuine

The end result: operators see a **prioritized, explained, and visually verified** list of incidents instead of an overwhelming flood of raw detections.

---

## Quick Start

### Prerequisites

- **Python 3.10+** (tested on Python 3.14.6)
- **pip** (Python package manager)

### Install & Run

```bash
# From this directory (v2/)
pip install -r backend/requirements.txt
python backend/run.py
```

A single server starts on `http://127.0.0.1:8000` serving everything:

| URL | What It Does |
|-----|-------------|
| [`http://127.0.0.1:8000/console/`](http://127.0.0.1:8000/console/) | 🖥️ **Operator Console** — the live tactical dashboard with map |
| [`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs) | 📖 **API Documentation** — interactive Swagger/OpenAPI UI |
| [`http://127.0.0.1:8000/health`](http://127.0.0.1:8000/health) | 💚 **Health Check** — system status and memory diagnostics |

### Configuration

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Purpose |
|----------|---------|
| `FIRMS_MAP_KEY` | NASA FIRMS API key (for pulling satellite data) |
| `OPENROUTER_API_KEYS` | AI vision model keys (comma-separated for rotation) |
| `DATABASE_URL` | Database connection (defaults to local SQLite) |

### CLI Commands

```bash
python backend/cli.py pipeline        # Run a full analysis cycle
python backend/cli.py data            # Regenerate console data files
python backend/cli.py severity-sweep  # Re-evaluate severity across all incidents
python backend/cli.py migrate         # Apply database migrations
```

### Run Tests

```bash
python -m pytest tests
# 178 tests across 17+ modules — all passing
```

Tests are fully isolated: they use a throwaway SQLite database and temporary export directories, so they never touch production data.

---

## How It Works — The 12-Stage Pipeline

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                       FIREX v2 Analysis Pipeline                       │
 │                                                                         │
 │  1. Run Lock           Only one pipeline run at a time (mutex)         │
 │  2. Ingestion          Pull live NASA FIRMS data, deduplicate          │
 │  3. GIS Enrichment     Nearest facility, mining basin, admin region    │
 │  4. Clustering         Group nearby detections (1,500m / 24h window)   │
 │  5. Incident Tracking  Link clusters to tracked incident records       │
 │  6. Climatology        Compare against 365 days of history             │
 │  7. Selection          Rank top 5 candidates for AI investigation      │
 │  8. Imagery            Fetch satellite photo + tactical HUD overlay    │
 │  9. AI Vision          Classify: fire / flare / mining / wildfire / …  │
 │ 10. Severity           Score 0–100 with 4 weighted factors             │
 │ 11. Alerting           Deduplicated alerts for HIGH / CRITICAL only    │
 │ 12. Export             Push results to dashboard + SSE broadcast       │
 └─────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

| Principle | What It Means |
|-----------|--------------|
| **Heat ≠ Fire** | A satellite thermal detection is just an infrared anomaly — not a confirmed emergency. Every incident must be verified. |
| **Never sum FRP** | Fire Radiative Power across multi-pixel clusters uses **max/mean/min only** — summation would inflate the physical energy reading. |
| **India only** | Detections outside sovereign Indian territory (68.7°E–97.4°E, 8.4°N–37.6°N) are discarded. |
| **Routine sources stay quiet** | Locations hot on 10+ days/year within their historical P95 envelope are capped at severity ≤ 20/100. |
| **New hotspots get a fair chance** | No-history locations use an alternate scoring model so they're never penalised with zeros. |
| **No alert spam** | One alert per incident per severity level. Duplicates are suppressed; only escalations trigger new alerts. |

---

## Documentation

| Document | Audience | Description |
|----------|----------|-------------|
| 📘 **[V2_LOGIC_EXPLAINED.md](V2_LOGIC_EXPLAINED.md)** | Everyone | Plain-language explanation of the entire system — no prior knowledge needed |
| 📗 **[V2_LOGIC_SPECIFICATION.md](V2_LOGIC_SPECIFICATION.md)** | Engineers & AI Agents | Authoritative technical specification with mathematical formulas, code references, and schema definitions |
| 📙 **[V2_DEFECT_REPORT.md](V2_DEFECT_REPORT.md)** | Engineers | Conformance audit — known divergences between the spec and the implementation |
| 📂 **[docs/](docs)** | Engineers | Stage verification reports for subsystems 1–4 |
| 📄 **[md/](md)** | Project context | SIH 2026 Complete Project Blueprint |

---

## Directory Structure

```
v2/
├── README.md                          ← You are here
├── V2_LOGIC_EXPLAINED.md              ← Beginner-friendly system guide
├── V2_LOGIC_SPECIFICATION.md          ← Technical specification (authoritative)
├── V2_DEFECT_REPORT.md                ← Conformance audit findings
├── run.py                             ← Convenience launcher
│
├── backend/                           ← Python backend (FastAPI)
│   ├── app/
│   │   ├── main.py                    Server entry point, route registration
│   │   ├── api/                       REST endpoints & SSE streaming
│   │   ├── core/                      Settings, logging, rate limiting (120 req/min)
│   │   ├── ingestion/                 NASA FIRMS data fetching & SHA-256 dedup
│   │   ├── gis/                       Geography: boundaries, facilities, mining basins
│   │   ├── incidents/                 Clustering (1,500m/24h) & lifecycle state machine
│   │   ├── behavior/                  365-day baselines & anomaly detection
│   │   ├── selection/                 Priority ranking for AI investigation
│   │   ├── imagery/                   Satellite photos & tactical HUD overlay
│   │   ├── intelligence/              AI vision: 12 prompt rules, key rotation, fallback
│   │   ├── severity/                  Danger scoring (0–100), Indian calibration
│   │   ├── alerts/                    Deduplicated alert dispatch & escalation
│   │   ├── orchestration/             Pipeline runner, mutex lock, SSE broadcaster
│   │   └── storage/                   SQLAlchemy models (15 tables)
│   ├── scripts/                       Offline data processing utilities
│   ├── data/                          Database & imagery cache
│   ├── .env.example                   Configuration template
│   └── requirements.txt              Python dependencies
│
├── frontend/                          ← Operator console (HTML/CSS/JS)
│   ├── index.html                     Dashboard — dark-themed tactical map UI
│   ├── js/                            Map rendering, SSE listener, dossier views
│   ├── styles/                        Design tokens, component styles
│   └── data/                          JSON feed files (written by pipeline)
│
├── tests/                             ← 178 automated tests
│   ├── conftest.py                    Test isolation (throwaway DB & directories)
│   ├── fixtures/                      Reference data & test constants
│   └── test_stage*.py                 Tests by subsystem (0–10 grouping)
│
├── docs/                              ← Stage verification reports (1–4)
└── md/                                ← SIH 2026 project blueprint
```

### Backend Modules at a Glance

| Module | Stage | What It Does |
|--------|-------|-------------|
| `ingestion/` | 2 | Pulls and deduplicates NASA FIRMS satellite telemetry |
| `gis/` | 3 | Haversine distance, point-in-polygon, facility lookup, mining basins |
| `incidents/` | 4–5 | Spatial-temporal clustering (DBSCAN) and incident lifecycle tracking |
| `behavior/` | 6 | 365-day thermal baselines, percentiles (P50/P90/P95), anomaly scoring |
| `selection/` | 7 | Dual-mode priority ranking with mandatory overrides |
| `imagery/` | 8 | Satellite photo cropping with crosshair, range rings, and scale bar |
| `intelligence/` | 9 | AI vision classification with 12 mandatory prompt rules |
| `severity/` | 10 | Composite 0–100 scoring with Indian FRP calibration and 4 overrides |
| `alerts/` | 11 | Exactly-once alert deduplication with monotonic escalation |
| `orchestration/` | 1, 12 | Pipeline runner, mutex, SSE events, JSON export |

---

## The Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | Python, FastAPI, SQLAlchemy | REST API, pipeline orchestration, database |
| **Database** | SQLite (dev) / PostgreSQL (prod) | 15 normalized tables, 2.9M+ historical observations |
| **AI Vision** | OpenRouter API | Multimodal image classification with fallback safety |
| **Satellite Data** | NASA FIRMS API | VIIRS & MODIS thermal detections |
| **Frontend** | HTML, CSS, JavaScript, Leaflet.js | Dark-themed tactical map console (no build step) |
| **Testing** | pytest | 178 tests with full database isolation |

---

## Relationship to v1

This directory (`v2/`) sits beside `v1/`, which holds the superseded pipeline and dashboard. **v2 does not depend on v1.** Two optional backward-compatibility links exist:

- **Imagery fallback:** The image server checks `v1/pipeline/03_imagery/crops` as a secondary source before rendering on demand — skipped silently when v1 is absent.
- **Data mirroring:** Pipeline exports are mirrored to `v1/dashboard/data/` only if that directory already exists — the pipeline never creates it.

Run v2 standalone with `python run.py <command>` from this directory. The repository-root `run.py` adds legacy v1 commands but is not required.

---

## License & Context

Built for **Smart India Hackathon (SIH) 2026**, Problem Statement 162, set by the **National Technical Research Organisation (NTRO)**. The problem asks for an AI-powered system to distinguish routine industrial thermal activity from genuine emergencies using space-borne satellite data over India.

> **Start here:** [V2_LOGIC_EXPLAINED.md](V2_LOGIC_EXPLAINED.md) for a complete walkthrough, or [V2_LOGIC_SPECIFICATION.md](V2_LOGIC_SPECIFICATION.md) for the technical deep dive.
