# FIREX / alternative UI

A second front end for PS 162, built as a drop-in alternative to
`section6_gis_map/index.html`. Same data, same pipeline outputs, different
information design: one dark glass surface, one accent colour, hand-built
charts, no framework and no build step.

Nothing in this folder writes to `section6_gis_map/`. That app keeps working
exactly as it did.

## Run

```
python "alternative UI/server.py"
```

Then open <http://localhost:8010>.

`server.py` is a `SimpleHTTPRequestHandler` subclass. It serves this folder at
`/` and mounts two read-only routes so the pipeline's outputs are read where
they already sit instead of being copied:

| Route     | Reads from                   | Needed for                                                                                |
| --------- | ---------------------------- | ----------------------------------------------------------------------------------------- |
| `/data/`  | `../section6_gis_map/data/`  | `incidents.json`, `ambient_firms.json`                                                    |
| `/crops/` | `../section3_imagery/crops/` | `incidents.json` stores absolute crop paths, e.g. `/crops/case_004/satellite_annotated.jpg` |

Requests that try to climb out of either root are refused, and the handler only
logs 4xx/5xx so the console stays readable. If a mount is missing it says so at
startup rather than failing later on a broken image.

Port 8010 is used so this can run beside the section 6 server without a clash.

## Views

| View            | What it answers                                                                        |
| --------------- | -------------------------------------------------------------------------------------- |
| Live map        | Where the detections are, ranked. Three columns: evidence rail, map, docked dossier     |
| Overview        | What arrived in this window: tiles, work queue, detection timeline, feed integrity      |
| Investigations  | Card grid of every case with its satellite crop and triage state                        |
| Industrial      | Detections inside an industrial footprint, grouped by site. A flare is not an incident  |
| Analytics       | Distributions, classification mix, how the satellite stated confidence, factor means    |
| Settings        | Window, base layer, ambient pixels, triage reset, and what this build actually reads    |

Clicking any case opens the drawer; **Full dossier** opens the modal with the
annotated crop, the model's observations and the five-factor risk breakdown.
Left/Right arrows step through the filtered list in rank order (ignored while
typing). Escape closes the topmost layer only.

### The map view is three columns

Like the section 6 console, and for the same reason: data on both sides, map in
the middle.

| Column       | Holds                                                                       |
| ------------ | --------------------------------------------------------------------------- |
| Rail, left   | Detection window metrics, risk histogram, class filters, the priority spine  |
| Map, centre  | The map, plus one small overlay cluster per corner and nothing over the middle |
| Dock, right  | The case dossier, always present: a prompt when nothing is selected          |

The dossier is docked rather than floated, so the marker you just clicked stays
visible while you read about it and the map keeps a stable width instead of
losing a third of itself on selection. Below 1280px three columns would leave
the map a strip, so there the dock goes back to being an overlay that slides in
over the map, and that is the only width at which it is one.

Class filters sit in the rail, above the list they filter, rather than floating
over the map. The map's four corners carry the view name, the in-view readout
with fit and ambient toggles, the base layer and zoom controls, and a marker key
that explains the encoding: ring colour is risk tier, glyph is classification, a
dashed ring means the vision model could not confirm it, a bare dot is an
unclassified FIRMS pixel. Switching to Imagery drops the basemap darkening and
uses the same `brightness(0.95) contrast(1.12)` the section 6 console uses,
because the reason to switch is to look at the ground.

## Layout

```
index.html          shell, inlined 36-symbol SVG sprite, view containers
server.py           static server with the two read-only mounts
styles/
  tokens.css        the only place colour, type, spacing and timing are defined
  surfaces.css      glass surfaces and the reduced-transparency fallback
  base.css          reset, typography, icons, focus, utilities
  layout.css        app frame, view grids, the three-column map view
  components.css    controls, filter bar, tags, meters, the priority spine
  cards.css         case cards, queue rows, facility rows, skeletons, states
  charts.css        histogram, ranked bars, timeline, legend
  map.css           Leaflet overrides, markers, popups, overlays, marker key
  dossier.css       docked drawer and modal
js/
  config.js         tokens JS needs: classes, tiers, filters, windows, icon()
  data.js           fetch, normalise, score, tier, triage persistence
  map.js            Leaflet init, markers, flyTo, base layer switching
  render.js         every view body, built as strings from state
  dossier.js        drawer and modal, focus trap, triage actions
  main.js           state, routing, event wiring, preferences
```

## How it is put together

**One state object, one render pass.** Every control writes to `state` and calls
`renderAll()`. Only the active view's body is rebuilt, so there is no diffing
layer and no chance of two controls disagreeing about the same value.

**Risk tier is the only source of hue.** Any element carrying `data-tier`
exposes one custom property, `--tier`, which markers, badges, meters, bars,
scores and legend swatches all read. `styles/components.css` is the single place
the ramp is mapped, so a tier change moves the whole UI at once.

**Colour is never the only channel.** Class is a glyph, tier is a ring colour,
and a detection the vision model could not confirm gets a dashed edge. The
distinction survives greyscale and colour blindness.

**Charts are hand-built.** No charting library. Hairline axes, dotted
gridlines, 2px marks, and values read from mono labels rather than a legend.
Radiative power is deliberately monochrome: it measures energy, not risk, and
the two must not share an axis.

**Blur is budgeted.** `.glass` has no `backdrop-filter` and is safe inside
scroll regions; `.glass--frosted` has one and is only used on fixed, sticky or
overlay layers. Under `prefers-reduced-transparency` both fall back to solid.
The docked dossier is plain `.glass`, and picks up a blur only in the ≤1280px
media query where it becomes an overlay.

**Nothing floats over the map that has a home beside it.** The map carries
navigation, a viewport readout and the marker key. The ranked list is in the
rail and the selected case is in the dock, so neither is drawn a second time
over the imagery an analyst switched to in order to see the ground.

**No secrets in the browser.** The front end reads the JSON the pipeline already
wrote. No API key, MAP_KEY or model credential is referenced anywhere in this
folder, and none should be added: keys stay server side.

## What is stored locally

`localStorage` only, and only in this browser: `firex_prefs` (view, window,
filter, base layer, ambient toggle) and one `firex_triage_<case_id>` per triage
decision. Settings has a Clear decisions control. No case data is cached.

## Deliberate differences from the reference design

- **No weather or locale strip.** The mock had one. This is a detection console;
  the temperature where the analyst is sitting is not evidence.
- **No emoji, no gradient badges, no "SECTION 01" eyebrows, no AI purple.** Type
  is Geist and JetBrains Mono; the only saturated colours are the risk ramp and
  a single blue for selection.
- **Numbers keep the precision the source reported.** MODIS states a percentage
  and VIIRS states a named band, and both are shown in their original wording
  rather than converted into a common invented scale.
- **Empty means empty.** Zero counts, missing crops and unread feeds say so in
  place instead of being hidden or filled with a placeholder.

## Verification

Checked with a Chrome DevTools Protocol driver against the running server (47
assertions covering boot, the three-column map view, selection, filters, the
imagery treatment, the marker key, all six views, preference persistence and
reload; 0 uncaught exceptions, 0 console errors) and by reading screenshots at
1600px and 1240px, which is what caught four defects assertions could not: a
self-referential `--tier` custom property that silently killed the entire risk
ramp; stroke styling written on the sprite's paths instead of the referencing
`<svg>`, which cannot cross the shadow boundary a `<use>` creates and left every
icon painting as a dark blob; a `position: relative` on the marker key that
overrode its overlay corner on source order and opened the panel off the top
edge of the map; and the bottom-centre filter bar colliding with the base layer
control once the map became the middle of three columns.

A grep for `console.*`, `debugger`, `TODO`, `FIXME`, `alert(` and `window.__`
over `index.html`, `js/`, `styles/` and `server.py` returns nothing: there is no
debug code, no scaffolding and no commented-out block in this folder. The four
`catch` blocks are intentional and each carries the reason in a comment.

## Browser support

Chromium, Edge, Firefox and Safari, current versions. Uses `color-mix()`,
`backdrop-filter`, `:focus-visible` and native ES modules. No polyfills, no
transpilation, no `node_modules`.


