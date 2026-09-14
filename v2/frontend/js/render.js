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
  return `<span class="tag tag--tier">${c.risk.tier} ${c.risk.score}</span>`;
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

  const rows = cases.map((c) => `
    <button class="spine__row" type="button" data-case="${escapeHtml(c.id)}"
            data-tier="${c.risk.tier}" data-selected="${c.id === selected ? 1 : 0}">
      <span class="spine__rank">${c.rank}</span>
      <span class="spine__main">
        <span class="spine__name">
          <span class="spine__cid">${escapeHtml(c.id)}</span>
          <span class="u-truncate">${escapeHtml(c.place)}</span>
        </span>
        <span class="spine__where u-truncate">
          ${icon(c.cls.icon, "i i--sm")}
          <span>${escapeHtml(c.cls.short)}</span>
          <span class="dot-sep">•</span>
          <span>${fmt.dec(c.frp)} MW</span>
        </span>
      </span>
      <span class="spine__score">${c.risk.score}</span>
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

export function renderOverview(el, ctx) {
  const { cases, ambient, selected } = ctx;
  const tiers = byTier(cases);
  const priority = (tiers.CRITICAL || 0) + (tiers.HIGH || 0);
  const confirmed = cases.filter((c) => c.confirmed).length;
  const sites = bySite(cases);

  const head = `<div class="grid-4">
    ${tile(metric(fmt.int(cases.length), "", "Detections", "In the selected window"), 0)}
    ${tile(metric(fmt.int(priority), "", "Need a decision", "Critical or high tier"), 40)}
    ${tile(metric(`${confirmed}<span class="metric__unit"> of ${cases.length}</span>`, "", "Visually confirmed", "Vision model was certain"), 80)}
    ${tile(metric(fmt.int(sites.length), "", "Distinct sites", "Grouped by reported place"), 120)}
  </div>`;

  const work = panel("Work queue",
    `<span class="tag tag--signal">${priority} priority</span>`,
    `<div id="ov-queue"></div>`,
    { foot: `<p class="u-micro">Ranked by the deterministic risk engine, highest first.</p>` });

  const integrity = panel("Feed integrity", integrityTag(),
    kvRows([
      ["Incidents", `${store.cases.length} records`],
      ["Ambient pixels", `${store.ambient.length} returns`],
      ["Newest acquisition", stampDate(store.anchor)],
      ["Unconfirmed", `${cases.length - confirmed} of ${cases.length}`],
      noticeRow(),
      ["Errors", store.errors.length
        ? store.errors.map((e) => escapeHtml(`${e.source}: ${e.message}`)).join("<br>")
        : "none"],
    ], "kv kv--wide"));

  const when = panel("Acquisition timeline",
    `<span class="u-micro">${cases.length} passes plotted on real time</span>`,
    timeline(cases, selected),
    { foot: legend() });

  const persistencePanel = panel("Satellite Passes & Time-Series Intelligence",
    `<span class="tag tag--signal">Section 7 & 8</span>`,
    kvRows([
      ["Cadence", "2x Daily (12-Hour Cadence)"],
      ["Satellites", "VIIRS (S-NPP, NOAA-20) & MODIS (Aqua, Terra)"],
      ["Pass Timing", "Day ~14:00 IST | Night ~02:30 IST"],
      ["Persistence Rules", "Day + Night Continuous Flare vs Sudden New Ignition"],
      ["Storage Engine", "SQLite WAL Time-Series (firex_history.db)"],
      ["Automated Daemon", "python run.py daemon [--interval 12] [--once]"],
    ], "kv kv--wide"),
    { foot: `<p class="u-micro">Historical multi-pass tracking separates stationary flares from emerging wildfire outbreaks.</p>` });

  set(el, `
    ${head}
    <div class="grid-2">${work}${integrity}</div>
    <div class="grid-2" style="margin-top:var(--s-3)">${persistencePanel}${panel("Risk distribution", "", `<div id="ov-hist"></div>`)}</div>
    ${when}
    <div class="grid-2">
      ${panel("Classification mix", `<span class="u-micro u-num">${cases.length} cases</span>`,
        ranksBlock(byClass(cases), cases.length))}
    </div>`);

  renderQueue(el.querySelector("#ov-queue"), cases, selected, null, 6);
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
                 alt="Satellite crop the vision model examined for ${escapeHtml(c.id)}">` : ""}
      </div>
      <div class="case__foot">
        <dl class="case__stats">
          <div class="case__stat"><dt>FRP</dt><dd>${fmt.dec(c.frp)} MW</dd></div>
          <div class="case__stat"><dt>Risk</dt><dd>${c.risk.score}</dd></div>
          <div class="case__stat"><dt>Conf</dt><dd>${escapeHtml(c.firms.confidence.display)}</dd></div>
        </dl>
        ${status === "UNREVIEWED" ? confTag(c) : `<span class="tag">${escapeHtml(triageOf(status).short)}</span>`}
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
   calls persistent. */

function facilityRow(site) {
  const top = site.top;
  const mix = [...new Set(site.cases.map((c) => c.cls.short))].join(", ");
  return `
    <div class="facility" data-tier="${top.risk.tier}">
      <button class="hit" type="button" data-case="${escapeHtml(top.id)}" data-open="modal"
              aria-label="Open the highest scoring case at ${escapeHtml(site.place)}"></button>
      <div style="min-width:0">
        <p class="facility__name">${icon(top.cls.icon, "i i--sm")}<span class="u-truncate">${escapeHtml(site.place)}</span></p>
        <p class="facility__where u-truncate">${escapeHtml(site.site || mix)}${
          site.cases.length > 1 ? `, ${site.cases.length} detections` : ""}</p>
      </div>
      <dl class="facility__nums">
        <div class="facility__num"><dt>FRP</dt><dd>${fmt.dec(site.frp)} MW</dd></div>
        <div class="facility__num"><dt>Top risk</dt><dd>${top.risk.score}</dd></div>
        <div class="facility__num"><dt>Tier</dt><dd>${tierTag(top)}</dd></div>
      </dl>
    </div>`;
}

export function renderIndustrial(el, cases) {
  const industrial = cases.filter((c) => c.cls.group === "industrial");
  const sites = bySite(industrial);
  const repeat = sites.filter((s) => s.cases.length > 1);
  const flares = industrial.filter((c) => c.classId === "gas_flare");
  const frp = stats(industrial.map((c) => c.frp));

  const head = `<div class="grid-4">
    ${tile(metric(fmt.int(industrial.length), "", "Industrial detections", "Fire, flare or mining class"))}
    ${tile(metric(fmt.int(sites.length), "", "Sites", "Grouped by reported place"), 40)}
    ${tile(metric(fmt.dec(frp.sum), "MW", "Combined FRP", "Sum across these detections"), 80)}
    ${tile(metric(fmt.int(repeat.length), "", "Repeat sites", "Seen in more than one pass"), 120)}
  </div>`;

  const list = sites.length
    ? panel("Sites", `<span class="u-micro u-num">${sites.length}</span>`,
        `<div>${sites.map(facilityRow).join("")}</div>`,
        { bodyCls: "panel__body--flush", foot:
          `<p class="u-micro">Ordered by the highest risk score recorded at each site.</p>` })
    : panel("Sites", "", stateBlock("No industrial classifications",
        "Nothing in this window was placed inside an industrial footprint.", "i-factory"));

  const flareNote = panel("Persistent flares",
    `<span class="u-micro u-num">${flares.length}</span>`,
    flares.length
      ? `<div>${bySite(flares).map(facilityRow).join("")}</div>`
      : stateBlock("No flares in this window", "No detection was classified as a gas flare.", "i-flare"),
    { bodyCls: flares.length ? "panel__body--flush" : "",
      foot: `<p class="u-micro">A steady flare is normal plant operation, so these are listed apart from event driven fires. Escalate one only when its radiative power departs from its own baseline.</p>` });

  set(el, head + list + flareNote);
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
    ${tile(metric(fmt.int(risk.n), "", "Cases scored", `${ambient.length} ambient pixels alongside`))}
    ${tile(metric(fmt.dec(risk.mean), "", "Mean risk", `Median ${risk.median}, range ${risk.min} to ${risk.max}`), 40)}
    ${tile(metric(fmt.dec(frp.median), "MW", "Median FRP", `Total ${fmt.dec(frp.sum)} MW`), 80)}
    ${tile(metric(fmt.dec(frp.max), "MW", "Strongest return", "Highest radiative power in window"), 120)}
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

  const mixes = `<div class="grid-2">
    ${panel("Classification mix", `<span class="u-micro u-num">${cases.length} cases</span>`,
      ranksBlock(byClass(cases), cases.length))}
    ${panel("How the satellite reported confidence", "",
      kvRows([
        ["Numeric percent", `${kinds.percent || 0} cases`],
        ["Named band", `${kinds.band || 0} cases`],
        ["Unreported", `${kinds.unknown || 0} cases`],
        ...Object.entries(sensors).map(([k, v]) => [k, `${v} cases`]),
      ], "kv kv--wide"),
      { foot: `<p class="u-micro">MODIS reports a percentage and VIIRS reports a band. Both are kept in their original wording so the console never invents precision the sensor did not report.</p>` })}
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
    ${field("Unclassified FIRMS pixels",
      "Shows every thermal return in the feed that the pipeline did not raise as a case. Useful for judging whether a case sits alone or inside a wider burn.",
      `<button class="switch" type="button" id="set-ambient" role="switch"
        aria-checked="${prefs.ambient}" aria-label="Show unclassified FIRMS pixels"></button>`)}
    ${field("Detection window",
      "Applies immediately across every view. The window is measured back from the newest acquisition in the feed, not from the clock on this machine.",
      seg("Detection window", Object.entries(WINDOWS).map(([k, v]) => [k, v.label, "window"]), prefs.window))}
    ${field("Base layer",
      "Canvas keeps the detections as the brightest marks on screen. Imagery is for confirming what is physically on the ground.",
      seg("Base layer", Object.entries(BASES).map(([k, v]) => [k, v.label, "base"]), prefs.base))}
    ${field("Triage decisions",
      `${reviewed} of ${store.cases.length} cases carry a decision. Clearing is immediate and cannot be undone.`,
      `<button class="btn btn--sm" type="button" id="set-clear-triage">
        ${icon("i-x", "i i--sm")}Clear decisions</button>`)}
  `);

  const sources = panel("Data sources", store.errors.length
    ? `<span class="tag tag--unconfirmed">${store.errors.length} failing</span>`
    : `<span class="tag">Both reachable</span>`,
    kvRows([
      ["Incident cases", escapeHtml(SOURCES.incidents)],
      ["Ambient returns", escapeHtml(SOURCES.ambient)],
      ["Records loaded", `${store.cases.length} cases, ${store.ambient.length} pixels`],
      ["Newest acquisition", stampDate(store.anchor)],
      ["Satellite crops", "/crops/, served from the imagery stage output"],
      noticeRow(),
      ["Failures", store.errors.length
        ? store.errors.map((e) => escapeHtml(`${e.source}: ${e.message}`)).join("<br>")
        : "none"],
    ], "kv kv--wide"),
    { foot: `<p class="u-micro">The console reads the same files the pipeline writes. It holds no copy of the data and no API key: keys stay server side.</p>` });

  const build = panel("This build", "", kvRows([
    ["Risk engine", "Five weighted factors, 30 / 25 / 20 / 15 / 10"],
    ["Tiers", TIERS.map((t) => `${t.label} ${t.min} to ${t.max}`).join("<br>")],
    ["Classifications", `${Object.keys(CLASSES).length}, including an explicit "not visually confirmable"`],
    ["Triage vocabulary", TRIAGE_ACTIONS.map((k) => escapeHtml(triageOf(k).label)).join("<br>")],
    ["Map", "Leaflet 1.9.4, Esri dark canvas and world imagery tiles"],
    ["Transparency", "Frosted surfaces fall back to solid under prefers-reduced-transparency"],
  ], "kv kv--wide"));

  set(el, controls + `<div class="grid-2">${sources}${build}</div>`);
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
