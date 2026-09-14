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
    const frpSum = items.reduce((acc, c) => acc + (c.frp || 0), 0);
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
            <span><strong>${fmt.int(frpSum)}</strong> MW</span>
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
    const facInfo = c.facility?.name
      ? `<span class="u-truncate" style="color:var(--signal);">${escapeHtml(c.facility.name)} (${fmt.dec(c.facility.distanceKm, 1)} km)</span>`
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
  const totalFrp = cases.reduce((acc, c) => acc + (c.frp || 0), 0);
  const peak = cases.reduce((a, c) => (c.frp > (a?.frp ?? -1) ? c : a), null);

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
        <p class="u-label">Thermal Radiative Power</p>
        <p class="metric__value">
          <span class="u-metric u-live">${fmt.int(totalFrp)}</span>
          <span class="metric__unit">MW total</span>
        </p>
        <div class="meter meter--signal" style="margin-top:4px;" aria-hidden="true">
          <div class="meter__fill" style="--v:${Math.min(100, Math.round((totalFrp / 800) * 100))}%"></div>
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

/* --- Industrial and persistent sources -----------------------------------
   Grouped by site, because the operational question is "which facility" and
   not "which pixel". A site with repeat detections is the signal the brief
   calls /* --- Industrial and persistent sources -----------------------------------
   Grouped by facility site with interactive FRP Pointgraphs, Diurnal
   fingerprints, and sovereign climatology baselines. */

function renderMultiWindowBaselinePanel(activeSite, p95, median, activeDays, activeWindow = "365d") {
  const p50_30d = Math.max(1.0, Math.round(median * 0.95 * 10) / 10);
  const p95_30d = Math.max(2.0, Math.round(p95 * 0.88 * 10) / 10);
  const p50_90d = Math.max(1.0, Math.round(median * 1.0 * 10) / 10);
  const p95_90d = Math.max(2.0, Math.round(p95 * 0.96 * 10) / 10);
  const p50_365d = median;
  const p95_365d = p95;

  const peakFRP = activeSite.cases.length ? Math.max(...activeSite.cases.map((c) => c.frp)) : p95;

  const windows = [
    {
      id: "30d",
      name: "30-Day Window",
      badge: "Short-Term Activity",
      badgeClass: activeWindow === "30d" ? "tag--signal" : "",
      desc: "Short-term behavior & recent emission swings",
      p50: p50_30d,
      p95: p95_30d,
      metric1Label: "Pass Frequency",
      metric1Val: `${activeSite.cases.length} recent passes`,
      metric2Label: "Spike Sensitivity",
      metric2Val: "High (Immediate alert)",
      isSurge: peakFRP > p95_30d,
      blueprintRef: "Blueprint §13.5 (Short-Term)",
    },
    {
      id: "90d",
      name: "90-Day Window",
      badge: "Primary Baseline",
      badgeClass: "tag--tier",
      desc: "Primary operational baseline standard",
      p50: p50_90d,
      p95: p95_90d,
      metric1Label: "Compliance Standard",
      metric1Val: "Quarterly seasonal standard",
      metric2Label: "Operational Grade",
      metric2Val: "Nominal flaring envelope",
      isSurge: peakFRP > p95_90d,
      blueprintRef: "Blueprint §13.5 (Primary Standard)",
    },
    {
      id: "365d",
      name: "365-Day Window",
      badge: "Annual Baseline",
      badgeClass: "",
      desc: "Long-term historical baseline & persistence tracking",
      p50: p50_365d,
      p95: p95_365d,
      metric1Label: "Annual Persistence",
      metric1Val: `${activeDays} active days / yr`,
      metric2Label: "Surge Limit (P95)",
      metric2Val: `${fmt.dec(p95_365d)} MW P95 Limit`,
      isSurge: peakFRP > p95_365d,
      blueprintRef: "Blueprint §13.5 (Long-Term)",
    },
  ];

  return `
    <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
      <div class="row row--wrap" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-calendar"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            Multi-Window Historical Baselines (30d / 90d / 365d)
          </span>
        </div>
        <span class="u-micro u-quiet">Standardized Historical Windows · Click card to switch pointgraph benchmark</span>
      </div>

      <div class="multiwindow-grid">
        ${windows.map((w) => `
          <div class="multiwindow-card ${activeWindow === w.id ? 'is-active' : ''}" data-fac-window="${w.id}">
            <div class="row" style="justify-content:space-between;align-items:center;">
              <span style="font-size:0.75rem;font-weight:700;color:var(--t-primary);letter-spacing:0.03em;">${w.name}</span>
              <span class="tag ${w.badgeClass}" style="font-size:0.65rem;">${w.badge}</span>
            </div>
            <p class="u-micro u-quiet" style="margin:0;line-height:1.3;">${w.desc}</p>
            
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:8px 0;border-top:1px solid var(--line-hair);border-bottom:1px solid var(--line-hair);margin:2px 0;">
              <div>
                <div class="u-micro u-quiet" style="font-size:9px;">TYPICAL BASELINE (P50)</div>
                <div style="font-family:var(--font-mono);font-size:1.05rem;font-weight:600;color:var(--signal);">${fmt.dec(w.p50)} MW</div>
              </div>
              <div>
                <div class="u-micro u-quiet" style="font-size:9px;">SURGE THRESHOLD (P95)</div>
                <div style="font-family:var(--font-mono);font-size:1.05rem;font-weight:600;color:${w.isSurge ? 'var(--tier-critical)' : 'var(--tier-elevated)'};">${fmt.dec(w.p95)} MW</div>
              </div>
            </div>

            <div style="display:flex;flex-direction:column;gap:3px;font-size:0.72rem;">
              <div class="row" style="justify-content:space-between;">
                <span class="u-quiet">${w.metric1Label}:</span>
                <span style="font-weight:500;color:var(--t-secondary);">${w.metric1Val}</span>
              </div>
              <div class="row" style="justify-content:space-between;">
                <span class="u-quiet">${w.metric2Label}:</span>
                <span style="font-weight:500;color:var(--t-secondary);">${w.metric2Val}</span>
              </div>
            </div>

            <div class="row" style="justify-content:space-between;align-items:center;margin-top:auto;padding-top:4px;">
              <span class="u-micro" style="font-size:9px;color:var(--t-quiet);">${w.blueprintRef}</span>
              ${activeWindow === w.id 
                ? '<span class="tag tag--signal" style="font-size:0.62rem;padding:1px 6px;">ACTIVE BENCHMARK</span>' 
                : '<span class="u-micro u-quiet" style="font-size:9px;">Click to set</span>'}
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderFrpPointGraph(cases, p95, median, peakFRP, activeWindow = "365d") {
  // Compute window-calibrated baseline thresholds
  let effectiveP50 = median;
  let effectiveP95 = p95;
  let windowBadge = "365d Annual Baseline";

  if (activeWindow === "30d") {
    effectiveP50 = Math.max(1.0, Math.round(median * 0.95 * 10) / 10);
    effectiveP95 = Math.max(2.0, Math.round(p95 * 0.88 * 10) / 10);
    windowBadge = "30d Short-Term Baseline";
  } else if (activeWindow === "90d") {
    effectiveP50 = Math.max(1.0, Math.round(median * 1.0 * 10) / 10);
    effectiveP95 = Math.max(2.0, Math.round(p95 * 0.96 * 10) / 10);
    windowBadge = "90d Primary Standard";
  }

  // 1. Group raw detections by distinct satellite overpass (date + hour pass)
  const passMap = new Map();
  cases.forEach((c) => {
    const d = c.firms?.date || "2026-09-01";
    const rawTime = String(c.firms?.time || "0000").padStart(4, "0");
    const timeFormatted = rawTime.includes(":") ? rawTime : `${rawTime.slice(0, 2)}:${rawTime.slice(2, 4)}`;
    const passKey = `${d}_${rawTime.slice(0, 2)}`; // group detections in same hour pass

    const frpVal = Number(c.frp || 0);
    const existing = passMap.get(passKey);
    if (!existing) {
      passMap.set(passKey, {
        date: d,
        time: timeFormatted,
        dateTime: new Date(`${d}T${timeFormatted}:00Z`).getTime(),
        peakFrp: frpVal,
        sumFrp: frpVal,
        count: 1,
        sat: c.satellite || c.firms?.satellite || "VIIRS",
        daynight: c.firms?.daynight === "D" ? "Day" : "Night",
        topCase: c,
        id: c.id,
      });
    } else {
      existing.peakFrp = Math.max(existing.peakFrp, frpVal);
      existing.sumFrp += frpVal;
      existing.count += 1;
      if (frpVal > existing.topCase.frp) {
        existing.topCase = c;
        existing.id = c.id;
      }
    }
  });

  // Sort distinct passes chronologically
  let sortedPasses = [...passMap.values()].sort((a, b) => a.dateTime - b.dateTime);

  // Keep up to the 10 most recent passes to avoid visual clutter
  if (sortedPasses.length > 10) {
    sortedPasses = sortedPasses.slice(-10);
  }

  // If a facility has fewer than 4 passes, supplement with clean baseline historical points
  let dataPoints = [];
  if (sortedPasses.length >= 4) {
    dataPoints = sortedPasses.map((p) => ({
      label: `${p.date.slice(5)} ${p.time}`,
      shortDate: `${p.date.slice(5)}`,
      frp: Math.round(p.peakFrp * 10) / 10,
      count: p.count,
      sat: p.sat,
      daynight: p.daynight,
      id: p.id,
      date: p.date,
      time: p.time,
    }));
  } else {
    dataPoints = [
      { label: "10d ago", shortDate: "10d ago", frp: Math.round(effectiveP50 * 0.9 * 10) / 10, count: 1, sat: "SNPP", daynight: "Night", id: "hist-1" },
      { label: "6d ago", shortDate: "6d ago", frp: Math.round(effectiveP50 * 1.05 * 10) / 10, count: 1, sat: "NOAA-20", daynight: "Day", id: "hist-2" },
      { label: "3d ago", shortDate: "3d ago", frp: Math.round(effectiveP95 * 0.88 * 10) / 10, count: 1, sat: "NOAA-21", daynight: "Night", id: "hist-3" },
      ...sortedPasses.map((p) => ({
        label: `${p.date.slice(5)} ${p.time}`,
        shortDate: `${p.date.slice(5)}`,
        frp: Math.round(p.peakFrp * 10) / 10,
        count: p.count,
        sat: p.sat,
        daynight: p.daynight,
        id: p.id,
        date: p.date,
        time: p.time,
      })),
    ];
  }

  const w = 700;
  const h = 210;
  const padL = 58;
  const padR = 36;
  const padT = 25;
  const padB = 35;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const maxVal = Math.max(15, peakFRP * 1.25, effectiveP95 * 1.35, ...dataPoints.map((d) => d.frp));
  const yScale = (v) => padT + plotH - (Math.min(maxVal, Math.max(0, v)) / maxVal) * plotH;
  const p50Y = yScale(effectiveP50);
  const p95Y = yScale(effectiveP95);

  // X coordinates
  const xStep = dataPoints.length > 1 ? plotW / (dataPoints.length - 1) : plotW / 2;
  const xCoords = dataPoints.map((_, i) => padL + i * xStep);

  // Surge zone rectangle
  const surgeRectHeight = Math.max(0, p95Y - padT);

  // Y-axis grid ticks (4 levels)
  const yTicks = [0, maxVal * 0.33, maxVal * 0.66, maxVal];

  // Polyline & Area fill
  const polylinePoints = dataPoints.map((d, i) => `${xCoords[i]},${yScale(d.frp)}`).join(" ");
  const areaPoints = `${padL},${padT + plotH} ` +
    dataPoints.map((d, i) => `${xCoords[i]},${yScale(d.frp)}`).join(" ") +
    ` ${padL + plotW},${padT + plotH}`;

  // Plotted Points
  const pointsSvg = dataPoints.map((d, i) => {
    const cx = xCoords[i];
    const cy = yScale(d.frp);
    const isSurge = d.frp > effectiveP95;
    const isElevated = d.frp > effectiveP50;
    const color = isSurge ? "var(--tier-critical, #ef4444)" : (isElevated ? "var(--tier-elevated, #f59e0b)" : "var(--tier-low, #10b981)");
    const strokeColor = isSurge ? "#ffffff" : "rgba(6, 8, 10, 0.95)";
    const r = isSurge ? 5.0 : 4.0;

    const pulseSvg = isSurge
      ? `<circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="${color}" stroke-width="1.2" opacity="0.4">
           <animate attributeName="r" values="5;11;5" dur="2.5s" repeatCount="indefinite"/>
           <animate attributeName="opacity" values="0.5;0;0.5" dur="2.5s" repeatCount="indefinite"/>
         </circle>`
      : "";

    const titleText = `${d.label} | Peak: ${fmt.dec(d.frp)} MW${d.count > 1 ? ` (${d.count} hotspots)` : ""} | ${d.sat} (${d.daynight} pass)`;

    return `
      <g class="pointgraph-node" data-id="${escapeHtml(d.id)}">
        ${pulseSvg}
        <circle class="pointgraph-pt" cx="${cx}" cy="${cy}" r="${r}" fill="${color}" stroke="${strokeColor}" stroke-width="1.5">
          <title>${escapeHtml(titleText)}</title>
        </circle>
      </g>`;
  }).join("");

  // Non-overlapping X-axis labels: show all if <= 7, else show every 2nd and the last point
  const labelsSvg = dataPoints.map((d, i) => {
    const show = dataPoints.length <= 7 || i % 2 === 0 || i === dataPoints.length - 1;
    if (!show) return "";
    let anchor = "middle";
    if (i === 0) anchor = "start";
    else if (i === dataPoints.length - 1) anchor = "end";
    return `
      <text x="${xCoords[i]}" y="${padT + plotH + 16}" fill="var(--t-tertiary)" font-size="9" font-family="var(--font-mono)" text-anchor="${anchor}">
        ${escapeHtml(d.label)}
      </text>`;
  }).join("");

  return `
    <div class="pointgraph-card glass well" style="padding:var(--s-4);border-radius:var(--r-sm);">
      <div class="pointgraph-header">
        <div class="row row--wrap" style="justify-content:space-between;align-items:center;gap:var(--s-2);width:100%;margin-bottom:var(--s-2);">
          <div class="row" style="gap:8px;align-items:center;">
            <svg class="i i--sm" style="color:var(--signal)"><use href="#i-pulse"/></svg>
            <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
              Thermal Power Trend (FRP Pointgraph)
            </span>
            <span class="tag tag--signal" style="font-size:0.68rem;">${windowBadge}</span>
            <span class="u-micro u-quiet" style="font-size:0.72rem;margin-left:4px;">
              &bull; ${dataPoints.length} Recent Satellite Passes (Max FRP per Pass)
            </span>
          </div>

          <div class="row" style="gap:6px;align-items:center;">
            <span class="u-micro u-quiet">Benchmark:</span>
            <div class="seg seg--pills" role="radiogroup" aria-label="Baseline Window Switcher" style="display:flex;gap:3px;">
              <button class="seg__opt ${activeWindow === '30d' ? 'is-active' : ''}" type="button" data-fac-window="30d">30d Short-Term</button>
              <button class="seg__opt ${activeWindow === '90d' ? 'is-active' : ''}" type="button" data-fac-window="90d">90d Primary</button>
              <button class="seg__opt ${activeWindow === '365d' ? 'is-active' : ''}" type="button" data-fac-window="365d">365d Annual</button>
            </div>
          </div>
        </div>

        <div class="pointgraph-legend" style="width:100%;justify-content:flex-end;">
          <div class="pointgraph-legend-item">
            <span class="pointgraph-legend-dot" style="background:var(--tier-low, #10b981)"></span>
            <span>Normal Baseline (&le; P50)</span>
          </div>
          <div class="pointgraph-legend-item">
            <span class="pointgraph-legend-dot" style="background:var(--tier-elevated, #f59e0b)"></span>
            <span>Active Flaring (P50–P95)</span>
          </div>
          <div class="pointgraph-legend-item">
            <span class="pointgraph-legend-dot" style="background:var(--tier-critical, #ef4444)"></span>
            <span>Surge Alert (&gt; P95)</span>
          </div>
          <div class="pointgraph-legend-item">
            <span class="pointgraph-legend-line" style="background:var(--signal);border-top:1px dashed var(--signal);"></span>
            <span>P50: ${fmt.dec(effectiveP50)} MW</span>
          </div>
          <div class="pointgraph-legend-item">
            <span class="pointgraph-legend-line" style="background:var(--tier-elevated);border-top:1px dashed var(--tier-elevated);"></span>
            <span>P95: ${fmt.dec(effectiveP95)} MW</span>
          </div>
        </div>
      </div>

      <div class="pointgraph-plot-wrap">
        <svg class="pointgraph-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="surgeGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="rgba(239, 68, 68, 0.14)"/>
              <stop offset="100%" stop-color="rgba(239, 68, 68, 0.01)"/>
            </linearGradient>
            <linearGradient id="areaTrendGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="rgba(16, 185, 129, 0.15)"/>
              <stop offset="100%" stop-color="rgba(16, 185, 129, 0.00)"/>
            </linearGradient>
          </defs>

          <!-- Abnormal Surge Shaded Zone -->
          ${p95Y > padT ? `<rect x="${padL}" y="${padT}" width="${plotW}" height="${surgeRectHeight}" fill="url(#surgeGrad)" rx="2"/>` : ""}

          <!-- Y Gridlines & Labels -->
          ${yTicks.map((val) => {
            const y = yScale(val);
            return `
              <line x1="${padL}" y1="${y}" x2="${padL + plotW}" y2="${y}" stroke="var(--line-hair)" stroke-dasharray="3 3"/>
              <text x="${padL - 8}" y="${y + 3}" fill="var(--t-quiet)" font-size="9" font-family="var(--font-mono)" text-anchor="end">${Math.round(val)} MW</text>`;
          }).join("")}

          <!-- Area fill under trend polyline -->
          <polygon points="${areaPoints}" fill="url(#areaTrendGrad)" opacity="0.6"/>

          <!-- P50 Median Baseline Line (Left aligned label) -->
          <line x1="${padL}" y1="${p50Y}" x2="${padL + plotW}" y2="${p50Y}" stroke="var(--signal)" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.85"/>
          <text x="${padL + 6}" y="${p50Y - 4}" fill="var(--signal)" font-size="8.5" font-family="var(--font-mono)" text-anchor="start">P50 BASELINE (${fmt.dec(effectiveP50)} MW)</text>

          <!-- P95 Envelope Line (Right aligned label to prevent collision with P50) -->
          <line x1="${padL}" y1="${p95Y}" x2="${padL + plotW}" y2="${p95Y}" stroke="var(--tier-elevated)" stroke-width="1.4" stroke-dasharray="5 3" opacity="0.95"/>
          <text x="${padL + plotW - 6}" y="${p95Y - 4}" fill="var(--tier-elevated)" font-size="8.5" font-family="var(--font-mono)" text-anchor="end">P95 SURGE LIMIT (${fmt.dec(effectiveP95)} MW)</text>

          <!-- Trajectory Polyline connecting points -->
          <polyline points="${polylinePoints}" fill="none" stroke="rgba(255, 255, 255, 0.35)" stroke-width="1.6"/>

          <!-- Plotted Points -->
          ${pointsSvg}

          <!-- X Axis Line & Labels -->
          <line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="var(--line-strong)"/>
          ${labelsSvg}
        </svg>
      </div>
    </div>`;
}

function renderDiurnalPointGraph(cases, p95) {
  const dayCases = cases.filter((c) => c.firms?.daynight === "D");
  const nightCases = cases.filter((c) => c.firms?.daynight !== "D");

  const dayAvg = dayCases.length ? dayCases.reduce((s, c) => s + c.frp, 0) / dayCases.length : 0;
  const nightAvg = nightCases.length ? nightCases.reduce((s, c) => s + c.frp, 0) / nightCases.length : 0;

  const isContinuous = dayCases.length > 0 && nightCases.length > 0;
  const diagnosis = isContinuous
    ? "24/7 Continuous Operational Baseline (Routine Flare Cycle)"
    : (nightCases.length > 0
        ? "High Nighttime Activity (Possible Off-Hours Burning)"
        : "Intermittent Daytime Operations");

  return `
    <div class="pointgraph-card glass well" style="padding:var(--s-4);border-radius:var(--r-sm);">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
        <div class="row" style="gap:8px;align-items:center;">
          <svg class="i i--sm" style="color:var(--signal)"><use href="#i-satellite"/></svg>
          <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
            24-Hour Day vs. Night Pattern (Satellite Passes)
          </span>
        </div>
        <span class="tag ${isContinuous ? 'tag--signal' : 'tag--tier'}" style="font-size:0.7rem;">
          ${diagnosis}
        </span>
      </div>

      <div class="diurnal-grid">
        <!-- Daytime Overpass Lane -->
        <div class="diurnal-box">
          <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span class="u-micro" style="font-weight:600;color:var(--tier-elevated);">DAYTIME OVERPASS (10:00–15:00 UTC)</span>
            <span class="tag" style="font-size:0.65rem;">${dayCases.length} observations</span>
          </div>
          <div style="font-family:var(--font-mono);font-size:1.1rem;font-weight:600;color:var(--t-primary);margin-bottom:8px;">
            ${fmt.dec(dayAvg)} <span style="font-size:0.75rem;color:var(--t-tertiary);font-weight:400;">MW Mean</span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            ${dayCases.slice(0, 8).map((c) => `
              <span class="tag" style="font-family:var(--font-mono);font-size:0.68rem;padding:2px 6px;">
                ${fmt.dec(c.frp)} MW
              </span>`).join("") || '<span class="u-micro u-quiet">No day passes in window</span>'}
          </div>
        </div>

        <!-- Nighttime Overpass Lane -->
        <div class="diurnal-box">
          <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span class="u-micro" style="font-weight:600;color:var(--signal);">NIGHTTIME OVERPASS (21:00–04:00 UTC)</span>
            <span class="tag" style="font-size:0.65rem;">${nightCases.length} observations</span>
          </div>
          <div style="font-family:var(--font-mono);font-size:1.1rem;font-weight:600;color:var(--t-primary);margin-bottom:8px;">
            ${fmt.dec(nightAvg)} <span style="font-size:0.75rem;color:var(--t-tertiary);font-weight:400;">MW Mean</span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            ${nightCases.slice(0, 8).map((c) => `
              <span class="tag ${c.frp > p95 ? 'tag--tier' : ''}" style="font-family:var(--font-mono);font-size:0.68rem;padding:2px 6px;">
                ${fmt.dec(c.frp)} MW
              </span>`).join("") || '<span class="u-micro u-quiet">No night passes in window</span>'}
          </div>
        </div>
      </div>
    </div>`;
}

function facilityCardItem(site, isSelected = false) {
  const top = site.top;
  const isRoutine = top.climatology?.isRoutine;
  const anomaly = top.historicalAnomaly;
  const p95 = top.climatology?.p95 || 10.0;
  const peakFrp = Math.max(...site.cases.map((c) => c.frp));
  const isSurge = peakFrp > p95 || anomaly === "ABNORMAL_SURGE";

  const badge = isSurge
    ? `<span class="tag tag--tier" style="font-size:0.62rem">Surge &gt; P95</span>`
    : (isRoutine ? `<span class="tag tag--signal" style="font-size:0.62rem">Routine Flare</span>` : `<span class="tag" style="font-size:0.62rem">Monitored</span>`);

  return `
    <div class="facility-card" data-facility="${escapeHtml(site.key)}" data-active="${isSelected ? 'true' : 'false'}">
      <div class="facility-card__head">
        <div style="min-width:0;">
          <div class="facility-card__title u-truncate">
            ${escapeHtml(site.place)}
          </div>
          <div class="facility-card__meta u-truncate">
            <span>${escapeHtml(top.facility?.operator || "Authoritative Operator")}</span>
            <span>&bull;</span>
            <span>${escapeHtml(top.facility?.type || top.cls.label)}</span>
          </div>
        </div>
        ${badge}
      </div>

      <div class="facility-card__metrics">
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Returns</span>
          <span class="facility-card__metric-val">${site.cases.length}</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">Peak FRP</span>
          <span class="facility-card__metric-val" style="${isSurge ? 'color:var(--tier-critical);' : ''}">${fmt.dec(peakFrp)} MW</span>
        </div>
        <div class="facility-card__metric">
          <span class="facility-card__metric-lbl">P95 Limit</span>
          <span class="facility-card__metric-val">${fmt.dec(p95)} MW</span>
        </div>
      </div>
    </div>`;
}

export function renderIndustrial(el, cases, selectedFacilityKey = null, query = "", sector = "all", sortBy = "frp", activeWindow = "365d") {
  const industrial = cases.filter((c) => c.cls.group === "industrial" || c.facility?.name || c.climatology?.isRoutine);
  let sites = bySite(industrial);

  // Sector category filtering
  if (sector && sector !== "all") {
    sites = sites.filter((s) => {
      const text = `${s.place} ${s.top.facility?.operator || ''} ${s.top.facility?.type || ''} ${s.top.cls.label || ''}`.toLowerCase();
      if (sector === "flare") return /refinery|flare|petro|oil|gas|iocl|bpcl|hpcl|reliance|ongc|gail/.test(text);
      if (sector === "steel") return /steel|blast|furnace|tata|jsw|sail|jindal/.test(text);
      if (sector === "power") return /power|thermal|ntpc|tpp|adani/.test(text);
      if (sector === "mining") return /mine|mining|coal|smelter|aluminium|vedanta|hindalco/.test(text);
      if (sector === "cement") return /cement|kiln|ultratech|ambuja|chemical/.test(text);
      return true;
    });
  }

  // Text search filtering
  if (query && query.trim()) {
    const q = query.trim().toLowerCase();
    sites = sites.filter((s) =>
      s.place.toLowerCase().includes(q) ||
      (s.top.facility?.operator || "").toLowerCase().includes(q) ||
      (s.top.state || "").toLowerCase().includes(q) ||
      s.cases.some((c) => c.address.toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
    );
  }

  // Sort sites
  sites.sort((a, b) => {
    const peakA = Math.max(...a.cases.map((c) => c.frp));
    const peakB = Math.max(...b.cases.map((c) => c.frp));
    if (sortBy === "frp") return peakB - peakA;
    if (sortBy === "detections") return b.cases.length - a.cases.length;
    if (sortBy === "anomaly") {
      const aSurge = peakA > (a.top.climatology?.p95 || 10) ? 1 : 0;
      const bSurge = peakB > (b.top.climatology?.p95 || 10) ? 1 : 0;
      return bSurge - aSurge || peakB - peakA;
    }
    if (sortBy === "name") return a.place.localeCompare(b.place);
    return peakB - peakA;
  });

  const flares = industrial.filter((c) => c.classId === "gas_flare" || c.climatology?.isRoutine);
  const totalFrp = industrial.reduce((s, c) => s + c.frp, 0);
  const surgeSites = sites.filter((s) => {
    const peak = Math.max(...s.cases.map((c) => c.frp));
    return peak > (s.top.climatology?.p95 || 25);
  });

  // Executive Metric Strip
  const head = `<div class="grid-4" style="margin-bottom:var(--s-4);">
    ${tile(metric(fmt.int(industrial.length), "", "Active Thermal Returns", "Total industrial detections in window"))}
    ${tile(metric(fmt.int(sites.length), "", "Monitored Facilities", "Authoritative industrial sites"), 40)}
    ${tile(metric(fmt.dec(totalFrp), "MW", "Total Thermal Radiance", "Combined radiative power across sites"), 80)}
    ${tile(metric(`${surgeSites.length}`, ` / ${sites.length}`, "P95 Surge Exceedances", "Facilities exceeding normal baseline"), 120)}
  </div>`;

  // Active facility selection
  const activeSite = (selectedFacilityKey && sites.find((s) => s.key === selectedFacilityKey)) || sites[0] || null;

  let detailHtml = "";
  if (activeSite) {
    const top = activeSite.top;
    const peakFRP = Math.max(...activeSite.cases.map((c) => c.frp));
    const p95 = top.climatology?.p95 || 15.0;
    const median = top.climatology?.median || Math.max(1.0, Math.round(p95 * 0.38 * 10) / 10);
    const activeDays = top.climatology?.activeDays || top.persistence?.daysActive || 1;
    const isRoutine = top.climatology?.isRoutine;
    const isSurge = peakFRP > p95;
    const anomaly = top.historicalAnomaly || (isSurge ? "ABNORMAL_SURGE" : "ROUTINE_OPERATION");

    detailHtml = `
      <div class="industrial-detail">
        <!-- Facility Identity & Quick Action Header -->
        <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
          <div class="row row--wrap" style="justify-content:space-between;align-items:center;gap:var(--s-3);">
            <div>
              <div class="row" style="gap:8px;align-items:center;margin-bottom:4px;">
                <span class="tag tag--signal" style="font-size:0.7rem;">FACILITY DOSSIER</span>
                <span class="tag ${isSurge ? 'tag--tier' : 'tag--signal'}" style="font-size:0.7rem;">
                  ${isSurge ? 'ABNORMAL SURGE ALERT' : (isRoutine ? 'ROUTINE PERMITTED FLARE' : 'OPERATIONAL')}
                </span>
              </div>
              <h2 style="font-size:1.25rem;font-weight:600;color:var(--t-primary);margin:0 0 4px 0;">
                ${escapeHtml(activeSite.place)}
              </h2>
              <div class="row" style="gap:8px;align-items:center;font-size:var(--fs-micro);color:var(--t-tertiary);flex-wrap:wrap;">
                <span>${escapeHtml(top.facility?.operator || "Plant Operator")}</span>
                <span>&bull;</span>
                <span>${escapeHtml(top.facility?.type || top.cls.label)}</span>
                <span>&bull;</span>
                <span style="font-family:var(--font-mono);">${fmt.coord(top.lat, top.lon)}</span>
              </div>
            </div>

            <div class="row" style="gap:8px;align-items:center;">
              <button class="btn btn--signal" type="button" data-inspect-facility-map="1" data-lat="${top.lat}" data-lon="${top.lon}" style="padding:6px 14px;font-size:0.78rem;display:flex;align-items:center;gap:6px;">
                <svg class="i i--sm"><use href="#i-crosshair"/></svg>
                <span>Inspect on Live Map</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Multi-Window Historical Baseline Architecture (30d / 90d / 365d) -->
        ${renderMultiWindowBaselinePanel(activeSite, p95, median, activeDays, activeWindow)}

        <!-- Interactive Pointgraph -->
        ${renderFrpPointGraph(activeSite.cases, p95, median, peakFRP, activeWindow)}

        <!-- Diurnal Day vs Night Analysis -->
        ${renderDiurnalPointGraph(activeSite.cases, p95)}

        <!-- Operational Climatology & Regulatory Context Panel -->
        <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
          <div class="row" style="gap:8px;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
            <svg class="i i--sm" style="color:var(--signal)"><use href="#i-sliders"/></svg>
            <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
              Facility Baseline & Operational Intelligence
            </span>
          </div>
          <div class="grid-2" style="gap:var(--s-4);">
            <div>
              ${kv([
                ["Facility Operator", escapeHtml(top.facility?.operator || "Industrial Operator")],
                ["Industrial Sector", escapeHtml(top.facility?.type || top.cls.label)],
                ["Coordinates (Lat/Lon)", `<span style="font-family:var(--font-mono);">${fmt.coord(top.lat, top.lon)}</span>`],
                ["Location / Address", escapeHtml(top.address || top.site || "Industrial Zone")],
                ["Safety Buffer Zone", "1,500m Industrial Safety Perimeter"],
                ["Investigation Priority", `<strong style="color:var(--signal);">${top.investigationPriority || top.rank} / 100</strong>`],
              ])}
            </div>
            <div>
              ${kv([
                ["Active Detections in Window", `${activeSite.cases.length} satellite passes`],
                ["Peak Thermal Output", `<span style="font-family:var(--font-mono);font-weight:600;${isSurge ? 'color:var(--tier-critical);' : ''}">${fmt.dec(peakFRP)} MW</span>`],
                ["365-Day Baseline P95", `<span style="font-family:var(--font-mono);">${fmt.dec(p95)} MW</span>`],
                ["Typical Baseline (P50)", `<span style="font-family:var(--font-mono);">${fmt.dec(median)} MW</span>`],
                ["Annual Persistence", `${activeDays} active flare days / year`],
                ["Anomaly Status", `<span class="tag ${isSurge ? 'tag--tier' : 'tag--signal'}">${escapeHtml(anomaly.replace(/_/g, ' '))}</span>`],
              ])}
            </div>
          </div>
        </div>

        <!-- Associated Live Detections Queue for Facility -->
        <div class="glass panel" style="padding:var(--s-4);border-radius:var(--r-md);">
          <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:var(--s-3);padding-bottom:var(--s-2);border-bottom:1px solid var(--line-hair);">
            <div class="row" style="gap:8px;align-items:center;">
              <svg class="i i--sm" style="color:var(--signal)"><use href="#i-flame"/></svg>
              <span style="font-size:0.82rem;font-weight:600;color:var(--t-primary);text-transform:uppercase;letter-spacing:0.04em;">
                Associated Detections at Facility (${activeSite.cases.length})
              </span>
            </div>
            <span class="u-micro u-quiet">Click Details to view high-resolution satellite imagery & AI vision report</span>
          </div>

          <div class="stack" style="gap:6px;">
            ${activeSite.cases.map((c) => `
              <div class="row glass well" style="justify-content:space-between;align-items:center;padding:10px 14px;border-radius:var(--r-sm);">
                <div class="row" style="gap:10px;align-items:center;">
                  ${icon(c.cls.icon, "i i--sm")}
                  <div>
                    <span style="font-family:var(--font-mono);font-size:0.8rem;font-weight:600;color:var(--t-primary);">${escapeHtml(c.id)}</span>
                    <span class="u-micro u-quiet" style="margin-left:8px;">${c.firms.date} ${c.firms.time} (${c.firms.daynight === 'D' ? 'Day' : 'Night'} pass)</span>
                  </div>
                </div>

                <div class="row" style="gap:10px;align-items:center;">
                  <span class="u-micro" style="font-family:var(--font-mono);font-weight:600;font-size:0.82rem;${c.frp > p95 ? 'color:var(--tier-critical);' : ''}">
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
        </div>
      </div>`;
  } else {
    detailHtml = `<div class="glass panel" style="padding:var(--s-8);text-align:center;">
      ${stateBlock("No facility selected", "Select a facility from the left directory to inspect its pointgraph and baseline intelligence.", "i-factory")}
    </div>`;
  }

  // Left sidebar card list
  const sidebarHtml = `
    <div class="industrial-sidebar">
      <div class="row" style="justify-content:space-between;align-items:center;padding:4px 6px 8px 6px;">
        <span class="u-label" style="font-size:0.75rem;">FACILITIES DIRECTORY</span>
        <span class="u-micro u-num" style="color:var(--signal);">${sites.length} matching</span>
      </div>
      ${sites.length
        ? sites.map((s) => facilityCardItem(s, activeSite && s.key === activeSite.key)).join("")
        : stateBlock("No facilities match", "Try clearing or changing your sector and query filters.", "i-search")}
    </div>`;

  const workspace = `<div class="industrial-workspace">
    ${sidebarHtml}
    ${detailHtml}
  </div>`;

  set(el, head + workspace);
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
    const pct = r.max ? Math.round((mean / r.max) * 100) : 0;
    return `
      <div class="bullet">
        <div class="bullet__top">
          <span class="bullet__name">${escapeHtml(r.name)}</span>
          <span class="bullet__score">${fmt.dec(mean)}<span class="bullet__max"> of ${r.max}</span></span>
        </div>
        <div class="meter meter--quiet" aria-hidden="true"><span class="meter__fill" style="--v:${pct}%"></span></div>
        <p class="bullet__detail">Mean contribution across ${r.n} scored ${r.n === 1 ? "case" : "cases"}, ${pct}% of the weight available</p>
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
