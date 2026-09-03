# SIH 2026 --- PS 162 Project Master Brief

## AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data

> **Purpose of this document:** This is the single source of truth for
> any AI assistant, developer, designer, or team member working on PS
> 162. Read this file before proposing architecture, writing code,
> changing the UI, or adding features.

------------------------------------------------------------------------

## 1. Problem Statement

### Official PS

-   **PS Number:** SIH26162
-   **PS Index:** 162
-   **Category:** Software
-   **Theme:** Miscellaneous
-   **Organization:** National Technical Research Organisation (NTRO)
-   **Submission deadline listed in the catalogue:** 20 September 2026
-   **Current catalogue idea count when this project was reviewed:**
    0/500
-   **NASA FIRMS dataset/resource link in the catalogue:**
    `firms.modaps.eosdis.nasa.gov/map`

### Official problem statement summary

Industrial facilities generate thermal signatures visible from space.
Existing satellite fire-monitoring systems such as NASA FIRMS detect
thermal anomalies, but do not by themselves reliably distinguish among:

-   industrial fires
-   gas flares
-   agricultural burning
-   mining activity
-   wildfires
-   persistent/other thermal sources

The required solution is an **AI-enabled geospatial system** that
integrates:

1.  thermal anomaly data,
2.  land-cover information,
3.  industrial infrastructure databases,
4.  satellite imagery,

to identify, classify, and monitor industrial fires and persistent
thermal sources.

### Expected deliverables from the PS

1.  Classification and segregation of industrial fires from forest fires
    and other natural fires.
2.  A GIS-based solution for storing and visualizing outputs as overlays
    on maps.

------------------------------------------------------------------------

# 2. Project Vision

## Working product concept

**FIREX --- AI Thermal Intelligence**

The product should feel like a **geospatial intelligence / incident
investigation platform**, not simply a fire map.

The central question the UI should answer is:

> **Where is the suspicious thermal event, what is it likely to be, how
> serious is it, and why does the system believe that?**

The product should combine:

``` text
NASA FIRMS
    ↓
Thermal anomaly
    ↓
Satellite imagery
    ↓
AI visual analysis
    ↓
Historical behavior
    ↓
Industrial / land-cover context
    ↓
Risk assessment
    ↓
GIS investigation dashboard
```

------------------------------------------------------------------------

# 3. Core Design Principle

## Do not claim that FIRMS directly detects an "industrial fire"

FIRMS provides satellite-derived **thermal anomaly / active-fire
detections**.

Our system performs the higher-level interpretation:

``` text
FIRMS says:
"Something thermally abnormal was detected here."

Our system says:
"This is most consistent with an industrial fire / gas flare /
wildfire / agricultural burn / other source / uncertain."
```

This distinction is important for scientific credibility.

The AI must be allowed to return:

**UNCERTAIN / NOT VISUALLY CONFIRMABLE**

when the available evidence is insufficient.

------------------------------------------------------------------------

# 4. Proposed Product

## Main modules

### A. Overview Dashboard

High-level operational summary:

-   total detections
-   critical events
-   high-risk events
-   industrial candidates
-   wildfires
-   gas flares
-   uncertain cases
-   recent events

### B. Live / Historical GIS Map

Display thermal detections as map overlays.

Suggested visual hierarchy:

-   🔴 Critical
-   🟠 High
-   🟡 Medium
-   ⚪ Low / uncertain

Do not show every detection as an identical red dot.

### C. Incident Investigation

The most important screen.

When a user clicks a detection:

-   satellite image
-   FIRMS metadata
-   AI classification
-   AI confidence
-   evidence/reasoning
-   nearest industrial facility
-   historical detections
-   thermal intensity
-   risk score
-   uncertainty
-   investigation status

### D. Historical / Time-Series View

Compare current and previous observations.

Possible outputs:

-   persistent thermal source
-   increasing activity
-   decreasing activity
-   isolated anomaly
-   recurring anomaly

### E. Industrial Intelligence

Show suspicious activity around:

-   refineries
-   petrochemical facilities
-   thermal power plants
-   steel plants
-   mines
-   LNG terminals
-   other industrial facilities

### F. Analytics

Charts for:

-   event counts
-   classifications
-   FRP distribution
-   high-risk locations
-   persistent hotspots
-   industrial facility activity

### G. Optional 3D Investigation

Use a 3D geospatial view for **showcasing and investigation**, not as
the primary AI imagery source.

Possible stack:

-   CesiumJS
-   Google Photorealistic 3D Tiles

The 3D view can fly to an incident and show the FIRMS coordinate, nearby
facility, and risk context.

------------------------------------------------------------------------

# 5. High-Level Architecture

``` text
                         FIREX
                           │
            ┌──────────────┴──────────────┐
            │                             │
       DATA LAYER                    PRESENTATION
            │                             │
     ┌──────┼──────────┐          ┌───────┼────────┐
     │      │          │          │       │        │
   FIRMS  Satellite   OSM       2D GIS  Incident  3D
     │      │          │          │       │        │
     └──────┼──────────┘          └───────┼────────┘
            │                             │
            ▼                             │
       Feature/context                    │
            │                             │
            ▼                             │
       Vision AI ────────────────→ Results
            │
            ▼
      Risk / decision engine
            │
            ▼
        PostgreSQL/PostGIS
```

------------------------------------------------------------------------

# 6. Development Philosophy

## Build cautiously and checkpoint-by-checkpoint

Do **not** build the entire application at once.

The project is intentionally divided into sections.

**Only proceed when the current section works.**

``` text
Section 1  → FIRMS
Section 2  → Detection selection/storage
Section 3  → Satellite imagery
Section 4  → AI vision
Section 5  → End-to-end pipeline
Section 6  → Basic map
Section 7  → Investigation UI
Section 8  → Historical intelligence
Section 9  → Industrial context
Section 10 → Risk engine
Section 11 → Multi-AI verification
Section 12 → Final dashboard
Section 13 → Online deployment
Section 14 → 3D showcase
```

------------------------------------------------------------------------

# 7. SECTION 1 --- NASA FIRMS

## Goal

Prove that the system can reliably obtain real FIRMS thermal-anomaly
data.

### First deliverable

A tiny Python program that:

``` text
NASA FIRMS
    ↓
Python
    ↓
print detections
```

### Expected useful fields

Depending on the FIRMS product, expect fields such as:

-   latitude
-   longitude
-   brightness temperature
-   scan
-   track
-   acquisition date
-   acquisition time
-   satellite
-   instrument
-   confidence
-   version
-   FRP
-   day/night

For VIIRS, the exact confidence representation should be respected
rather than assuming it is always a 0--100 score.

### Test checklist

-   [ ] FIRMS MAP_KEY works
-   [ ] Real detections are returned
-   [ ] Coordinates are valid
-   [ ] FRP is present
-   [ ] acquisition date/time is understood
-   [ ] satellite is known
-   [ ] confidence representation is understood
-   [ ] raw response is saved for debugging

### STOP CONDITION

Do not build satellite retrieval or AI integration until Section 1
works.

------------------------------------------------------------------------

# 8. SECTION 2 --- Select Test Detections

Start with **5--10 real detections**, not hundreds.

Try to include different contexts:

1.  industrial area
2.  forest
3.  agricultural area
4.  likely flare / persistent source
5.  uncertain/random source

Store:

``` text
id
latitude
longitude
acq_date
acq_time
satellite
instrument
frp
confidence
source/product
```

### Test

Every selected coordinate should be valid and manually inspectable.

### STOP CONDITION

If the selected records are unreliable or duplicated, fix this before
moving forward.

------------------------------------------------------------------------

# 9. SECTION 3 --- Satellite Imagery

## Goal

Determine whether a usable image can actually be obtained around a FIRMS
detection.

This is one of the highest-risk assumptions in the project.

For one detection:

``` text
FIRMS coordinate
      ↓
Find suitable satellite scene
      ↓
Crop around detection
      ↓
Save image
```

Example:

``` text
case_001/
    firms.json
    satellite.jpg
```

### Manually inspect the image

Check:

-   correct geographic area
-   reasonable spatial detail
-   acceptable cloud coverage
-   sensible acquisition date
-   image centered around the detection
-   whether useful visual evidence exists

### Important limitation

A FIRMS thermal anomaly may not be visually obvious in an RGB/optical
image because:

-   the hotspot may be too small
-   clouds may obscure the area
-   smoke may obscure the source
-   the source may be industrial heat rather than visible flames
-   imagery may not be temporally aligned

### STOP CONDITION

If images are consistently unusable, **change the imagery strategy
before adding AI**.

------------------------------------------------------------------------

# 10. SECTION 4 --- Vision AI

## Goal

Test whether a vision model can meaningfully interpret one real
satellite image.

Start with one provider.

Preferred initial candidates:

1.  Gemini
2.  Groq/Qwen vision
3.  OpenRouter vision model
4.  Mistral multimodal model
5.  Claude or another provider if available

### Input

Send:

``` text
SATELLITE IMAGE

+

FIRMS metadata:
Latitude
Longitude
FRP
Brightness
Confidence
Satellite
Date/time
```

### Requested classes

``` text
industrial_fire
gas_flare
wildfire
agricultural_burning
mining_or_other_thermal_source
uncertain
```

### Required response shape

Prefer strict JSON:

``` json
{
  "classification": "industrial_fire",
  "confidence": 0.87,
  "alternative_classification": "gas_flare",
  "visual_evidence": [
    "industrial structures visible",
    "concentrated thermal/visual anomaly"
  ],
  "uncertainty": "medium"
}
```

### Prompt principle

The model must not be told that FIRMS has already confirmed a fire.

It should be told that FIRMS detected a thermal anomaly.

It must be able to say:

``` text
uncertain
```

### Test

Run at least 5 cases.

The objective is not initially to prove perfect accuracy.

The objective is:

> **Does the approach produce useful, defensible classifications often
> enough to justify building the full system?**

------------------------------------------------------------------------

# 11. SECTION 5 --- First End-to-End Pipeline

Connect the first four sections:

``` text
FIRMS
 ↓
Detection
 ↓
Coordinates
 ↓
Satellite image
 ↓
AI
 ↓
Structured classification
```

Example CLI output:

``` text
========================================
FIREX TEST
========================================

FIRMS
Lat: XX.XXXX
Lon: XX.XXXX
FRP: XX MW
Confidence: nominal
Satellite: NOAA-21

Satellite image: SUCCESS

AI:
Classification: industrial_fire
Confidence: 0.89

Status: SUCCESS
========================================
```

### Test

Run 5 cases without manually changing code between cases.

### STOP CONDITION

If the pipeline works on 5 cases, proceed to frontend.

------------------------------------------------------------------------

# 12. SECTION 6 --- Basic GIS Map

## Goal

Create a simple frontend map.

Do not make the final polished UI yet.

``` text
Map
 ├── detection
 ├── detection
 ├── detection
 └── detection
```

Clicking a marker should show:

-   incident ID
-   lat/lon
-   FRP
-   confidence
-   acquisition time
-   satellite

### Suggested frontend

-   React
-   Vite
-   MapLibre GL JS or Leaflet

### STOP CONDITION

Verify that coordinates shown on the frontend correspond to FIRMS data.

------------------------------------------------------------------------

# 13. SECTION 7 --- Incident Investigation Screen

This is the first major SIH-facing screen.

Suggested layout:

``` text
┌─────────────────────────┬─────────────────────────┐
│                         │ AI ASSESSMENT           │
│     SATELLITE IMAGE     │                         │
│                         │ Industrial Fire         │
│          🔥             │ 89%                     │
│                         │                         │
├─────────────────────────┴─────────────────────────┤
│ FIRMS METADATA                                    │
│ FRP | Confidence | Satellite | Date | Time        │
└───────────────────────────────────────────────────┘
```

Add:

-   classification
-   confidence
-   evidence
-   uncertainty
-   FIRMS data
-   image
-   nearby facility

### Goal

A non-technical judge should understand the event within a few seconds.

------------------------------------------------------------------------

# 14. SECTION 8 --- Historical Intelligence

For a selected coordinate/cluster, retrieve historical FIRMS
observations.

Calculate:

-   detection count
-   first detection
-   latest detection
-   average FRP
-   maximum FRP
-   persistence
-   recent trend

Example:

``` text
14-day history

Detections: 17
Average FRP: 31 MW
Maximum FRP: 72 MW
Persistence: HIGH
Trend: INCREASING
```

## UI feature

Add a time slider:

``` text
14 days ago ─────────────● Today
```

Optional comparison:

``` text
BEFORE                 CURRENT
[image]                [image]
FRP: 12 MW             FRP: 61 MW
```

------------------------------------------------------------------------

# 15. SECTION 9 --- Industrial and Land-Cover Context

The PS explicitly expects integration of industrial and land-cover
information.

Use geospatial context such as:

-   refinery
-   power plant
-   steel plant
-   mine
-   LNG terminal
-   chemical facility
-   forest
-   agricultural area
-   urban area

For each incident calculate distances or spatial relationships.

Example:

``` text
Nearest industrial facility
Oil refinery — 280 m

Forest — 4.2 km
Agriculture — 2.1 km
```

OpenStreetMap can be a useful source for mapped infrastructure, subject
to its data/licensing requirements.

------------------------------------------------------------------------

# 16. SECTION 10 --- Risk / Priority Engine

Do not let an LLM alone determine operational risk.

Use transparent, deterministic features alongside AI.

Possible inputs:

``` text
AI classification/confidence
FIRMS confidence
FRP
historical persistence
trend
industrial proximity
land-cover compatibility
```

Example conceptual score:

``` text
AI evidence                 40%
FIRMS confidence            20%
FRP                         15%
Industrial proximity        10%
Historical persistence      10%
Land-cover compatibility     5%
```

These percentages are **initial design placeholders**, not scientific
truth.

Calibrate them after collecting test cases.

Output:

``` text
0–30    LOW
31–60   MEDIUM
61–80   HIGH
81–100  CRITICAL
```

Always show the reasons behind the score.

------------------------------------------------------------------------

# 17. SECTION 11 --- Optional Multi-AI Verification

Use multiple models only after the single-model pipeline works.

Example:

``` text
                 Satellite image
                       ↓
              ┌────────┴────────┐
              ↓                 ↓
           Gemini             Groq
              ↓                 ↓
        Industrial 89%    Industrial 92%
              └────────┬────────┘
                       ↓
                  Consensus
```

If they disagree:

``` text
UNCERTAIN
Human verification recommended
```

This is preferable to forcing a false certainty.

------------------------------------------------------------------------

# 18. SECTION 12 --- Final Frontend

## Navigation

Keep the application focused:

``` text
🔥 Overview
🗺 Live Map
🔍 Investigations
🏭 Industrial
📊 Analytics
⚙ Settings
```

## Overview

Show:

-   total detections
-   critical events
-   high-risk events
-   industrial candidates
-   wildfires
-   flares
-   uncertain events

## Live Map

Central map with filters:

``` text
[All] [Critical] [Industrial] [Wildfire] [Flare] [Uncertain]
```

## Investigation

Show:

-   image
-   AI classification
-   confidence
-   evidence
-   FIRMS data
-   historical behavior
-   industrial context
-   risk score

## Analytics

Show:

-   detections over time
-   classification distribution
-   high-risk locations
-   persistent sources
-   industrial-facility activity

------------------------------------------------------------------------

# 19. 3D Showcase

## Purpose

3D is a **presentation/investigation layer**, not a replacement for the
actual satellite evidence.

Potential architecture:

``` text
React
  ↓
CesiumJS
  ↓
Google Photorealistic 3D Tiles
```

Use 3D to:

-   fly to the incident
-   show nearby industrial infrastructure
-   show the FIRMS coordinate
-   show a risk radius/overlay
-   visually demonstrate the context

Do not extract or train AI on Google 3D content.

Do not treat the Google 3D view as the scientific evidence for the fire
classification.

------------------------------------------------------------------------

# 20. Online Deployment

## Initial deployment

The system can be deployed online after the first stable pipeline.

Suggested simple architecture:

``` text
React frontend
      ↓
HTTPS
      ↓
FastAPI backend
      ↓
NASA FIRMS
Satellite imagery
AI provider
Database
```

## Wasmer

The team already has access to Wasmer Pro, but the **free/Hobby tier
should be used for initial validation if sufficient**.

Use server-side environment variables for API keys.

Never expose:

-   FIRMS MAP_KEY
-   Gemini API key
-   Groq API key
-   other provider secrets

inside the frontend bundle.

### Initial cloud milestone

Deploy:

``` text
FIRMS → backend → AI → frontend
```

before adding all advanced features.

------------------------------------------------------------------------

# 21. Data Model

A future PostgreSQL/PostGIS schema can include:

## fire_detections

``` text
id
source
source_record_id
latitude
longitude
geometry
acquisition_date
acquisition_time
satellite
instrument
confidence_raw
confidence_normalized
brightness_ti4
brightness_ti5
frp
daynight
created_at
```

## imagery

``` text
id
detection_id
provider
acquisition_date
image_uri
cloud_score
resolution
bbox
created_at
```

## ai_analyses

``` text
id
detection_id
provider
model
classification
confidence
alternative_classification
evidence_json
uncertainty
created_at
```

## facilities

``` text
id
name
type
geometry
source
```

## risk_assessments

``` text
id
detection_id
risk_score
risk_level
factors_json
created_at
```

------------------------------------------------------------------------

# 22. API Contracts

Keep AI provider code behind a common interface.

Conceptually:

``` text
analyze_image(
    image,
    firms_metadata,
    provider
) -> AnalysisResult
```

This allows:

``` text
Gemini
Groq
OpenRouter
Claude
```

to be swapped without rebuilding the application.

Expected normalized response:

``` json
{
  "classification": "industrial_fire",
  "confidence": 0.89,
  "alternative_classification": "gas_flare",
  "visual_evidence": [],
  "uncertainty": "medium",
  "model": "..."
}
```

------------------------------------------------------------------------

# 23. AI Provider Strategy

## Primary candidate

### Gemini

Use as the first provider to test because its current API supports
multimodal image input and Google lists free-tier pricing for eligible
models.

## Secondary

### Groq / Qwen vision

Useful for fast vision inference and structured output.

## Fallback

### OpenRouter

Useful as a model-switching layer and fallback.

## Optional

### Claude

Useful for high-quality comparison if an affordable/available API route
is available.

## AWS Rekognition

Use primarily as supplementary computer vision rather than assuming its
generic labels alone solve industrial-fire classification.

Possible use:

``` text
AWS:
Factory
Smoke
Building
Industrial structure

LLM:
Industrial fire vs flare vs other
```

------------------------------------------------------------------------

# 24. Important API / Data Considerations

## NASA FIRMS

A free FIRMS MAP_KEY is required for API/web services.

Current FIRMS documentation lists a limit of:

**5,000 transactions per 10-minute interval**

and notes that larger requests can consume multiple transactions.

The Area API supports bounding-box queries and a 1--5 day range.

For this project, query only the target geography instead of downloading
global data unnecessarily.

### Satellite source preference

FIRMS currently provides VIIRS NOAA-20 and NOAA-21 products among its
available sources.

NASA currently warns about Suomi-NPP data received after 9 March 2026
and says Suomi-NPP product delivery is scheduled to cease on 1 November
2026. Therefore, the project should prioritize NOAA-20/NOAA-21 rather
than depending on Suomi-NPP.

------------------------------------------------------------------------

# 25. Image Acquisition Principle

Do not make Google Maps imagery the core AI training/analysis
dependency.

Preferred approach:

``` text
FIRMS
 ↓
Open/appropriate satellite imagery
 ↓
AI
```

Google Maps/Google 3D can be used for visualization where permitted by
the relevant API terms.

The image source must be documented for every analyzed image.

Store:

-   source
-   date
-   resolution
-   bounding box
-   cloud/quality metadata when available

------------------------------------------------------------------------

# 26. Avoid the "AI says fire" trap

Bad product:

``` text
FIRMS → image → LLM says fire
```

Better product:

``` text
FIRMS thermal evidence
+
Satellite visual evidence
+
Historical behavior
+
Industrial proximity
+
Land-cover context
+
AI classification
+
Transparent risk engine
```

This makes the system much closer to the actual PS.

------------------------------------------------------------------------

# 27. Important Frontend UX

## Main incident card

``` text
INCIDENT #1842

🔴 CRITICAL

Industrial Fire
91%

FRP
61.3 MW

FIRMS Confidence
Nominal

Nearest Facility
Oil Refinery — 280 m

Persistence
HIGH

[ INVESTIGATE ]
```

## "Why suspicious?"

Show the factors:

``` text
+ High thermal intensity
+ Near industrial facility
+ Persistent detections
+ AI classification
+ High FIRMS confidence
```

## AI disagreement

If models disagree:

``` text
⚠ AI DISAGREEMENT

Gemini: Gas flare — 62%
Groq: Industrial fire — 71%

Recommendation:
Human verification
```

------------------------------------------------------------------------

# 28. What NOT to Build Early

Do not begin with:

-   mobile app
-   complicated authentication
-   huge database
-   local ML training
-   custom deep-learning model
-   chatbot
-   fancy animations
-   3D map
-   live alert infrastructure
-   global-scale processing
-   hundreds of AI calls

First prove:

``` text
1 FIRMS point
→ 1 usable image
→ 1 AI result
```

Then scale:

``` text
1 → 5 → 20 → 50 → 100
```

------------------------------------------------------------------------

# 29. Development Checkpoints

## Checkpoint 1

### FIRMS works

-   [ ] API key
-   [ ] real detection
-   [ ] coordinates
-   [ ] metadata

## Checkpoint 2

### Image works

-   [ ] correct location
-   [ ] usable image
-   [ ] reasonable date
-   [ ] acceptable quality

## Checkpoint 3

### AI works

-   [ ] image accepted
-   [ ] classification
-   [ ] JSON
-   [ ] uncertainty
-   [ ] evidence

## Checkpoint 4

### Pipeline works

``` text
FIRMS → image → AI
```

## Checkpoint 5

### Map works

## Checkpoint 6

### Investigation works

## Checkpoint 7

### Historical analysis works

## Checkpoint 8

### Industrial context works

## Checkpoint 9

### Risk engine works

## Checkpoint 10

### Final UI works

## Checkpoint 11

### Online deployment works

## Checkpoint 12

### 3D showcase works

------------------------------------------------------------------------

# 30. Suggested Team Split

For 3--4 people:

## Person 1 --- Data/backend

-   FIRMS
-   imagery acquisition
-   geospatial processing
-   database

## Person 2 --- AI

-   vision APIs
-   prompts
-   structured outputs
-   evaluation
-   provider fallback

## Person 3 --- Frontend/GIS

-   map
-   dashboard
-   investigation screen
-   analytics
-   3D integration later

## Person 4 --- Integration/research

-   OSM/industrial data
-   testing
-   validation dataset
-   documentation
-   presentation/demo

Everyone should agree on API contracts early.

------------------------------------------------------------------------

# 31. Evaluation Strategy

Do not claim accuracy without ground truth.

Create a small manually reviewed test set.

For each case:

``` text
case_id
FIRMS data
image
human interpretation
AI result
AI confidence
correct/incorrect
notes
```

Track:

-   classification accuracy
-   uncertain rate
-   false industrial-fire rate
-   false wildfire rate
-   flare confusion
-   cloud/poor-image failure rate
-   AI provider disagreement

The goal is to understand failure modes, not just maximize a single
accuracy number.

------------------------------------------------------------------------

# 32. Demo Story

The ideal SIH demonstration:

### Step 1

Open Overview.

> "The system has detected 127 thermal anomalies."

### Step 2

Filter to critical.

> "Eight events require investigation."

### Step 3

Select an industrial candidate.

### Step 4

Open Investigation.

Show:

-   FIRMS metadata
-   satellite image
-   AI classification
-   confidence

### Step 5

Open historical comparison.

> "The event has persisted and increased in thermal intensity."

### Step 6

Show industrial context.

> "The event is 280 m from an oil refinery."

### Step 7

Show risk explanation.

> "91/100 --- Critical."

### Step 8

Optional 3D view.

Fly to the facility and show the incident context.

This should take approximately 2--3 minutes.

------------------------------------------------------------------------

# 33. First-Day Objective

Do **not** start with React.

The first milestone is:

``` text
ONE real FIRMS detection
        ↓
coordinates
        ↓
usable satellite image
        ↓
vision AI
        ↓
structured classification
```

If this works, the concept is technically promising.

If it fails, identify which link failed before building more software.

------------------------------------------------------------------------

# 34. Golden Rule for Any AI Assistant Working on This Project

Before changing architecture or writing code:

1.  Read this document.
2.  Identify the current checkpoint.
3.  Do not skip checkpoints.
4.  Do not invent API fields.
5.  Do not assume satellite imagery is always available.
6.  Do not assume a thermal anomaly is a confirmed fire.
7.  Preserve uncertainty.
8.  Keep API keys server-side.
9.  Prefer small tests before large-scale processing.
10. Do not replace the core geospatial reasoning with an LLM.
11. Keep AI providers replaceable.
12. Do not add features merely because they look impressive; they must
    support the PS.
13. Every major feature should have a measurable test.
14. If a section fails, stop and fix it before moving forward.

------------------------------------------------------------------------

# 35. Current Technology Direction

## Initial stack

``` text
Frontend:
React + Vite
MapLibre GL JS / Leaflet

Backend:
Python + FastAPI

Data:
SQLite initially
PostgreSQL + PostGIS later

FIRMS:
NASA FIRMS API

Satellite imagery:
Open/appropriate satellite imagery source

AI:
Gemini first
Groq/Qwen as alternative
OpenRouter as fallback
Claude optional

Industrial/geospatial:
OSM + suitable open datasets

3D:
CesiumJS + Google Photorealistic 3D Tiles

Deployment:
Wasmer initially
```

This stack is intentionally flexible. Do not lock every technology
before Sections 1--4 are validated.

------------------------------------------------------------------------

# 36. Definition of a Successful MVP

The MVP is successful when a user can:

1.  open the online application,
2.  see FIRMS thermal anomalies on a map,
3.  select an anomaly,
4.  inspect satellite imagery,
5.  see an AI classification,
6.  see the supporting FIRMS metadata,
7.  see nearby industrial/geospatial context,
8.  see historical activity,
9.  see an explainable risk score,
10. understand why the event was prioritized.

The MVP does **not** need:

-   perfect classification
-   global coverage
-   autonomous emergency response
-   local ML
-   a mobile app
-   perfect real-time imagery
-   a huge training dataset

------------------------------------------------------------------------

# 37. Final Product Definition

**FIREX is an AI-assisted geospatial intelligence platform that
transforms NASA FIRMS thermal anomaly detections into explainable
industrial-fire and persistent-thermal-source investigations by
combining satellite imagery, historical thermal behavior, land-cover
information, industrial infrastructure, and multimodal AI.**

The differentiator is not merely:

> "We use AI to detect fires."

The differentiator is:

> **"We take a satellite-detected thermal anomaly and build an
> evidence-backed investigation around it."**
