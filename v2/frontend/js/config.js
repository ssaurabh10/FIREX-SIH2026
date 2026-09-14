/* ==========================================================================
   config - taxonomy, scales, formatters
   The vocabulary of the domain lives here so no view invents its own labels.
   ========================================================================== */

export const SOURCES = {
  incidents: "data/incidents.json",
  ambient: "data/ambient_firms.json",
};

export const MAP_HOME = { center: [22.4, 79.5], zoom: 5 };

/* Risk tiers exactly as the scoring engine defines them. The engine is the
   authority and it lives in section10_risk_engine/risk_scorer.py, which cuts at
   >= 81 critical, >= 61 high, >= 36 medium, and low below that. These bands had
   medium starting at 31, so a case scoring 31 to 35 was low to the engine and
   medium in the browser: the same record wore two tiers depending on which
   surface you read it from. Anything published in the feed is trusted over these
   numbers now (see normaliseCase), and a disagreement is reported rather than
   quietly resolved, but the bands still have to be right for the cases the feed
   leaves untiered. */
export const TIERS = [
  { id: "CRITICAL", min: 81, max: 100, label: "Critical" },
  { id: "HIGH", min: 61, max: 80, label: "High" },
  { id: "MEDIUM", min: 36, max: 60, label: "Medium" },
  { id: "LOW", min: 0, max: 35, label: "Low" },
];

export function tierOf(score) {
  const n = Number(score) || 0;
  return (TIERS.find((t) => n >= t.min && n <= t.max) || TIERS[3]).id;
}

export function isTier(id) {
  return TIERS.some((t) => t.id === id);
}

/* Classification taxonomy. `icon` is the glyph that carries the class on the
   map, so severity colour stays free to carry risk instead. */
export const CLASSES = {
  uncontrolled_industrial_fire: { label: "Uncontrolled industrial fire", short: "Uncontrolled", icon: "i-warning", group: "critical" },
  industrial_fire: { label: "Industrial fire / Smelter", short: "Industrial", icon: "i-factory", group: "industrial" },
  gas_flare: { label: "Gas flare", short: "Flare", icon: "i-flare", group: "industrial" },
  mining_or_other_thermal_source: { label: "Mining / Coal seam fire", short: "Mining", icon: "i-mining", group: "industrial" },
  wildfire: { label: "Wildfire", short: "Wildfire", icon: "i-wildfire", group: "natural" },
  agricultural_burning: { label: "Agricultural burning", short: "Agricultural", icon: "i-crop", group: "natural" },
  uncertain: { label: "Not visually confirmable", short: "Uncertain", icon: "i-question", group: "unknown" },
};

export const UNKNOWN_CLASS = CLASSES.uncertain;

export function classOf(id) {
  return CLASSES[id] || UNKNOWN_CLASS;
}

/* Filters, in the order the master brief specifies them. */
export const FILTERS = [
  { id: "all", label: "All", test: () => true },
  { id: "critical", label: "Critical", test: (c) => c.risk.tier === "CRITICAL" || c.risk.tier === "HIGH" },
  { id: "industrial", label: "Industrial", test: (c) => c.classId === "industrial_fire" || c.classId === "uncontrolled_industrial_fire" },
  { id: "flare", label: "Flare", test: (c) => c.classId === "gas_flare" },
  { id: "mining", label: "Mining", test: (c) => c.classId === "mining_or_other_thermal_source" },
  { id: "wildfire", label: "Wildfire", test: (c) => c.classId === "wildfire" },
  { id: "agri", label: "Agricultural", test: (c) => c.classId === "agricultural_burning" },
  { id: "uncertain", label: "Unconfirmed", test: (c) => !c.confirmed },
];

export const WINDOWS = {
  "24h": { hours: 24, label: "24H" },
  "48h": { hours: 48, label: "48H" },
  all: { hours: Infinity, label: "All" },
};

/* Base layers, named once. The settings control is written from this and a
   stored preference is checked against it, so a hand-edited or stale value in
   localStorage cannot ask the map for a layer that does not exist. */
export const BASES = {
  dark: { label: "Canvas" },
  satellite: { label: "Imagery" },
};

/* --- Triage vocabulary ---------------------------------------------------
   One list, used by the buttons, the badge and the persisted value. The
   previous console defined these twice and the two lists disagreed, so every
   reviewed case still displayed as unreviewed. */

export const TRIAGE = {
  UNREVIEWED: { label: "Unreviewed", short: "Unreviewed", tone: "quiet" },
  CONFIRMED_INDUSTRIAL: { label: "Confirmed industrial fire", short: "Confirmed", tone: "critical" },
  ROUTINE_FLARE: { label: "Routine flare, no action", short: "Routine", tone: "low" },
  ESCALATED: { label: "Escalated for field check", short: "Escalated", tone: "critical" },
  DISMISSED: { label: "Dismissed, not industrial", short: "Dismissed", tone: "quiet" },
};

export const TRIAGE_ACTIONS = ["CONFIRMED_INDUSTRIAL", "ROUTINE_FLARE", "ESCALATED", "DISMISSED"];

export function triageOf(id) {
  return TRIAGE[id] || TRIAGE.UNREVIEWED;
}

/* --- FIRMS confidence ----------------------------------------------------
   MODIS reports 0-100, VIIRS reports a band. Both are normalised to a number
   for sorting, but the original wording is kept for display so the console
   never invents precision the satellite did not report. */

const BANDS = { low: 20, nominal: 55, high: 85, n: 55, l: 20, h: 85 };

export function parseConfidence(raw) {
  const text = String(raw ?? "").trim();
  const pct = text.match(/^(\d+(?:\.\d+)?)\s*%?$/);
  if (pct) return { value: Number(pct[1]), display: text.endsWith("%") ? text : `${pct[1]}%`, kind: "percent" };
  const band = BANDS[text.toLowerCase()];
  if (band !== undefined) return { value: band, display: text.toLowerCase(), kind: "band" };
  return { value: null, display: text || "unreported", kind: "unknown" };
}

/* --- Formatters ----------------------------------------------------------- */

export const fmt = {
  int: (n) => (Number.isFinite(+n) ? Math.round(+n).toLocaleString("en-IN") : "-"),
  dec: (n, d = 1) => (Number.isFinite(+n) ? (+n).toFixed(d) : "-"),
  pct: (n) => (Number.isFinite(+n) ? `${Math.round(+n * 100)}%` : "-"),
  coord: (lat, lon) => `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`,
  /* "2026-09-03" + "09:39" -> "03 Sep, 09:39 UTC" */
  stamp: (date, time) => {
    if (!date) return "-";
    const d = new Date(`${date}T00:00:00Z`);
    const day = String(d.getUTCDate()).padStart(2, "0");
    const mon = d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
    return time ? `${day} ${mon}, ${time} UTC` : `${day} ${mon}`;
  },
  /* FIRMS ambient rows store acq_time as HHMM without a leading zero. */
  hhmm: (raw) => {
    const s = String(raw ?? "").padStart(4, "0");
    return `${s.slice(0, 2)}:${s.slice(2)}`;
  },
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

/* Location names in the feed are long and parenthetical. The short form is the
   part before the first bracket, which is always the place. */
export function shortPlace(name) {
  return String(name || "").split("(")[0].replace(/\s+$/, "").trim();
}

export function siteNote(name) {
  const m = String(name || "").match(/\(([^)]+)\)/);
  return m ? m[1].trim() : "";
}

export const icon = (id, cls = "i") =>
  `<svg class="${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;
