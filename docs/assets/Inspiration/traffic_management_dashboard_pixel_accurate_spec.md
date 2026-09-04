# Traffic Management Dashboard — Pixel-Accurate UI Specification

> **Purpose:** Recreate the supplied dashboard screenshot as closely as possible, preserving the **exact visual language, layout, blur, glassmorphism, spacing, typography hierarchy, borders, shadows, icon treatment, map treatment, and color system**.
>
> **Only the DATA may change.** All visual/design decisions in this document are immutable unless explicitly required for responsive behavior.
>
> **Reference screenshot:** 1448 × 1086 px.

---

## 1. NON-NEGOTIABLE VISUAL CONTRACT

The implementation must visually match the supplied reference.

### Do not change

- Overall dark / near-black appearance
- Glassmorphism / frosted-glass treatment
- Blur intensity
- Panel translucency
- Border opacity
- Corner radii
- Shadows
- Typography scale and weights
- Spacing rhythm
- Card proportions
- Navigation structure
- Icon sizing / placement
- Chart geometry and visual treatment
- Map panel position, crop behavior, overlays, and controls
- Warning/alert panel styling
- Green / amber / red semantic colors
- Bottom metric panels
- Left vehicle cards
- General density of information
- Hover/active styling language

### Allowed to change

Only runtime data:

- Vehicle IDs
- Vehicle names / models
- Vehicle status
- Fuel / battery values
- Passenger load
- Passenger counts
- Route names
- Depot / terminal labels
- Schedule deviations
- Traffic incidents
- Weather values
- Alert text
- Map marker positions
- Route polylines
- Chart values
- Timestamps
- Analytics values
- Any other Firebase-sourced business data

**Do not redesign the UI to fit new data.** Data must fit the existing visual containers.

---

# 2. RECOMMENDED IMPLEMENTATION

Use a modern web stack such as:

- React
- TypeScript
- Vite / Next.js
- Tailwind CSS or CSS Modules
- Lucide / Phosphor / another thin-line icon set
- Recharts / SVG for charts
- Mapbox GL JS / MapLibre GL JS / Google Maps JS for the map
- Firebase Web SDK

The exact framework is not important. The rendered result is.

---

# 3. PAGE COMPOSITION

The full page is a single high-density dashboard.

Reference viewport:

```text
1448 × 1086
```

The page contains:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ top navigation                                                              │
├───────────────┬───────────────────────────────────────────────┬─────────────┤
│ left sidebar  │                    map area                   │ alert panel  │
│               │                                               │ (overlay)    │
│ filters       │                                               │              │
│ status cards  │                                               │              │
│ efficiency    │                                               │              │
│ vehicle cards │                                               │              │
├───────────────┴──────────────────────┬────────────────────────┴─────────────┤
│                                      │                                       │
│ Schedule Offset                      │ Total Passengers                      │
│                                      │                                       │
└──────────────────────────────────────┴───────────────────────────────────────┘
```

The map occupies the visual center and is the dominant area.

---

# 4. GLOBAL CANVAS

## Background

Use a very dark neutral background.

Approximate base:

```css
--page-bg: #050708;
```

Avoid pure white and avoid a fully black `#000` UI.

The screenshot contains multiple extremely dark neutral surfaces rather than one flat black background.

## Base text colors

```css
--text-primary: rgba(255,255,255,0.92);
--text-secondary: rgba(255,255,255,0.62);
--text-muted: rgba(255,255,255,0.38);
--text-faint: rgba(255,255,255,0.24);
```

Do not use bright solid white for normal dashboard text.

---

# 5. GLASSMORPHISM SYSTEM

This is one of the most important characteristics of the reference.

## General glass surface

Use a translucent dark layer over the background/map:

```css
background:
  linear-gradient(
    135deg,
    rgba(28,31,32,0.70),
    rgba(10,12,13,0.58)
  );

backdrop-filter: blur(18px) saturate(115%);
-webkit-backdrop-filter: blur(18px) saturate(115%);
```

For stronger glass panels:

```css
backdrop-filter: blur(24px) saturate(120%);
```

Do not use a flat opaque `background: #111`.

## Glass border

Use extremely subtle borders:

```css
border: 1px solid rgba(255,255,255,0.055);
```

Some elevated panels can use:

```css
border: 1px solid rgba(255,255,255,0.075);
```

Borders should be visible only enough to separate adjacent glass surfaces.

## Glass shadow

Use soft, wide shadows:

```css
box-shadow:
  0 18px 45px rgba(0,0,0,0.28),
  inset 0 1px 0 rgba(255,255,255,0.025);
```

Avoid sharp drop shadows.

## Highlight layer

For important cards:

```css
background-image:
  linear-gradient(
    180deg,
    rgba(255,255,255,0.028),
    rgba(255,255,255,0)
  );
```

---

# 6. CORNER RADIUS SYSTEM

Use a consistent rounded language.

Suggested tokens:

```css
--radius-sm: 10px;
--radius-md: 14px;
--radius-lg: 18px;
--radius-xl: 22px;
```

Approximate screenshot usage:

- Small controls: 9–12px
- Status cards: 12–16px
- Vehicle cards: 17–20px
- Main panels: 18–22px
- Large bottom cards: 18–22px

Never use sharp rectangular panels.

---

# 7. TOP NAVIGATION

The top navigation is a horizontal glass/dark bar integrated into the page rather than looking like a separate bright header.

Approximate structure:

```text
[logo]   [Live Map]  Fleet  Routes  Analytics  Maintenance  Alerts  Reports  Settings                [search] [utility] [bell] [avatar]
```

## Logo

Top-left.

Use a small abstract white diagonal-line mark.

Do not place a large colored logo.

## Navigation

Active item:

```text
Live Map
```

Use a rounded pill / soft dark glass capsule.

Approximate active styling:

```css
background: rgba(255,255,255,0.065);
border: 1px solid rgba(255,255,255,0.035);
box-shadow: 0 8px 24px rgba(0,0,0,0.18);
```

Inactive navigation:

```css
color: rgba(255,255,255,0.45);
```

Active label:

```css
color: rgba(255,255,255,0.90);
```

## Right controls

Three small utility controls:

- Search
- Small circular utility / status icon
- Notification bell with tiny red unread dot
- Circular profile avatar

Keep icons thin and understated.

---

# 8. LEFT SIDEBAR

The left panel is a vertically stacked dashboard column.

Approximate width at 1448px viewport:

```text
~ 430px
```

Do not make the sidebar narrow.

It starts below the top navigation and contains:

1. Time selector
2. Range / Filters
3. Online / Offline cards
4. Efficiency graph
5. Four vehicle cards in a 2 × 2 grid

---

# 9. TIME FILTER ROW

At the top of the left sidebar:

```text
[24h] [7d] [30d]     [Range] [Filters]
```

The row consists of compact dark glass controls.

Selected `24h` is slightly brighter.

Approximate styling:

```css
background: rgba(255,255,255,0.055);
border: 1px solid rgba(255,255,255,0.045);
border-radius: 10px;
```

Text is small and muted.

Icons are thin-line and approximately 13–15px.

---

# 10. ONLINE / OFFLINE CARDS

Two equal cards.

Layout:

```text
┌─────────────────┐ ┌─────────────────┐
│ ● Online        │ │ ▲ Offline       │
│                 │ │                 │
│       12        │ │        4        │
└─────────────────┘ └─────────────────┘
```

## Online

Semantic indicator:

```css
color: #64D977;
```

Use a small green circular status dot.

## Offline

Semantic indicator:

```css
color: #F04438;
```

Use a small red triangular warning icon.

Numbers are significantly larger than labels.

Use a thin font weight for large numeric values.

---

# 11. EFFICIENCY PANEL

This is the large chart panel under the status cards.

Header:

```text
Overview of Efficiency                               ^
```

Large value:

```text
78.3 %
```

Small label:

```text
Overall
```

## Chart

Use a dark transparent graph region.

Characteristics:

- Thin dotted / dashed horizontal reference lines
- Very thin line chart
- Small points
- Subtle filled region below the line
- A few highlighted orange/yellow data points
- White/gray main line
- Minimal axis labels
- Low visual contrast
- No bright chart background

Reference time axis:

```text
00:00      06:00      12:00      18:00      24:00
```

Right side reference percentages:

```text
100%
75%
50%
25%
```

Do not add a standard chart legend unless needed by the data.

---

# 12. VEHICLE CARD GRID

Two columns × two rows.

Example reference cards:

```text
MA-2031
VOLVO B8RLE

DA-1420
ASHOK LEYLAND

BA-2209
BHARATBENZ, 1015R

GJ-0421
ASHOK LEYLAND
```

These names are examples only.

Firebase data should replace them.

## Vehicle card structure

Top:

```text
VEHICLE ID                         ⋮
MODEL
```

Center:

- Thin-line vehicle/bus illustration

Lower metrics:

```text
Depot                         Fuel 89%      ...
```

Bottom:

- Small route/path mini-chart
- Depot ↔ Terminal labels
- Circular marker / position indicator

## Vehicle illustration

The vehicle illustration must be:

- monochrome
- gray/white line-art
- low opacity
- very thin stroke
- centered
- not a colored SVG

Use outline SVG rather than an emoji or photographic asset.

## Vehicle mini route

Very subtle line graphic.

Use a thin gray line with one white circular node.

---

# 13. MAIN MAP AREA

The map is the visual centerpiece.

It is framed by the same dark glass treatment as the rest of the interface.

## Map appearance

The screenshot uses:

- Dark satellite / terrain imagery
- Desaturated grayscale land
- Deep dark blue/black water
- Limited green terrain
- White road / route emphasis
- Low overall saturation
- Strong vignette toward edges
- Dark UI controls on top

Do not use a standard bright Google Maps appearance.

Recommended rendering:

```css
filter:
  grayscale(0.82)
  brightness(0.72)
  contrast(1.08)
  saturate(0.72);
```

If the map provider allows a custom dark/satellite style, prefer style-level control over CSS filtering.

## Important

The basemap must remain visually consistent even when Firebase data changes.

Firebase controls the overlays/data, not the visual design of the map.

---

# 14. MAP HEADER

Top-left of map:

```text
Traffic Management

[ Bus-2201 › ]   [ ↗ View all ]
```

Title is large and thin.

Approximate:

```css
font-size: 31–34px;
font-weight: 300–400;
letter-spacing: -0.02em;
```

Subtitle controls are compact dark glass pills.

---

# 15. WEATHER CONTROL

Top-right of map:

```text
☁ 23°C                         ˅
```

Dark translucent rounded capsule.

Below/next to it are several compact square icon controls.

Keep these subtle.

---

# 16. MAP ROUTES

The reference contains several route/connection treatments.

## Primary route

Use a thin bright white line.

```css
stroke: rgba(255,255,255,0.90);
```

## Secondary route

Use a dashed white route:

```css
stroke: rgba(255,255,255,0.80);
stroke-dasharray: 6 8;
```

## Road network

Keep roads low-contrast.

The selected route should always stand out more than normal roads.

---

# 17. MAP MARKERS

Markers follow a restrained semantic color system.

### Blue

Active vehicle / selected fleet marker.

Approximate:

```css
#1688F7
```

### Red

Incident / danger marker.

Approximate:

```css
#F04438
```

### Yellow / amber

Warning / attention marker.

Approximate:

```css
#D9B900
```

### White

Neutral route / checkpoint markers.

Markers should have soft halos when selected.

---

# 18. PASSENGERS LOAD POPUP

Centered around a selected map point.

A circular translucent selection ring surrounds the marker.

Attached information panel:

```text
Passengers Load      ×

87%
```

Panel uses stronger glass:

```css
background: rgba(30,34,34,0.62);
backdrop-filter: blur(24px);
```

Large value should remain understated rather than brightly colored.

---

# 19. MAP BOTTOM CONTROLS

Bottom-left of map:

Three compact circular/square glass controls.

Suggested controls:

- Center / locate
- Layers
- Fullscreen

Each approximately:

```text
36–40px
```

Use subtle borders and no solid bright backgrounds.

---

# 20. ALERT PANEL

Top-right overlay over the map.

Width approximately:

```text 250–280px
```

Header:

```text
Warning                            ×
12 Current Issues
```

Panel is dark translucent glass.

---

# 21. ALERT CARD — CRITICAL

Top alert:

```text
⚠ Heavy Congestion on NH-66
Maharashtra
```

Accent:

```css
#F04438
```

Inside nested panel:

```text
Accident Report
At 12:45 PM, 2.3 km ahead

Weather Impact
Visibility < 200m

Roadwork
Delay expected: 15–20 min
```

Use nested glass blocks.

Never use a large solid red box.

Red is an accent only.

---

# 22. ALERT CARD — DIVERSION

Use green success / route accent:

```css
#67D39A
```

Example structure:

```text
◉ Diversion: Coastal Route
  Goa-17A
```

Keep background nearly neutral.

---

# 23. ALERT CARD — CLEARED

Use red/neutral indicator plus status wording:

```text
● Bus-2201: Inspected & Cleared
  Ready to resume schedule
```

The visual hierarchy is more important than the exact wording.

---

# 24. BOTTOM METRICS

Two large cards span the lower section.

Approximate layout:

```text
┌───────────────────────────────┐ ┌───────────────────────────────────┐
│ Schedule Offset               │ │ Total Passengers                   │
│                               │ │                                   │
│ ± 2.5 min                     │ │ 142,530                           │
│ Average deviation             │ │ today                             │
│                               │ │                                   │
│ Early ... On time ... Late    │ │ line chart                         │
└───────────────────────────────┘ └───────────────────────────────────┘
```

---

# 25. SCHEDULE OFFSET CARD

Header:

```text
Schedule Offset                                      »
```

Large value:

```text
± 2.5 min
```

Caption:

```text
Average deviation
```

Timeline:

```text
Early     -5m        On time        +5m       +15m     Late
```

Use semantic colors:

- Early / good: green
- On time: neutral white/gray
- Slightly late: amber
- Very late: red

Then show vehicle rows such as:

```text
GJ-0421   -3m    On time    +2m    +8m    +12m
MA-2031   -7m    -2m        On time +6m   +11m
```

Exact values must come from Firebase.

---

# 26. TOTAL PASSENGERS CARD

Header:

```text
Total Passengers                                      »
```

Large metric:

```text
142,530
```

Small qualifier:

```text
today
```

Chart:

- Thin white/gray line
- Subtle filled region
- Small orange highlighted section where applicable
- Dashed horizontal reference lines
- No axes box
- Minimal time labels

Time axis:

```text
00:00      06:00      12:00      18:00      24:00
```

Right-side values approximately:

```text
200k
100k
0
```

---

# 27. TYPOGRAPHY

Use a modern geometric / neo-grotesk sans-serif.

Preferred choices:

1. Inter
2. Geist
3. Manrope

Do not use serif fonts.

## Main title

```css
font-weight: 300–400;
letter-spacing: -0.02em;
```

## Large metrics

Use light/regular weights.

Do not make the numbers bold.

## Labels

Small, muted, compact.

Recommended approximate sizes:

```text
Page title:        31–34px
Large KPI:         35–42px
Section heading:   13–16px
Card label:        10–13px
Secondary text:    10–12px
Axis labels:        9–11px
```

---

# 28. ICONOGRAPHY

Use only simple outline icons.

Recommended stroke:

```text
1.4–1.8px
```

Avoid:

- Filled icon packs
- Cartoon icons
- Emoji
- Heavy 3D icons
- Bright colored icons except semantic status indicators

Icons should visually disappear into the UI until needed.

---

# 29. SPACING SYSTEM

Use a tight dashboard grid.

Suggested base:

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-7: 32px;
```

Most gaps should be 8–24px.

Avoid excessive whitespace.

The reference is information-dense.

---

# 30. RESPONSIVE BEHAVIOR

Pixel matching applies first to the reference desktop composition.

At smaller widths:

### ≥ 1200px

Preserve desktop composition.

### 900–1199px

- Reduce sidebar width proportionally
- Keep map dominant
- Reduce typography slightly
- Keep all core cards

### < 900px

Collapse into:

```text
Top navigation
Map
Key alerts
KPI cards
Vehicle cards
```

However, responsive changes must preserve the same design language.

Do not create a different visual theme for mobile.

---

# 31. FIREBASE DATA ARCHITECTURE

The UI must be separated from Firebase.

Recommended architecture:

```text
Firebase
   ↓
Data service / repository
   ↓
Normalized domain data
   ↓
UI components
```

Do not put raw Firebase queries throughout components.

Suggested folders:

```text
src/
├── components/
│   ├── TopNav/
│   ├── Sidebar/
│   ├── StatusCards/
│   ├── EfficiencyChart/
│   ├── VehicleCard/
│   ├── MapPanel/
│   ├── AlertPanel/
│   ├── ScheduleOffset/
│   └── PassengerChart/
│
├── services/
│   └── firebase/
│       ├── config.ts
│       ├── vehicles.ts
│       ├── alerts.ts
│       ├── routes.ts
│       ├── analytics.ts
│       └── weather.ts
│
├── adapters/
│   └── dashboardAdapter.ts
│
├── types/
│   └── dashboard.ts
│
└── styles/
    ├── tokens.css
    └── dashboard.css
```

---

# 32. FIREBASE DATA CONTRACT

The exact database schema may differ.

Create an adapter layer that maps the existing Firebase schema into the dashboard's normalized shape.

Example normalized model:

```ts
type Vehicle = {
  id: string;
  model: string;
  manufacturer?: string;
  status: "online" | "offline";
  fuelPercent?: number;
  batteryPercent?: number;
  passengerLoadPercent?: number;
  depot?: string;
  terminal?: string;
  latitude: number;
  longitude: number;
  routeId?: string;
  scheduleOffsetMinutes?: number;
  efficiencyPercent?: number;
};
```

Alert:

```ts
type Alert = {
  id: string;
  severity: "critical" | "warning" | "info" | "cleared";
  title: string;
  location?: string;
  description?: string;
  timestamp?: string;
  impact?: string;
};
```

Route:

```ts
type Route = {
  id: string;
  name: string;
  status?: "active" | "diversion" | "delayed";
  coordinates: [number, number][];
};
```

Analytics:

```ts
type AnalyticsPoint = {
  timestamp: string;
  value: number;
};
```

Weather:

```ts
type Weather = {
  temperatureC: number;
  condition?: string;
};
```

---

# 33. IMPORTANT FIREBASE RULE

Do not change styling based on data.

Examples:

Bad:

```text
Firebase returns more vehicles → redesign cards
```

Correct:

```text
Firebase returns more vehicles → preserve the card component
                              → scroll/paginate/filter the data
```

Bad:

```text
Long alert text → enlarge alert panel
```

Correct:

```text
Long alert text → clamp / wrap inside the existing alert component
```

The visual container remains consistent.

---

# 34. REALTIME FIREBASE UPDATES

Use Firebase realtime listeners where appropriate.

Examples:

```text
Vehicles
Alerts
Locations
Passenger counts
Schedule status
```

When data updates:

- update values
- update markers
- update charts
- preserve transitions
- preserve panel sizes
- preserve spacing

Do not cause the entire dashboard to visually jump.

Use short transitions:

```css
transition:
  opacity 180ms ease,
  transform 180ms ease,
  background-color 180ms ease;
```

Avoid exaggerated animations.

---

# 35. MAP + FIREBASE

Firebase should drive:

- Vehicle markers
- Vehicle marker color/state
- Route geometry
- Route state
- Passenger-load popup
- Incident markers
- Diversion markers
- Selected vehicle
- Active route

The base map style remains fixed.

Pseudo-flow:

```text
Firebase vehicle update
        ↓
normalizeVehicle()
        ↓
dashboard state
        ↓
map marker update
        ↓
sidebar vehicle card update
        ↓
passenger / status updates
```

---

# 36. DATA-TO-UI MAPPING

| Firebase data | UI location |
|---|---|
| Vehicle count | Online / Offline cards |
| Vehicle records | Vehicle card grid |
| Efficiency samples | Efficiency chart |
| Vehicle position | Map marker |
| Route geometry | Map route line |
| Passenger load | Map popup |
| Passenger history | Total Passengers chart |
| Alerts | Warning panel |
| Schedule deviations | Schedule Offset |
| Weather | Weather chip |
| Vehicle fuel | Vehicle card |
| Vehicle depot | Vehicle card |
| Vehicle model | Vehicle card |

---

# 37. DATA FALLBACKS

When Firebase has missing fields:

Do not break the visual layout.

Use:

```text
null → "—"
```

or suppress only the specific value.

Do not show:

```text
undefined
null
NaN
```

Do not resize components because of missing fields.

---

# 38. LOADING STATE

Loading state must still look like the dashboard.

Use subtle skeleton / shimmer layers inside the existing glass cards.

Never show a generic full-page spinner.

Example:

```css
background:
  linear-gradient(
    90deg,
    rgba(255,255,255,0.025),
    rgba(255,255,255,0.055),
    rgba(255,255,255,0.025)
  );
```

Keep animation slow and subtle.

---

# 39. ERROR STATE

Do not replace the dashboard with a giant error screen.

Example:

```text
Data unavailable
```

inside the affected card.

Preserve the component's shape and glass styling.

---

# 40. INTERACTION RULES

### Hover

Slightly brighten glass:

```css
background-color / overlay:
rgba(255,255,255,0.02–0.04)
```

### Selected vehicle

- Blue marker becomes emphasized
- Card border becomes slightly brighter
- Map popup appears
- Existing layout stays unchanged

### Alert selection

Expand only the alert's existing content area.

Do not redesign the alert panel.

---

# 41. COLOR TOKENS

Use a restrained palette.

```css
:root {
  --bg-0: #050708;
  --bg-1: rgba(15,17,18,0.78);
  --bg-2: rgba(24,27,28,0.68);
  --bg-3: rgba(32,35,36,0.56);

  --white-92: rgba(255,255,255,0.92);
  --white-72: rgba(255,255,255,0.72);
  --white-62: rgba(255,255,255,0.62);
  --white-45: rgba(255,255,255,0.45);
  --white-30: rgba(255,255,255,0.30);
  --white-16: rgba(255,255,255,0.16);
  --white-08: rgba(255,255,255,0.08);
  --white-05: rgba(255,255,255,0.05);

  --success: #64D977;
  --danger: #F04438;
  --warning: #D9B900;
  --info: #1688F7;
}
```

These are visual approximations from the screenshot and should be tuned against the reference during implementation.

---

# 42. CSS SURFACE EXAMPLE

```css
.glass {
  background:
    linear-gradient(
      135deg,
      rgba(29,32,33,0.72),
      rgba(11,13,14,0.58)
    );

  border: 1px solid rgba(255,255,255,0.055);

  box-shadow:
    0 18px 45px rgba(0,0,0,0.28),
    inset 0 1px 0 rgba(255,255,255,0.02);

  backdrop-filter: blur(18px) saturate(115%);
  -webkit-backdrop-filter: blur(18px) saturate(115%);

  border-radius: 18px;
}
```

---

# 43. MAP OVERLAY DARKENING

If using a map that is visually brighter than the reference, use an overlay instead of changing the dashboard colors.

```css
.map::after {
  content: "";
  position: absolute;
  inset: 0;

  pointer-events: none;

  background:
    linear-gradient(
      180deg,
      rgba(0,0,0,0.18),
      rgba(0,0,0,0.04) 40%,
      rgba(0,0,0,0.20)
    );
}
```

Then tune the map source/styling itself.

---

# 44. CHART RULES

Charts are part of the visual language.

Always:

- use very thin strokes
- use subtle grid lines
- avoid thick axes
- avoid large legends
- keep text low-contrast
- use transparent chart areas
- use rounded / smooth curves where appropriate
- use small highlights sparingly

Do not turn the dashboard into a colorful analytics dashboard.

---

# 45. VEHICLE CARD DENSITY

Vehicle cards must remain visually dense.

Each card includes:

```text
vehicle ID
model
menu icon
vehicle outline
fuel metric
status metric
depot
terminal
mini route graph
position marker
```

Even when values change, keep all major zones.

---

# 46. EXACT DATA REPLACEMENT PRINCIPLE

Treat the screenshot as a fixed presentation template.

Conceptually:

```ts
const dashboardView = {
  layout: FIXED,
  style: FIXED,
  colors: FIXED,
  glass: FIXED,
  geometry: FIXED,

  data: LIVE_FROM_FIREBASE,
};
```

Never:

```ts
style = generatedFromFirebase(data);
```

Instead:

```ts
const data = subscribeToFirebase();
renderFixedDashboard(data);
```

---

# 47. COMPONENT API DESIGN

Example:

```tsx
<TopNav
  active="Live Map"
/>

<Sidebar
  vehicles={vehicles}
  efficiency={efficiency}
  onlineCount={onlineCount}
  offlineCount={offlineCount}
/>

<MapPanel
  vehicles={vehicles}
  routes={routes}
  alerts={alerts}
  selectedVehicle={selectedVehicle}
/>

<AlertPanel
  alerts={alerts}
/>

<ScheduleOffset
  vehicles={vehicles}
/>

<PassengerChart
  data={passengerHistory}
/>
```

Components should receive data, not query Firebase directly.

---

# 48. DESKTOP LAYOUT CSS STARTING POINT

Use the screenshot proportions as the baseline, then tune against the reference.

```css
.dashboard {
  min-height: 100vh;
  padding: 18px 20px 20px;
}

.dashboard-grid {
  display: grid;

  grid-template-columns:
    minmax(370px, 0.31fr)
    minmax(620px, 1fr);

  grid-template-rows:
    auto
    minmax(0, 1fr)
    300px;

  gap: 12px;
}

.sidebar {
  grid-column: 1;
  grid-row: 2 / 4;
}

.map-panel {
  grid-column: 2;
  grid-row: 2;
}

.bottom-metrics {
  grid-column: 2;
  grid-row: 3;

  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
```

Tune exact dimensions visually against the 1448 × 1086 reference.

---

# 49. REFERENCE-BASED QA PROCESS

Every implementation pass should compare the rendered UI against the reference screenshot.

Check in this exact order:

## A. Macro geometry

- Overall page proportions
- Sidebar width
- Map size
- Bottom panel height
- Header height
- Margins between sections

## B. Glass

- Surface opacity
- Blur
- Edge softness
- Border visibility
- Internal highlight

## C. Typography

- Font family
- Weight
- Size
- Tracking
- Line height

## D. Components

- Card radius
- Icon placement
- Chart dimensions
- Vehicle illustrations
- Alert layout

## E. Color

- Black/gray balance
- White text opacity
- Green
- Red
- Amber
- Blue

## F. Data only

After the UI is visually matched, verify that Firebase values populate every relevant field.

---

# 50. DO NOT "IMPROVE" THE DESIGN

This instruction is critical.

Do not:

- add gradients that aren't present
- add extra cards
- add extra charts
- add new navigation items
- make buttons more colorful
- introduce a sidebar collapse button on desktop
- change the map style to a bright theme
- make glass more transparent than the reference
- use excessive blur
- make text brighter
- use huge shadows
- redesign vehicle cards
- modernize the UI
- simplify the dashboard
- rearrange sections
- invent new UX patterns

The objective is **reference replication**, not redesign.

---

# 51. FIREBASE INTEGRATION EXAMPLE

Illustrative pattern:

```ts
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "./config";

export function subscribeToVehicles(
  onUpdate: (vehicles: Vehicle[]) => void
) {
  return onSnapshot(
    collection(db, "vehicles"),
    (snapshot) => {
      const vehicles = snapshot.docs.map((doc) =>
        normalizeVehicle({
          id: doc.id,
          ...doc.data(),
        })
      );

      onUpdate(vehicles);
    }
  );
}
```

The exact collection names must match the existing Firebase project.

Do not invent or migrate the user's database schema unless requested.

---

# 52. FINAL ACCEPTANCE CRITERIA

The project is complete only when:

### Visual

- [ ] It looks like the supplied screenshot at desktop size.
- [ ] Glassmorphism is visibly the same style.
- [ ] Blur is subtle and layered.
- [ ] Borders are extremely subtle.
- [ ] Background is near-black.
- [ ] Map dominates the center.
- [ ] Sidebar proportions match.
- [ ] Bottom cards match.
- [ ] Alert panel matches.
- [ ] Vehicle cards match.
- [ ] Typography hierarchy matches.
- [ ] Semantic colors match.

### Data

- [ ] Firebase values populate the existing components.
- [ ] Live updates work where configured.
- [ ] Map markers update from data.
- [ ] Routes update from data.
- [ ] Alerts update from data.
- [ ] Passenger metrics update from data.
- [ ] Schedule offset updates from data.
- [ ] Efficiency chart updates from data.

### Engineering

- [ ] Firebase logic is separated from presentation.
- [ ] No hard-coded live business values are required.
- [ ] Missing values do not break layout.
- [ ] Components remain reusable.
- [ ] Desktop composition remains fixed and reference-driven.

---

# 53. ONE-SENTENCE IMPLEMENTATION RULE

> **Rebuild the screenshot as a fixed, pixel-accurate dark glassmorphism dashboard and use Firebase only as the live data layer underneath it; changing the data must never change the visual design.**
