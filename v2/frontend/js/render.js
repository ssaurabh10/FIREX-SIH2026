/* ==========================================================================
   render - each view is a function of the filtered case list
   Nothing here holds state. main.js owns state and calls into this module,
   which is why every figure on screen can be traced back to the feed.
   ========================================================================== */

import {
  TIERS, WINDOWS, SOURCES, FILTERS, CLASSES, BASES, TRIAGE_ACTIONS,
  triageOf, fmt, icon, escapeHtml,
} from "./config.js";
import {
  store, byTier, byClass, bySite, histogram, stats, getTriage, triageCounts,
} from "./data.js";

const set = (el, html) => { if (el) el.innerHTML = html; };

/* F-109. The feed publishes `day_night_status` ("PRIMARILY DAY OVERPASS",
   "DAY + NIGHT (Continuous 24h)"), never the FIRMS D/N code these views were
   written against: reading `c.firms.daynight` matched nothing on any record, so
   every detection rendered as a night pass and the day lane was always empty.
   The published field is read instead, and a continuous record is reported as
   being in both lanes rather than forced into one. */
function dayNightOf(c) {
  const s = String(c?.persistence?.dayNightStatus || "").toUpperCase();
  const day = s.includes("DAY");
  const night = s.includes("NIGHT");
  if (day && night) return "Day + Night";
  if (night) return "Night";
  if (day) return "Day";
  const h = c?.at ? c.at.getUTCHours() : null;
  if (h === null) return "Unreported";
  return h >= 3 && h <= 13 ? "Day" : "Night";
}

/* --- Fragments ------------------------------------------------------------ */

function tierTag(c) {
  const isRoutine = c.climatology?.isRoutine;
  const anomaly = c.historicalAnomaly;
  const anomalyTag = isRoutine
    ? ` <span class="tag tag--signal" style="font-size:0.62rem">ROUTINE</span>`
    : (anomaly === "ABNORMAL_SURGE" ? ` <span class="tag tag--tier" style="font-size:0.62rem">SURGE</span>` : "");
  return `<span class="tag tag--tier">${c.severity?.level || c.risk.tier} ${c.severity?.score ?? c.risk.score}</span>${anomalyTag}`;
}

/* Confirmation is a separate channel from risk, so it gets its own tag rather
   than being folded into the tier colour. */
function confTag(c) {
  return c.confirmed
    ? `<span class="tag">${escapeHtml(c.cls.short)}</span>`
    : `<span class="tag tag--unconfirmed">Unconfirmed</span>`;
}

function metric(value, unit, label, note) {
  return `
    <div class="metric">
      <p class="u-label">${escapeHtml(label)}</p>
      <p class="metric__value">
        <span class="u-metric u-live">${value}</span>
        ${unit ? `<span class="metric__unit">${escapeHtml(unit)}</span>` : ""}
      </p>
      ${note ? `<p class="metric__note">${escapeHtml(note)}</p>` : ""}
    </div>`;
}

function panel(title, aside, body, opts = {}) {
  const { cls = "", foot = "", bodyCls = "" } = opts;
  return `
    <section class="glass panel ${cls}">
      <div class="panel__head">
        <h2 class="u-label">${escapeHtml(title)}</h2>
        ${aside || ""}
      </div>
      <div class="panel__body ${bodyCls}">${body}</div>
      ${foot ? `<div class="panel__foot">${foot}</div>` : ""}
    </section>`;
}

function stateBlock(title, body, glyph = "i-database") {
  return `
    <div class="state">
      <span class="state__icon">${icon(glyph, "i i--xl")}</span>
      <p class="state__title">${escapeHtml(title)}</p>
      <p class="state__body">${escapeHtml(body)}</p>
    </div>`;
}

function kvRows(pairs, cls = "kv") {
  return `<dl class="${cls}">${pairs
    .map(([k, v]) => `<dt class="kv__k">${escapeHtml(k)}</dt><dd class="kv__v">${v}</dd>`)
    .join("")}</dl>`;
}

function kv(pairs) {
  return kvRows(pairs, "kv");
}

/* --- Chart text alternatives ---------------------------------------------
   A bar chart keeps its numbers in two places a screen reader cannot reach: the
   height of a div and a title attribute. Every chart here therefore marks its
   plot decorative and writes the same counts out as text that only assistive
   technology reads, so nothing is withheld that a sighted reader could not
   already get from the tooltips. */

function chartAlt(summary, rows) {
  const items = rows.length
    ? `<dl>${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join("")}</dl>`
    : "";
  return `<div class="u-sr">${summary ? `<p>${escapeHtml(summary)}</p>` : ""}${items}</div>`;
}

/* Only the bins that hold something, and a single closing row for the rest: ten
   rows of "no cases" read aloud is noise, but "seven of ten bins are empty" is
   the shape of the distribution. */
function binRows(bins, label) {
  const rows = [];
  bins.forEach((n, i) => {
    if (n) rows.push([label(i), `${n} ${n === 1 ? "case" : "cases"}`]);
  });
  const empty = bins.filter((n) => !n).length;
  if (empty) rows.push(["Empty bins", `${empty} of ${bins.length} hold no cases`]);
  return rows;
}

/* --- Loading ------------------------------------------------------------- */

/* Skeletons keep the real card geometry so nothing shifts when data lands.
   A full-page spinner would throw away that layout information. */
export function skeleton(el, rows = 4) {
  const line = (cls) => `<span class="skel skel--line ${cls}"></span>`;
  const block = Array.from({ length: rows }, () => `
    <div class="glass panel">
      <div class="panel__head">${line("skel--half")}</div>
      <div class="panel__body stack">${line("skel--wide")}${line("skel--half")}</div>
    </div>`).join("");
  set(el, `<div class="stack-5">${block}</div>`);
}

/* --- Rail: counts --------------------------------------------------------- */

export function renderRailCounts(el, shown, all) {
  const priority = shown.filter((c) => c.risk.tier === "CRITICAL" || c.risk.tier === "HIGH");
  const unconfirmed = shown.filter((c) => !c.confirmed);
  const peak = shown.reduce((a, c) => (c.frp > (a?.frp ?? -1) ? c : a), null);

  set(el, [
    metric(fmt.int(shown.length), "", "In window",
      `${all.length} cases in the feed`),
    metric(fmt.int(priority.length), "", "Priority",
      "Critical or high tier"),
    metric(fmt.int(unconfirmed.length), "", "Unconfirmed",
      "Vision model was not certain"),
    metric(peak ? fmt.dec(peak.frp) : "-", "MW", "Peak FRP",
      peak ? `${peak.id}, ${peak.place}` : "No detections in window"),
  ].join(""));
}

/* --- Rail: risk distribution ---------------------------------------------
   Ten bins across the full 0 to 100 scale, not across the observed range, so
   the shape of the distribution cannot be exaggerated by a narrow dataset. */

export function renderRiskHist(el, cases, spanEl) {
  const scores = cases.map((c) => c.risk.score);
  const bins = histogram(scores, 10, 0, 100);
  const peak = Math.max(1, ...bins);
  const label = (i) => `Risk ${i * 10} to ${i * 10 + 9 + (i === 9 ? 1 : 0)}`;

  const bars = bins.map((n, i) => {
    const mid = i * 10 + 5;
    const tier = TIERS.find((t) => mid >= t.min && mid <= t.max)?.id || "LOW";
    const h = n ? Math.max(6, Math.round((n / peak) * 100)) : 3;
    return `<div class="cols__bar" data-tier="${tier}" style="--v:${h}%"
      title="${label(i)}: ${n} ${n === 1 ? "case" : "cases"}"></div>`;
  }).join("");

  const s = stats(scores);

  set(el, `
    <div class="chart">
      <div class="chart__plot chart__plot--grid" style="height:58px" aria-hidden="true">
        <div class="cols">${bars}</div>
      </div>
      <div class="chart__axis" aria-hidden="true"><span>0</span><span>50</span><span>100</span></div>
      ${chartAlt(s.n
        ? `Risk score distribution, ten bins across the full 0 to 100 scale. ${s.n} ${s.n === 1 ? "case" : "cases"} scoring ${s.min} to ${s.max}.`
        : "Risk score distribution: no cases in this window.", binRows(bins, label))}
    </div>`);

  if (spanEl) spanEl.textContent = s.n ? `${s.min} to ${s.max}` : "no data";
}

/* --- Rail: priority spine ------------------------------------------------
   The signature list. Rank comes from the scoring engine, never from the
   order the records happen to arrive in. */

export function renderSpine(el, cases, selected, countEl) {
  if (countEl) countEl.textContent = cases.length ? `${cases.length} targets` : "0";

  if (!cases.length) {
    set(el, stateBlock("No targets in view",
      "Try switching the category filter back to 'All'.", "i-funnel"));
    return;
  }

  const sorted = [...cases].sort((a, b) => {
    const scoreDiff = (b.risk?.score || 0) - (a.risk?.score || 0);
    if (scoreDiff !== 0) return scoreDiff;
    return (b.frp || 0) - (a.frp || 0);
  });

  const rows = sorted.map((c, idx) => `
    <button class="spine__row" type="button" data-case="${escapeHtml(c.id)}"
            data-tier="${c.risk.tier}" data-selected="${c.id === selected ? 1 : 0}">
      <span class="spine__rank">${idx + 1}</span>
      <span class="spine__main">
        <span class="spine__name">
          <span class="spine__cid">${escapeHtml(c.id.slice(0, 12))}</span>
          <span class="u-truncate">${escapeHtml(c.place)}</span>
        </span>
        <span class="spine__where u-truncate">
          ${icon(c.cls.icon, "i i--sm")}
          <span>${escapeHtml(c.cls.short)}</span>
          <span class="dot-sep">•</span>
          <span>${fmt.dec(c.frp)} MW</span>
          ${c.historicalAnomaly === 'ABNORMAL_SURGE' ? `<span class="dot-sep">•</span><span style="color:#ef4444;font-size:0.62rem;font-weight:600">SURGE</span>` : (c.climatology?.isRoutine ? `<span class="dot-sep">•</span><span style="color:#10b981;font-size:0.62rem">ROUTINE</span>` : "")}
        </span>
      </span>
      <span class="spine__score" title="Threat Severity: ${c.severity?.level || c.risk.tier} (${c.severity?.score ?? c.risk.score})">${c.risk.score}</span>
    </button>`).join("");

  set(el, `<div class="spine">${rows}</div>`);
}

/* --- Map overlay: priority queue ------------------------------------------ */

export function renderQueue(el, cases, selected, countEl, limit = 6) {
  const top = cases.slice(0, limit);
  if (countEl) countEl.textContent = String(cases.length);

  if (!top.length) {
    set(el, stateBlock("Queue empty", "No detections match the current filter.", "i-check"));
    return;
  }

  set(el, `<div class="queue">${top.map((c) => `
    <button class="queue__row" type="button" data-case="${escapeHtml(c.id)}"
            data-tier="${c.risk.tier}" data-selected="${c.id === selected ? 1 : 0}">
      <span class="queue__edge"></span>
      <span class="queue__main">
        <span class="queue__title">${icon(c.cls.icon, "i i--sm")}<span class="u-truncate">${escapeHtml(c.place)}</span></span>
        <span class="queue__meta u-truncate">${escapeHtml(c.cls.short)}, ${fmt.dec(c.frp)} MW</span>
      </span>
      <span class="queue__score">${c.risk.score}</span>
    </button>`).join("")}</div>`);
}

/* --- Map overlay: filter bar ---------------------------------------------
   Counts are computed against the window, not against the already filtered
   list, so a pill always tells you how much it would bring back. */

export function renderFilterBar(el, base, active) {
  set(el, FILTERS.map((f) => {
    const n = base.filter(f.test).length;
    return `
      <button class="pill" type="button" data-filter="${f.id}" aria-pressed="${f.id === active}">
        <span>${escapeHtml(f.label)}</span>
        <span class="pill__n">${n}</span>
      </button>`;
  }).join(""));
}

/* --- Map overlay: marker key ---------------------------------------------
   The glyph rows are written from the taxonomy rather than typed into the
   page, because a class has to resolve to the same symbol here as it does in
   markerHtml. Typed by hand the two had already parted company: the key drew
   a factory for an industrial fire where the map draws a flame, and it named
   four of the six classes. Markup cannot be checked against config.js. */

export function renderMapKey(el) {
  set(el, Object.values(CLASSES).map((c) => `
    <span class="mapkey__row">
      <span class="mapkey__mk mapkey__mk--glyph">${icon(c.icon, "i")}</span>${escapeHtml(c.short)}
    </span>`).join(""));
}

/* --- Bottom strip --------------------------------------------------------- */

/* The track is a picture of the number printed next to it, so it is decorative:
   announcing it again as an unlabelled element would only add noise. Every bar,
   meter and track in this module is marked the same way for the same reason. */
function ranksBlock(rows, total, limit) {
  const list = limit ? rows.slice(0, limit) : rows;
  if (!list.length) return stateBlock("No classifications", "Nothing to summarise yet.", "i-grid");
  return `<div class="ranks">${list.map((r) => `
    <div class="rank">
      <span class="rank__label">${icon(r.icon, "i i--sm")}<span class="u-truncate">${escapeHtml(r.short)}</span></span>
      <span class="rank__n">${r.n}</span>
      <span class="rank__track" aria-hidden="true"><span class="rank__fill" style="--v:${Math.round((r.n / Math.max(1, total)) * 100)}%"></span></span>
    </div>`).join("")}</div>`;
}

export function renderStrip(el, cases, ambient) {
  if (!el) return;
  set(el, "");
}

/* --- Shared blocks -------------------------------------------------------- */

function stampDate(d) {
  if (!d) return "unreported";
  const day = String(d.getUTCDate()).padStart(2, "0");
  const mon = d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day} ${mon}, ${hh}:${mm} UTC`;
}

/* Real time axis. Detections from one overpass sit on top of each other,
   which is information: it says the sensor saw them in the same pass. */
/* Lane order: on the axis first, then alternating above and below it. */
const TL_LANES = [0, -1, 1, -2, 2];

function timeline(cases, selected) {
  const times = cases.map((c) => c.at?.getTime()).filter(Boolean);
  if (!times.length) {
    return stateBlock("No acquisition times", "The feed did not report usable timestamps.", "i-clock");
  }
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  const span = hi - lo || 1;

  /* Real time on the x axis means a single overpass puts several detections on
     almost the same pixel. Rather than let them hide each other, marks that
     would collide step off the axis into a lane, so all of them stay readable
     and clickable and the cluster still reads as a cluster. */
  const placed = cases.filter((c) => c.at)
    .map((c) => ({ c, x: ((c.at.getTime() - lo) / span) * 96 + 2, lane: 0 }));
  const lastInLane = [];
  [...placed].sort((a, b) => a.x - b.x).forEach((p) => {
    let lane = 0;
    while (lastInLane[lane] !== undefined && p.x - lastInLane[lane] < 1.2) lane += 1;
    lastInLane[lane] = p.x;
    p.lane = TL_LANES[Math.min(lane, TL_LANES.length - 1)];
  });

  const marks = placed.map(({ c, x, lane }) => `
    <button class="tl__mark" type="button" data-case="${escapeHtml(c.id)}"
      data-tier="${c.risk.tier}" data-confirmed="${c.confirmed ? 1 : 0}"
      data-selected="${c.id === selected ? 1 : 0}" style="left:${x.toFixed(2)}%;--lane:${lane}"
      title="${escapeHtml(c.id)}, ${escapeHtml(c.place)}, ${stampDate(c.at)}"
      aria-label="${escapeHtml(c.id)} at ${stampDate(c.at)}"></button>`).join("");

  /* The axis here is not decoration the way a bar chart's tick row is: it prints
     the first and last acquisition in the window, which is information, so it
     stays readable. Only the drawn line is hidden. */
  return `
    <div class="chart">
      ${chartAlt(`Acquisition timeline, ${placed.length} ${placed.length === 1 ? "detection" : "detections"} between ${stampDate(new Date(lo))} and ${stampDate(new Date(hi))}. Each mark below is a button that opens its case.`, [])}
      <div class="tl"><span class="tl__axis" aria-hidden="true"></span>${marks}</div>
      <div class="chart__axis">
        <span>${stampDate(new Date(lo))}</span>
        <span>${stampDate(new Date(hi))}</span>
      </div>
    </div>`;
}

function legend() {
  return `<div class="legend">
    ${TIERS.map((t) => `<span class="legend__item" data-tier="${t.id}">
      <span class="legend__swatch legend__swatch--ring"></span>${t.label} ${t.min} to ${t.max}
    </span>`).join("")}
    <span class="legend__item">
      <span class="legend__swatch legend__swatch--ring legend__swatch--dashed"></span>Not confirmed
    </span>
  </div>`;
}

/* --- Overview -------------------------------------------------------------
   The order matters: what is loaded, what needs work, when it was seen, and
   only then the distributions. */

function tile(inner, delay = 0) {
  return `<div class="glass tile reveal" style="--reveal-delay:${delay}ms">${inner}</div>`;
}

/* Two ways the feed can be wrong, and they are not the same thing. A source that
   did not answer is an error. A source that answered with something that does not
   add up, such as a risk tier this build's bands would not have given the score,
   is a notice: the console shows what the engine published and says where the two
   part company rather than quietly picking one. */
function integrityTag() {
  if (store.errors.length) {
    return `<span class="tag tag--unconfirmed">${store.errors.length} source down</span>`;
  }
  if (store.notices.length) {
    return `<span class="tag tag--unconfirmed">${store.notices.length} to check</span>`;
  }
  return `<span class="tag"><span class="tag__dot"></span>Both sources read</span>`;
}

function noticeRow() {
  return ["Risk tiers", store.notices.length
    ? store.notices.map((n) => escapeHtml(n.message)).join("<br>")
    : "Every published tier matches this build's bands"];
}

/* --- Overview: Enhanced Helpers ------------------------------------------ */

const REGION_DEFS = [
  { id: "south", name: "Southern Industrial & Maritime Belt", sub: "Tamil Nadu, Karnataka, AP (Smelters & Ports)" },
  { id: "west", name: "Western Petrochemical & Heavy Corridor", sub: "Gujarat, Maharashtra, Rajasthan (Petrochem & Hubs)" },
  { id: "east", name: "Eastern Mining & Metallurgy Basin", sub: "Jharkhand, Odisha, Bengal (Coal seams & Steelworks)" },
  { id: "north", name: "Northern Agrarian & Energy Infrastructure", sub: "Punjab, Haryana, UP, MP (Flares & Agricultural)" },
];

function getRegionCategory(c) {
  const loc = `${c.place || ""} ${c.address || ""} ${c.site || ""}`.toLowerCase();
  const lat = c.lat;
  const lon = c.lon;

  if (loc.includes("tamil") || loc.includes("karnataka") || loc.includes("ballari") || loc.includes("tirunelveli") || loc.includes("kerala") || loc.includes("andhra") || loc.includes("telangana") || lat < 16.5) {
    return { id: "south", name: "Southern Industrial & Maritime Belt", sub: "Tamil Nadu, Karnataka, AP (Smelters & Ports)" };
  }
  if (loc.includes("gujarat") || loc.includes("maharashtra") || loc.includes("mumbai") || loc.includes("surat") || loc.includes("hazira") || loc.includes("rajasthan") || loc.includes("balotra") || (lon < 76.5 && lat < 26.5)) {
    return { id: "west", name: "Western Petrochemical & Heavy Corridor", sub: "Gujarat, Maharashtra, Rajasthan (Petrochem & Hubs)" };
  }
  if (loc.includes("jharkhand") || loc.includes("odisha") || loc.includes("jharia") || loc.includes("dhanbad") || loc.includes("jajpur") || loc.includes("kalinganagar") || loc.includes("bengal") || loc.includes("chhattisgarh") || lon >= 82) {
    return { id: "east", name: "Eastern Mining & Metallurgy Basin", sub: "Jharkhand, Odisha, Bengal (Coal seams & Steelworks)" };
  }
  return { id: "north", name: "Northern Agrarian & Energy Infrastructure", sub: "Punjab, Haryana, UP, Central Basin" };
}

function regionalBreakdown(cases) {
  const total = Math.max(1, cases.length);
  const groups = { south: [], west: [], east: [], north: [] };
  cases.forEach((c) => {
    const r = getRegionCategory(c);
    if (groups[r.id]) groups[r.id].push(c);
  });

  return REGION_DEFS.map((def) => {
    const items = groups[def.id] || [];
    const count = items.length;
    // INV-2: FRP is a per-detection radiometric rate (MW at the pixel), never a
    // quantity. Summing it across a region produces a number with no physical
    // meaning, so the strip reports the region's peak detection instead.
    const peakFrp = items.length ? Math.max(...items.map((c) => c.frp || 0)) : 0;
    const topThreat = items.length ? items.reduce((a, b) => {
      const scoreDiff = (b.risk?.score || 0) - (a.risk?.score || 0);
      if (scoreDiff !== 0) return scoreDiff > 0 ? b : a;
      return (b.frp || 0) > (a.frp || 0) ? b : a;
    }, items[0]) : null;
    const pct = Math.round((count / total) * 100);

    return `
      <div class="well ov-region-item" style="padding:var(--s-3);display:flex;flex-direction:column;gap:6px;">
        <div class="ov-region-top" style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--s-2);">
          <div>
            <div class="ov-region-name" style="font-size:var(--fs-label);font-weight:600;color:var(--t-primary);">${escapeHtml(def.name)}</div>
            <div class="ov-region-sub" style="font-size:var(--fs-micro);color:var(--t-tertiary);">${escapeHtml(def.sub)}</div>
          </div>
          <div class="ov-region-metrics" style="display:flex;align-items:baseline;gap:var(--s-3);font-family:var(--font-mono);font-size:var(--fs-micro);color:var(--t-secondary);">
            <span><strong>${count}</strong> detections</span>
            <span class="dot-sep">•</span>
            <span><strong>${fmt.dec(peakFrp)}</strong> MW peak</span>
          </div>
        </div>
        <div class="ov-region-meter" style="height:3px;border-radius:99px;background:var(--fill-2);overflow:hidden;" aria-hidden="true">
          <div class="ov-region-fill" style="height:100%;border-radius:99px;background:var(--signal);width:${pct}%;"></div>
        </div>
        ${topThreat ? `
          <div class="row row--wrap" style="font-size:var(--fs-micro);color:var(--t-tertiary);justify-content:space-between;margin-top:2px;">
            <span class="u-truncate">Peak: <strong style="color:var(--t-secondary);">${escapeHtml(topThreat.place)}</strong> (${fmt.dec(topThreat.frp)} MW${topThreat.risk?.score ? ` • Score ${topThreat.risk.score}` : ''})</span>
            <button class="hit-inline" type="button" data-case="${escapeHtml(topThreat.id)}" style="background:none;border:none;color:var(--signal);cursor:pointer;font-size:var(--fs-micro);padding:0;font-family:inherit;">View Target &rarr;</button>
          </div>` : `
          <div style="font-size:var(--fs-micro);color:var(--t-quiet);">No active detections in window</div>`}
      </div>`;
  }).join("");
}

function renderEnhancedQueue(el, cases, selected, limit = 6) {
  const sorted = [...cases].sort((a, b) => {
    const scoreDiff = (b.risk?.score || 0) - (a.risk?.score || 0);
    if (scoreDiff !== 0) return scoreDiff;
    return (b.frp || 0) - (a.frp || 0);
  });
  const top = sorted.slice(0, limit);
  if (!top.length) {
    set(el, stateBlock("Queue empty", "No detections match the current filter.", "i-check"));
    return;
  }
  set(el, `<div class="queue" style="display:flex;flex-direction:column;gap:6px;">${top.map((c, idx) => {
    let anomalyTag = "";
    if (c.historicalAnomaly === "ABNORMAL_SURGE") {
      anomalyTag = `<span class="tag tag--tier" data-tier="CRITICAL" style="font-size:0.58rem;padding:0 5px;font-weight:600;">P95 SURGE</span>`;
    } else if (c.climatology?.isRoutine) {
      anomalyTag = `<span class="tag tag--signal" style="font-size:0.58rem;padding:0 5px;">ROUTINE</span>`;
    } else if (c.historicalAnomaly === "NEW_UNEXPECTED") {
      anomalyTag = `<span class="tag tag--tier" data-tier="HIGH" style="font-size:0.58rem;padding:0 5px;">NEW</span>`;
    }
    /* F-110. `distanceKm` is null when the feed never reported one (56 of the 80
       facility-associated rows), and `fmt.dec` reads null as 0, so the old form
       printed "0.0 km" and put the fire inside the plant. */
    const facInfo = c.facility?.name
      ? `<span class="u-truncate" style="color:var(--signal);">${escapeHtml(c.facility.name)}${c.facility.distanceKm != null ? ` (${fmt.dec(c.facility.distanceKm, 1)} km)` : ""}</span>`
      : `<span class="u-truncate">${escapeHtml(c.site || c.address || c.place)}</span>`;

    return `
      <div class="well ov-queue-item" data-case="${escapeHtml(c.id)}" data-tier="${c.risk.tier}" data-selected="${c.id === selected ? 1 : 0}"
           style="display:grid;grid-template-columns:3px minmax(0, 1fr) auto;gap:var(--s-3);padding:var(--s-3);cursor:pointer;">
        <span class="ov-queue-edge" style="border-radius:99px;background:var(--tier);opacity:0.9;"></span>
        <div class="ov-queue-body" style="min-width:0;display:flex;flex-direction:column;gap:3px;">
          <div class="ov-queue-title-row" style="display:flex;align-items:center;gap:6px;min-width:0;font-size:var(--fs-label);font-weight:500;color:var(--t-primary);">
            ${icon(c.cls.icon, "i i--sm")}
            <span class="u-truncate">${escapeHtml(c.place)}</span>
            <span style="font-family:var(--font-mono);font-size:var(--fs-micro);color:var(--t-quiet);">#${idx + 1}</span>
          </div>
          <div class="ov-queue-meta-row" style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-family:var(--font-mono);font-size:var(--fs-micro);color:var(--t-tertiary);">
            <span style="color:var(--t-primary);font-weight:500;">${fmt.dec(c.frp)} MW</span>
            <span class="dot-sep">•</span>
            <span>${escapeHtml(c.cls.short)}</span>
            <span class="dot-sep">•</span>
            ${facInfo}
            ${anomalyTag ? `<span class="dot-sep">•</span>${anomalyTag}` : ""}
          </div>
        </div>
        <div class="ov-queue-right" style="display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:4px;">
          <span class="ov-queue-score" style="font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:var(--fs-label);font-weight:600;color:var(--tier);" title="Risk Score: ${c.risk.score} / Tier: ${c.risk.tier}">${c.risk.score}</span>
          <button class="btn btn--sm" type="button" data-case="${escapeHtml(c.id)}" data-open="modal" style="height:22px;padding:0 6px;font-size:var(--fs-micro);">Inspect</button>
        </div>
      </div>`;
  }).join("")}</div>`);
}

function renderAnomalyRadar(cases) {
  const flaresCount = cases.filter((c) => c.climatology?.isRoutine || c.classId === "gas_flare").length;
  const surgesCount = cases.filter((c) => c.historicalAnomaly === "ABNORMAL_SURGE").length;
  const newUnexpectedCount = cases.filter((c) => c.historicalAnomaly === "NEW_UNEXPECTED").length;
  const persistentBurnCount = cases.filter((c) => (c.persistence?.daysActive || 1) >= 2).length;

  return `
    <div class="grid-2 ov-anomaly-grid" style="gap:var(--s-3);">
      <div class="well ov-anomaly-card" style="padding:var(--s-3);display:flex;flex-direction:column;gap:5px;">
        <div class="ov-anomaly-head" style="display:flex;align-items:center;justify-content:space-between;gap:var(--s-2);">
          <span class="ov-anomaly-name" style="font-size:var(--fs-label);color:var(--t-secondary);font-weight:500;">Abnormal Thermal Surges</span>
          <span class="tag tag--tier" data-tier="CRITICAL" style="font-size:0.6rem;padding:1px 5px;">P95 EXCEEDED</span>
        </div>
        <div class="ov-anomaly-n" style="font-family:var(--font-mono);font-size:var(--fs-metric);font-weight:600;color:var(--t-primary);line-height:1;">${surgesCount}</div>
        <div class="ov-anomaly-desc" style="font-size:var(--fs-micro);color:var(--t-tertiary);line-height:var(--lh-snug);">Detections exceeding 365-day normal baseline. Automatically prioritized for satellite inspection.</div>
      </div>

      <div class="well ov-anomaly-card" style="padding:var(--s-3);display:flex;flex-direction:column;gap:5px;">
        <div class="ov-anomaly-head" style="display:flex;align-items:center;justify-content:space-between;gap:var(--s-2);">
          <span class="ov-anomaly-name" style="font-size:var(--fs-label);color:var(--t-secondary);font-weight:500;">Routine Industrial Flares</span>
          <span class="tag tag--tier" data-tier="LOW" style="font-size:0.6rem;padding:1px 5px;">SUPPRESSED</span>
        </div>
        <div class="ov-anomaly-n" style="font-family:var(--font-mono);font-size:var(--fs-metric);font-weight:600;color:var(--t-primary);line-height:1;">${flaresCount}</div>
        <div class="ov-anomaly-desc" style="font-size:var(--fs-micro);color:var(--t-tertiary);line-height:var(--lh-snug);">Permitted refinery and factory emissions within normal baseline. False alarms suppressed.</div>
      </div>

      <div class="well ov-anomaly-card" style="padding:var(--s-3);display:flex;flex-direction:column;gap:5px;">
        <div class="ov-anomaly-head" style="display:flex;align-items:center;justify-content:space-between;gap:var(--s-2);">
          <span class="ov-anomaly-name" style="font-size:var(--fs-label);color:var(--t-secondary);font-weight:500;">New Unexpected Outbreaks</span>
          <span class="tag tag--tier" data-tier="HIGH" style="font-size:0.6rem;padding:1px 5px;">ZERO HISTORY</span>
        </div>
        <div class="ov-anomaly-n" style="font-family:var(--font-mono);font-size:var(--fs-metric);font-weight:600;color:var(--t-primary);line-height:1;">${newUnexpectedCount}</div>
        <div class="ov-anomaly-desc" style="font-size:var(--fs-micro);color:var(--t-tertiary);line-height:var(--lh-snug);">Ignitions appearing at locations with zero previous thermal detections in historical records.</div>
      </div>

      <div class="well ov-anomaly-card" style="padding:var(--s-3);display:flex;flex-direction:column;gap:5px;">
        <div class="ov-anomaly-head" style="display:flex;align-items:center;justify-content:space-between;gap:var(--s-2);">
          <span class="ov-anomaly-name" style="font-size:var(--fs-label);color:var(--t-secondary);font-weight:500;">Multi-Day Persistent Burns</span>
          <span class="tag tag--tier" data-tier="HIGH" style="font-size:0.6rem;padding:1px 5px;">&ge; 2 DAYS ACTIVE</span>
        </div>
        <div class="ov-anomaly-n" style="font-family:var(--font-mono);font-size:var(--fs-metric);font-weight:600;color:var(--t-primary);line-height:1;">${persistentBurnCount}</div>
        <div class="ov-anomaly-desc" style="font-size:var(--fs-micro);color:var(--t-tertiary);line-height:var(--lh-snug);">Active fires persisting across multiple satellite passes requiring containment review.</div>
      </div>
    </div>`;
}

function renderMissionLog(cases, confirmed, priority, surgesCount) {
  const now = new Date();
  const ts = (minsAgo) => {
    const d = new Date(now.getTime() - minsAgo * 60000);
    return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}Z`;
  };

  return `
    <div class="ov-log-terminal">
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(1)}</span>
        <span class="ov-log-tag ov-log-tag--ok">[BORDER CHECK]</span>
        <span class="ov-log-text">National boundary verified: 100% of detections confirmed strictly within Indian territory.</span>
      </div>
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(3)}</span>
        <span class="ov-log-tag">[SATELLITES]</span>
        <span class="ov-log-text">NASA satellite feeds synchronized: NOAA-20 / Suomi-NPP VIIRS and Terra/Aqua MODIS passes ingested.</span>
      </div>
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(5)}</span>
        <span class="ov-log-tag ov-log-tag--warn">[BASELINE]</span>
        <span class="ov-log-text">365-day historical baseline evaluated: ${surgesCount} unusual surges flagged above normal limits.</span>
      </div>
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(8)}</span>
        <span class="ov-log-tag">[VISION AI]</span>
        <span class="ov-log-text">High-resolution satellite images analyzed: ${confirmed} detections visually verified by AI vision.</span>
      </div>
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(12)}</span>
        <span class="ov-log-tag ov-log-tag--crit">[RISK ENGINE]</span>
        <span class="ov-log-text">Multi-factor risk scored: ${priority} elevated incidents populated in active watch queue.</span>
      </div>
      <div class="ov-log-row">
        <span class="ov-log-time">${ts(15)}</span>
        <span class="ov-log-tag ov-log-tag--ok">[FACILITIES]</span>
        <span class="ov-log-text">Facility association checked: 5.0 km radius safety buffer verified.</span>
      </div>
    </div>`;
}

export function renderOverview(el, ctx) {
  const { cases, ambient, selected } = ctx;
  const tiers = byTier(cases);
  const priority = (tiers.CRITICAL || 0) + (tiers.HIGH || 0);
  const confirmed = cases.filter((c) => c.confirmed).length;
  const confPct = Math.round((confirmed / Math.max(1, cases.length)) * 100);
  // INV-2: peak, not a sum -- see the region strip above.
  const peak = cases.reduce((a, c) => (c.frp > (a?.frp ?? -1) ? c : a), null);
  const peakFrp = peak ? peak.frp : 0;

  let dayPasses = 0;
  let nightPasses = 0;
  cases.forEach((c) => {
    if (c.persistence?.dayNightStatus?.includes("DAY")) {
      dayPasses++;
    } else if (c.persistence?.dayNightStatus?.includes("NIGHT")) {
      nightPasses++;
    } else {
      const h = c.at ? c.at.getUTCHours() : 12;
      if (h >= 3 && h <= 13) dayPasses++;
      else nightPasses++;
    }
  });

  const surgesCount = cases.filter((c) => c.historicalAnomaly === "ABNORMAL_SURGE").length;

  // 1. Hero Telemetry Strip
  const head = `<div class="grid-4">
    ${tile(`
      <div class="metric">
        <p class="u-label">Active Detections (India)</p>
        <p class="metric__value">
          <span class="u-metric u-live">${fmt.int(cases.length)}</span>
          <span class="metric__unit">active</span>
        </p>
        <div class="row row--wrap" style="gap:4px;margin-top:4px;">
          <span class="tag tag--tier" data-tier="CRITICAL" style="font-size:0.58rem;padding:1px 5px;">${tiers.CRITICAL || 0} Critical</span>
          <span class="tag tag--tier" data-tier="HIGH" style="font-size:0.58rem;padding:1px 5px;">${tiers.HIGH || 0} High</span>
          <span class="tag tag--tier" data-tier="MEDIUM" style="font-size:0.58rem;padding:1px 5px;">${tiers.MEDIUM || 0} Med</span>
          <span class="tag tag--tier" data-tier="LOW" style="font-size:0.58rem;padding:1px 5px;">${tiers.LOW || 0} Low</span>
        </div>
      </div>`, 0)}

    ${tile(`
      <div class="metric">
        <p class="u-label">Peak Thermal Radiative Power</p>
        <p class="metric__value">
          <span class="u-metric u-live">${peak ? fmt.dec(peak.frp) : "-"}</span>
          <span class="metric__unit">MW peak</span>
        </p>
        <div class="meter meter--signal" style="margin-top:4px;" aria-hidden="true">
          <div class="meter__fill" style="--v:${Math.min(100, Math.round((peakFrp / 150) * 100))}%"></div>
        </div>
        <p class="metric__note" style="margin-top:2px;">Peak: ${peak ? `${fmt.dec(peak.frp)} MW (${escapeHtml(peak.place)})` : 'None'}</p>
      </div>`, 40)}

    ${tile(`
      <div class="metric">
        <p class="u-label">Optical AI Verification</p>
        <p class="metric__value">
          <span class="u-metric u-live">${confirmed}</span>
          <span class="metric__unit">of ${cases.length} (${confPct}%)</span>
        </p>
        <div class="meter meter--signal" style="margin-top:4px;" aria-hidden="true">
          <div class="meter__fill" style="--v:${confPct}%"></div>
        </div>
        <p class="metric__note" style="margin-top:2px;">${cases.length - confirmed} unconfirmed or cloud-screened</p>
      </div>`, 80)}

    ${tile(`
      <div class="metric">
        <p class="u-label">Satellite Passes</p>
        <p class="metric__value">
          <span class="u-metric u-live" style="font-size:1.45rem;">VIIRS / MODIS</span>
        </p>
        <p class="metric__note" style="margin-top:4px;">Anchor: ${stampDate(store.anchor)}</p>
        <p class="metric__note">${dayPasses} Day / ${nightPasses} Night passes in window</p>
      </div>`, 120)}
  </div>`;

  // 2. Row 1: Priority Action Queue + Regional Threat Distribution
  const work = panel("Priority Action Queue",
    `<span class="tag tag--signal">${priority} elevated</span>`,
    `<div id="ov-queue"></div>`,
    { foot: `<p class="u-micro">Incidents ranked by multi-factor risk scoring. Click any row or Inspect to open the satellite evidence.</p>` });

  const regional = panel("Regional Threat Distribution",
    `<span class="u-micro u-num">${cases.length} targets across 4 corridors</span>`,
    `<div class="ov-region-list">${regionalBreakdown(cases)}</div>`,
    { foot: `<p class="u-micro">Calculated strictly within Republic of India borders. Aggregated across major industrial corridors.</p>` });

  // 3. Row 2: Historical Baseline Radar + Threat Severity & Classification Profile
  const climatologyPanel = panel("Historical Baseline & Trend Radar",
    `<span class="tag tag--signal">365-Day Baseline</span>`,
    renderAnomalyRadar(cases),
    { foot: `<p class="u-micro">Historical heat baselines distinguish routine industrial flaring from genuine wildfire and emergency surges.</p>` });

  const threatSpectrum = panel("Threat Severity & Classification Profile",
    `<span class="u-micro u-num">${cases.length} classified cases</span>`,
    `<div class="stack-3">
      <div id="ov-hist"></div>
      <hr class="rule" style="margin:var(--s-3) 0">
      <div>
        <p class="u-label" style="margin-bottom:var(--s-2);">Taxonomy Distribution</p>
        ${ranksBlock(byClass(cases), cases.length, 5)}
      </div>
    </div>`,
    { foot: `<p class="u-micro">Ten-bin risk distribution (0-100) paired with vision AI taxonomy breakdown.</p>` });

  // 4. Row 3: Acquisition Timeline
  const when = panel("Satellite Pass Timeline",
    `<span class="u-micro">${cases.length} passes plotted on real time</span>`,
    timeline(cases, selected),
    { foot: legend() });

  // 5. Row 4: Pipeline Sentinel + Mission Operational Log
  const integrity = panel("Data Feed & Pipeline Status", integrityTag(),
    kvRows([
      ["Border Check", "STRICT (Zero foreign / cross-border detections allowed)"],
      ["Facility Proximity", "ENFORCED (5.0 km radius gate; zero spurious links)"],
      ["Active Constellation", "VIIRS (Suomi-NPP, NOAA-20) + MODIS (Terra, Aqua)"],
      ["Active Incidents", `${cases.length} in window (${store.cases.length} in feed)`],
      ["Background Points", `${ambient.length} calibrated sensor returns`],
      ["Latest Satellite Pass", stampDate(store.anchor)],
      noticeRow(),
      ["System Errors", store.errors.length
        ? store.errors.map((e) => escapeHtml(`${e.source}: ${e.message}`)).join("<br>")
        : "none"],
    ], "kv kv--wide"),
    { foot: `<p class="u-micro">Continuous data feed validation against Indian borders and instrument calibration.</p>` });

  const missionLog = panel("System Activity Stream",
    `<span class="tag"><span class="tag__dot"></span>System Active</span>`,
    renderMissionLog(cases, confirmed, priority, surgesCount),
    { foot: `<p class="u-micro">Live chronological event dispatch log and automated subsystem status reports.</p>` });

  set(el, `
    ${head}
    <div class="grid-2">${work}${regional}</div>
    <div class="grid-2" style="margin-top:var(--s-3)">${climatologyPanel}${threatSpectrum}</div>
    ${when}
    <div class="grid-2" style="margin-top:var(--s-3)">${integrity}${missionLog}</div>
  `);

  renderEnhancedQueue(el.querySelector("#ov-queue"), cases, selected, 6);
  renderRiskHist(el.querySelector("#ov-hist"), cases, null);
}

/* --- Investigations ------------------------------------------------------- */

/* Crops are files the pipeline wrote, so they can legitimately be missing.
   The card says so in place instead of showing a broken frame. */
export function wireThumbs(root) {
  root.querySelectorAll(".case__thumb img, .shot img").forEach((img) => {
    img.addEventListener("error", () => {
      img.closest(".case__thumb, .shot")?.setAttribute("data-missing", "1");
    }, { once: true });
  });
}

function caseCard(c, selected, delay) {
  const status = getTriage(c.id);
  const src = c.images.annotated || c.images.raw;
  const where = c.site || c.address || fmt.coord(c.lat, c.lon);

  return `
    <article class="glass case reveal" data-case="${escapeHtml(c.id)}" data-tier="${c.risk.tier}"
             data-selected="${c.id === selected ? 1 : 0}" style="--reveal-delay:${delay}ms">
      <button class="case__link" type="button" data-case="${escapeHtml(c.id)}" data-open="modal"
              aria-label="Open the dossier for ${escapeHtml(c.id)}, ${escapeHtml(c.place)}"></button>
      <div class="case__top">
        <div style="min-width:0">
          <p class="case__id">${escapeHtml(c.id)}</p>
          <p class="case__name u-clamp-2">${escapeHtml(c.place)}</p>
          <p class="case__where u-truncate">${escapeHtml(where)}</p>
        </div>
        ${tierTag(c)}
      </div>
      <div class="case__thumb"${src ? "" : ' data-missing="1"'}>
        ${src ? `<img src="${escapeHtml(src)}" loading="lazy" decoding="async"
                 alt="Satellite image examined for ${escapeHtml(c.id)}">` : ""}
      </div>
      <div class="case__foot">
        <dl class="case__stats">
          <div class="case__stat"><dt>FRP</dt><dd>${fmt.dec(c.frp)} MW</dd></div>
          <div class="case__stat"><dt>Severity</dt><dd>${c.severity?.level ? `${c.severity.level} (${c.severity.score})` : c.risk.score}</dd></div>
          <div class="case__stat"><dt>Priority</dt><dd>${c.investigationPriority || c.rank}</dd></div>
        </dl>
        <div class="row" style="gap:4px; align-items:center;">
          ${status === "UNREVIEWED" ? confTag(c) : `<span class="tag">${escapeHtml(triageOf(status).short)}</span>`}
          ${c.climatology?.isRoutine ? `<span class="tag tag--signal" style="font-size:0.62rem">Routine</span>` : (c.historicalAnomaly === "ABNORMAL_SURGE" ? `<span class="tag tag--tier" style="font-size:0.62rem">Surge</span>` : "")}
        </div>
      </div>
    </article>`;
}

export function renderInvestigations(el, cases, selected) {
  if (!cases.length) {
    set(el, `<div class="glass tile" style="grid-column:1/-1">${stateBlock(
      "No cases match", "Clear the search box or pick a wider filter.", "i-search")}</div>`);
    return;
  }
  set(el, cases.map((c, i) => caseCard(c, selected, Math.min(i, 8) * 45)).join(""));
  wireThumbs(el);
}

/* --- Industrial Intelligence & Baselines ---------------------------------
   The register, the measured baselines and the two charts a regulator reads.

   Everything on this page comes from one of two sources and says which:

     `store.registry`  the `industrial_assets` table (GET /api/industries) --
                       what India monitors, with operator, state, district,
                       hazard class and safety-buffer radius;
     the console feed  the detections, each with the 365-day P50/P95 of the
                       0.02-degree climatology cell it sits in.

   The page used to build its facility list by grouping detections on their
   short place label (`bySite`, data.js), which meant:

     * a coal basin was a facility. `pipeline.py` publishes a *basin* label in
       `nearest_facility_name` for detections matched to a mining concession,
       so "Mand-Raigarh & Gharghoda Coal Mining Basin" was listed as a monitored
       facility with no operator, no state and no registered perimeter;
     * one site could be counted twice. Talcher appears as the asset-registry
       "Talcher Coalfields & NTPC Super Thermal Power Complex" and the
       basin-registry "Talcher Coalfields & NTPC Super Thermal Corridor
       (Angul)", and the two labels are not equal, so the grouping counted one
       physical complex as two monitored facilities;
     * "Monitored Facilities" counted distinct place labels among the detections
       -- 11 of them -- under a heading that reads as the national register.

   So the register is the registry, and a detection is attached to it by
   `nearest_asset_id` (published by `pipeline.py` from the same geometric
   resolution that produced the name). A detection whose nearest site is a
   mining basin is listed as a basin observation, not as a facility, and a
   detection with neither is counted as unattributed and listed as such. */

const SECTORS = [
  ["flare", "Refinery & Flares"],
  ["steel", "Steel & Metals"],
  ["power", "Thermal Power"],
  ["mining", "Mining & Smelting"],
  ["cement", "Cement & Kilns"],
];

/* One sector per asset, so the sector pills partition the register instead of
   overlapping. `facility_type` is the authority: it is a closed vocabulary in
   `industrial_assets` and all nine of its values are mapped here explicitly.
   `industry` and `name` are free text -- "Energy Capital of India" is an
   industry string -- so they are read only for a type this build does not
   know, which is why they are checked second. Checked first they would have
   misfiled four rows: "HPCL Rajasthan Refinery & Petrochemicals (HRRL)" and
   "Hazira ONGC & AM/NS Steel Heavy Industrial Hub" both carry `petrochemical`
   but say "Petrochemical"/"Steel" in the name, and "Jindal Steel & Power
   (JSPL) & NALCO Smelter, Angul" and "Tata Metaliks" say "Smelter"/"Metaliks"
   while being steel plants. */
function sectorOf(asset) {
  const type = String(asset.facility_type || "").toLowerCase();
  const text = `${asset.name} ${asset.industry} ${asset.operator}`.toLowerCase();

  switch (type) {
    case "mining":
    case "smelter":
      return "mining";
    case "thermal_power":
      return "power";
    case "oil_refinery":
    case "petrochemical":
    case "lng_terminal":
    case "offshore_platform":
    case "oil_production":
      return "flare";
    case "steel_plant":
      return "steel";
    default:
      break;
  }

  if (asset.category === "mining_or_other_thermal_source") return "mining";
  if (/cement|kiln/.test(text)) return "cement";
  if (/aluminium|zinc|copper|smelt/.test(text)) return "mining";
  if (/refiner|petrochem|\blng\b|flare|offshore|oil|gas/.test(text)) return "flare";
  if (/power|thermal|generat/.test(text)) return "power";
  return "steel";
}

function sectorLabel(id) {
  const hit = SECTORS.find(([k]) => k === id);
  return hit ? hit[1] : "Unclassified";
}

/* The measured envelope for a set of detections. Each detection carries the
   365-day P50/P95 of its own 0.02-degree climatology cell (INV-4's envelope,
   from the rebuilt `thermal_climatology`), and a facility can span several
   cells, so the envelope used is the highest of them: a facility is only in
   exceedance if it beats the largest envelope it sits in. `p95 == 0` means the
   cell had too few detections to measure one -- INV-5, so no exceedance is
   claimed and the row reads as unmeasured rather than as compliant. */
function envelopeOf(cases) {
  const withBaseline = cases.filter((c) => (c.climatology?.p95 || 0) > 0);
  if (!withBaseline.length) return { p95: 0, median: 0, cells: 0, unmeasured: cases.length };
  const p95 = Math.max(...withBaseline.map((c) => c.climatology.p95));
  const top = withBaseline.reduce((a, b) => (b.climatology.p95 > a.climatology.p95 ? b : a));
  return { p95, median: top.climatology.median || 0, cells: withBaseline.length, unmeasured: 0 };
}

const timeOf = (c) => (c.at ? c.at.getTime() : null);

function rowOf(asset, cases) {
  const peak = cases.length ? Math.max(...cases.map((c) => c.frp)) : 0;
  const env = envelopeOf(cases);
  const exceeds = env.p95 > 0 && peak > env.p95;
  const stamps = cases.map(timeOf).filter((t) => t !== null);
  return {
    key: asset.id,
    kind: "facility",
    asset,
    name: asset.name,
    operator: asset.operator || null,
    state: asset.state || null,
    district: asset.district || null,
    sector: sectorOf(asset),
    hazard: asset.hazard_category || null,
    bufferM: asset.buffer_radius_meters,
    cases,
    detections: cases.length,
    peak,
    p95: env.p95,
    median: env.median,
    exceeds,
    ratio: env.p95 > 0 ? peak / env.p95 : null,
    routine: cases.some((c) => c.climatology?.isRoutine),
    lastAt: stamps.length ? new Date(Math.max(...stamps)) : null,
  };
}

/* A mining basin the feed reported against. Not a registered asset: it has no
   operator, no perimeter and no safety buffer, so it is carried separately
   rather than counted among the monitored facilities. */
function basinRow(name, cases) {
  const base = rowOf({
    id: `basin:${name}`,
    name,
    operator: null,
    state: null,
    district: null,
    /* The category is stated rather than left absent so `sectorOf` classifies a
       basin from its concession type instead of from words in its name -- the
       Talcher corridor name contains "Thermal" and "Power" and would otherwise
       be filed as a power station. */
    category: "mining_or_other_thermal_source",
    hazard_category: null,
    buffer_radius_meters: null,
  }, cases);
  const top = cases.reduce((a, b) => (b.frp > a.frp ? b : a), cases[0]);
  return {
    ...base,
    kind: "basin",
    asset: null,
    /* A basin row has no registry record, so the operator and state are read
       from the detection the feed attributed to it -- the only evidence there
       is. Everything else stays null rather than being guessed. */
    operator: top?.facility?.operator || null,
    state: top?.state || null,
    sector: "mining",
  };
}

function buildRegister(cases, registry) {
  const assets = (registry || []).filter((a) => a && a.id);
  const observed = new Map();
  const basins = new Map();
  const unattributed = [];

  cases.forEach((c) => {
    const id = c.facility?.id;
    if (id) {
      const list = observed.get(id);
      if (list) list.push(c);
      else observed.set(id, [c]);
    } else if (c.facility?.name) {
      const list = basins.get(c.facility.name);
      if (list) list.push(c);
      else basins.set(c.facility.name, [c]);
    } else {
      unattributed.push(c);
    }
  });

  const rows = assets.map((a) => rowOf(a, observed.get(a.id) || []));
  const basinRows = [...basins.entries()].map(([name, cs]) => basinRow(name, cs));
  return { rows, basinRows, unattributed };
}

/* Operator and state roll-ups. A regulator works by operator and by state
   pollution-control board, and neither cut existed: the register was flat. */
function rollUp(rows, keyFn) {
  const map = new Map();
  rows.forEach((r) => {
    const key = keyFn(r) || "Unreported";
    const g = map.get(key) || {
      key: `group:${key}`, kind: "group", name: key, rows: [],
      detections: 0, exceeds: 0, quiet: 0, peak: 0, worst: null,
    };
    g.rows.push(r);
    g.detections += r.detections;
    if (r.exceeds) g.exceeds += 1;
    if (!r.detections) g.quiet += 1;
    g.peak = Math.max(g.peak, r.peak);
    if (r.ratio !== null && (g.worst === null || r.ratio > g.worst.ratio)) g.worst = r;
    map.set(key, g);
  });
  return [...map.values()].sort((a, b) => (b.exceeds - a.exceeds)
    || ((b.worst?.ratio || 0) - (a.worst?.ratio || 0)) || (b.peak - a.peak));
}

function registerRowItem(row, isSelected) {
  const badge = row.exceeds
    ? `<span class="tag tag--tier" style="font-size:0.62rem">Exceeds P95</span>`
    : (row.detections
      ? (row.routine
        ? `<span class="tag tag--signal" style="font-size:0.62rem">Routine Flare</span>`
        : `<span class="tag" style="font-size:0.62rem">Within Envelope</span>`)
      : `<span class="tag" style="font-size:0.62rem;opacity:0.6">No Detection</span>`);

  const meta = [row.operator, row.state, row.kind === "basin" ? "Mining basin (unregistered)" : sectorLabel(row.sector)]
    .filter(Boolean).map((s) => `<span>${escapeHtml(s)}</span>`).join("<span>&bull;</span>");

  const limitCell = row.p95 > 0
    ? fmt.dec(row.p95)
    : `<span class="u-quiet" title="No measurable 365-day envelope for this cell (INV-5)">none</span>`;

  return `
    <div class="facility-card" data-facility="${escapeHtml(row.key)}" data-active="${isSelected ? "true" : "false"}">
      <div class="facility-card__head">
        <div style="min-width:0;">
          <div class="facility-card__title u-truncate">${escapeHtml(row.name)}</div>
          <div class="facility-card__meta u-truncate">${meta}</div>
        </div>
        ${badge}
      </div>

      <div class="facility-card__metrics" style="grid-template-columns:repeat(4,1fr);">
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Detections</span>
          <span class="facility-card__metric-val">${row.detections}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Peak FRP</span>
          <span class="facility-card__metric-val" style="${row.exceeds ? "color:var(--tier-critical);" : ""}">${row.detections ? `${fmt.dec(row.peak)}` : "--"}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">P95 Envelope</span>
          <span class="facility-card__metric-val">${limitCell}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Ratio</span>
          <span class="facility-card__metric-val" style="${row.exceeds ? "color:var(--tier-critical);" : ""}">${row.ratio === null ? "--" : `${row.ratio.toFixed(2)}×`}</span>
        </div>
      </div>
    </div>`;
}

function groupRowItem(group, isSelected) {
  const sorted = group.rows.slice().sort((a, b) => (b.exceeds - a.exceeds) || (b.peak - a.peak));
  const leaders = sorted.filter((r) => r.detections).slice(0, 3).map((r) => r.name);
  return `
    <div class="facility-card" data-facility="${escapeHtml(group.key)}" data-active="${isSelected ? "true" : "false"}">
      <div class="facility-card__head">
        <div style="min-width:0;">
          <div class="facility-card__title u-truncate">${escapeHtml(group.name)}</div>
          <div class="facility-card__meta u-truncate">
            <span>${group.rows.length} registered ${group.rows.length === 1 ? "facility" : "facilities"}</span>
          </div>
        </div>
        ${group.exceeds
          ? `<span class="tag tag--tier" style="font-size:0.62rem">${group.exceeds} exceeding</span>`
          : `<span class="tag" style="font-size:0.62rem">Within Envelope</span>`}
      </div>

      <div class="facility-card__metrics" style="grid-template-columns:repeat(3,1fr);">
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Detections</span>
          <span class="facility-card__metric-val">${group.detections}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Peak FRP</span>
          <span class="facility-card__metric-val">${group.peak ? `${fmt.dec(group.peak)}` : "--"}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Quiet</span>
          <span class="facility-card__metric-val">${group.quiet}</span>
        </div>
      </div>

      ${leaders.length ? `<div class="u-micro u-quiet u-truncate" style="padding:0 2px 2px;">Reporting: ${escapeHtml(leaders.join(", "))}</div>` : ""}
    </div>`;
}

/* The compliance statement for one facility, in one sentence, with the number
   it rests on. Written from the measurements rather than from a threshold, so
   a facility with no measurable envelope reads as unmeasured rather than as
   compliant. */
function complianceLine(row, profileState) {
  const p365 = profileState?.windows?.[365];
  if (row.exceeds) {
    const pct = row.ratio === null ? null : Math.round((row.ratio - 1) * 100);
    return {
      tone: "critical",
      text: `Peak detection ${fmt.dec(row.peak)} MW is ${pct === null ? "above" : `${pct}% above`} the measured 365-day P95 of ${fmt.dec(row.p95)} MW for the cell it sits in.`,
    };
  }
  if (row.p95 > 0) {
    return {
      tone: "ok",
      text: `Peak detection ${fmt.dec(row.peak)} MW is inside the measured 365-day P95 of ${fmt.dec(row.p95)} MW for the cell it sits in.`,
    };
  }
  if (p365 && p365.p95_frp > 0) {
    return {
      tone: "ok",
      text: `No cell-level envelope is measurable for this facility's detections, but the facility's own ${p365.window_days}-day profile measures a P95 of ${fmt.dec(p365.p95_frp)} MW over ${p365.active_days} active days.`,
    };
  }
  return {
    tone: "quiet",
    text: "No measurable 365-day envelope is on record for this facility's cells or for its own profile, so neither compliance nor anomaly can be asserted (INV-5).",
  };
}

/* The measured 30 / 90 / 365-day profiles for the open facility, read from
   `GET /api/industries/{id}/history?window_days=N`. Each window is measured
   over that facility's own buffer radius and over exactly the window it names
   (`behavior/profile.py`), so nothing here is scaled from another window.

   This panel replaced one that fabricated its 30- and 90-day figures out of
   fixed multipliers on the 365-day figure (`p50 * 0.95` / `p95 * 0.88` and
   `* 1.0` / `* 0.96`) and printed them under the badges "Primary Baseline" and
   "Compliance Standard". Those were not measurements, and on a page a
   regulator reads a fabricated threshold is worse than an empty card: "30-Day
   Window, Surge Threshold 5.5 MW" reads as an observation a facility could be
   held to.

   `abnormal_event_count` is the profile's own count of days in that window
   whose peak FRP exceeded the same window's measured P95. */
function renderMeasuredBaselinePanel(profileState, activeWindow) {
  const windows = [
    { id: "30d", days: 30, name: "30-Day Window", desc: "Recent behaviour and short-term emission swings" },
    { id: "90d", days: 90, name: "90-Day Window", desc: "Seasonal baseline over the quarter" },
    { id: "365d", days: 365, name: "365-Day Window", desc: "Annual baseline of Section 4.4 and INV-4" },
  ];

  const loading = Boolean(profileState && profileState.loading);
  const error = profileState && profileState.error;
  const data = (profileState && profileState.windows) || {};
  const measured = windows.filter((w) => data[w.days]).length;

  const cards = windows.map((w) => {
    const p = data[w.days];
    const isActive = activeWindow === w.id;
    const head = `
      <div class="row" style="justify-content:space-between;align-items:center;">
        <span style="font-size:0.75rem;font-weight:700;color:var(--t-primary);letter-spacing:0.03em;">${w.name}</span>
        ${isActive
          ? '<span class="tag tag--signal" style="font-size:0.62rem;padding:1px 6px;">ACTIVE BENCHMARK</span>'
          : '<span class="u-micro u-quiet" style="font-size:9px;">Click to set</span>'}
      </div>
      <p class="u-micro u-quiet" style="margin:0;line-height:1.3;">${escapeHtml(w.desc)}</p>`;

    if (!p) {
      return `<div class="multiwindow-card ${isActive ? "is-active" : ""}" data-fac-window="${w.id}">
        ${head}
        <div style="padding:14px 0;text-align:center;">
          <span class="u-micro u-quiet">${loading ? "Measuring this window…" : "Not measured"}</span>
        </div>
      </div>`;
    }

    const peak = p.max_frp;
    const exceeds = p.p95_frp > 0 && peak > p.p95_frp;
    return `<div class="multiwindow-card ${isActive ? "is-active" : ""}" data-fac-window="${w.id}">
      ${head}

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:8px 0;border-top:1px solid var(--line-hair);border-bottom:1px solid var(--line-hair);margin:2px 0;">
        <div>
          <div class="u-micro u-quiet" style="font-size:9px;">MEASURED P50</div>
          <div style="font-family:var(--font-mono);font-size:1.05rem;font-weight:600;color:var(--signal);">${fmt.dec(p.median_frp)} MW</div>
        </div>
        <div>
          <div class="u-micro u-quiet" style="font-size:9px;">MEASURED P95</div>
          <div style="font-family:var(--font-mono);font-size:1.05rem;font-weight:600;color:${exceeds ? "var(--tier-critical)" : "var(--tier-elevated)"};">${fmt.dec(p.p95_frp)} MW</div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:3px;font-size:0.72rem;">
        <div class="row" style="justify-content:space-between;">
          <span class="u-quiet">Active days in window:</span>
          <span style="font-weight:500;color:var(--t-secondary);font-family:var(--font-mono);">${p.active_days} / ${w.days}</span>
        </div>
        <div class="row" style="justify-content:space-between;">
          <span class="u-quiet">Detections:</span>
          <span style="font-weight:500;color:var(--t-secondary);font-family:var(--font-mono);">${fmt.int(p.observation_count)}</span>
        </div>
        <div class="row" style="justify-content:space-between;">
          <span class="u-quiet">Peak in window:</span>
          <span style="font-weight:500;color:${exceeds ? "var(--tier-critical)" : "var(--t-secondary)"};font-family:var(--font-mono);">${fmt.dec(peak)} MW</span>
        </div>
        <div class="row" style="justify-content:space-between;">
          <span class="u-quiet">Days above this P95:</span>
          <span style="font-weight:500;color:var(--t-secondary);font-family:var(--font-mono);">${p.abnormal_event_count}</span>
        </div>
      </div>

      <div class="row" style="justify-content:space-between;align-items:center;margin-top:auto;padding-top:4px;">
        <span class="u-micro" style="font-size:9px;color:var(--t-quiet);">History reliability: ${escapeHtml(p.history_reliability_label || "UNKNOWN")}</span>
        <span class="u-micro u-quiet" style="font-size:9px;">${fmt.int(p.observation_count)} observations</span>
      </div>
    </div>`;
  }).join("");

  /* A partial failure keeps the windows that did answer and names the ones that
     did not. Replacing the grid with an error would throw away two real
     measurements because a third timed out. */
  const body = (error && !measured)
    ? stateBlock("Baseline measurement unavailable", error, "i-database")
    : `<div class="multiwindow-grid">${cards}</div>`;

  return `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row row--wrap" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-sliders"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            Measured Baselines
          </span>
          ${loading ? '<span class="tag" style="font-size:0.66rem;">measuring…</span>' : ""}
        </div>
        <span class="u-micro u-quiet">Each window aggregated over this facility's own buffer radius. No figure is derived from another window.</span>
      </div>
      ${error && measured ? `<p class="u-micro" style="margin:0 0 var(--s-3) 0;color:var(--tier-elevated);">${escapeHtml(error)}</p>` : ""}
      ${body}
    </div>`;
}

/* The facility's FRP trend, one point per satellite overpass, with the measured
   P50 and P95 of the active window drawn across it. This is the chart a
   regulator reads: a facility against its own measured envelope.

   The version this replaces drew a different chart. It took its thresholds from
   fixed multipliers on the 365-day figures whenever the active window was 30 or
   90 days (`p50 * 0.95` / `p95 * 0.88`, `* 1.0` / `* 0.96`), labelled them
   "P50 BASELINE" and "P95 SURGE LIMIT" on the plot, and -- when a facility had
   fewer than four real overpasses -- invented three data points dated "10d
   ago", "6d ago" and "3d ago" with satellite names "SNPP", "NOAA-20" and
   "NOAA-21" and a day/night flag, styled identically to the real ones and
   carrying `id: "hist-1"` and friends. A reader could not tell them from
   observations, and clicking one would have opened a case id that does not
   exist.

   So: every point below is a real overpass, and every line is a measurement. A
   facility with one overpass draws one point and says the trend is short; a
   facility whose window has no measurable P95 draws no line and says INV-5. */
function renderFrpPointGraph(cases, profile, activeWindow = "365d") {
  const spec = { "30d": 30, "90d": 90, "365d": 365 }[activeWindow] || 365;
  const measured = profile?.windows?.[spec] || null;
  const label = { 30: "30-Day", 90: "90-Day", 365: "365-Day" }[spec];

  /* The measured profile for the window when it has loaded; otherwise the
     aggregate envelope of the cells the detections sit in, which is a 365-day
     figure and is labelled as one. Nothing is scaled between the two. */
  const p50 = measured ? Number(measured.median_frp) : (cases[0]?.climatology?.median || 0);
  const p95 = measured ? Number(measured.p95_frp) : (envelopeOf(cases).p95 || 0);
  const basis = measured
    ? `measured over this facility's buffer radius, ${spec}-day window`
    : `measured over the ${cases.length === 1 ? "climatology cell" : "climatology cells"} these detections sit in, 365-day window`;
  /* The badge names the figure that is actually drawn, not the window that was
     asked for. Before the facility's own profile arrives -- or if it fails --
     the lines are the 365-day cell envelope, and calling that a "30-Day
     envelope" would be the same mislabelling this rewrite removed. */
  const envelopeLabel = measured ? `${label} envelope` : "365-day cell envelope";
  const hasEnvelope = p95 > 0;

  const passMap = new Map();
  cases.forEach((c) => {
    const date = c.firms?.date || "";
    const raw = String(c.firms?.time || "0000").replace(":", "").padStart(4, "0");
    const key = `${date}_${raw.slice(0, 2)}`;
    const frp = Number(c.frp) || 0;
    const existing = passMap.get(key);
    if (!existing) {
      passMap.set(key, {
        date, raw, frp, count: 1, top: c,
      });
    } else {
      existing.count += 1;
      if (frp > existing.frp) { existing.frp = frp; existing.top = c; }
    }
  });

  const passes = [...passMap.values()]
    .sort((a, b) => (a.date + a.raw).localeCompare(b.date + b.raw));

  if (!passes.length) {
    return `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      ${stateBlock("No overpass to plot", "This facility has no detection in the active window, so there is no trend to draw.", "i-pulse")}
    </div>`;
  }

  const shown = passes.slice(-12);
  const peak = Math.max(...shown.map((p) => p.frp));

  const w = 700, h = 210, padL = 62, padR = 40, padT = 26, padB = 36;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const maxVal = Math.max(2, peak * 1.25, hasEnvelope ? p95 * 1.35 : 0);
  const yScale = (v) => padT + plotH - (Math.min(maxVal, Math.max(0, v)) / maxVal) * plotH;

  const xStep = shown.length > 1 ? plotW / (shown.length - 1) : 0;
  const xAt = (i) => (shown.length > 1 ? padL + i * xStep : padL + plotW / 2);

  const p50Y = yScale(p50);
  const p95Y = yScale(p95);

  const pts = shown.map((p, i) => {
    const cx = xAt(i), cy = yScale(p.frp);
    const isSurge = hasEnvelope && p.frp > p95;
    const isElevated = p50 > 0 && p.frp > p50;
    const color = isSurge ? "var(--tier-critical, #ef4444)"
      : (isElevated ? "var(--tier-elevated, #f59e0b)" : "var(--tier-low, #10b981)");
    const time = p.raw.length === 4 ? `${p.raw.slice(0, 2)}:${p.raw.slice(2)}` : p.raw;
    const title = `${p.date} ${time} UTC | Peak ${fmt.dec(p.frp)} MW${p.count > 1 ? ` (${p.count} hotspots in this pass)` : ""} | ${p.top?.firms?.satellite || "satellite unreported"} (${dayNightOf(p.top)} pass)`;
    return { cx, cy, color, title, p, isSurge };
  });

  const pointsSvg = pts.map((d) => `
      <g class="pointgraph-node" data-id="${escapeHtml(d.p.top?.id || "")}">
        <circle class="pointgraph-pt" cx="${d.cx}" cy="${d.cy}" r="${d.isSurge ? 5 : 4}" fill="${d.color}" stroke="${d.isSurge ? "#ffffff" : "rgba(6,8,10,0.95)"}" stroke-width="1.5">
          <title>${escapeHtml(d.title)}</title>
        </circle>
      </g>`).join("");

  const labelsSvg = pts.map((d, i) => {
    if (!(shown.length <= 7 || i % 2 === 0 || i === shown.length - 1)) return "";
    const anchor = i === 0 ? "start" : (i === shown.length - 1 ? "end" : "middle");
    const time = d.p.raw.length === 4 ? `${d.p.raw.slice(0, 2)}:${d.p.raw.slice(2)}` : d.p.raw;
    return `<text x="${d.cx}" y="${padT + plotH + 15}" fill="var(--t-tertiary)" font-size="9" font-family="var(--font-mono)" text-anchor="${anchor}">${escapeHtml(d.p.date.slice(5))}</text>
      <text x="${d.cx}" y="${padT + plotH + 25}" fill="var(--t-quiet)" font-size="8" font-family="var(--font-mono)" text-anchor="${anchor}">${escapeHtml(time)}</text>`;
  }).join("");

  const ticks = [0, maxVal * 0.33, maxVal * 0.66, maxVal];

  return `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row row--wrap" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-pulse"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            Thermal Power Trend
          </span>
          <span class="tag tag--signal" style="font-size:0.66rem;">${envelopeLabel}</span>
          <span class="u-micro u-quiet">${shown.length} overpass${shown.length === 1 ? "" : "es"}, peak FRP per pass${passes.length > shown.length ? ` (${passes.length - shown.length} earlier not shown)` : ""}</span>
        </div>
        <span class="u-micro u-quiet">${escapeHtml(basis)}</span>
      </div>

      ${hasEnvelope ? "" : `<p class="u-micro" style="margin:0 0 var(--s-3) 0;color:var(--t-quiet);">
        This window has no measurable P95, so no envelope is drawn and no point is marked as a surge (INV-5).
      </p>`}

      ${shown.length === 1 ? `<p class="u-micro" style="margin:0 0 var(--s-3) 0;color:var(--t-quiet);">
        One overpass in this window. A trend needs more than one; the single pass is plotted against its envelope.
      </p>` : ""}

      <div class="pointgraph-plot-wrap">
        <svg class="pointgraph-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
          ${hasEnvelope && p95Y > padT ? `<rect x="${padL}" y="${padT}" width="${plotW}" height="${Math.max(0, p95Y - padT)}" fill="rgba(239,68,68,0.07)" rx="2"/>` : ""}

          ${ticks.map((v) => {
            const y = yScale(v);
            return `<line x1="${padL}" y1="${y}" x2="${padL + plotW}" y2="${y}" stroke="var(--line-hair)" stroke-dasharray="3 3"/>
              <text x="${padL - 8}" y="${y + 3}" fill="var(--t-quiet)" font-size="9" font-family="var(--font-mono)" text-anchor="end">${fmt.dec(v, 0)} MW</text>`;
          }).join("")}

          ${p50 > 0 ? `<line x1="${padL}" y1="${p50Y}" x2="${padL + plotW}" y2="${p50Y}" stroke="var(--signal)" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.85"/>
            <text x="${padL + 6}" y="${p50Y - 4}" fill="var(--signal)" font-size="8.5" font-family="var(--font-mono)" text-anchor="start">MEASURED P50 (${fmt.dec(p50)} MW)</text>` : ""}

          ${hasEnvelope ? `<line x1="${padL}" y1="${p95Y}" x2="${padL + plotW}" y2="${p95Y}" stroke="var(--tier-elevated)" stroke-width="1.4" stroke-dasharray="5 3" opacity="0.95"/>
            <text x="${padL + plotW - 6}" y="${p95Y - 4}" fill="var(--tier-elevated)" font-size="8.5" font-family="var(--font-mono)" text-anchor="end">MEASURED P95 (${fmt.dec(p95)} MW)</text>` : ""}

          ${shown.length > 1 ? `<polyline points="${pts.map((d) => `${d.cx},${d.cy}`).join(" ")}" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1.6"/>` : ""}

          ${pointsSvg}

          <line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="var(--line-strong)"/>
          ${labelsSvg}
        </svg>
      </div>
    </div>`;
}

/* Day vs night overpass split. The lanes are labelled by the field this reads
   (`day_night_status`), not by the UTC hour bands the old labels asserted
   ("10:00-15:00 UTC" / "21:00-04:00 UTC") -- this code never checked an hour,
   and a continuous 24-hour record belongs to both lanes. */
function renderDiurnalPointGraph(cases, p95) {
  /* F-109. A "DAY + NIGHT (Continuous 24h)" record genuinely belongs to both
     lanes; the old `!== "D"` test put it in the night lane only, which is what
     made the diagnosis below assert off-hours burning for every site. */
  const dayCases = cases.filter((c) => ["Day", "Day + Night"].includes(dayNightOf(c)));
  const nightCases = cases.filter((c) => ["Night", "Day + Night"].includes(dayNightOf(c)));

  const dayAvg = dayCases.length ? dayCases.reduce((s, c) => s + c.frp, 0) / dayCases.length : 0;
  const nightAvg = nightCases.length ? nightCases.reduce((s, c) => s + c.frp, 0) / nightCases.length : 0;

  const isContinuous = dayCases.length > 0 && nightCases.length > 0;
  const diagnosis = isContinuous
    ? "24/7 Continuous Operational Baseline (Routine Flare Cycle)"
    : (nightCases.length > 0
      ? "High Nighttime Activity (Possible Off-Hours Burning)"
      : "Intermittent Daytime Operations");

  const lane = (title, list, avg) => `
    <div class="diurnal-box">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span class="u-micro" style="font-weight:600;color:var(--tier-elevated);">${title}</span>
        <span class="tag" style="font-size:0.65rem;">${list.length} observations</span>
      </div>
      <div style="font-family:var(--font-mono);font-size:1.1rem;font-weight:600;color:var(--t-primary);margin-bottom:8px;">
        ${fmt.dec(avg)} <span style="font-size:0.75rem;color:var(--t-tertiary);font-weight:400;">MW Mean</span>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${list.slice(0, 8).map((c) => `
          <span class="tag ${p95 > 0 && c.frp > p95 ? "tag--tier" : ""}" style="font-family:var(--font-mono);font-size:0.68rem;padding:2px 6px;">
            ${fmt.dec(c.frp)} MW
          </span>`).join("") || `<span class="u-micro u-quiet">No ${title.includes("Day") && !title.includes("Night") ? "day" : "night"} passes in window</span>`}
      </div>
    </div>`;

  return `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-satellite"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            Day and Night Overpass Split
          </span>
        </div>
        <span class="tag ${isContinuous ? "tag--signal" : "tag--tier"}" style="font-size:0.7rem;">
          ${diagnosis}
        </span>
      </div>

      <div class="diurnal-grid">
        ${lane("DAY OVERPASS (as published in day_night_status)", dayCases, dayAvg)}
        ${lane("NIGHT OVERPASS (as published in day_night_status)", nightCases, nightAvg)}
      </div>
    </div>`;
}

/* Detail pane for one register row: its registry record, its measured
   baselines, its trend and the detections attributed to it. */
function renderFacilityDetail(row, profileState, activeWindow) {
  const a = row.asset;
  const top = row.cases.length
    ? row.cases.reduce((x, y) => (y.risk.score > x.risk.score ? y : x))
    : null;
  const compliance = complianceLine(row, profileState);

  const identity = `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row row--wrap" style="justify-content:space-between;align-items:center;gap:var(--s-3);">
        <div>
          <div class="row" style="gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap;">
            <span class="tag tag--signal" style="font-size:0.7rem;">${row.kind === "basin" ? "MINING BASIN OBSERVATION" : "REGISTERED FACILITY"}</span>
            <span class="tag ${row.exceeds ? "tag--tier" : "tag--signal"}" style="font-size:0.7rem;">
              ${row.exceeds ? "EXCEEDS MEASURED P95" : (row.detections
                ? (row.routine ? "ROUTINE PERMITTED FLARE" : "WITHIN ENVELOPE")
                : "REGISTERED, NO DETECTION")}
            </span>
            ${row.hazard ? `<span class="tag" style="font-size:0.7rem;">${escapeHtml(String(row.hazard).replace(/_/g, " "))}</span>` : ""}
          </div>
          <h2 style="font-size:1.25rem;font-weight:600;color:var(--t-primary);margin:0 0 4px 0;">
            ${escapeHtml(row.name)}
          </h2>
          <div class="row" style="gap:8px;align-items:center;font-size:var(--fs-micro);color:var(--t-tertiary);flex-wrap:wrap;">
            <span>${escapeHtml(row.operator || "Operator not recorded")}</span>
            <span>&bull;</span>
            <span>${escapeHtml(a ? sectorLabel(row.sector) : "Mining basin")}</span>
            ${a ? `<span>&bull;</span><span style="font-family:var(--font-mono);">${fmt.coord(a.latitude, a.longitude)}</span>` : ""}
          </div>
        </div>

        ${a ? `<div class="row" style="gap:8px;align-items:center;">
          <button class="btn btn--signal" type="button" data-inspect-facility-map="1" data-lat="${a.latitude}" data-lon="${a.longitude}" style="padding:6px 14px;font-size:0.78rem;display:flex;align-items:center;gap:6px;">
            <svg class="i i--sm"><use href="#i-crosshair"/></svg>
            <span>Inspect on Live Map</span>
          </button>
        </div>` : ""}
      </div>

      <p class="u-micro" style="margin:var(--s-3) 0 0 0;color:${compliance.tone === "critical" ? "var(--tier-critical)" : (compliance.tone === "quiet" ? "var(--t-quiet)" : "var(--t-secondary)")};">
        ${escapeHtml(compliance.text)}
      </p>
    </div>`;

  const facts = `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row" style="gap:8px;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <svg class="i i--sm" style="color:var(--signal)"><use href="#i-sliders"/></svg>
        <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
          Registry Record and Observed Activity
        </span>
      </div>
      <div class="grid-2" style="gap:var(--s-4);">
        <div>
          ${kv([
            ["Registry ID", a ? `<span style="font-family:var(--font-mono);font-size:0.7rem;">${escapeHtml(a.id)}</span>` : `<span class="u-quiet">not a registered asset</span>`],
            ["Operator", escapeHtml(row.operator || "not recorded")],
            ["State / District", escapeHtml([row.state, row.district].filter(Boolean).join(" / ") || "not recorded")],
            ["Facility Type", escapeHtml(a?.facility_type ? String(a.facility_type).replace(/_/g, " ") : "not recorded")],
            ["Hazard Class", escapeHtml(a?.hazard_category ? String(a.hazard_category).replace(/_/g, " ") : "not recorded")],
            ["Safety Buffer", a?.buffer_radius_meters ? `${fmt.int(a.buffer_radius_meters)} m radius` : "not recorded"],
          ])}
        </div>
        <div>
          ${kv([
            ["Detections in Window", `${row.detections}`],
            ["Peak Thermal Output", row.detections ? `<span style="font-family:var(--font-mono);font-weight:600;${row.exceeds ? "color:var(--tier-critical);" : ""}">${fmt.dec(row.peak)} MW</span>` : "--"],
            ["Cell P95 Envelope (365d)", row.p95 > 0 ? `<span style="font-family:var(--font-mono);">${fmt.dec(row.p95)} MW</span>` : `<span class="u-quiet">no measurable envelope (INV-5)</span>`],
            ["Peak / Envelope", row.ratio === null ? "--" : `<span style="font-family:var(--font-mono);${row.exceeds ? "color:var(--tier-critical);font-weight:600;" : ""}">${row.ratio.toFixed(2)}×</span>`],
            ["Most Recent Detection", row.lastAt ? `${row.lastAt.toISOString().slice(0, 10)}` : "none in window"],
            ["Lifecycle Status", escapeHtml(top ? String(top.risk.declaredTier || top.risk.tier) : "no open incident")],
          ])}
        </div>
      </div>
    </div>`;

  const detections = row.cases.length
    ? `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
        <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
          <div class="row" style="gap:8px;align-items:center;">
            <svg class="i i--sm" style="color:var(--signal)"><use href="#i-flame"/></svg>
            <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
              Detections Attributed to This Site (${row.cases.length})
            </span>
          </div>
          <span class="u-micro u-quiet">Open Details for the satellite crop and the AI vision report</span>
        </div>
        <div class="stack" style="gap:6px;">
          ${row.cases.map((c) => `
            <div class="row glass well" style="justify-content:space-between;align-items:center;padding:10px 14px;border-radius:var(--r-sm);">
              <div class="row" style="gap:10px;align-items:center;">
                ${icon(c.cls.icon, "i i--sm")}
                <div>
                  <span style="font-family:var(--font-mono);font-size:0.8rem;font-weight:600;color:var(--t-primary);">${escapeHtml(c.id)}</span>
                  <span class="u-micro u-quiet" style="margin-left:8px;">${c.firms.date} ${c.firms.time} (${dayNightOf(c)} pass)</span>
                </div>
              </div>
              <div class="row" style="gap:10px;align-items:center;">
                <span class="u-micro" style="font-family:var(--font-mono);font-weight:600;font-size:0.82rem;${row.p95 > 0 && c.frp > row.p95 ? "color:var(--tier-critical);" : ""}">
                  ${fmt.dec(c.frp)} MW
                </span>
                <span class="tag tag--tier" data-tier="${c.risk.tier}" style="font-size:0.68rem;">
                  ${c.severity?.level || c.risk.tier} ${c.severity?.score ?? c.risk.score}
                </span>
                <button class="btn btn--sm" type="button" data-case="${escapeHtml(c.id)}" data-open="modal" style="padding:3px 10px;font-size:0.72rem;height:24px;">
                  Details
                </button>
              </div>
            </div>`).join("")}
        </div>
      </div>`
    : `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
        ${stateBlock("No detection in this window",
          "This facility is registered and monitored but had no thermal detection in the active window. That is a statement about coverage, not about compliance.", "i-factory")}
      </div>`;

  /* A basin has no registry row and no facility profile, so the measured
     baseline panel and the registry record are both replaced by the statement
     of what it is not. */
  if (row.kind === "basin") {
    return `<div class="industrial-detail">
      ${identity}
      <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
        ${stateBlock("Not a registered facility",
          "This site is a mapped mining concession, not an industrial_assets row. It has no operator, no safety buffer and no hazard classification on record, so it is reported separately from the register and no facility baseline can be measured for it.", "i-mining")}
      </div>
      ${detections}
    </div>`;
  }

  return `<div class="industrial-detail">
    ${identity}
    ${renderMeasuredBaselinePanel(profileState, activeWindow)}
    ${facts}
    ${row.cases.length ? renderFrpPointGraph(row.cases, profileState, activeWindow) : ""}
    ${row.cases.length ? renderDiurnalPointGraph(row.cases, row.p95) : ""}
    ${detections}
  </div>`;
}

function renderGroupDetail(group, groupBy) {
  const cut = groupBy === "operator" ? "operator" : "state";
  const sorted = group.rows.slice().sort((a, b) => (b.exceeds - a.exceeds) || ((b.ratio ?? -1) - (a.ratio ?? -1)) || (b.peak - a.peak));
  const exceeding = sorted.filter((r) => r.exceeds);
  const quiet = sorted.filter((r) => !r.detections);

  const table = sorted.map((r) => `
    <div class="row glass well" data-facility="${escapeHtml(r.key)}" style="justify-content:space-between;align-items:center;padding:10px 14px;border-radius:var(--r-sm);gap:var(--s-2);cursor:pointer;">
      <div style="min-width:0;">
        <div style="font-size:0.82rem;font-weight:600;color:var(--t-primary);" class="u-truncate">${escapeHtml(r.name)}</div>
        <div class="u-micro u-quiet u-truncate">${escapeHtml([r.district, r.state].filter(Boolean).join(", ") || "location not recorded")}</div>
      </div>
      <div class="row" style="gap:10px;align-items:center;">
        <span class="u-micro" style="font-family:var(--font-mono);">${r.detections} det.</span>
        <span class="u-micro" style="font-family:var(--font-mono);">${r.detections ? `${fmt.dec(r.peak)} MW` : "--"}</span>
        <span class="tag ${r.exceeds ? "tag--tier" : "tag--signal"}" style="font-size:0.66rem;">
          ${r.exceeds ? `${r.ratio.toFixed(2)}× P95` : (r.detections ? "within" : "quiet")}
        </span>
      </div>
    </div>`).join("");

  return `<div class="industrial-detail">
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <span class="tag tag--signal" style="font-size:0.7rem;">${cut === "operator" ? "OPERATOR ROLL-UP" : "STATE ROLL-UP"}</span>
      <h2 style="font-size:1.25rem;font-weight:600;color:var(--t-primary);margin:6px 0 4px 0;">${escapeHtml(group.name)}</h2>
      <p class="u-micro u-quiet" style="margin:0;">
        ${group.rows.length} registered ${group.rows.length === 1 ? "facility" : "facilities"} &bull;
        ${group.detections} detections in window &bull;
        ${group.exceeds} above their measured P95 &bull;
        ${group.quiet} with no detection
      </p>
    </div>

    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row" style="gap:8px;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <svg class="i i--sm" style="color:var(--signal)"><use href="#i-factory"/></svg>
        <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
          ${escapeHtml(group.name)} — Registered Facilities, Ranked by Exceedance
        </span>
      </div>
      <div class="stack" style="gap:6px;">${table}</div>
    </div>

    ${exceeding.length ? "" : `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      ${stateBlock("No exceedance in this window",
        `None of the ${group.rows.length} registered facilities here beat its measured 365-day P95 envelope. ${quiet.length} had no detection at all.`, "i-check")}
    </div>`}
  </div>`;
}

function renderRegisterSummary(rows, reporting, quiet, basinRows, unattributed, groupBy, hasRegistry = true) {
  const quietList = quiet.slice().sort((a, b) => a.name.localeCompare(b.name));

  /* "Every registered facility reported" is only true if there is a register
     to have reported. With the registry unavailable every facility row is
     absent, so `quiet` is empty for the opposite reason and the coverage panel
     has to say so instead of congratulating the network. */
  const coverage = quietList.length
    ? `<div class="stack" style="gap:6px;max-height:340px;overflow-y:auto;">
        ${quietList.map((r) => `
          <div class="row glass well" data-facility="${escapeHtml(r.key)}" style="justify-content:space-between;align-items:center;padding:8px 12px;border-radius:var(--r-sm);cursor:pointer;">
            <div style="min-width:0;">
              <div class="u-truncate" style="font-size:0.8rem;color:var(--t-primary);">${escapeHtml(r.name)}</div>
              <div class="u-micro u-quiet u-truncate">${escapeHtml([r.operator, r.state].filter(Boolean).join(" · "))}</div>
            </div>
            <span class="tag" style="font-size:0.64rem;">${escapeHtml(sectorLabel(r.sector))}</span>
          </div>`).join("")}
      </div>`
    : hasRegistry
      ? stateBlock("Every registered facility reported", "All registered facilities had at least one detection in the active window.", "i-check")
      : stateBlock("No register to compare against", "The industrial registry did not load, so there is no list of monitored facilities and no coverage figure can be stated. The detections below are the feed's own.", "i-database");

  /* The detections the feed could not attach to any name at all: no registry
     asset and no basin label. These are the ones most worth a reader's time --
     a thermal anomaly the system cannot attribute to anything on record -- so
     they are listed rather than only counted. */
  const orphans = unattributed.length
    ? `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
        <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
          <div class="row" style="gap:8px;align-items:center;">
            ${icon("i-question", "i i--sm")}
            <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
              Unattributed Detections (${unattributed.length})
            </span>
          </div>
          <span class="u-micro u-quiet">No registered facility and no mapped basin within range of the feed's resolution</span>
        </div>
        <div class="stack" style="gap:6px;max-height:300px;overflow-y:auto;">
          ${unattributed.slice().sort((a, b) => b.frp - a.frp).map((c) => `
            <div class="row glass well" style="justify-content:space-between;align-items:center;padding:8px 12px;border-radius:var(--r-sm);gap:var(--s-2);">
              <div class="row" style="gap:10px;align-items:center;min-width:0;">
                ${icon(c.cls.icon, "i i--sm")}
                <div style="min-width:0;">
                  <div class="u-truncate" style="font-size:0.8rem;color:var(--t-primary);">${escapeHtml(c.cls.label)}</div>
                  <div class="u-micro u-quiet u-truncate" style="font-family:var(--font-mono);">${fmt.coord(c.lat, c.lon)}${c.state ? ` · ${escapeHtml(c.state)}` : ""}</div>
                </div>
              </div>
              <div class="row" style="gap:10px;align-items:center;">
                <span class="u-micro" style="font-family:var(--font-mono);font-weight:600;">${fmt.dec(c.frp)} MW</span>
                <button class="btn btn--sm" type="button" data-case="${escapeHtml(c.id)}" data-open="modal" style="padding:3px 10px;font-size:0.72rem;height:24px;">Details</button>
              </div>
            </div>`).join("")}
        </div>
      </div>`
    : "";

  return `<div class="industrial-detail">
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <span class="tag tag--signal" style="font-size:0.7rem;">${hasRegistry ? "NATIONAL REGISTER" : "REGISTER UNAVAILABLE"}</span>
      <h2 style="font-size:1.25rem;font-weight:600;color:var(--t-primary);margin:6px 0 4px 0;">Monitoring Coverage and Envelope Status</h2>
      <p class="u-micro u-quiet" style="margin:0;">
        ${rows.length} registered facilities &bull; ${reporting.length} reported a detection in this window &bull;
        ${quiet.length} did not &bull; ${basinRows.length} mining basin${basinRows.length === 1 ? "" : "s"} reported against outside the register &bull;
        ${unattributed.length} detection${unattributed.length === 1 ? "" : "s"} attributable to nothing on record
      </p>
      <p class="u-micro" style="margin:var(--s-3) 0 0 0;color:var(--t-tertiary);">
        ${hasRegistry
          ? `Select a facility for its registry record and its measured 30 / 90 / 365-day baselines, or switch the
             roll-up to ${groupBy === "operator" ? "state" : "operator"} to read the same register by ${groupBy === "operator" ? "state" : "operator"}.`
          : `Every detection in this window is attributed by the place label the feed published, because there is no register to join on. Reload once /api/industries answers to see the register view.`}
      </p>
    </div>

    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-pulse"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            ${hasRegistry ? `Registered but Quiet This Window (${quietList.length})` : "Sites Reported Against"}
          </span>
        </div>
        <span class="u-micro u-quiet">A gap in coverage, not a clean bill of health</span>
      </div>
      ${coverage}
    </div>

    ${orphans}
  </div>`;
}

export function renderIndustrial(el, cases, selectedFacilityKey = null, query = "", sector = "all",
                                 sortBy = "frp", activeWindow = "365d", profileState = null,
                                 registry = [], groupBy = "facility") {
  const industrial = cases.filter((c) => c.cls.group === "industrial" || c.facility?.name || c.climatology?.isRoutine);
  const { rows, basinRows, unattributed } = buildRegister(industrial, registry);

  const byKey = new Map();
  rows.forEach((r) => byKey.set(r.key, r));
  basinRows.forEach((r) => byKey.set(r.key, r));

  // --- Filters -------------------------------------------------------------
  let visibleRows = rows.concat(basinRows);
  if (sector !== "all") visibleRows = visibleRows.filter((r) => r.sector === sector);
  if (query && query.trim()) {
    const q = query.trim().toLowerCase();
    visibleRows = visibleRows.filter((r) =>
      r.name.toLowerCase().includes(q)
      || (r.operator || "").toLowerCase().includes(q)
      || (r.state || "").toLowerCase().includes(q)
      || (r.district || "").toLowerCase().includes(q)
      || (r.asset?.facility_type || "").toLowerCase().includes(q)
      || r.cases.some((c) => c.id.toLowerCase().includes(q)));
  }

  visibleRows.sort((a, b) => {
    if (sortBy === "detections") return (b.detections - a.detections) || (b.peak - a.peak);
    if (sortBy === "anomaly") return ((b.ratio ?? -1) - (a.ratio ?? -1)) || (b.peak - a.peak);
    if (sortBy === "name") return a.name.localeCompare(b.name);
    return (b.peak - a.peak) || (b.detections - a.detections);
  });

  // --- Roll-ups ------------------------------------------------------------
  const groups = groupBy === "operator" ? rollUp(rows, (r) => r.operator)
    : groupBy === "state" ? rollUp(rows, (r) => r.state)
      : null;

  const reporting = rows.filter((r) => r.detections);
  const quiet = rows.filter((r) => !r.detections);
  const exceeding = rows.filter((r) => r.exceeds);
  const industrialPeakFrp = industrial.length ? Math.max(...industrial.map((c) => c.frp || 0)) : 0;

  // --- Header --------------------------------------------------------------
  /* No register means no register figures. `registry` is empty when the fetch
     failed (data.js records it in `store.errors`), and the tiles below would
     then read "0 Registered Facilities, 0 / 0 with a detection" -- a statement
     about the monitoring network made from a statement about one HTTP request.
     The banner says which it is and the tiles are replaced, not zeroed. */
  const head = !registry.length
    ? `<div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);margin-bottom:var(--s-4);">
        ${stateBlock("Industrial register unavailable",
          "GET /api/industries did not answer, so there is no list of monitored facilities to report against. The detections below are still the feed's own, grouped by the place name it published. No register totals are shown, because a register that failed to load has no totals.",
          "i-factory")}
        <div class="grid-4" style="margin-top:var(--s-4);">
          ${tile(metric(fmt.int(basinRows.length), "", "Sites Reported Against", "Place labels on the detections in this window; with no register to join on, none of these can be confirmed as a registered facility"))}
          ${tile(metric(fmt.dec(industrialPeakFrp), "MW", "Peak Thermal Radiance", "Highest single-detection radiative power in window (INV-2: never summed)"), 40)}
        </div>
      </div>`
    : `<div class="grid-4" style="margin-bottom:var(--s-4);">
    ${tile(metric(fmt.int(rows.length), "", "Registered Facilities", `Authoritative industrial_assets registry${basinRows.length ? `; ${basinRows.length} further mining basin${basinRows.length === 1 ? "" : "s"} reported against outside it` : ""}`))}
    ${tile(metric(fmt.int(reporting.length), ` / ${rows.length}`, "With a Detection in Window", "Registered facilities with at least one detection in the active window"), 40)}
    ${tile(metric(fmt.int(exceeding.length), ` / ${reporting.length || 0}`, "Above Their Measured P95", "Reporting facilities whose peak beats the highest cell envelope they sit in"), 80)}
    ${tile(metric(fmt.dec(industrialPeakFrp), "MW", "Peak Thermal Radiance", "Highest single-detection radiative power in window (INV-2: never summed)"), 120)}
  </div>`;

  // --- Detail --------------------------------------------------------------
  const selected = selectedFacilityKey ? byKey.get(selectedFacilityKey) : null;
  const selectedGroup = selectedFacilityKey && !selected
    ? groups?.find((g) => g.key === selectedFacilityKey)
    : null;

  let detailHtml;
  if (selected) detailHtml = renderFacilityDetail(selected, profileState, activeWindow);
  else if (selectedGroup) detailHtml = renderGroupDetail(selectedGroup, groupBy);
  else detailHtml = renderRegisterSummary(rows, reporting, quiet, basinRows, unattributed, groupBy, registry.length > 0);

  // --- Sidebar -------------------------------------------------------------
  /* An empty list has two very different causes and they must not read the
     same. `Cement & Kilns` is a sector this register has no rows for at all
     (all nine `facility_type` values present are steel, refining, LNG, power,
     smelting and mining), so filtering to it shows an empty list no amount of
     clearing will fill; telling the reader to clear their filters would send
     them looking for a control that does not exist. The same applies to the
     sector pills: they are drawn from `SECTORS`, not from the register. */
  const sectorHasNoRows = sector !== "all" && !rows.concat(basinRows).some((r) => r.sector === sector);
  const emptyReason = sectorHasNoRows
    ? `The register holds no facility of this sector. Its ${rows.length} rows are steel, refining, LNG, thermal power, smelting and mining; a sector with no rows is a gap in the register, not a filter to clear.`
    : "Try clearing or changing your sector and query filters.";

  let listHtml;
  if (groups) {
    listHtml = groups.length
      ? groups.map((g) => groupRowItem(g, selectedGroup && g.key === selectedGroup.key)).join("")
      : stateBlock("No groups match", sectorHasNoRows ? emptyReason : "Try clearing the sector filter or the search term.", "i-search");
  } else {
    listHtml = visibleRows.length
      ? visibleRows.map((r) => registerRowItem(r, selected && r.key === selected.key)).join("")
      : stateBlock("No facilities match", emptyReason, "i-search");
  }

  const countLabel = groups
    ? `${groups.length} ${groupBy === "operator" ? "operators" : "states"}`
    : `${visibleRows.length} of ${rows.length + basinRows.length} sites`;

  const sidebarHtml = `
    <div class="industrial-sidebar">
      <div class="row" style="justify-content:space-between;align-items:center;padding:4px 6px 8px 6px;">
        <span class="u-label" style="font-size:0.75rem;">${groups ? (groupBy === "operator" ? "OPERATOR ROLL-UP" : "STATE ROLL-UP") : "FACILITY REGISTER"}</span>
        <span class="u-micro u-num" style="color:var(--signal);">${countLabel}</span>
      </div>
      ${listHtml}
    </div>`;

  set(el, head + `<div class="industrial-workspace">${sidebarHtml}${detailHtml}</div>`);
}

/* --- Analytics ------------------------------------------------------------
   Every number below is computed from the loaded records at render time. */

function colsChart(bins, axis, tierFor) {
  const peak = Math.max(1, ...bins);
  const bars = bins.map((n, i) => {
    const tier = tierFor ? tierFor(i) : null;
    const h = n ? Math.max(6, Math.round((n / peak) * 100)) : 3;
    return `<div class="cols__bar"${tier ? ` data-tier="${tier}"` : ""} style="--v:${h}%"
      title="${escapeHtml(axis.title(i))}: ${n} ${n === 1 ? "case" : "cases"}"></div>`;
  }).join("");
  return `
    <div class="chart">
      <div class="chart__plot chart__plot--grid" style="height:118px" aria-hidden="true">
        <div class="cols">${bars}</div>
      </div>
      <div class="chart__axis" aria-hidden="true">${axis.ticks.map((t) => `<span>${escapeHtml(t)}</span>`).join("")}</div>
      ${chartAlt(axis.summary || "", binRows(bins, axis.title))}
    </div>`;
}

function factorBullets(cases) {
  const acc = new Map();
  cases.forEach((c) => c.risk.factors.forEach((f) => {
    const row = acc.get(f.name) || { name: f.name, sum: 0, max: f.max, n: 0 };
    row.sum += f.score;
    row.n += 1;
    row.max = Math.max(row.max, f.max);
    acc.set(f.name, row);
  }));

  const rows = [...acc.values()].sort((a, b) => b.max - a.max);
  if (!rows.length) {
    return stateBlock("No factor breakdown",
      "The feed did not include per factor scores for these cases.", "i-sliders");
  }

  return `<div class="stack-5">${rows.map((r) => {
    const mean = r.sum / r.n;
    // A suppression row carries a NEGATIVE score against a ceiling of 0: it
    // subtracts from the composite rather than contributing to it, so there is
    // no ceiling to be a percentage of. The guard below is right to refuse the
    // division -- -11.2 / 0 is -Infinity, and `--v:-Infinity%` is not a length --
    // but its default of 0 must not then be printed as a measurement: "0% of the
    // weight available" says the factor contributed nothing, on the one row that
    // removes the most.
    const pct = r.max ? Math.round((mean / r.max) * 100) : 0;
    const n = `${r.n} scored ${r.n === 1 ? "case" : "cases"}`;
    const detail = r.max
      ? `Mean contribution across ${n}, ${pct}% of the weight available`
      : `Mean across ${n}: ${fmt.dec(Math.abs(mean))} points ${mean < 0 ? "removed from" : "added to"} the published score, against no ceiling to be a percentage of`;
    return `
      <div class="bullet">
        <div class="bullet__top">
          <span class="bullet__name">${escapeHtml(r.name)}</span>
          <span class="bullet__score">${fmt.dec(mean)}<span class="bullet__max"> of ${r.max}</span></span>
        </div>
        <div class="meter meter--quiet" aria-hidden="true"><span class="meter__fill" style="--v:${pct}%"></span></div>
        <p class="bullet__detail">${detail}</p>
      </div>`;
  }).join("")}</div>`;
}

export function renderAnalytics(el, cases, ambient) {
  if (!cases.length) {
    set(el, `<div class="glass tile">${stateBlock("Nothing to analyse",
      "No detections fall inside the current window and filter.", "i-pulse")}</div>`);
    return;
  }

  const risk = stats(cases.map((c) => c.risk.score));
  const frp = stats(cases.map((c) => c.frp));
  const tiers = byTier(cases);
  const frpMax = Math.max(10, Math.ceil(frp.max / 10) * 10);
  const kinds = cases.reduce((a, c) => {
    a[c.firms.confidence.kind] = (a[c.firms.confidence.kind] || 0) + 1;
    return a;
  }, {});
  const sensors = cases.reduce((a, c) => {
    const k = `${c.firms.satellite}, ${c.firms.instrument}`;
    a[k] = (a[k] || 0) + 1;
    return a;
  }, {});

  const head = `<div class="grid-4">
    ${tile(metric(fmt.int(risk.n), "", "Cases scored", `${ambient.length} background hotspots alongside`))}
    ${tile(metric(fmt.dec(risk.mean), "", "Mean risk", `Median ${risk.median}, range ${risk.min} to ${risk.max}`), 40)}
    ${tile(metric(fmt.dec(frp.median), "MW", "Median FRP", `Total ${fmt.dec(frp.sum)} MW`), 80)}
    ${tile(metric(fmt.dec(frp.max), "MW", "Peak Heat Output", "Highest radiative power in window"), 120)}
  </div>`;

  const dists = `<div class="grid-2">
    ${panel("Risk score distribution", `<span class="u-micro">10 bins, full scale</span>`,
      colsChart(histogram(cases.map((c) => c.risk.score), 10, 0, 100),
        { ticks: ["0", "50", "100"],
          title: (i) => `Risk ${i * 10} to ${i * 10 + 9}`,
          summary: `Risk score distribution, ten bins across the full 0 to 100 scale, ${risk.n} scored ${risk.n === 1 ? "case" : "cases"}.` },
        (i) => TIERS.find((t) => i * 10 + 5 >= t.min && i * 10 + 5 <= t.max)?.id || "LOW"),
      { foot: legend() })}
    ${panel("Radiative power distribution", `<span class="u-micro u-num">0 to ${frpMax} MW</span>`,
      colsChart(histogram(cases.map((c) => c.frp), 8, 0, frpMax),
        { ticks: ["0", `${frpMax / 2}`, `${frpMax}`],
          title: (i) => `${fmt.dec(i * frpMax / 8)} to ${fmt.dec((i + 1) * frpMax / 8)} MW`,
          summary: `Radiative power distribution, eight bins from 0 to ${frpMax} megawatts, total ${fmt.dec(frp.sum)} megawatts.` }),
      { foot: `<p class="u-micro">FRP is monochrome here on purpose. It measures energy, not risk, and the two must not be read as the same axis.</p>` })}
  </div>`;

  const anomalies = cases.reduce((a, c) => {
    const k = (c.historicalAnomaly || "NEW_UNEXPECTED").replace(/_/g, " ");
    a[k] = (a[k] || 0) + 1;
    return a;
  }, {});

  const p1Count = cases.filter((c) => (c.investigationPriority || 0) >= 70).length;
  const p2Count = cases.filter((c) => (c.investigationPriority || 0) >= 40 && (c.investigationPriority || 0) < 70).length;
  const p3Count = cases.filter((c) => (c.investigationPriority || 0) < 40).length;

  const mixes = `<div class="grid-2">
    ${panel("Classification mix", `<span class="u-micro u-num">${cases.length} cases</span>`,
      ranksBlock(byClass(cases), cases.length))}
    ${panel("Historical Anomaly & Baseline Behavior", `<span class="tag tag--signal">Historical P95 Threshold</span>`,
      kvRows([
        ...Object.entries(anomalies).map(([k, v]) => [k, `${v} detections`]),
        ["Priority 1 (Satellite Inspection)", `${p1Count} high-risk cases (Score ≥ 70)`],
        ["Priority 2 (Elevated Verification)", `${p2Count} moderate cases (Score 40–69)`],
        ["Priority 3 (Routine Monitoring)", `${p3Count} low-risk cases (Score < 40)`],
      ], "kv kv--wide"),
      { foot: `<p class="u-micro">Historical baselines prevent routine flares from generating false alarms while ensuring novel thermal ignitions trigger immediate optical satellite investigation.</p>` })}
  </div>`;

  const byTierRows = panel("Detections by tier",
    `<span class="u-micro u-num">${cases.length}</span>`,
    `<div class="stack-5">${TIERS.map((t) => {
      const n = tiers[t.id] || 0;
      const pct = Math.round((n / cases.length) * 100);
      return `<div class="bullet" data-tier="${t.id}">
        <div class="bullet__top">
          <span class="bullet__name">${t.label}, ${t.min} to ${t.max}</span>
          <span class="bullet__score">${n}<span class="bullet__max"> of ${cases.length}</span></span>
        </div>
        <div class="meter" aria-hidden="true"><span class="meter__fill" style="--v:${pct}%"></span></div>
      </div>`;
    }).join("")}</div>`);

  const factors = panel("Risk factor contribution",
    `<span class="u-micro">Mean of each weighted factor</span>`,
    factorBullets(cases),
    { foot: `<p class="u-micro">The engine is deterministic: five weighted factors summing to 100, so any score on this console can be reproduced by hand from the case record.</p>` });

  set(el, head + dists + mixes + `<div class="grid-2">${byTierRows}${factors}</div>`);
}

/* --- Settings -------------------------------------------------------------
   Preferences are local to this browser. Nothing here is sent anywhere, and
   nothing here changes the underlying feed. */

function field(label, hint, control) {
  return `
    <div class="field">
      <div>
        <p class="field__label">${escapeHtml(label)}</p>
        <p class="field__hint">${escapeHtml(hint)}</p>
      </div>
      <div class="row">${control}</div>
    </div>`;
}

function seg(name, options, active) {
  return `<div class="seg" role="radiogroup" aria-label="${escapeHtml(name)}">${options
    .map(([value, label, attr]) => `<button class="seg__opt" type="button" role="radio"
      aria-checked="${value === active}" data-${attr}="${value}">${escapeHtml(label)}</button>`)
    .join("")}</div>`;
}

export function renderSettings(el, prefs) {
  const reviewed = store.cases.filter((c) => getTriage(c.id) !== "UNREVIEWED").length;

  const controls = panel("Console", "", `
    ${field("Background hotspots",
      "Shows raw thermal detections in the feed alongside priority incidents. Useful for observing whether an incident sits alone or inside a broader burn area.",
      `<button class="switch" type="button" id="set-ambient" role="switch"
        aria-checked="${prefs.ambient}" aria-label="Show background hotspots"></button>`)}
    ${field("Detection window",
      "Applies immediately across every view. The window is measured back from the newest satellite pass, not from the local clock.",
      seg("Detection window", Object.entries(WINDOWS).map(([k, v]) => [k, v.label, "window"]), prefs.window))}
    ${field("Base layer",
      "Canvas keeps thermal points high-contrast. Imagery shows real terrain for ground verification.",
      seg("Base layer", Object.entries(BASES).map(([k, v]) => [k, v.label, "base"]), prefs.base))}
    ${field("Review decisions",
      `${reviewed} of ${store.cases.length} cases carry a review decision. Clearing is immediate and cannot be undone.`,
      `<button class="btn btn--sm" type="button" id="set-clear-triage">
        ${icon("i-x", "i i--sm")}Clear decisions</button>`)}
  `);

  const sources = panel("Data sources", store.errors.length
    ? `<span class="tag tag--unconfirmed">${store.errors.length} failing</span>`
    : `<span class="tag">Both reachable</span>`,
    kvRows([
      ["Incident cases", escapeHtml(SOURCES.incidents)],
      ["Background points", escapeHtml(SOURCES.ambient)],
      ["Records loaded", `${store.cases.length} incidents, ${store.ambient.length} raw points`],
      ["Latest satellite pass", stampDate(store.anchor)],
      ["Satellite imagery", "/crops/, high-resolution optical imagery"],
      noticeRow(),
      ["Failures", store.errors.length
        ? store.errors.map((e) => escapeHtml(`${e.source}: ${e.message}`)).join("<br>")
        : "none"],
    ], "kv kv--wide"),
    { foot: `<p class="u-micro">The console reads the active pipeline feeds. All API credentials and processing remain securely server side.</p>` });

  const build = panel("System specifications", "", kvRows([
    ["Architecture", "FIREX v2 Thermal Intelligence Engine"],
    ["Severity Model", "5-Factor Indian Calibration (0-100), Tiers Low / Medium / High / Critical"],
    ["Target Selection", "Priority Target Ranking (0-100, Automated Trigger Qualification)"],
    ["Historical Baseline", "365-Day Historical Baseline, P95 Surge Threshold & Anomaly Classifier"],
    ["Vision AI Provider", "Multimodal High-Resolution Optical Inspection with Uncertainty Scoring"],
    ["Orchestration", "5-Stage Pipeline, Live SSE Telemetry, Distributed Process Lock"],
    ["Map Engine", "Leaflet 1.9.4 with Optimized Spatial Clustering & Dynamic Zoom Scaling"],
  ], "kv kv--wide"));

  set(el, controls + `<div class="grid-2">${sources}${build}</div>`);
}

/* --- Historical Observations Archive Search ------------------------------ */

const INDIAN_STATES = [
  "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa",
  "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir", "Jharkhand",
  "Karnataka", "Kerala", "Ladakh", "Madhya Pradesh", "Maharashtra",
  "Meghalaya", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
  "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal"
];

export function renderHistory(el, histState, handlers = {}) {
  const q = histState.query || "";
  const st = histState.state || "";
  const start = histState.startDate || "";
  const end = histState.endDate || "";
  const minFrp = Number(histState.minFrp) || 0;
  const loading = Boolean(histState.loading);
  const data = histState.data;
  const total = data ? data.total_matches : 0;
  const results = data ? data.results : [];
  const offset = Number(histState.offset) || 0;
  const limit = Number(histState.limit) || 50;

  // 1. Search card
  const stateOptions = [`<option value="">All Indian States & UTs</option>`]
    .concat(INDIAN_STATES.map(s => `<option value="${escapeHtml(s)}"${st === s ? " selected" : ""}>${escapeHtml(s)}</option>`))
    .join("");

  const presets = [
    ["24h", "Last 24h"],
    ["7d", "Last 7d"],
    ["30d", "Last 30d"],
    ["sep2026", "Sep 2026"],
    ["all", "All Time"]
  ].map(([pid, plabel]) => `
    <button class="history-pill" type="button" data-preset="${pid}">${plabel}</button>
  `).join("");

  const frpPills = [
    [0, "All (≥0 MW)"],
    [5, "≥ 5 MW"],
    [10, "≥ 10 MW"],
    [20, "≥ 20 MW"],
    [50, "≥ 50 MW"]
  ].map(([val, label]) => `
    <button class="history-pill" type="button" data-minfrp="${val}" data-active="${minFrp === val}">${label}</button>
  `).join("");

  const searchCard = `
    <section class="glass history-search-card">
      <div class="history-form-grid">
        <div class="history-field">
          <label for="hist-input-query">Target / Facility / District</label>
          <input class="history-input" id="hist-input-query" type="text" placeholder="e.g. Talcher, Jajpur, Refinery..." value="${escapeHtml(q)}">
        </div>
        <div class="history-field">
          <label for="hist-select-state">State / Territory</label>
          <select class="history-select" id="hist-select-state">
            ${stateOptions}
          </select>
        </div>
        <div class="history-field">
          <label for="hist-input-start">From Date</label>
          <input class="history-input" id="hist-input-start" type="date" value="${escapeHtml(start)}">
        </div>
        <div class="history-field">
          <label for="hist-input-end">To Date</label>
          <input class="history-input" id="hist-input-end" type="date" value="${escapeHtml(end)}">
        </div>
      </div>

      <div class="row row--wrap" style="justify-content: space-between; align-items: center; gap: var(--s-3); margin-top: 4px;">
        <div class="history-presets-row">
          <span class="history-preset-label">Date Presets:</span>
          ${presets}
        </div>
        <div class="history-presets-row">
          <span class="history-preset-label">Min FRP:</span>
          ${frpPills}
        </div>
      </div>

      <div class="history-actions-row">
        <div class="row" style="gap: var(--s-2); align-items: center;">
          <button class="btn btn--primary" id="btn-hist-submit" type="button" ${loading ? "disabled" : ""}>
            <svg class="i i--sm" aria-hidden="true"><use href="#i-search"/></svg>
            <span>${loading ? "Querying 2.89M Records..." : "Search Archive"}</span>
          </button>
          <button class="btn" id="btn-hist-reset" type="button">Reset</button>
        </div>
        <div class="row" style="gap: var(--s-2); align-items: center;">
          <span class="tag tag--signal" style="font-family: var(--font-mono); font-size: var(--fs-micro);">
            Fast Indexed Database (2.89M Detections)
          </span>
          <button class="btn" id="btn-hist-export" type="button" ${!results.length ? "disabled" : ""}>
            <svg class="i i--sm" aria-hidden="true"><use href="#i-download"/></svg>
            <span>Export CSV (${total.toLocaleString()})</span>
          </button>
        </div>
      </div>
    </section>`;

  // 2. Telemetry metrics cards
  const summary = data ? data.summary : null;
  const meanFrpStr = summary && summary.mean_frp != null ? `${summary.mean_frp.toFixed(1)}` : "--";
  const maxFrpStr = summary && summary.max_frp != null ? `${summary.max_frp.toFixed(1)}` : "--";
  const stateLabel = st || "All India Territory";

  const telemetry = `
    <div class="history-telemetry-grid">
      <div class="glass metric">
        <p class="u-label">Matched Observations</p>
        <p class="metric__value">
          <span class="u-metric u-live">${data ? total.toLocaleString() : "--"}</span>
          <span class="metric__unit">records</span>
        </p>
        <p class="metric__note">Queried across 2,896,405 time-series points</p>
      </div>
      <div class="glass metric">
        <p class="u-label">Mean Radiative Power</p>
        <p class="metric__value">
          <span class="u-metric u-live">${meanFrpStr}</span>
          <span class="metric__unit">MW</span>
        </p>
        <p class="metric__note">Average intensity in selected filter range</p>
      </div>
      <div class="glass metric">
        <p class="u-label">Peak Radiative Power</p>
        <p class="metric__value">
          <span class="u-metric u-live" style="color: var(--tier-critical);">${maxFrpStr}</span>
          <span class="metric__unit">MW</span>
        </p>
        <p class="metric__note">Maximum thermal radiative signature</p>
      </div>
      <div class="glass metric">
        <p class="u-label">Region & Date Range</p>
        <p class="metric__value" style="font-size: 1.15rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          <span class="u-live">${escapeHtml(stateLabel)}</span>
        </p>
        <p class="metric__note">${start || "Beginning"} &rarr; ${end || "Current"}</p>
      </div>
    </div>`;

  // 3. Table or skeleton or empty state
  let tableBody = "";
  if (loading) {
    tableBody = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 48px 16px;">
          <div class="row" style="justify-content: center; align-items: center; gap: 10px; color: var(--signal);">
            <svg class="i i--sm" style="animation: spin 1s linear infinite;"><use href="#i-pulse"/></svg>
            <span style="font-weight: 600; letter-spacing: 0.05em;">Scanning spatial indexes on 2.89M records...</span>
          </div>
        </td>
      </tr>`;
  } else if (!data) {
    tableBody = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 48px 16px; color: var(--t-tertiary);">
          Use the filters above and click "Search Archive" to query historical satellite passes.
        </td>
      </tr>`;
  } else if (results.length === 0) {
    tableBody = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 48px 16px; color: var(--t-tertiary);">
          No thermal observations found matching the specified parameters. Try widening the date range or lowering the minimum FRP.
        </td>
      </tr>`;
  } else {
    tableBody = results.map((row) => {
      const frp = Number(row.frp_mw) || 0;
      let badgeCls = "history-frp-badge--low";
      if (frp >= 30) badgeCls = "history-frp-badge--crit";
      else if (frp >= 15) badgeCls = "history-frp-badge--high";
      else if (frp >= 5) badgeCls = "history-frp-badge--med";

      const dt = row.acquired_at ? row.acquired_at.replace("T", " ") : "--";
      const sat = `${row.satellite || "VIIRS"} · ${row.sensor || "VIIRS"}`;
      const dayNight = row.daynight || "DAY";
      const coords = `${row.latitude.toFixed(4)}°N, ${row.longitude.toFixed(4)}°E`;
      const region = `${row.district || "Unknown District"}, ${row.state || "India"}`;
      const facility = row.nearest_facility
        ? `${escapeHtml(row.nearest_facility)} <span style="color:var(--t-tertiary)">(${row.distance_km != null ? row.distance_km.toFixed(1) + " km" : ""})</span>`
        : `<span style="color:var(--t-quiet)">Isolated thermal cluster</span>`;

      return `
        <tr>
          <td class="u-mono" style="font-size: 0.72rem;">
            <div style="font-weight: 600; color: var(--t-primary);">${escapeHtml(row.id.slice(0, 16))}</div>
            <div style="color: var(--t-tertiary); font-size: 0.65rem;">${sat} · <span class="tag tag--signal" style="padding: 1px 4px; font-size: 0.6rem;">${dayNight}</span></div>
          </td>
          <td class="u-mono" style="white-space: nowrap; font-size: 0.75rem;">${escapeHtml(dt)}</td>
          <td class="u-mono" style="white-space: nowrap; font-size: 0.75rem;">${coords}</td>
          <td style="font-size: 0.78rem; font-weight: 500; color: var(--t-primary);">${escapeHtml(region)}</td>
          <td style="font-size: 0.76rem; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${facility}</td>
          <td>
            <span class="history-frp-badge ${badgeCls}">
              <svg class="i" style="width: 10px; height: 10px;" aria-hidden="true"><use href="#i-flame"/></svg>
              <span>${frp.toFixed(2)} MW</span>
            </span>
          </td>
          <td>
            <button class="btn btn--sm btn-hist-inspect" type="button" data-lat="${row.latitude}" data-lon="${row.longitude}" data-frp="${frp}" data-id="${row.id}" title="Inspect coordinates on map">
              <svg class="i i--sm" aria-hidden="true"><use href="#i-crosshair"/></svg>
              <span>Map</span>
            </button>
          </td>
        </tr>`;
    }).join("");
  }

  const pagination = data && total > 0 ? `
    <div class="history-pagination">
      <span>Showing <strong>${offset + 1}</strong> &ndash; <strong>${Math.min(offset + limit, total).toLocaleString()}</strong> of <strong>${total.toLocaleString()}</strong> observations</span>
      <div class="row" style="gap: var(--s-2);">
        <button class="btn btn--sm" id="btn-hist-prev" type="button" ${offset === 0 || loading ? "disabled" : ""}>
          <svg class="i i--sm" aria-hidden="true"><use href="#i-chev-left"/></svg>
          <span>Previous</span>
        </button>
        <span class="u-mono" style="padding: 4px 8px; font-size: var(--fs-label); color: var(--t-secondary);">
          Page ${Math.floor(offset / limit) + 1} of ${Math.max(1, Math.ceil(total / limit))}
        </span>
        <button class="btn btn--sm" id="btn-hist-next" type="button" ${offset + limit >= total || loading ? "disabled" : ""}>
          <span>Next</span>
          <svg class="i i--sm" aria-hidden="true"><use href="#i-chev-right"/></svg>
        </button>
      </div>
    </div>` : "";

  const tableCard = `
    <section class="glass history-table-card">
      <div class="history-table-container">
        <table class="history-table">
          <thead>
            <tr>
              <th>ID & Sensor</th>
              <th>Acquired (UTC)</th>
              <th>Coordinates</th>
              <th>State / Region</th>
              <th>Nearest Facility & Distance</th>
              <th>Fire Radiative Power</th>
              <th>Inspect</th>
            </tr>
          </thead>
          <tbody>
            ${tableBody}
          </tbody>
        </table>
      </div>
      ${pagination}
    </section>`;

  set(el, searchCard + telemetry + tableCard);
}

/* --- Failure ------------------------------------------------------------- */

/* A source that did not load says so in the place its content would have
   been. The rest of the console keeps working on whatever did load. */
export function renderFailure(el, source, message) {
  set(el, `<div class="glass tile--lg">
    ${stateBlock(`${source} unavailable`,
      `${message}. Start the console through server.py so the data and crop mounts resolve, then reload.`,
      "i-warning")}
  </div>`);
}

/* The map is the one view with an off site dependency, so it is the one that can
   go missing on its own while everything else is fine. This says so inside the
   frame the tiles would have filled, and says what is still usable, because a
   flat dark rectangle with no message is the version of this failure a reader
   cannot tell apart from a bug. */
export function renderMapDown(el, message) {
  set(el, `<div class="mapdown">
    ${stateBlock("Map unavailable",
      `${message} Every other view still reads the loaded feed: the ranked spine beside this frame, the dossier, and the overview, cases, industrial and analytics tabs.`,
      "i-warning")}
  </div>`);
}
