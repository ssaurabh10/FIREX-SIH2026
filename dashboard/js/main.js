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
} from "./map.js";
import * as ui from "./render.js";
import { initDossier, showDrawer, showModal, isModalOpen, refresh } from "./dossier.js";

const PREFS_KEY = "firex_prefs";

const state = {
  view: "map",
  window: "48h",
  filter: "all",
  query: "",
  ambient: true,
  base: "dark",
  theme: "dark",
  selected: null,
};

const el = {};

function grab() {
  [
    "brand-window", "map-sub", "rail-counts", "risk-hist", "risk-span", "spine", "spine-count",
    "filterbar", "map-strip", "in-view", "alert-flag", "q", "q-clear", "mapkey-glyphs",
    "overview-body", "overview-window", "inv-grid", "inv-filters",
    "industrial-body", "analytics-body", "settings-body",
  ].forEach((id) => { el[id] = document.getElementById(id); });
}

/* --- Derived lists -------------------------------------------------------- */

const windowed = () => store.cases.filter((c) => inWindow(c, state.window));

function visible() {
  const f = FILTERS.find((x) => x.id === state.filter) || FILTERS[0];
  const q = state.query.trim().toLowerCase();
  return windowed().filter(f.test).filter((c) => !q ||
    `${c.id} ${c.place} ${c.site} ${c.address} ${c.cls.label}`.toLowerCase().includes(q));
}

const ambientInWindow = () => store.ambient.filter((p) => inWindow(p, state.window));

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
  view: (v) => Object.prototype.hasOwnProperty.call(VIEWS, v),
  window: (v) => Object.prototype.hasOwnProperty.call(WINDOWS, v),
  filter: (v) => FILTERS.some((f) => f.id === v),
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
  } catch { /* first run, or storage blocked */ }
  document.documentElement.setAttribute("data-theme", state.theme);
}

function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      view: state.view, window: state.window, filter: state.filter,
      base: state.base, ambient: state.ambient, theme: state.theme,
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
};

const VIEWS = {
  map: () => {},
  overview: () => {
    if (el["overview-window"]) el["overview-window"].innerHTML = windowSeg();
    ui.renderOverview(el["overview-body"],
      { cases: visible(), ambient: ambientInWindow(), selected: state.selected });
  },
  investigations: () => ui.renderInvestigations(el["inv-grid"], visible(), state.selected),
  industrial: () => ui.renderIndustrial(el["industrial-body"], visible()),
  analytics: () => ui.renderAnalytics(el["analytics-body"], visible(), ambientInWindow()),
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
  const key = `${state.window}|${state.ambient}|${points.length}`;
  if (key === ambientKey) return;
  ambientKey = key;
  drawAmbient(points, state.ambient);
}

function renderAll() {
  const win = windowed();
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

  /* Skeletons in the real panel geometry, so nothing shifts when data lands. */
  ["overview-body", "inv-grid", "industrial-body", "analytics-body", "settings-body"]
    .forEach((id) => ui.skeleton(el[id], 3));
  setView(state.view);

  await load();
  renderAll();
  if (state.view === "map") requestAnimationFrame(resize);
  window.addEventListener("resize", debounce(() => { if (state.view === "map") resize(); }, 150));
}

boot().catch(fatal);
