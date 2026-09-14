/* ==========================================================================
   main - state, routing, event wiring
   One state object, one render pass. Every control writes to state and calls
   render, so the console can never show two views disagreeing about a filter.
   ========================================================================== */

import { FILTERS, WINDOWS, BASES, fmt } from "./config.js";
import { load, store, inWindow, setTriage, getTriage } from "./data.js";
import {
  initMap, mapState, setBase, drawCases, drawAmbient,
  select, clearSelection, hover, fitAll, home, zoomBy, resize, countInView,
} from "./map.js?v=4";
import * as ui from "./render.js?v=17";
import { initDossier, showDrawer, showModal, isModalOpen, refresh } from "./dossier.js?v=15";

const PREFS_KEY = "firex_prefs";

const state = {
  view: "map",
  window: "all",
  filter: "all",
  frpThreshold: 0,
  query: "",
  ambient: false,
  base: "dark",
  theme: "dark",
  selected: null,
  selectedFacility: null,
  facilityQuery: "",
  facilitySector: "all",
  facilitySort: "frp",
  facilityWindow: "365d",
};

const el = {};

function grab() {
  [
    "brand-window", "map-sub", "rail-counts", "risk-hist", "risk-span", "spine", "spine-count",
    "filterbar", "map-strip", "in-view", "alert-flag", "q", "q-clear", "mapkey-glyphs",
    "overview-body", "overview-window", "inv-grid", "inv-filters",
    "industrial-body", "analytics-body", "history-body", "settings-body",
  ].forEach((id) => { el[id] = document.getElementById(id); });
}

/* --- Derived lists -------------------------------------------------------- */

const frpMin = () => Number(state.frpThreshold) || 0;

const windowed = () => store.cases.filter((c) => inWindow(c, state.window));

const windowedWithFrp = () => {
  const min = frpMin();
  return windowed().filter((c) => !min || Number(c.frp || 0) >= min);
};

function visible() {
  const f = FILTERS.find((x) => x.id === state.filter) || FILTERS[0];
  const q = state.query.trim().toLowerCase();
  const min = frpMin();
  return windowed()
    .filter(f.test)
    .filter((c) => !min || Number(c.frp || 0) >= min)
    .filter((c) => !q ||
      `${c.id} ${c.place} ${c.site} ${c.address} ${c.cls.label}`.toLowerCase().includes(q));
}

const ambientInWindow = () => {
  const min = frpMin();
  return store.ambient
    .filter((p) => inWindow(p, state.window))
    .filter((p) => !min || Number(p.frp || 0) >= min);
};

/* --- Preferences ----------------------------------------------------------
   Local to this browser. The console stores no case data and no credentials. */

/* Every stored value is checked against the vocabulary that owns it before it
   reaches state, and an unrecognised one is dropped so the built-in default
   stands. Three of the five used to go through unchecked, which meant a stale or
   hand-edited entry could put the console into a state no control could reach:
   a view id with no section left every panel hidden, a base id asked the map for
   a layer that does not exist, and a non-boolean ambient flag drove an
   aria-checked attribute that read "1" to a screen reader. */
const PREF_VALID = {
  view: (v) => ["map", "overview", "investigations", "industrial", "analytics", "history", "settings"].includes(v),
  window: (v) => Object.prototype.hasOwnProperty.call(WINDOWS, v),
  filter: (v) => FILTERS.some((f) => f.id === v),
  frpThreshold: (v) => typeof v === "number" && v >= 0,
  base: (v) => Object.prototype.hasOwnProperty.call(BASES, v),
  ambient: (v) => typeof v === "boolean",
  theme: (v) => v === "dark" || v === "light",
};

export function setTheme(mode) {
  state.theme = mode === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  const toggle = document.getElementById("theme-toggle-input");
  if (toggle) toggle.checked = state.theme === "dark";
  savePrefs();
}

function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    Object.entries(PREF_VALID).forEach(([key, valid]) => {
      if (saved[key] !== undefined && valid(saved[key])) state[key] = saved[key];
    });
    // Ambient dots OFF by default unless explicitly activated in session
    if (saved.ambient_v2_set !== true) {
      state.ambient = false;
    }
    // In v2, default window to 'all' so detections are never silently filtered out
    if (!saved.window || saved.window === "24h") {
      state.window = "all";
    }
  } catch { /* first run, or storage blocked */ }
  document.documentElement.setAttribute("data-theme", state.theme);
}

function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      view: state.view, window: state.window, filter: state.filter,
      frpThreshold: state.frpThreshold,
      base: state.base, ambient: state.ambient, ambient_v2_set: true, theme: state.theme,
    }));
  } catch { /* private mode: preferences last for this session only */ }
}

/* --- Reveal on scroll ----------------------------------------------------- */

const revealer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.setAttribute("data-shown", "1");
    revealer.unobserve(entry.target);
  });
}, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });

const revealed = new Set();

/* A view animates in the first time it is opened. After that a render is a data
   update rather than an entrance, so the nodes are marked shown instead of being
   observed: replaying the stagger on every keystroke made the card grid fade
   itself back in while the query was still being typed. */
function observeReveals(root, view) {
  const nodes = root.querySelectorAll(".reveal:not([data-shown])");
  if (revealed.has(view)) {
    nodes.forEach((node) => node.setAttribute("data-shown", "1"));
    return;
  }
  revealed.add(view);
  nodes.forEach((node) => revealer.observe(node));
}

/* One render per burst of typing. Nothing else in the console needs this: every
   other control is one press, one intent, one render. */
function debounce(fn, ms) {
  let timer = null;
  const run = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  run.cancel = () => clearTimeout(timer);
  return run;
}

/* --- Selection ------------------------------------------------------------ */

function caseById(id) {
  return store.cases.find((c) => c.id === id) || null;
}

function markSelection() {
  document.querySelectorAll("[data-case][data-selected]").forEach((node) => {
    node.setAttribute("data-selected", node.dataset.case === state.selected ? "1" : "0");
  });
}

/* The spine is a short scroll region, so a case picked from a marker or with the
   arrow keys can be ranked below its fold and left highlighted where nobody can
   see it. Scroll the spine itself rather than calling scrollIntoView, which also
   scrolls every scrollable ancestor and would drag the map out of view at the
   widths where the map view scrolls. Only ever called on a deliberate selection,
   so a render never yanks the list back while it is being read. */
function revealSelected() {
  const box = el.spine;
  const row = box?.querySelector('.spine__row[data-selected="1"]');
  if (!row) return;
  const b = box.getBoundingClientRect();
  const r = row.getBoundingClientRect();
  if (r.top < b.top) box.scrollTop -= b.top - r.top;
  else if (r.bottom > b.bottom) box.scrollTop += r.bottom - b.bottom;
}

function pick(id, { modal = false, fly = true } = {}) {
  const c = caseById(id);
  if (!c) return;
  state.selected = id;
  select(id, { fly: fly && state.view === "map" });
  showDrawer(c);
  if (modal) showModal(c);
  markSelection();
  revealSelected();
}

function step(delta) {
  const list = visible();
  if (!list.length) return;
  const at = list.findIndex((c) => c.id === state.selected);
  const next = list[(at + delta + list.length) % list.length] || list[0];
  pick(next.id, { modal: isModalOpen() });
}

/* --- Small formatters ----------------------------------------------------- */

function anchorStamp() {
  const d = store.anchor;
  if (!d) return "no acquisitions";
  const day = String(d.getUTCDate()).padStart(2, "0");
  const mon = d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${day} ${mon}, ${hh}:${mm} UTC`;
}

/* The window control is repeated above the overview so the totals on that page
   can never be read against a window the reader cannot see. */
function windowSeg() {
  return `<div class="seg" role="radiogroup" aria-label="Detection window">${Object.entries(WINDOWS)
    .map(([id, w]) => `<button class="seg__opt" type="button" role="radio"
      aria-checked="${id === state.window}" data-window="${id}">${w.label}</button>`)
    .join("")}</div>`;
}

/* --- Header state --------------------------------------------------------- */

/* The bell carries a dot, not a number, so the count lives in the label where
   a screen reader and a tooltip can both reach it. */
function updateAlerts(win) {
  const waiting = win.filter((c) =>
    (c.risk.tier === "CRITICAL" || c.risk.tier === "HIGH") && getTriage(c.id) === "UNREVIEWED");
  if (el["alert-flag"]) el["alert-flag"].hidden = waiting.length === 0;

  const btn = document.getElementById("btn-alerts");
  if (!btn) return;
  const label = waiting.length
    ? `${waiting.length} priority case${waiting.length === 1 ? "" : "s"} waiting on a decision, jump to the first`
    : "No priority cases waiting on a decision";
  btn.setAttribute("aria-label", label);
  btn.title = label;
}

function updateInView(counts) {
  if (!el["in-view"]) return;
  const n = counts && typeof counts.cases === "number" ? counts : countInView();
  el["in-view"].textContent = String(n.cases);
}

/* --- Controls -------------------------------------------------------------
   Every pressed state is pushed back from state, so a window changed in the
   settings view is already correct on the map segment when you return to it. */

function updateSpotlightAmbience() {
  const nav = document.getElementById("spotlight-nav");
  if (!nav) return;
  const activeTab = nav.querySelector(`.spotlight-nav__item[data-view="${state.view}"]`);
  if (activeTab) {
    const navRect = nav.getBoundingClientRect();
    const tabRect = activeTab.getBoundingClientRect();
    const leftOffset = tabRect.left - navRect.left;
    nav.style.setProperty("--ambience-x", `${leftOffset}px`);
    nav.style.setProperty("--active-tab-w", `${tabRect.width}px`);
  }
}

function initSpotlightNav() {
  const nav = document.getElementById("spotlight-nav");
  if (!nav) return;
  
  nav.addEventListener("mousemove", (e) => {
    const navRect = nav.getBoundingClientRect();
    const mouseX = e.clientX - navRect.left;
    nav.style.setProperty("--spotlight-x", `${mouseX}px`);
    nav.style.setProperty("--spotlight-opacity", "1");
  });

  nav.addEventListener("mouseleave", () => {
    nav.style.setProperty("--spotlight-opacity", "0");
  });

  updateSpotlightAmbience();
}

function syncControls() {
  document.querySelectorAll("button[data-window]").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.window === state.window));
  });
  document.querySelectorAll("button[data-base]").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.base === state.base));
  });
  document.querySelectorAll("button[data-frp]").forEach((b) => {
    const bVal = Number(b.dataset.frp) || 0;
    b.setAttribute("aria-checked", String(bVal === state.frpThreshold));
  });
  document.getElementById("btn-ambient")?.setAttribute("aria-pressed", String(state.ambient));
  document.querySelectorAll(".tab[data-view]").forEach((t) => {
    if (t.dataset.view === state.view) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  });
  const themeToggle = document.getElementById("theme-toggle-input");
  if (themeToggle) themeToggle.checked = state.theme === "dark";
  updateSpotlightAmbience();
}

/* --- Views ---------------------------------------------------------------- */

const VIEW_BODY = {
  overview: "overview-body",
  investigations: "inv-grid",
  industrial: "industrial-body",
  analytics: "analytics-body",
  history: "history-body",
  settings: "settings-body",
};

const histState = {
  query: "",
  state: "",
  startDate: "2026-09-01",
  endDate: "",
  minFrp: 0,
  limit: 50,
  offset: 0,
  loading: false,
  data: null,
};

async function executeHistorySearch() {
  const qInput = document.getElementById("hist-input-query");
  const stSelect = document.getElementById("hist-select-state");
  const sInput = document.getElementById("hist-input-start");
  const eInput = document.getElementById("hist-input-end");

  if (qInput) histState.query = qInput.value.trim();
  if (stSelect) histState.state = stSelect.value;
  if (sInput) histState.startDate = sInput.value;
  if (eInput) histState.endDate = eInput.value;

  histState.loading = true;
  if (el["history-body"]) ui.renderHistory(el["history-body"], histState);

  try {
    const params = new URLSearchParams();
    if (histState.query) params.set("query", histState.query);
    if (histState.state) params.set("state", histState.state);
    if (histState.startDate) params.set("start_date", histState.startDate);
    if (histState.endDate) params.set("end_date", histState.endDate);
    if (histState.minFrp > 0) params.set("min_frp", String(histState.minFrp));
    params.set("limit", String(histState.limit));
    params.set("offset", String(histState.offset));

    const res = await fetch(`/api/history/search?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    histState.data = data;
  } catch (err) {
    console.error("Historical search query failed:", err);
    histState.data = { total_matches: 0, returned: 0, limit: histState.limit, offset: histState.offset, results: [], summary: null };
  } finally {
    histState.loading = false;
    if (el["history-body"]) ui.renderHistory(el["history-body"], histState);
  }
}

function exportHistoryCsv() {
  if (!histState.data || !histState.data.results || !histState.data.results.length) return;
  const rows = histState.data.results;
  const headers = ["Observation ID", "Satellite", "Sensor", "Acquired (UTC)", "Day/Night", "Latitude", "Longitude", "State", "District", "Nearest Industrial Asset", "Distance (km)", "FRP (MW)", "Confidence"];
  const csvContent = [
    headers.join(","),
    ...rows.map(r => [
      `"${r.id}"`,
      `"${r.satellite || ""}"`,
      `"${r.sensor || ""}"`,
      `"${r.acquired_at || ""}"`,
      `"${r.daynight || ""}"`,
      r.latitude,
      r.longitude,
      `"${(r.state || "").replace(/"/g, '""')}"`,
      `"${(r.district || "").replace(/"/g, '""')}"`,
      `"${(r.nearest_facility || "").replace(/"/g, '""')}"`,
      r.distance_km != null ? r.distance_km.toFixed(3) : "",
      r.frp_mw != null ? r.frp_mw : "",
      `"${r.confidence || ""}"`
    ].join(","))
  ].join("\r\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 10);
  link.setAttribute("href", url);
  link.setAttribute("download", `FIREX_Historical_Observations_${histState.state || "India"}_${ts}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function wireHistorySearch() {
  const container = el["history-body"];
  if (!container) return;

  container.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;

    const submitBtn = t.closest("#btn-hist-submit");
    if (submitBtn) {
      histState.offset = 0;
      executeHistorySearch();
      return;
    }

    const resetBtn = t.closest("#btn-hist-reset");
    if (resetBtn) {
      histState.query = "";
      histState.state = "";
      histState.startDate = "2026-09-01";
      histState.endDate = "";
      histState.minFrp = 0;
      histState.offset = 0;
      histState.data = null;
      ui.renderHistory(container, histState);
      return;
    }

    const exportBtn = t.closest("#btn-hist-export");
    if (exportBtn) {
      exportHistoryCsv();
      return;
    }

    const presetBtn = t.closest("button[data-preset]");
    if (presetBtn) {
      const pid = presetBtn.dataset.preset;
      const today = new Date().toISOString().slice(0, 10);
      if (pid === "24h") {
        histState.startDate = today;
        histState.endDate = today;
      } else if (pid === "7d") {
        const d = new Date();
        d.setDate(d.getDate() - 7);
        histState.startDate = d.toISOString().slice(0, 10);
        histState.endDate = today;
      } else if (pid === "30d") {
        const d = new Date();
        d.setDate(d.getDate() - 30);
        histState.startDate = d.toISOString().slice(0, 10);
        histState.endDate = today;
      } else if (pid === "sep2026") {
        histState.startDate = "2026-09-01";
        histState.endDate = "2026-09-15";
      } else if (pid === "all") {
        histState.startDate = "";
        histState.endDate = "";
      }
      histState.offset = 0;
      executeHistorySearch();
      return;
    }

    const frpBtn = t.closest("button[data-minfrp]");
    if (frpBtn) {
      histState.minFrp = Number(frpBtn.dataset.minfrp) || 0;
      histState.offset = 0;
      executeHistorySearch();
      return;
    }

    const prevBtn = t.closest("#btn-hist-prev");
    if (prevBtn) {
      histState.offset = Math.max(0, histState.offset - histState.limit);
      executeHistorySearch();
      return;
    }

    const nextBtn = t.closest("#btn-hist-next");
    if (nextBtn) {
      histState.offset += histState.limit;
      executeHistorySearch();
      return;
    }

    const inspectBtn = t.closest(".btn-hist-inspect");
    if (inspectBtn) {
      const lat = Number(inspectBtn.dataset.lat);
      const lon = Number(inspectBtn.dataset.lon);
      if (!isNaN(lat) && !isNaN(lon)) {
        setView("map");
        if (mapState.map) {
          mapState.map.setView([lat, lon], 13);
        }
      }
      return;
    }
  });

  container.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target && e.target.id === "hist-input-query") {
      histState.offset = 0;
      executeHistorySearch();
    }
  });
}

const VIEWS = {
  map: () => {},
  overview: () => {
    if (el["overview-window"]) el["overview-window"].innerHTML = windowSeg();
    ui.renderOverview(el["overview-body"],
      { cases: visible(), ambient: ambientInWindow(), selected: state.selected });
  },
  investigations: () => ui.renderInvestigations(el["inv-grid"], visible(), state.selected),
  industrial: () => ui.renderIndustrial(el["industrial-body"], windowed(), state.selectedFacility, state.facilityQuery, state.facilitySector, state.facilitySort, state.facilityWindow),
  analytics: () => ui.renderAnalytics(el["analytics-body"], windowed(), ambientInWindow()),
  history: () => {
    ui.renderHistory(el["history-body"], histState);
    if (!histState.data && !histState.loading) {
      executeHistorySearch();
    }
  },
  settings: () => ui.renderSettings(el["settings-body"], state),
};

/* Only the view on screen is rebuilt. The others are rebuilt when they open,
   which keeps a filter change from touching five hundred nodes at once. */
function renderView() {
  if (!store.loaded) return;   /* the skeletons hold the shape until data lands */
  const failed = store.errors.find((e) => e.source === "incidents");
  const body = el[VIEW_BODY[state.view]];

  if (failed && body) {
    ui.renderFailure(body, "Incident cases", failed.message);
    body.firstElementChild?.style.setProperty("grid-column", "1 / -1");
  } else {
    VIEWS[state.view]?.();
  }
  const host = document.getElementById(`view-${state.view}`);
  if (host) observeReveals(host, state.view);
}

/* --- One render pass ------------------------------------------------------ */

/* Ambient pixels are filtered by the window alone: no class filter and no query
   touches them. Rebuilding every one of them on each keystroke, filter press and
   triage decision meant hundreds of canvas markers and their tooltips thrown
   away and rebuilt identically, so the inputs are compared first. The feed is
   loaded once and never mutated, so its length settles the rest. */
let ambientKey = "";

function drawAmbientIfChanged(points) {
  const key = `${state.window}|${state.ambient}|${state.frpThreshold}|${points.length}`;
  if (key === ambientKey) return;
  ambientKey = key;
  drawAmbient(points, state.ambient);
}

function renderAll() {
  const win = windowedWithFrp();
  const list = visible();
  const amb = ambientInWindow();
  const failed = store.errors.find((e) => e.source === "incidents");

  if (el["brand-window"]) {
    el["brand-window"].textContent = failed
      ? "incident source unavailable"
      : `${win.length} in ${WINDOWS[state.window].label}, newest ${anchorStamp()}`;
  }
  /* Three things this line can be reporting: no data, data but no map to put it
     on, or the normal case. The empty frame is the one a reader cannot diagnose
     unaided, so it gets said out loud rather than left to the notice behind it. */
  if (el["map-sub"]) {
    let sub;
    if (failed) {
      sub = "Incident cases did not load. Start the console through server.py, then reload.";
    } else if (!mapState.map) {
      sub = `${list.length} of ${win.length} detections listed. The map is unavailable, so they are in the spine and the other views only.`;
    } else {
      sub = `${list.length} of ${win.length} detections shown, ${fmt.int(amb.length)} unclassified pixels`;
    }
    el["map-sub"].textContent = sub;
  }

  if (el["rail-counts"]) ui.renderRailCounts(el["rail-counts"], win, store.cases);
  if (el["risk-hist"]) ui.renderRiskHist(el["risk-hist"], win, el["risk-span"]);
  if (el.spine) ui.renderSpine(el.spine, list, state.selected, el["spine-count"]);
  if (el.filterbar) ui.renderFilterBar(el.filterbar, win, state.filter);
  if (el["inv-filters"]) ui.renderFilterBar(el["inv-filters"], win, state.filter);
  if (el["map-strip"]) ui.renderStrip(el["map-strip"], list, amb);

  drawCases(list);
  drawAmbientIfChanged(amb);

  syncControls();
  updateAlerts(win);
  updateInView();
  renderView();
  markSelection();
  refresh();
  savePrefs();
}

function setView(id) {
  if (!document.getElementById(`view-${id}`)) return;
  state.view = id;
  document.querySelectorAll(".view").forEach((v) => {
    v.setAttribute("data-active", v.id === `view-${id}` ? "1" : "0");
  });
  syncControls();
  renderView();
  /* Leaflet measured a hidden frame while another view was up, so the map has
     to be told it has a size again. */
  if (id === "map") resize();
  savePrefs();
}

/* --- Destructive control --------------------------------------------------
   Clearing every triage decision cannot be undone, so the button arms on the
   first press and only clears on a second. No native confirm dialog: it would
   be the one piece of chrome on the page the console does not control. */

let armTimer = null;

function armClear(btn) {
  if (btn.dataset.armed === "1") {
    clearTimeout(armTimer);
    store.cases.forEach((c) => setTriage(c.id, "UNREVIEWED"));
    renderAll();
    return;
  }
  btn.dataset.armed = "1";
  btn.textContent = "Press again to clear every decision";
  clearTimeout(armTimer);
  armTimer = setTimeout(renderAll, 4000);
}

/* The bell is only worth pressing if it lands on the case that needs the
   decision, so it widens the filter far enough to show it. */
function jumpToPriority() {
  const waiting = windowed().filter((c) =>
    (c.risk.tier === "CRITICAL" || c.risk.tier === "HIGH") && getTriage(c.id) === "UNREVIEWED");
  if (!waiting.length) return;

  const target = waiting[0];
  const active = FILTERS.find((f) => f.id === state.filter);
  if (active && !active.test(target)) state.filter = "critical";
  if (state.query) {
    state.query = "";
    if (el.q) el.q.value = "";
    if (el["q-clear"]) el["q-clear"].hidden = true;
  }
  setView("map");
  renderAll();
  pick(target.id, { modal: false });
}

/* --- Wiring ---------------------------------------------------------------
   Delegated from the document, because most of these controls are written by
   a render pass and would lose a directly bound listener. */

function wireDelegates() {
  document.addEventListener("click", (event) => {
    const t = event.target;
    if (!(t instanceof Element)) return;

    const tab = t.closest(".tab[data-view]");
    if (tab) { setView(tab.dataset.view); return; }

    /* Markers report through the map's own selection callback, and the drawer
       and modal own their clicks, so both are left alone here. */
    const hit = t.closest("[data-case]");
    if (hit && !hit.closest("#map, .drawer, .modal")) {
      pick(hit.dataset.case, { modal: hit.dataset.open === "modal" });
      return;
    }

    /* Scoped to buttons on purpose. The map frame itself carries data-base to
       drive its CSS, and a bare [data-base] would swallow every click inside
       the map stage, filter pills included. */
    const win = t.closest("button[data-window]");
    if (win) { state.window = win.dataset.window; renderAll(); return; }

    const base = t.closest("button[data-base]");
    if (base) {
      state.base = base.dataset.base;
      setBase(state.base);
      syncControls();
      savePrefs();
      return;
    }

    const filter = t.closest("button[data-filter]");
    if (filter) { state.filter = filter.dataset.filter; renderAll(); return; }

    const frp = t.closest("button[data-frp]");
    if (frp) {
      const val = Number(frp.dataset.frp) || 0;
      if (state.frpThreshold === val && val !== 0) {
        state.frpThreshold = 0; // toggle off back to all
      } else {
        state.frpThreshold = val;
      }
      syncControls();
      renderAll();
      savePrefs();
      return;
    }

    const fac = t.closest("[data-facility]");
    if (fac) {
      state.selectedFacility = fac.dataset.facility;
      renderView();
      return;
    }

    const secBtn = t.closest("#industrial-sector-filter button[data-sector]");
    if (secBtn) {
      state.facilitySector = secBtn.dataset.sector || "all";
      document.querySelectorAll("#industrial-sector-filter button[data-sector]").forEach((b) => {
        b.classList.toggle("is-active", b.dataset.sector === state.facilitySector);
        b.setAttribute("aria-checked", String(b.dataset.sector === state.facilitySector));
      });
      renderView();
      return;
    }

    const inspectMapBtn = t.closest("[data-inspect-facility-map]");
    if (inspectMapBtn) {
      const lat = Number(inspectMapBtn.dataset.lat);
      const lon = Number(inspectMapBtn.dataset.lon);
      if (!isNaN(lat) && !isNaN(lon)) {
        setView("map");
        if (mapState.map) {
          mapState.map.flyTo([lat, lon], 14, { duration: 1.2 });
        }
      }
      return;
    }

    const facWinBtn = t.closest("[data-fac-window]");
    if (facWinBtn) {
      state.facilityWindow = facWinBtn.dataset.facWindow || "365d";
      renderView();
      return;
    }

    if (t.closest("#set-ambient")) { state.ambient = !state.ambient; renderAll(); return; }

    const clear = t.closest("#set-clear-triage");
    if (clear) armClear(clear);
  });

  /* Hover locates a case on the map: one attribute flip, no layer rebuild. */
  const hoverHandler = (on) => (event) => {
    const t = event.target;
    if (!(t instanceof Element)) return;
    const hit = t.closest("[data-case]");
    if (hit && !hit.closest("#map")) hover(hit.dataset.case, on);
  };
  document.addEventListener("pointerover", hoverHandler(true));
  document.addEventListener("pointerout", hoverHandler(false));
}

function wireControls() {
  const on = (id, fn) => document.getElementById(id)?.addEventListener("click", fn);
  on("btn-fit", () => fitAll());
  on("btn-home", () => home());
  on("btn-zoom-in", () => zoomBy(1));
  on("btn-zoom-out", () => zoomBy(-1));
  on("btn-ambient", () => { state.ambient = !state.ambient; renderAll(); });
  on("btn-alerts", jumpToPriority);

  const facInput = document.getElementById("facility-search-input");
  if (facInput) {
    const onFacSearch = debounce(() => {
      state.facilityQuery = facInput.value;
      renderView();
    }, 120);
    facInput.addEventListener("input", onFacSearch);
  }

  const sortSelect = document.getElementById("industrial-sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      state.facilitySort = e.target.value || "frp";
      renderView();
    });
  }

  const themeToggle = document.getElementById("theme-toggle-input");
  if (themeToggle) {
    themeToggle.checked = state.theme === "dark";
    themeToggle.addEventListener("change", (e) => {
      setTheme(e.target.checked ? "dark" : "light");
    });
  }

  /* Typing is the one control that fires many times for a single intent, so the
     render is coalesced. The query itself is written immediately: a pill pressed
     mid-burst has to filter against the text that is already in the box. */
  const renderSoon = debounce(renderAll, 120);

  el.q?.addEventListener("input", () => {
    state.query = el.q.value;
    if (el["q-clear"]) el["q-clear"].hidden = !state.query;
    renderSoon();
  });
  el["q-clear"]?.addEventListener("click", () => {
    renderSoon.cancel();
    el.q.value = "";
    state.query = "";
    el["q-clear"].hidden = true;
    el.q.focus();
    renderAll();
  });
}

/* Arrow keys walk the filtered list in rank order. Ignored while typing, so
   the search box keeps its own cursor movement. */
function wireKeys() {
  document.addEventListener("keydown", (event) => {
    const t = event.target;
    if (t instanceof HTMLElement &&
        (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
  });
}

/* --- Satellite Orbit & Persistence Sync Widget (Section 7 & 8) ----------- */
async function updatePersistenceWidget() {
  try {
    const res = await fetch("/api/history-stats");
    if (!res.ok) return;
    const data = await res.json();
    const passBadge = document.getElementById("daemon-pass-badge");
    const totalHotspots = document.getElementById("daemon-total-hotspots");
    const lastUpdated = document.getElementById("daemon-last-updated");

    if (passBadge) passBadge.textContent = `${data.current_pass} PASS ACTIVE`;
    if (totalHotspots) totalHotspots.textContent = Number(data.total_hotspots).toLocaleString();
    if (lastUpdated) lastUpdated.textContent = data.last_run ? `Last pass: ${data.last_run.split(" ")[1] || data.last_run}` : "Last updated: Today";
  } catch { /* graceful fallback */ }
}

function wirePersistenceSync() {
  const syncBtn = document.getElementById("btn-trigger-sync");
  const runBtn = document.getElementById("btn-run-analysis");
  const scrim = document.getElementById("sync-scrim");
  if (!scrim) return;

  const triggerButtons = [syncBtn, runBtn].filter(Boolean);
  if (!triggerButtons.length) return;

  const barFill = document.getElementById("sync-bar-fill");
  const pctDisplay = document.getElementById("sync-pct-display");
  const phaseLabel = document.getElementById("sync-phase-label");
  const badgeStatus = document.getElementById("sync-badge-status");
  const timerLabel = document.getElementById("sync-timer-label");
  const logTerminal = document.getElementById("sync-log-terminal");
  const footerStatus = document.getElementById("sync-footer-status");
  const closeBtn = document.getElementById("sync-btn-close");

  let activeEvtSource = null;
  let activeTimerInterval = null;

  function closeModal() {
    scrim.setAttribute("data-open", "0");
    if (activeEvtSource) {
      try { activeEvtSource.close(); } catch {}
      activeEvtSource = null;
    }
    if (activeTimerInterval) {
      clearInterval(activeTimerInterval);
      activeTimerInterval = null;
    }
    triggerButtons.forEach((b) => { b.disabled = false; });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closeModal);
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && scrim.getAttribute("data-open") === "1") {
      closeModal();
    }
  });

  function addLog(msg, tag = "STREAM") {
    if (!logTerminal) return;
    const now = new Date().toTimeString().split(" ")[0];
    const row = document.createElement("div");
    row.className = "sync-log-entry";
    row.innerHTML = `<span class="sync-log-ts">[${now}]</span><span class="sync-log-msg">[${tag}] ${msg}</span>`;
    logTerminal.appendChild(row);
    logTerminal.scrollTop = logTerminal.scrollHeight;
  }

  const startPipelineSync = () => {
    triggerButtons.forEach((b) => { b.disabled = true; });
    const origSyncHtml = syncBtn ? syncBtn.innerHTML : "";
    const origRunHtml = runBtn ? runBtn.innerHTML : "";
    if (syncBtn) syncBtn.innerHTML = `<span class="tag__dot" style="background:#38bdf8"></span> Syncing...`;
    if (runBtn) runBtn.innerHTML = `<span class="tag__dot" style="background:#38bdf8"></span> Running...`;

    // Open Modal HUD
    scrim.setAttribute("data-open", "1");
    if (barFill) barFill.style.width = "0%";
    if (pctDisplay) pctDisplay.textContent = "0%";
    if (phaseLabel) phaseLabel.innerHTML = `<span class="tag__dot" style="background:#38bdf8;width:6px;height:6px;border-radius:50%;"></span> CONNECTING TO ORBIT ENGINE...`;
    if (badgeStatus) {
      badgeStatus.className = "sync-badge sync-badge--running";
      badgeStatus.innerHTML = `<span class="tag__dot" style="background:#38bdf8;width:7px;height:7px;border-radius:50%;"></span> ORBIT PIPELINE ACTIVE`;
    }
    if (footerStatus) {
      footerStatus.textContent = "INITIALIZING SATELLITE ANALYSIS WORKFLOW...";
      footerStatus.style.color = "#38bdf8";
    }

    // Reset Stages
    for (let i = 1; i <= 5; i++) {
      const row = document.getElementById(`sync-stage-${i}`);
      const icon = row ? row.querySelector(".sync-stage-icon") : null;
      const statusBadge = document.getElementById(`sync-status-${i}`);
      if (row) row.setAttribute("data-status", "pending");
      if (icon) icon.textContent = `${i}`;
      if (statusBadge) {
        statusBadge.textContent = "PENDING";
        statusBadge.style.color = "";
      }
    }

    const subprogressEl = document.getElementById("sync-stage-5-subprogress");
    const subfillEl = document.getElementById("sync-stage-5-subfill");
    const subtextEl = document.getElementById("sync-stage-5-subtext");
    if (subprogressEl) subprogressEl.style.display = "none";
    if (subfillEl) subfillEl.style.width = "0%";
    if (subtextEl) subtextEl.textContent = "Waiting to inspect targets...";

    // Reset log terminal
    if (logTerminal) {
      logTerminal.innerHTML = "";
      addLog("Starting automated thermal analysis pipeline...", "SYSTEM");
    }

    // Start timer
    const startTime = Date.now();
    activeTimerInterval = setInterval(() => {
      const elapsedSec = Math.floor((Date.now() - startTime) / 1000);
      const mm = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
      const ss = String(elapsedSec % 60).padStart(2, "0");
      if (timerLabel) timerLabel.textContent = `ELAPSED: ${mm}:${ss}`;
    }, 500);

    // Connect to Server-Sent Events stream
    let isCompleted = false;
    activeEvtSource = new EventSource("/api/trigger-sync-stream");
    const evtSource = activeEvtSource;

    const handleSseMessage = async (event) => {
      try {
        const data = JSON.parse(event.data);
        const stageNum = Number(data.stage || 0);
        const pct = Math.min(100, Math.max(0, Number(data.pct || 0)));
        const cIdx = data.candidate_index || (data.data && data.data.candidate_index);
        const cTotal = data.candidates_total || (data.data && data.data.candidates_total);

        // Update progress bar & percent
        if (barFill) barFill.style.width = `${pct}%`;
        if (pctDisplay) pctDisplay.textContent = `${pct}%`;

        if (data.label && phaseLabel) {
          if (stageNum === 5 && cIdx && cTotal) {
            phaseLabel.innerHTML = `<span class="tag__dot"></span> STAGE 5: AI VISION ANALYSIS (${cIdx}/${cTotal})`;
          } else {
            phaseLabel.innerHTML = `<span class="tag__dot"></span> STAGE ${stageNum}: ${data.label.toUpperCase()}`;
          }
        }

        // Add to terminal log
        if (data.detail) {
          addLog(`${data.label} — ${data.detail}`, `STAGE ${stageNum}`);
        }

        // Update stages
        for (let i = 1; i <= 5; i++) {
          const row = document.getElementById(`sync-stage-${i}`);
          const icon = row ? row.querySelector(".sync-stage-icon") : null;
          const statusBadge = document.getElementById(`sync-status-${i}`);
          const desc = document.getElementById(`sync-desc-${i}`);

          if (i < stageNum) {
            if (row) row.setAttribute("data-status", "done");
            if (icon) icon.textContent = "✓";
            if (statusBadge) statusBadge.textContent = "VERIFIED ✓";
          } else if (i === stageNum) {
            if (data.done && pct >= 100) {
              if (row) row.setAttribute("data-status", "done");
              if (icon) icon.textContent = "✓";
              if (statusBadge) statusBadge.textContent = "VERIFIED ✓";
            } else {
              if (row) row.setAttribute("data-status", "active");
              if (icon) icon.textContent = `${i}`;
              if (statusBadge) {
                if (i === 5 && cIdx && cTotal) {
                  statusBadge.textContent = `TARGET ${cIdx}/${cTotal} (${Math.round((cIdx/cTotal)*100)}%)`;
                } else {
                  statusBadge.textContent = "PROCESSING...";
                }
              }
            }
            if (desc && data.detail) desc.textContent = data.detail;
          } else {
            if (row) row.setAttribute("data-status", "pending");
            if (icon) icon.textContent = `${i}`;
            if (statusBadge) statusBadge.textContent = "PENDING";
          }
        }

        // Handle Stage 5 specific sub-progress
        if (stageNum === 5 && cIdx && cTotal) {
          const subPct = Math.min(100, Math.round((cIdx / cTotal) * 100));
          if (subprogressEl) subprogressEl.style.display = "flex";
          if (subfillEl) subfillEl.style.width = `${subPct}%`;
          if (subtextEl) {
            const incCode = data.incident_code || (data.data && data.data.incident_code) || "";
            subtextEl.textContent = `Inspecting Target ${cIdx} of ${cTotal} (${subPct}%)${incCode ? ` — ${incCode}` : ""}`;
          }
        } else if (stageNum > 5 || (data.done && pct >= 100)) {
          if (subprogressEl) {
            subprogressEl.style.display = "flex";
            if (subfillEl) subfillEl.style.width = "100%";
            if (subtextEl) subtextEl.textContent = "All targets analyzed with Vision AI";
          }
        }

        if (footerStatus && data.detail) {
          footerStatus.textContent = data.detail.slice(0, 80);
        }

        // Check if finished
        if (data.done || pct >= 100) {
          if (isCompleted) return;
          isCompleted = true;
          if (activeTimerInterval) {
            clearInterval(activeTimerInterval);
            activeTimerInterval = null;
          }
          evtSource.close();

          // Mark all stages complete
          for (let i = 1; i <= 5; i++) {
            const row = document.getElementById(`sync-stage-${i}`);
            const icon = row ? row.querySelector(".sync-stage-icon") : null;
            const statusBadge = document.getElementById(`sync-status-${i}`);
            if (row) row.setAttribute("data-status", "done");
            if (icon) icon.textContent = "✓";
            if (statusBadge) statusBadge.textContent = "VERIFIED ✓";
          }

          if (barFill) barFill.style.width = "100%";
          if (pctDisplay) pctDisplay.textContent = "100%";
          if (badgeStatus) {
            badgeStatus.className = "sync-badge sync-badge--done";
            badgeStatus.innerHTML = `<span class="tag__dot"></span> ANALYSIS COMPLETE`;
          }
          if (phaseLabel) {
            phaseLabel.innerHTML = `<span class="tag__dot"></span> ALL 5 STAGES COMPLETE`;
          }
          if (footerStatus) {
            footerStatus.textContent = "Analysis complete. Incident dossiers updated.";
          }

          addLog("Pipeline synchronization complete. Updated incident dossiers deployed.", "SUCCESS");

          // Reload data and refresh feed
          await load();
          await updatePersistenceWidget();
          renderAll();

          // Smooth close after brief pause for verification
          setTimeout(() => {
            scrim.setAttribute("data-open", "0");
            triggerButtons.forEach((b) => {
              b.disabled = false;
              if (syncBtn) syncBtn.innerHTML = origSyncHtml;
              if (runBtn) runBtn.innerHTML = origRunHtml;
            });
          }, 2400);
        }
      } catch (err) {
        console.error("Pipeline stream error:", err);
      }
    };

    evtSource.onmessage = handleSseMessage;
    const BLUEPRINT_EVENTS = [
      "analysis.started", "firms.fetched", "gis.completed", "clustering.completed",
      "selection.completed", "imagery.started", "ai.started", "ai.completed",
      "severity.completed", "alert.created", "analysis.completed", "analysis.failed"
    ];
    BLUEPRINT_EVENTS.forEach((evtName) => {
      evtSource.addEventListener(evtName, handleSseMessage);
    });

    evtSource.onerror = (err) => {
      if (isCompleted) return;
      if (activeTimerInterval) {
        clearInterval(activeTimerInterval);
        activeTimerInterval = null;
      }
      evtSource.close();
      console.warn("SSE connection error or closed:", err);
      addLog("Stream connection closed or completed. Refreshing live telemetry layers...", "INFO");
      
      // Fallback reload and close
      (async () => {
        await load();
        await updatePersistenceWidget();
        renderAll();
        setTimeout(() => {
          scrim.setAttribute("data-open", "0");
          triggerButtons.forEach((b) => { b.disabled = false; });
          if (syncBtn) syncBtn.innerHTML = origSyncHtml;
          if (runBtn) runBtn.innerHTML = origRunHtml;
        }, 1000);
      })();
    };
  };

  triggerButtons.forEach((btn) => {
    btn.addEventListener("click", startPipelineSync);
  });
}

/* --- Boot ----------------------------------------------------------------- */

/* Leaflet is fetched from a CDN, so it is the one part of this console that a
   slow, filtered or offline network can take away. It used to be called into on
   the first line of boot with nothing between the call and the rest of the
   function: a missing global threw there, and the tabs, the search box, the
   arrow keys, the dossier, the data load and all five other views were never
   wired at all. The page went dark and said nothing. Nothing after this point
   needs a map, so now the map is the only thing lost, and the frame says why. */
function mapDown() {
  const reason = mapState.error || "The map is unavailable.";
  const frame = document.getElementById("mapframe");
  const box = document.getElementById("map");
  frame?.setAttribute("data-down", "1");
  /* role="application" asks a screen reader to stop interpreting keystrokes and
     hand them to the widget. With no widget there, that is a promise the element
     cannot keep, so the frame goes back to being a plain region holding a notice. */
  box?.removeAttribute("role");
  box?.removeAttribute("aria-label");
  ui.renderMapDown(box, reason);
  /* The overlay clusters that only act on a map are hidden by CSS off this
     attribute rather than disabled here, so a later render pass cannot bring
     them back looking live. The window, filter and ambient preferences stay
     reachable in the rail and in settings: they are stored either way, and they
     apply the next time the console loads with a map. */
}

/* Last resort, for a failure this console did not anticipate. A silent dark page
   is the one outcome an analyst cannot act on, so something has to be said in the
   page itself. Built with textContent and no help from the render module, because
   whatever just failed may be the reason. */
function fatal(err) {
  console.error("FIREX console failed to start", err);
  try {
    const box = document.createElement("div");
    box.className = "bootfail";
    box.setAttribute("role", "alert");
    const title = document.createElement("strong");
    title.textContent = "The console did not start.";
    const body = document.createElement("p");
    body.textContent = `${err?.message || String(err)}. Serve this folder through `
      + `server.py and reload. The browser console holds the full trace.`;
    box.append(title, body);
    document.body.prepend(box);
  } catch { /* nothing left to report with */ }
}

async function boot() {
  grab();
  loadPrefs();

  if (initMap()) setBase(state.base);
  else mapDown();

  /* A legend for the taxonomy, not for the window, so it is written once here
     and never touched by a render pass. */
  ui.renderMapKey(el["mapkey-glyphs"]);
  mapState.onSelect = (id) => pick(id, { fly: false });
  mapState.onViewChange = updateInView;

  initDossier({
    onTriage: () => renderAll(),
    onStep: (delta) => step(delta),
    onClose: () => { state.selected = null; clearSelection(); renderAll(); },
  });

  wireDelegates();
  wireControls();
  wireKeys();
  initSpotlightNav();
  wirePersistenceSync();
  updatePersistenceWidget();
  wireHistorySearch();

  /* Skeletons in the real panel geometry, so nothing shifts when data lands. */
  ["overview-body", "inv-grid", "industrial-body", "analytics-body", "history-body", "settings-body"]
    .forEach((id) => ui.skeleton(el[id], 3));
  setView(state.view);

  await load();
  renderAll();
  if (state.view === "map") requestAnimationFrame(resize);
  window.addEventListener("resize", debounce(() => { if (state.view === "map") resize(); }, 150));
}

boot().catch(fatal);
