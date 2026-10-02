# FIREX v2 — System Logic Explained

**An AI-Powered Satellite Intelligence System for Detecting Real Industrial Fires Across India**

> *This document explains how FIREX v2 works in plain language. No prior knowledge of the project, satellite systems, or geospatial technology is required.*

---

## Table of Contents

1. [What Problem Does FIREX Solve?](#1-what-problem-does-firex-solve)
2. [The Core Idea in One Paragraph](#2-the-core-idea-in-one-paragraph)
3. [Key Concepts You Need to Know](#3-key-concepts-you-need-to-know)
4. [The Six Unbreakable Rules](#4-the-six-unbreakable-rules)
5. [How the System Works: The 12-Stage Pipeline](#5-how-the-system-works-the-12-stage-pipeline)
6. [How Severity Scoring Works](#6-how-severity-scoring-works)
7. [How the AI Vision System Works](#7-how-the-ai-vision-system-works)
8. [How the Alert System Works](#8-how-the-alert-system-works)
9. [The Operator Console (Frontend Dashboard)](#9-the-operator-console-frontend-dashboard)
10. [The Database: What Gets Stored](#10-the-database-what-gets-stored)
11. [How to Run the System](#11-how-to-run-the-system)
12. [Project Directory Map](#12-project-directory-map)
13. [Frequently Asked Questions](#13-frequently-asked-questions)

---

## 1. What Problem Does FIREX Solve?

### The Challenge

NASA operates a global system called **FIRMS** (Fire Information for Resource Management System) that uses satellites orbiting the Earth to detect heat sources on the ground. These satellites — primarily **VIIRS** (aboard Suomi NPP and NOAA-20) and **MODIS** (aboard Terra and Aqua) — scan the Earth's surface using infrared sensors and report anything that looks unusually hot.

The problem is: **detecting heat is not the same as detecting a fire emergency.**

India has thousands of legitimate, routine heat sources that these satellites pick up every single day:

| Source | Why It's Hot | Is It an Emergency? |
|--------|-------------|---------------------|
| **Oil refinery flare stacks** | Refineries burn excess gas through tall pipes called "flares" — this is normal and safe | ❌ No |
| **Steel plant blast furnaces** | Steel production requires temperatures above 1,500°C — furnaces glow 24/7 | ❌ No |
| **Coal mine seam fires** | Underground coal deposits in places like Jharia (Jharkhand) burn slowly for years | ❌ No (it's chronic) |
| **Agricultural crop burning** | Farmers in Punjab and Haryana burn crop stubble after harvest (Oct–Nov) | ❌ No (it's deliberate) |
| **Actual industrial fire** | An uncontrolled fire at a chemical plant, storage tank, or warehouse | ✅ **YES** |

When a government command center receives 500+ satellite alerts per day and 95% of them are routine refinery flares, operators stop paying attention. This is called **"alert fatigue"** — and it means a real emergency gets buried in noise.

### What FIREX v2 Does

FIREX v2 takes those raw satellite heat detections and runs them through a 12-stage intelligence pipeline that:

1. **Filters out** detections from outside India's borders
2. **Groups** nearby detections into physical incidents
3. **Checks history** — "Has this exact spot been hot before? For how many days?"
4. **Looks at satellite photos** — AI examines optical imagery to see what's actually there
5. **Scores the danger** — Produces a 0–100 severity score based on multiple factors
6. **Alerts only when necessary** — Sends a notification only for genuinely dangerous situations

The end result: an operator sees a prioritized list of incidents with clear explanations, satellite photos, and risk ratings — instead of an overwhelming flood of raw heat detections.

---

## 2. The Core Idea in One Paragraph

> FIREX v2 continuously pulls live satellite heat-detection data from NASA, checks whether each detection falls inside India, groups nearby detections into tracked incidents, compares each incident's heat intensity against a full year of historical data for that exact location, fetches high-resolution satellite photos and sends them to an AI vision model that classifies what it sees (refinery flare, industrial fire, mining activity, wildfire, crop burning, or uncertain), computes a composite danger score from 0 to 100 using four weighted factors, and alerts human operators only when the score crosses into dangerous territory — all in a single automated run that takes seconds.

---

## 3. Key Concepts You Need to Know

Before diving into how the system works, here are the key terms explained simply:

### FRP — Fire Radiative Power
- **What it is:** A measurement of how much heat energy a fire or heat source is releasing, measured in **megawatts (MW)**.
- **Think of it as:** A thermometer for fires as seen from space.
- **Example values:**
  - A small crop burn: ~2–5 MW
  - A normal refinery flare: ~5–20 MW
  - A large industrial fire: ~50–150+ MW
  - A catastrophic explosion: 200+ MW

### FIRMS — Fire Information for Resource Management System
- **What it is:** NASA's system that collects and distributes fire/heat detection data from satellites.
- **How we use it:** FIREX pulls live data from FIRMS every time the pipeline runs.

### Confidence Score
- **What it is:** NASA's own estimate of how sure they are that a detection is a real heat source (not a sensor glitch or sunlight reflection).
- **Range:** 0–100%, with "high" meaning NASA is quite confident.

### GIS — Geographic Information System
- **What it is:** The part of the system that understands geography — which state a coordinate is in, whether it's inside a known refinery, how far away the nearest industrial facility is, whether it's in a protected forest, etc.

### P50, P90, P95, P99 — Statistical Percentiles
- **What they mean:**
  - **P50 (Median):** Half of all readings are below this value. For India, the median heat detection is **4.05 MW** — most detections are quite mild.
  - **P90:** Only 10% of readings exceed this value (**13.32 MW**).
  - **P95:** Only 5% of readings exceed this value (**20.81 MW**) — anything above this for a given location is unusually hot.
  - **P99:** Only 1% of readings exceed this value (**64.49 MW**) — extreme, disaster-level intensity.
- **Why they matter:** By comparing a current reading against a location's *own* historical P95, the system can tell the difference between "this steel plant is hot, as always" and "this steel plant is three times hotter than its worst day in the past year."

### SSE — Server-Sent Events
- **What it is:** A way for the server to push live updates to the browser in real time, like a news ticker. The operator console uses this to show pipeline progress as it happens.

---

## 4. The Six Unbreakable Rules

FIREX v2 enforces six rules that can **never** be violated by any part of the system. These are called **invariants** — they are the system's constitution.

### Rule 1: Heat ≠ Disaster
> A satellite heat detection is just an infrared anomaly. It must **never** be treated as a confirmed fire without further verification.

*Why:* A satellite can't tell the difference between a refinery doing its job and a refinery on fire. Both look like "hot spot" from 800 km up.

### Rule 2: Never Add Up Heat Values
> When multiple satellite detections are grouped into one incident, you compute the **maximum**, **average**, and **minimum** FRP — but you **never sum them**.

*Why:* If a fire has 10 satellite pixels at 5 MW each, saying "50 MW fire!" is physically misleading. Those 10 pixels might overlap, or they might just be 10 views of the same 5 MW flame. The peak reading (max) is the honest number.

### Rule 3: India Only
> Any detection outside India's borders (latitude 8.4°N–37.6°N, longitude 68.7°E–97.4°E, plus a detailed polygon mask) is discarded.

*Why:* This is a sovereign Indian defense system — processing foreign territory is out of scope and could cause diplomatic issues.

### Rule 4: Routine Sources Stay Quiet
> A location that has been hot on 10+ days per year, operating within its own historical 95th-percentile (P95) intensity, is labelled **"ROUTINE_FLARE"** and its severity is capped at ≤ 20 out of 100.

*Why:* A refinery flare that has been burning normally for 300 days is not an emergency. The system should not cry wolf.

### Rule 5: New Hotspots Get a Fair Chance
> A brand-new heat detection with no historical data must **never** be penalised with a zero score just because there's no history to compare against.

*Why:* A new fire at a previously cold location is potentially the most dangerous kind — it could be an explosion. The system uses an alternate scoring model that relies on physical intensity and AI analysis instead of historical comparison.

### Rule 6: No Alert Spam
> An alert is sent **only once** per incident unless the danger level **strictly escalates** (e.g., from HIGH to CRITICAL). Repeated detections at the same severity level do not generate duplicate alerts.

*Why:* If a fire burns for 3 days and the system runs 50 times, the operator should get 1 alert — not 50.

---

## 5. How the System Works: The 12-Stage Pipeline

When FIREX v2 runs an analysis cycle, it executes twelve stages in sequence, like an assembly line. Here's what each stage does, explained simply:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FIREX v2 Pipeline Overview                       │
│                                                                     │
│  Stage 1:  Lock the pipeline (only one run at a time)              │
│     ↓                                                               │
│  Stage 2:  Pull live satellite data from NASA                      │
│     ↓                                                               │
│  Stage 3:  Identify where each detection is (geography)            │
│     ↓                                                               │
│  Stage 4:  Group nearby detections into incidents                  │
│     ↓                                                               │
│  Stage 5:  Link new groups to existing tracked incidents           │
│     ↓                                                               │
│  Stage 6:  Compare against 365 days of history                    │
│     ↓                                                               │
│  Stage 7:  Rank incidents by priority for investigation           │
│     ↓                                                               │
│  Stage 8:  Fetch satellite photos and draw tactical overlays      │
│     ↓                                                               │
│  Stage 9:  AI examines the photos and classifies each incident    │
│     ↓                                                               │
│  Stage 10: Calculate danger score (0–100)                         │
│     ↓                                                               │
│  Stage 11: Send alerts for dangerous incidents                    │
│     ↓                                                               │
│  Stage 12: Export results to dashboard and notify operators       │
└─────────────────────────────────────────────────────────────────────┘
```

### Stage 1 — Run Lock & Audit Record

**What it does:** Ensures only one pipeline run happens at a time, and creates a timestamped audit record.

**Why it matters:** If two pipeline runs happen simultaneously, they could process the same satellite data twice, create duplicate incidents, or corrupt each other's state. A thread-safe "mutex lock" prevents this — if someone tries to start a second run while one is in progress, they get an HTTP 409 error ("Already running").

**Example:** `RUN-20260930-130000-a1b2c3` — a unique run ID with the timestamp and a random suffix.

---

### Stage 2 — Satellite Data Ingestion

**What it does:** Connects to NASA's FIRMS API, downloads the latest thermal detection data, validates each record, and stores only new ones.

**How deduplication works:** Each observation gets a fingerprint made from:
```
SATELLITE_SENSOR_LATITUDE_LONGITUDE_DATETIME
```
This fingerprint is hashed using SHA-256 (a cryptographic function) and truncated to 20 characters. If an observation with the same hash already exists in the database, it's skipped — preventing duplicates when the pipeline runs multiple times.

**What gets checked for each detection:**
- ✅ Is the latitude/longitude inside India? (Rule 3)
- ✅ Is the data well-formed? (valid numbers, timestamps, etc.)
- ✅ Is this a new detection we haven't seen before?

---

### Stage 3 — Geographic Enrichment

**What it does:** For each new detection, determines:
- Which **state and district** it's in (administrative boundaries)
- The **nearest industrial facility** (refinery, steel plant, power station, etc.) and the distance in meters
- Whether it's **inside** a known facility's boundary
- Whether it's in a **mining basin** (Korba, Jharia, Singrauli, etc.)
- Whether it's in a **protected forest** or wildlife reserve
- The **land cover type** at that location

**How distance is calculated:** Using the **Haversine formula** — a standard calculation for finding the distance between two points on a sphere (the Earth). This accounts for the curvature of the Earth, unlike a simple straight-line calculation on a flat map.

**How "inside a facility" is determined:** Using a **ray-casting algorithm** — imagine standing at the detection point and shooting a laser beam due east. Count how many times it crosses the facility's boundary polygon. If it crosses an odd number of times, the point is inside the polygon. This is a classic computational geometry technique.

---

### Stage 4 — Spatial-Temporal Clustering

**What it does:** Groups individual satellite detections that are close together in both **space** and **time** into physical "clusters" representing a single real-world event.

**The grouping rules:**
- **Spatial:** Two detections within **1,500 meters** (1.5 km) of each other
- **Temporal:** Two detections within **24 hours** of each other
- Both conditions must be true for two detections to be grouped together

**What is computed for each cluster:**

| Statistic | How It's Calculated | Why |
|-----------|-------------------|-----|
| **Max FRP** | Highest single reading in the group | Represents peak intensity |
| **Mean FRP** | Average of all readings | Represents typical intensity |
| **Min FRP** | Lowest single reading | Represents minimum intensity |
| **Total FRP** | ⛔ **BANNED** — never computed | Rule 2: summing is misleading |
| **Center** | Average latitude & longitude of all detections | Geographic centroid |
| **Footprint** | Distance from center to farthest detection + buffer | How big the event is |

---

### Stage 5 — Incident Association & Lifecycle

**What it does:** Links the newly formed clusters to existing tracked incidents, or creates new incident records.

**How incidents are tracked:** Each incident follows a lifecycle state machine:

```
NEW → INVESTIGATING → ACTIVE → PERSISTENT → ESCALATED
                ↓         ↓          ↓
             SUBSIDING ← ← ← ← ← ←
                ↓
             RESOLVED ← REOPENED
```

- A cluster that overlaps an existing incident's footprint is **associated** with it (the incident grows).
- A cluster in a new area becomes a **new incident** with a code like `INC-2026-0001`.
- Incidents that stop receiving new detections eventually move to `SUBSIDING` → `RESOLVED`.
- If a resolved incident flares up again, it can be `REOPENED`.

---

### Stage 6 — Historical Baseline & Climatology

**What it does:** For each incident's location, the system looks up a **full year (365 days)** of historical satellite data to understand what is "normal" for that spot.

**What it calculates:**
- **Median FRP (P50):** The typical heat level at this location
- **P90 FRP:** The level exceeded only 10% of the time
- **P95 FRP:** The level exceeded only 5% of the time — anything above this is unusual
- **Active days:** How many days out of 365 had heat detections (a steel plant might have 300+)
- **Night ratio:** What fraction of detections happen at night (industrial sources tend to be nocturnal)
- **Persistence score:** A 0–1 measure of how continuously active this spot is

**How it classifies the situation:**

```
                        Low Persistence           High Persistence
                        (< 0.5)                   (≥ 0.5)
                   ┌─────────────────────────┬─────────────────────────┐
  Normal           │ Transient benign burn    │ Routine refinery flare  │
  (Anomaly < 50)   │ (probably nothing)       │ (normal operations)     │
                   ├─────────────────────────┼─────────────────────────┤
  Abnormal         │ Sudden ignition/disaster │ Flare runaway/blowout   │
  (Anomaly ≥ 50)   │ ⚠️ INVESTIGATE          │ ⚠️ INVESTIGATE          │
                   └─────────────────────────┴─────────────────────────┘
```

**The grid system:** India is divided into a grid of cells, each **0.02° × 0.02°** (roughly 2.2 km × 2.2 km). Historical statistics are stored per cell, built from the national archive of **2,895,064 satellite observations**.

---

### Stage 7 — Candidate Selection & Prioritization

**What it does:** Ranks all active incidents by priority to decide which ones deserve the expensive AI visual investigation (since AI calls cost money and time, only the top 5 per run are investigated).

**The scoring formula:**

For incidents **with** historical data:
```
Priority = 0.40 × FRP_Score + 0.30 × Persistence_Score + 0.20 × FIRMS_Confidence + 0.10 × Anomaly_Score
```

For **new** incidents with no history:
```
Priority = 0.45 × FRP_Score + 0.30 × Persistence_Score + 0.25 × FIRMS_Confidence
```

**Automatic overrides** — these force priority ≥ 90 regardless of formula:
- 🔴 **Extreme FRP:** ≥ 150 MW with high NASA confidence
- 🔴 **High Persistence:** Persistence score ≥ 85 (multi-day sustained combustion)
- 🔴 **Strong Anomaly:** Current FRP is 3× or more above the historical median

**Limits:**
- At most **500 incidents** are evaluated per pass (newest first)
- At most **5 incidents** are sent for AI investigation per run

---

### Stage 8 — Satellite Imagery & Tactical Overlay

**What it does:** For each selected candidate, fetches a high-resolution optical satellite image centered on the incident's coordinates and draws a military-style tactical overlay on top of it.

**The tactical HUD (Heads-Up Display) includes:**

```
┌──────────────────────────────────────────────────────────────────┐
│ TARGET: INC-2026-0001   LAT: 30.1234°  LON: 74.9876°  FRP: 42.5│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│                         ╭────┼────╮    ← 80% Range Ring          │
│                       ╭─│────┼────│─╮                            │
│                    ───┼──────●──────┼─── ← Crosshair             │
│                       ╰─│────┼────│─╯                            │
│                         ╰────┼────╯    ← 40% Range Ring          │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ ├── 500m ──┤ [Scale Bar]                         ▲ N             │
└──────────────────────────────────────────────────────────────────┘
```

- **Crosshair:** Crimson red, marks the exact center of the detection
- **Range rings:** Concentric circles showing physical distances (e.g., 200m, 400m) so the operator can judge scale
- **Scale bar:** Shows real-world distance in meters
- **Banner:** Shows incident code, coordinates, and FRP

The zoom level is automatically chosen to frame the incident's footprint properly — it's not a fixed zoom.

---

### Stage 9 — Multimodal AI Vision Analysis

**What it does:** Sends the satellite photo (with tactical overlay) plus all contextual data (location, facility info, history) to an AI vision model and asks it to classify what it sees.

**The six possible classifications:**

| Classification | What It Means | Example |
|---------------|--------------|---------|
| `industrial_fire` | An uncontrolled blaze at an industrial facility | Refinery tank fire, warehouse fire |
| `gas_flare` | A controlled, operational gas flare | Normal refinery flare stack |
| `wildfire` | Forest or brush fire in natural terrain | Fire in a national park |
| `agricultural_burning` | Deliberate crop residue burning | Stubble burning in Punjab |
| `mining_related` | Heat from mining operations | Coal seam fire in Jharia |
| `uncertain` | Can't determine — cloud cover, low resolution, ambiguous | Cloudy satellite image |

**The 12 rules the AI must follow:**

1. Treat heat detections as anomalies, not confirmed fires
2. Actually **look** at the satellite photo, don't just read the metadata
3. Use location and facility info as context for what it sees
4. Never invent or guess missing information
5. Don't assign a danger score (that's the next stage's job)
6. Always provide a primary classification AND an alternative hypothesis
7. Describe specific visible features (smoke plumes, flame cores, etc.)
8. Cite specific contextual evidence (facility proximity, P95 comparison)
9. State any uncertainties openly (cloud cover, sensor limitations)
10. When in doubt, classify as "uncertain" rather than guessing
11. Never claim absolute certainty from orbital imagery
12. Output must be valid JSON matching the exact required format

**The AI response looks like:**
```json
{
  "classification": "gas_flare",
  "confidence": 85.0,
  "alternative": {
    "classification": "industrial_fire",
    "confidence": 15.0
  },
  "visual_evidence": [
    "Elevated flare stack visible at center of refinery",
    "Tight localized plume with no ground damage"
  ],
  "contextual_evidence": [
    "Located 42m inside HMEL Bathinda Refinery",
    "18.2 MW is within historical P95 of 24.5 MW"
  ],
  "uncertainties": [
    "Image acquired at 2.2m/pixel during daylight"
  ]
}
```

**Fallback behavior:** If the AI service is unavailable (API keys exhausted, rate limited, etc.), the system falls back to a safe default: classification is set to `uncertain`, confidence is capped at 50%, and the incident is flagged for re-investigation on the next pass. An outage never produces a false high-confidence classification.

---

### Stage 10 — Severity Scoring Engine

**What it does:** Computes a final composite danger score from **0 to 100** for each investigated incident, using multiple weighted factors.

**The four severity tiers:**

| Score Range | Level | What It Means |
|-------------|-------|---------------|
| 0 – 24.9 | **LOW** | Routine thermal activity, no action needed |
| 25.0 – 49.9 | **MEDIUM** | Elevated but not critical, monitor closely |
| 50.0 – 74.9 | **HIGH** | Significant hazard, requires attention |
| 75.0 – 100.0 | **CRITICAL** | Immediate emergency, dispatch response |

**Two scoring models:**

**Model A** — for incidents with historical data:
```
Score = 0.35 × FRP_Score + 0.30 × Historical_Deviation + 0.20 × AI_Score + 0.15 × GIS_Score
```

**Model B** — for new incidents without history:
```
Score = 0.50 × FRP_Score + 0.30 × AI_Score + 0.20 × GIS_Score
```

*Notice Model B gives more weight to FRP and AI, since there's no history to compare against. This ensures Rule 5 (new hotspots get a fair chance) is respected.*

**What each factor measures:**

| Factor | What It Captures | Example |
|--------|-----------------|---------|
| **FRP Score** | How intense the heat is, calibrated to Indian norms | 42 MW → moderate; 150 MW → extreme |
| **Historical Deviation** | How far above normal this reading is for this location | 3× the P95 → severe anomaly |
| **AI Score** | The AI's classification weighted by its confidence | "Industrial fire" at 90% confidence → high score |
| **GIS Score** | How dangerous the location is | Inside a refinery → 95; open field → 15 |

**Emergency overrides** — these force a minimum severity regardless of the formula:

| Situation | Trigger | Forced Level |
|-----------|---------|-------------|
| **Industrial catastrophe** | AI says "industrial fire" with ≥ 80% confidence AND inside a facility | **CRITICAL** (min 80) |
| **Extreme thermal radiation** | FRP ≥ 150 MW with ≥ 80% NASA confidence | **HIGH** (min 55) |
| **Abnormal flare surge** | Current FRP ≥ 3× the location's P95 ceiling | **HIGH** (min 55) |
| **Protected forest wildfire** | AI says "wildfire" AND location is in a protected area | **MEDIUM** (min 30) |

**Routine flare suppression (Rule 4):** If a detection is at a known routine source, operating within its historical P95 envelope, the final score is clamped to ≤ 20 (LOW). No matter how the individual factors add up, a normal refinery flare stays quiet.

---

### Stage 11 — Alert Engine

**What it does:** Decides whether to send an alert notification based on the severity score, and prevents duplicate alerts.

**Rules:**
- Only **HIGH** and **CRITICAL** incidents generate alerts
- If an incident already has an active alert at the same severity → **no new alert** (Rule 6)
- If severity escalates (e.g., HIGH → CRITICAL) → **new escalated alert**, old one is marked superseded
- LOW and MEDIUM incidents are silently suppressed from alerting

**Alert lifecycle:**
```
[New detection] → NEW → ACKNOWLEDGED (by operator) → RESOLVED
                              ↓
                           DISMISSED (marked as false alarm)
```

---

### Stage 12 — Export & Broadcast

**What it does:** Packages up all the results and delivers them:

1. **Console data files** — JSON files that the operator dashboard reads:
   - `incidents.json` — All active incidents with classifications, scores, and coordinates
   - `ambient_firms.json` — Background satellite detections for map context
   - `queue_summary.json` — Summary statistics (counts by severity level, etc.)

2. **SSE broadcast** — Real-time status events pushed to any connected browser, so the operator sees the pipeline's progress live

3. **Severity sweep** — A final pass over all displayable incidents to ensure their severity is up to date (some may have aged or changed since last evaluation)

**Atomic file writes:** Data files are written using a safe two-step process: write to a temporary file first, then atomically rename it to the real filename. This prevents a browser from reading a half-written file.

---

## 6. How Severity Scoring Works

This section provides a deeper look at the math behind the 0–100 severity score.

### FRP Score — Measuring Heat Intensity

The raw FRP (in megawatts) is converted to a 0–100 scale using a **logarithmic** function:

```
FRP_Score = min(100, 25 × log₂(FRP / 4.05 + 1))
```

The division by 4.05 (India's national median) means:
- **4.05 MW** (average detection) → Score of **25** (Low/Medium boundary)
- **13.32 MW** (top 10%) → Score of **52.5** (High territory)
- **20.81 MW** (top 5%) → Score of **65.4** (solidly High)
- **64.49 MW** (top 1%) → Score of **100** (maximum)

*Why logarithmic?* Because heat intensity spans an enormous range (1 MW to 500+ MW). A linear scale would make most detections look identical. A log scale spreads them out proportionally, making the differences between "warm" and "dangerously hot" visually and numerically clear.

### Historical Deviation Score — How Unusual Is This?

Compares the current FRP against the location's historical P95:

| Ratio (Current ÷ P95) | Score | Meaning |
|------------------------|-------|---------|
| ≤ 1.0× | 0–50 | Within normal range |
| 1.0× – 2.0× | 50–80 | Above normal, notable |
| 2.0× – 3.0× | 80–100 | Significantly abnormal |
| ≥ 3.0× | 100 | Catastrophic deviation |

For **routine flares** operating within their P95 envelope, this score is clamped to ≤ 20.

### AI Source Score — What the AI Thinks

```
AI_Score = Base_Rating × AI_Confidence + 50 × (1 - AI_Confidence)
```

Base ratings by classification:

| Classification | Base Rating | Reasoning |
|---------------|------------|-----------|
| `industrial_fire` | 92 | Fires at facilities are very dangerous |
| `wildfire` | 75 | Forest fires are serious |
| `mining_related` | 65 | Mining heat is chronic but notable |
| `uncertain` | 50 | Can't tell — stay neutral |
| `gas_flare` | 38 | Controlled, expected |
| `agricultural_burning` | 32 | Deliberate, temporary |

*Notice: when AI confidence is low, the score regresses toward 50 (neutral) — the system doesn't trust uncertain AI verdicts.*

### GIS Context Score — How Dangerous Is the Location?

| Location Context | Score | Why |
|-----------------|-------|-----|
| Inside a high-hazard facility (refinery, LNG, chemical) | **95** | Explosive materials nearby |
| Inside a general industrial facility | **75** | Industrial risk |
| Inside a protected eco-sensitive area | **85** | Environmental damage |
| Within 500m of a facility | **65** | Close proximity danger |
| Within 1,500m | **45** | Moderate proximity |
| Within 3,000m | **30** | Some proximity |
| Open area (>3 km from anything) | **15** | Low context risk |

---

## 7. How the AI Vision System Works

### The Investigation Package

Before calling the AI, the system assembles a comprehensive package:

1. **The satellite photo** — a high-resolution optical crop with the tactical HUD overlay (crosshair, range rings, scale bar)
2. **Location context** — nearest facility name, type, distance, whether the point is inside it
3. **FIRMS data** — FRP value, confidence, satellite name, sensor
4. **Historical context** — 365-day median FRP, P95 ceiling, persistence rating, number of active days
5. **Administrative context** — state, district

This package gives the AI everything it needs to make an informed classification.

### Key Pool & Fallback System

The system manages multiple API keys for the AI vision service:

- **Rotation:** Keys are used in round-robin fashion to spread API usage
- **Rate limit protection:** If a key gets a "Too Many Requests" (HTTP 429) response, it's quarantined for 60 seconds
- **Auth failure protection:** If a key gets an authentication error (HTTP 401/402/403), it's quarantined for 1 hour
- **Fallback:** If all keys are exhausted or quarantined, the system produces a safe fallback response:
  - Classification: `uncertain`
  - Confidence: capped at 50%
  - `needs_reinvestigation: true`

This ensures the system never crashes from AI unavailability, and never produces a misleading high-confidence result when no AI actually looked at the image.

---

## 8. How the Alert System Works

### When Alerts Fire

```
Severity is LOW or MEDIUM?     → No alert (silently monitored)
Severity is HIGH or CRITICAL?  → Check deduplication rules:
  ├─ No existing alert?        → CREATE new alert ✅
  ├─ Existing alert at same level? → SUPPRESS (no duplicate) ❌
  └─ Existing alert at LOWER level? → ESCALATE ✅
      (Create new alert, mark old one as superseded)
```

### Alert States

| State | Meaning | Can Transition To |
|-------|---------|------------------|
| **NEW** | Just created, unacknowledged | ACKNOWLEDGED, RESOLVED, DISMISSED |
| **ACKNOWLEDGED** | Operator has seen it | RESOLVED, DISMISSED |
| **RESOLVED** | Incident has subsided | *(terminal — no further changes)* |
| **DISMISSED** | Operator marked as false alarm | *(terminal — no further changes)* |

### Escalation Behavior

When an incident escalates (e.g., from HIGH to CRITICAL):
1. A new alert is created at the higher level
2. The old alert gets a `superseded_by` pointer to the new one
3. The old alert is automatically resolved
4. An `ALERT_ESCALATED` event is logged in the audit trail

This means the operator always sees the most current severity assessment, not a stale one.

---

## 9. The Operator Console (Frontend Dashboard)

The operator console is a **tactical web application** that provides a real-time operational picture of all satellite thermal intelligence across India.

### What the Console Shows

The console is organized into five primary operator views via the spotlight navigation bar:

1. **Live Map** — The primary real-time operational picture across India:
   - **Interactive Leaflet Map**: Clean circular incident markers scaled by Fire Radiative Power (FRP) and colored by threat tier (Critical, High, Medium, Low), with category icons (industrial, agricultural, unclassified).
   - **Basemap Switcher**: Instant switching between high-resolution Satellite Imagery and monochromatic Canvas layers.
   - **FRP Difference Filter**: Fast thresholds (`All FRP`, `≥ 2 MW`, and default `≥ 5 MW`) to focus on major thermal emitters.
   - **Priority Incidents List**: Real-time ranked list of top thermal targets by risk score and heat output, with quick filters and marker legend.
   - **Ambient Context**: Optional background layer of raw unclassified satellite hotspots.

2. **Investigations** — Evidence verification workbench:
   - Side-by-side incident cards pairing satellite infrared detections with high-resolution optical imagery analyzed by AI vision.
   - Human operator verification and triage tools.

3. **Industry** — National industrial registry and baseline tracking:
   - Comprehensive facility register categorized across key sectors (Refinery & Flares, Steel & Metals, Coal & Mining, Power Generation, Chemical Plants).
   - Facility search and 365-day normal thermal envelope comparison.

4. **History** — Historical observation archive:
   - Deep search interface querying over 2.89 million historical thermal detections across India.
   - Multi-parameter filtering by state, district, date range, and minimum FRP.

5. **Settings & Incident Dossier**:
   - **Incident Dossier**: Deep-dive inspector drawer displaying optical satellite crops, tactical HUD range rings, AI confidence breakdown, and deterministic 5-factor risk scores.
   - **Settings**: Local operator preferences, persistence toggles, and console controls.

### Technology

- **No build step** — Pure modern HTML5, CSS3, and ES6 JavaScript (zero React, zero Webpack)
- **Map engine:** Leaflet.js with custom GPU-accelerated SVG glyph markers
- **Theme system:** Full Dark and Light theme support with animated toggle and ambient spotlight tracking
- **Responsive design:** Fully optimized for desktop monitors, tablets, and mobile smartphones with slide-out sheets
- **Served by the backend** at `http://localhost:8000/console/`

---

## 10. The Database: What Gets Stored

FIREX v2 uses a relational database (SQLite for development, PostgreSQL for production) with **15 tables**:

| Table | What It Stores | Key Fields |
|-------|---------------|------------|
| `observations` | Raw satellite detections | lat, lon, FRP, satellite, time |
| `incidents` | Tracked physical incidents | code, status, severity, classification |
| `incident_observations` | Links detections to incidents | incident_id, observation_id |
| `industrial_assets` | Known facilities (refineries, plants) | name, type, operator, location |
| `imagery_records` | Satellite photo metadata | incident_id, image URLs |
| `ai_investigations` | AI analysis results | classification, confidence, evidence |
| `severity_assessments` | Danger scores | score (0–100), level, factors |
| `thermal_climatology` | 365-day heat statistics per grid cell | P50, P90, P95, active days |
| `historical_baselines` | Per-location cached baseline summaries | detection counts, reliability |
| `historical_anomalies` | Anomaly detection audit trail | FRP ratio, anomaly score |
| `alert_records` | Sent alerts | severity level, status |
| `incident_events` | Immutable audit log | event type, timestamp, payload |
| `analysis_runs` | Pipeline execution records | status, duration, counts |
| `behavior_profiles` | Time-series behavior rollups | persistence, night ratio |
| `behavior_daily_summaries` | Per-day activity summaries | max FRP, observation count |

### The Climatology Grid

India is divided into a grid of **0.02° × 0.02°** cells (~2.2 km × 2.2 km each). The `thermal_climatology` table stores one row per cell containing the 365-day statistics for that exact ground location. The grid key looks like `GRID_21.16_72.68` — both coordinates are multiples of 0.02.

This table was built from **2,895,064 sovereign Indian FIRMS observations** and contains approximately **247,000 cells** covering India.

---

## 11. How to Run the System

### Prerequisites

- **Python 3.10+** (verified on Python 3.14.6)
- **pip** (Python package manager)

### Quick Start

```bash
# Navigate to the v2 directory
cd v2/

# Install dependencies
pip install -r backend/requirements.txt

# Start the server
python backend/run.py
```

This starts a single server on `http://127.0.0.1:8000` that serves both the API and the operator console.

### Key URLs

| URL | What It Does |
|-----|-------------|
| `http://127.0.0.1:8000/console/` | **Operator Console** — the main dashboard |
| `http://127.0.0.1:8000/docs` | **API Documentation** — interactive Swagger/OpenAPI docs |
| `http://127.0.0.1:8000/health` | **Health Check** — system status and diagnostics |

### Configuration

Secrets and settings are stored in `backend/.env` (see `backend/.env.example` for the template):
- **NASA FIRMS API key** — for pulling satellite data
- **OpenRouter API keys** — for the AI vision model
- **Database URL** — defaults to a local SQLite file

### Command-Line Interface

```bash
# Run the full analysis pipeline
python backend/cli.py pipeline

# Regenerate console data files
python backend/cli.py data

# Run a severity sweep
python backend/cli.py severity-sweep

# Run database migrations
python backend/cli.py migrate
```

### Running Tests

```bash
# From the v2/ directory
python -m pytest tests

# Current: 178 tests across 17+ modules, all passing
```

Tests are fully isolated — they use a throwaway database and temporary directories, so they never touch production data.

---

## 12. Project Directory Map

```
v2/
├── V2_LOGIC_SPECIFICATION.md      ← Technical spec (the authoritative source)
├── V2_LOGIC_EXPLAINED.md          ← This document (beginner-friendly explanation)
├── V2_DEFECT_REPORT.md            ← Known issues and conformance audit
├── README.md                      ← Project setup and directory overview
├── run.py                         ← Convenience launcher script
│
├── backend/                       ← Python backend (FastAPI)
│   ├── app/
│   │   ├── main.py                ← Server entry point, route registration
│   │   ├── api/                   ← REST endpoints and SSE streaming
│   │   ├── core/                  ← Settings, logging, rate limiting
│   │   ├── ingestion/             ← NASA FIRMS data fetching and parsing
│   │   ├── gis/                   ← Geography: boundaries, facilities, mining basins
│   │   ├── incidents/             ← Clustering and incident lifecycle
│   │   ├── behavior/              ← 365-day baselines and anomaly detection
│   │   ├── selection/             ← Priority ranking for AI investigation
│   │   ├── imagery/               ← Satellite photo cropping and HUD overlay
│   │   ├── intelligence/          ← AI vision integration and prompt rules
│   │   ├── severity/              ← Danger scoring engine
│   │   ├── alerts/                ← Alert deduplication and escalation
│   │   ├── orchestration/         ← Pipeline runner, SSE broadcaster, mutex
│   │   └── storage/               ← Database models and connections
│   ├── scripts/                   ← Offline data processing scripts
│   ├── data/                      ← Database file and imagery cache
│   └── requirements.txt           ← Python dependencies
│
├── frontend/                      ← Operator console (HTML/CSS/JS)
│   ├── index.html                 ← Main dashboard page
│   ├── js/                        ← Application logic, map, rendering
│   ├── styles/                    ← CSS (tokens, components, layout)
│   └── data/                      ← JSON feed files (written by pipeline)
│
├── tests/                         ← 178 automated tests
│   ├── conftest.py                ← Test isolation setup
│   ├── fixtures/                  ← Test data and reference values
│   └── test_stage*.py             ← Tests organized by subsystem
│
├── docs/                          ← Stage verification reports
└── md/                            ← SIH 2026 project blueprint
```

---

## 13. Frequently Asked Questions

### "How often does the pipeline run?"

The pipeline can be triggered three ways:
1. **API call** — `POST /api/analysis/run` starts a synchronous run
2. **Cron schedule** — Can be configured to run automatically at intervals
3. **CLI command** — `python backend/cli.py pipeline` runs it once from the terminal

Each run takes seconds to complete. Only one run can execute at a time (Stage 1 ensures this).

### "What happens if the AI is unavailable?"

The system falls back to a safe default: classification is set to `uncertain` at ≤ 50% confidence, and the incident is flagged for re-investigation next time. The system never crashes and never produces a false high-confidence result from a failed AI call.

### "Can this detect fires in real time?"

Nearly. There's inherent latency from the satellite's orbital period (each satellite passes over India a few times per day), NASA's processing time (minutes to hours), and the pipeline's execution time (seconds). In practice, a fire might be detected within 1–4 hours of ignition, depending on satellite passes.

### "What satellites does FIREX use?"

- **VIIRS** (Visible Infrared Imaging Radiometer Suite) on Suomi NPP and NOAA-20 — the primary sensor, with ~375m ground resolution
- **MODIS** (Moderate Resolution Imaging Spectroradiometer) on Terra and Aqua — an older but still useful sensor with ~1km resolution

Both detect heat in the mid-infrared band (around 4 μm wavelength).

### "Why not just sum up all the FRP values?"

Because it's physically misleading. Satellite pixels often overlap, and multiple pixels might be seeing the same fire from slightly different angles or at slightly different times. If a single 10 MW fire is captured by 5 overlapping pixels, reporting "50 MW" would be a fivefold exaggeration. The **maximum** FRP across pixels is the honest representation of peak intensity.

### "What's the difference between V2_LOGIC_SPECIFICATION.md and this document?"

The **Specification** is the authoritative technical reference — it contains precise mathematical formulas, exact line-number references to source code, detailed divergence notes, and is written for engineers and AI agents who need to modify the system. **This document** explains the same system in plain language for anyone who wants to understand what FIREX does and how it works, without needing to read code or understand advanced mathematics.

### "What is SIH 2026?"

**Smart India Hackathon 2026** — a national innovation competition organized by the Government of India. FIREX v2 was built for **Problem Statement 162**, which was set by the **NTRO** (National Technical Research Organisation), India's technical intelligence agency. The problem asked for an AI-powered system to distinguish between routine industrial thermal activity and genuine emergencies using satellite data.

### "Is this a production system?"

FIREX v2 is a working prototype with production-grade architecture — 178 passing tests, formal invariants, audit trails, rate limiting, and atomic data exports. It processes real NASA satellite data and produces real classifications. For full production deployment, it would need operational hardening (monitoring, HA deployment, dedicated credentials for all AI providers, etc.).

---

> **For the authoritative technical specification with mathematical formulas, code references, and schema definitions, see [V2_LOGIC_SPECIFICATION.md](V2_LOGIC_SPECIFICATION.md).**
