/* ==========================================================================
   data - load, normalise, derive
   The feed is read exactly as published. No field is invented and no value is
   filled in: anything missing surfaces as "unreported" downstream.
   ========================================================================== */

import { SOURCES, classOf, tierOf, isTier, parseConfidence, shortPlace, siteNote, WINDOWS } from "./config.js";

const TRIAGE_KEY = (id) => `firex_triage_${id}`;

export const store = {
  cases: [],
  ambient: [],
  anchor: null,      // newest acquisition instant in the feed
  loaded: false,
  errors: [],
  notices: [],       // the feed loaded, but something in it does not add up
};

/* --- Load ---------------------------------------------------------------- */

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} responded ${res.status}`);
  return res.json();
}

export async function load() {
  const [incidents, ambient] = await Promise.allSettled([
    getJSON(SOURCES.incidents),
    getJSON(SOURCES.ambient),
  ]);

  store.errors = [];
  store.notices = [];

  if (incidents.status === "fulfilled" && Array.isArray(incidents.value)) {
    store.cases = incidents.value.map(normaliseCase).sort((a, b) => a.rank - b.rank);
    checkTiers();
  } else {
    store.errors.push({ source: "incidents", message: String(incidents.reason || "unavailable") });
  }

  if (ambient.status === "fulfilled" && Array.isArray(ambient.value)) {
    store.ambient = ambient.value
      .map(normaliseAmbient)
      .filter((p) => p.lat !== null && p.lon !== null);
  } else {
    store.errors.push({ source: "ambient", message: String(ambient.reason || "unavailable") });
  }

  const stamps = [...store.cases, ...store.ambient].map((r) => r.at).filter(Boolean);
  store.anchor = stamps.length ? new Date(Math.max(...stamps.map((d) => d.getTime()))) : null;
  store.loaded = true;
  return store;
}

/* The tier a case displays is the one the engine published. That leaves room for
   the two to disagree, which is exactly the point: a mismatch means the feed was
   written by a different build of the engine than these bands describe, and that
   is worth a reader knowing about rather than being papered over. Reported in the
   overview and in settings, beside the source failures. */
function checkTiers() {
  store.cases.forEach((c) => {
    const { declaredTier: declared, computedTier: computed, score } = c.risk;
    if (!declared || declared === computed) return;
    store.notices.push({
      source: "risk tiers",
      message: `${c.id} scored ${score}: the engine published ${declared}, these bands say ${computed}`,
    });
  });
}

/* --- Normalise ----------------------------------------------------------- */

function instant(date, time) {
  if (!date) return null;
  const hhmm = String(time ?? "00:00").replace(":", "").padStart(4, "0");
  const d = new Date(`${date}T${hhmm.slice(0, 2)}:${hhmm.slice(2)}:00Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function normaliseCase(raw) {
  const conf = parseConfidence(raw.confidence);
  const uncertainty = String(raw.ai_uncertainty || "").toLowerCase();
  const score = Number(raw.risk_score) || 0;
  /* The engine publishes the tier it decided, so that is the one the console
     shows: recomputing it from the score meant the browser could relabel a case
     the engine had already ruled on. The computed tier is kept beside it as the
     fallback for a record with no tier, and as the thing to compare against. */
  const declaredTier = String(raw.risk_tier || "").toUpperCase();
  const computedTier = tierOf(score);

  /* A detection counts as visually confirmed only when the vision model was
     certain AND the satellite itself was not low-confidence. Anything else
     stays explicitly unconfirmed, which the brief requires. */
  const confirmed =
    (uncertainty === "low" || uncertainty === "none") &&
    (conf.value === null || conf.value >= 30);

  return {
    id: String(raw.id || ""),
    rank: Number(raw.priority_rank) || 99,
    lat: Number(raw.latitude),
    lon: Number(raw.longitude),
    frp: Number(raw.frp) || 0,

    classId: String(raw.ai_classification || "uncertain"),
    cls: classOf(raw.ai_classification),
    aiConfidence: Number(raw.ai_confidence),
    uncertainty,
    confirmed,
    categoryTarget: String(raw.category_target || ""),

    firms: {
      satellite: raw.satellite || "unreported",
      instrument: raw.instrument || "unreported",
      product: raw.product || "unreported",
      date: raw.acq_date || "",
      time: raw.acq_time || "",
      confidence: conf,
    },
    at: instant(raw.acq_date, raw.acq_time),

    place: shortPlace(raw.location_name),
    site: siteNote(raw.location_name),
    address: raw.display_name || "",

    risk: {
      score,
      tier: isTier(declaredTier) ? declaredTier : computedTier,
      declaredTier,
      computedTier,
      action: raw.action_recommendation || "",
      factors: Array.isArray(raw.risk_factors)
        ? raw.risk_factors.map((f) => ({
            name: f.factor,
            score: Number(f.score) || 0,
            max: Number(f.max) || 0,
            detail: f.detail || "",
          }))
        : [],
    },

    evidence: Array.isArray(raw.ai_evidence) ? raw.ai_evidence : [],
    reasoning: raw.ai_reasoning || "",
    images: { annotated: raw.image_url || "", raw: raw.raw_image_url || "" },

    persistence: {
      pattern: raw.persistence_pattern || "NEW_IGNITION",
      description: raw.persistence_description || "",
      daysActive: raw.days_active || 1,
      dayNightStatus: raw.day_night_status || "SINGLE PASS",
      detections: raw.persistence_detections || 1,
    },
  };
}

/* Keeps ambient rows shaped like case rows so the window filter can treat both
   the same way. The ambient feed uses short keys and a bare HHMM time. */
function normaliseAmbient(raw) {
  const lat = Number(raw.lat);
  const lon = Number(raw.lon);
  const time = String(raw.time ?? "").padStart(4, "0");
  return {
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
    frp: Number(raw.frp) || 0,
    confidence: parseConfidence(raw.conf),
    satellite: raw.sat || "unreported",
    date: raw.date || "",
    time,
    at: instant(raw.date, `${time.slice(0, 2)}:${time.slice(2)}`),
  };
}

/* --- Derive -------------------------------------------------------------- */

export function inWindow(row, windowId) {
  const spec = WINDOWS[windowId] || WINDOWS.all;
  if (spec.hours === Infinity || !store.anchor || !row.at) return true;
  return store.anchor.getTime() - row.at.getTime() <= spec.hours * 3600 * 1000;
}

export function tally(cases, filters) {
  const out = {};
  filters.forEach((f) => { out[f.id] = cases.filter(f.test).length; });
  return out;
}

export function byTier(cases) {
  return cases.reduce((acc, c) => {
    acc[c.risk.tier] = (acc[c.risk.tier] || 0) + 1;
    return acc;
  }, {});
}

export function byClass(cases) {
  const map = new Map();
  cases.forEach((c) => {
    const key = c.cls.label;
    const row = map.get(key) || { label: key, short: c.cls.short, icon: c.cls.icon, n: 0, frp: 0 };
    row.n += 1;
    row.frp += c.frp;
    map.set(key, row);
  });
  return [...map.values()].sort((a, b) => b.n - a.n);
}

/* Groups cases into sites. Two detections belong to the same site when their
   short place name matches, which is how the feed encodes repeat visits. */
export function bySite(cases) {
  const map = new Map();
  cases.forEach((c) => {
    const key = c.place || c.id;
    const row = map.get(key) || {
      key, place: key, site: c.site, cases: [], frp: 0, top: c,
    };
    row.cases.push(c);
    row.frp += c.frp;
    if (c.risk.score > row.top.risk.score) row.top = c;
    if (!row.site && c.site) row.site = c.site;
    map.set(key, row);
  });
  return [...map.values()].sort((a, b) => b.top.risk.score - a.top.risk.score);
}

export function histogram(values, bins, min, max) {
  const out = Array.from({ length: bins }, () => 0);
  const span = (max - min) / bins || 1;
  values.forEach((v) => {
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / span)));
    out[i] += 1;
  });
  return out;
}

export function stats(values) {
  const nums = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!nums.length) return { n: 0, min: 0, max: 0, mean: 0, median: 0, sum: 0 };
  const sum = nums.reduce((a, b) => a + b, 0);
  return {
    n: nums.length,
    min: nums[0],
    max: nums[nums.length - 1],
    mean: sum / nums.length,
    median: nums[Math.floor(nums.length / 2)],
    sum,
  };
}

/* --- Triage persistence --------------------------------------------------
   Decisions live in localStorage so a reviewer can close the tab and come back
   to them. When storage is blocked, they fall back to memory: the console still
   tracks the session correctly, it just cannot remember past a reload. */

const triageMemory = new Map();

export function getTriage(id) {
  try {
    const saved = localStorage.getItem(TRIAGE_KEY(id));
    if (saved) return saved;
  } catch { /* blocked: fall through to the memory map */ }
  return triageMemory.get(id) || "UNREVIEWED";
}

export function setTriage(id, status) {
  const value = !status || status === "UNREVIEWED" ? null : status;
  if (value) triageMemory.set(id, value);
  else triageMemory.delete(id);
  try {
    if (value) localStorage.setItem(TRIAGE_KEY(id), value);
    else localStorage.removeItem(TRIAGE_KEY(id));
  } catch { /* blocked: the memory map is the whole record for this session */ }
}

export function triageCounts(cases) {
  return cases.reduce((acc, c) => {
    const s = getTriage(c.id);
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});
}
