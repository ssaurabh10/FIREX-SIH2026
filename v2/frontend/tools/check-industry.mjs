/* ==========================================================================
   check-industry - does the industry view hold the properties it claims?

   Run against a live backend (the console reads /api/console/feed and
   /api/industries, and this reads the same two endpoints):

       cd v2/frontend && node tools/check-industry.mjs

   Why it exists. Two defects shipped in this view that nothing else caught:

     * the 30- and 90-day baseline cards were the 365-day figures times fixed
       multipliers, printed under compliance-sounding badges; and the FRP trend
       chart added three invented overpasses ("10d ago", satellite "SNPP") to
       any facility with fewer than four real ones;
     * a duplicate `function renderMeasuredBaselinePanel` declaration sat in
       render.js, which `node --check` accepts (script-mode parsing allows
       function redeclaration) and the browser rejects. Only importing the file
       as an ES module finds that.

   So this checks both: it imports the real modules as ES modules, and it
   asserts the measurements are the measurements.

   It needs render.js to be importable as ESM, and the frontend has no
   package.json (it is served as static files, not bundled), so the modules are
   copied into a temporary directory with one before importing. The copies are
   deleted on the way out. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const API = process.env.FIREX_API || "http://127.0.0.1:8000";
const SRC = path.join(import.meta.dirname, "..", "js");

let failures = 0;
const fail = (m) => { failures += 1; console.log(`  FAIL ${m}`); };
const ok = (m) => console.log(`  ok   ${m}`);
const check = (cond, m) => (cond ? ok(m) : fail(m));

/* --- 0. Every module parses as an ES module -------------------------------
   `node --check render.js` parses as a *script*, and script-mode parsing
   accepts a duplicate `function` declaration that a module rejects -- which is
   how a second `renderMeasuredBaselinePanel` reached a working tree with a
   green syntax check. The same flag on a `.mjs` copy parses as a module and
   reports `Identifier 'x' has already been declared`, so each module is copied
   out under that extension and checked. Running the file's own check in a
   child process keeps this to the syntax pass alone: the modules are never
   evaluated, so a module that touches the DOM on import is still checkable.

   This runs before the import below on purpose. A duplicate declaration is
   raised while the module graph is being compiled, so importing first would
   die on an unhandled rejection with a stack trace instead of naming the file
   and the identifier. */
console.log("--- module parse ---");
const { execFileSync } = await import("node:child_process");
const parseTmp = fs.mkdtempSync(path.join(os.tmpdir(), "firex-parse-"));
let parseOk = true;
try {
  for (const f of ["config.js", "data.js", "map.js", "render.js", "dossier.js", "main.js"]) {
    const copy = path.join(parseTmp, f.replace(/\.js$/, ".mjs"));
    fs.writeFileSync(copy, fs.readFileSync(path.join(SRC, f), "utf8"));
    try {
      execFileSync(process.execPath, ["--check", copy], { stdio: "pipe" });
      ok(`${f} parses as an ES module`);
    } catch (err) {
      /* --check writes the offending line to stderr; take the message, not the
         whole dump, so a failure reads as one line like every other check. */
      const said = String(err.stderr || err.message).split("\n").find((l) => /Error/.test(l));
      fail(`${f}: ${(said || err.message).trim()}`);
      parseOk = false;
    }
  }
} finally {
  fs.rmSync(parseTmp, { recursive: true, force: true });
}
if (!parseOk) {
  console.log("\n1 FAILURE -- a module does not compile, so nothing below it can run");
  process.exit(1);
}

/* --- Import the real modules ---------------------------------------------
   The frontend has no package.json (it is served as static files, not
   bundled), so the modules are copied into a temporary directory with one
   before importing. The copies are deleted on the way out. */
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "firex-industry-"));
let render;
try {
  for (const f of ["config.js", "data.js", "render.js"]) {
    const code = fs.readFileSync(path.join(SRC, f), "utf8")
      .replace(/from "\.\/(config|data)\.js[^"]*"/g, 'from "./$1.js"');
    fs.writeFileSync(path.join(tmp, f), code);
  }
  fs.writeFileSync(path.join(tmp, "package.json"), '{"type":"module"}');
  globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  render = await import(`file://${path.join(tmp, "render.js").replace(/\\/g, "/")}`);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}

/* --- The live data, normalised the way data.js does ---------------------- */
let feed, registry;
try {
  feed = await (await fetch(`${API}/api/console/feed`)).json();
  registry = await (await fetch(`${API}/api/industries?limit=500`)).json();
} catch (err) {
  console.error(`Cannot reach ${API} -- start the backend first (python run.py serve).`);
  console.error(String(err && err.message || err));
  process.exit(2);
}

const INDUSTRIAL = new Set(["uncontrolled_industrial_fire", "industrial_fire", "gas_flare",
  "mining_or_other_thermal_source", "mining_related"]);
const ICONS = { gas_flare: "i-flare", industrial_fire: "i-factory", uncontrolled_industrial_fire: "i-factory",
  mining_or_other_thermal_source: "i-mining", mining_related: "i-mining", wildfire: "i-wildfire",
  agricultural_burning: "i-crop", uncertain: "i-question" };

const cases = feed.incidents.map((r) => {
  const hhmm = String(r.acq_time || "0000").replace(":", "").padStart(4, "0");
  const at = new Date(`${r.acq_date}T${hhmm.slice(0, 2)}:${hhmm.slice(2)}:00Z`);
  const name = String(r.ai_classification || "uncertain").toLowerCase();
  return {
    id: r.id, frp: Number(r.frp) || 0, lat: Number(r.latitude), lon: Number(r.longitude),
    state: r.state, place: r.location_name || "",
    at: Number.isNaN(at.getTime()) ? null : at,
    cls: { group: INDUSTRIAL.has(name) ? "industrial" : "other", label: name, short: name, icon: ICONS[name] || "i-question" },
    firms: { date: r.acq_date || "", time: r.acq_time || "", satellite: r.satellite },
    persistence: { dayNightStatus: r.day_night_status },
    risk: { score: Number(r.risk_score) || 0, tier: r.risk_tier, declaredTier: r.risk_tier },
    severity: { score: Number(r.severity_score) || 0, level: r.severity_level },
    climatology: { median: Number(r.baseline_median) || 0, p95: Number(r.baseline_p95) || 0,
      activeDays: Number(r.active_days_365d) || 0, isRoutine: Boolean(r.is_routine_flare) },
    facility: { id: r.nearest_asset_id || null, name: r.nearest_facility_name || null,
      operator: r.operator || null, type: r.facility_type || null },
  };
});

function draw(opts = {}) {
  const el = { innerHTML: "" };
  render.renderIndustrial(el, cases, opts.selected ?? null, opts.query ?? "", opts.sector ?? "all",
    opts.sort ?? "frp", opts.window ?? "365d", opts.profile ?? null,
    opts.registry ?? registry, opts.group ?? "facility");
  return el.innerHTML;
}

const M = (days, median, p95, obs, active) => ({ window_days: days, median_frp: median, p95_frp: p95,
  observation_count: obs, active_days: active, max_frp: p95 * 1.05, abnormal_event_count: 0,
  history_reliability_label: "HIGH" });
const profile = (id) => ({ id, loading: false, error: null,
  windows: { 30: M(30, 2, 3, 20, 10), 90: M(90, 3, 4.5, 60, 30), 365: M(365, 4, 6, 200, 90) } });

/* --- 1. The register ------------------------------------------------ */
console.log(`\nfeed: ${cases.length} incidents, register: ${registry.length} facilities\n`);
console.log("--- structure ---");

const summary = draw();
const reporting = (summary.match(/data-facility=/g) || []).length;
check(reporting > 0, `${reporting} rows drawn with no selection`);
check(/Registered Facilities/.test(summary), "the register totals are the registry, not the detections");

for (const [label, opts] of [
  ["operator roll-up", { group: "operator" }],
  ["state roll-up", { group: "state" }],
  ["sector = cement", { sector: "cement" }],
  ["sector = steel", { sector: "steel" }],
  ["query matching", { query: "odisha" }],
  ["query matching nothing", { query: "zzzznomatch" }],
  ["sort by exceedance", { sort: "anomaly" }],
  ["registry unavailable", { registry: [] }],
]) {
  let html;
  try { html = draw(opts); } catch (err) { fail(`${label}: threw ${err.message}`); continue; }
  const open = (html.match(/<div/g) || []).length;
  const close = (html.match(/<\/div>/g) || []).length;
  if (open !== close) fail(`${label}: ${open} <div> vs ${close} </div>`);
  if (/undefined|NaN|\[object Object\]/.test(html)) fail(`${label}: leaked undefined/NaN/[object Object]`);
  ok(`${label} — ${html.length} chars, ${open} divs balanced`);
}

/* --- 2. Every registered facility renders ---------------------------- */
let rendered = 0;
const broken = [];
for (const a of registry) {
  try { draw({ selected: a.id, profile: profile(a.id) }); rendered += 1; }
  catch (err) { broken.push(`${a.name}: ${err.message}`); }
}
check(rendered === registry.length, `all ${registry.length} registry rows render (${broken.join("; ") || "none failed"})`);

/* --- 3. The measurements are measurements --------------------------- */
console.log("\n--- baselines ---");
const fid = cases.find((c) => c.facility?.id)?.facility.id;
if (!fid) {
  console.log("  (no facility in this window has a registry match; skipping the per-facility checks)");
} else {
  const p = profile(fid);
  const d365 = draw({ selected: fid, profile: p, window: "365d" });
  const d30 = draw({ selected: fid, profile: p, window: "30d" });

  check(["30-Day Window", "90-Day Window", "365-Day Window"].every((w) => d365.includes(w)),
    "all three measured windows are drawn");
  check(d365.includes("MEASURED P95 (6.0 MW)"), "365d chart envelope is the 365d measurement");
  check(d30.includes("MEASURED P95 (3.0 MW)"), "30d chart envelope is the 30d measurement");
  check(!d30.includes("MEASURED P95 (6.0 MW)"), "the 30d chart does not fall back to the 365d figure");

  /* The multipliers that used to stand in for the 30d/90d windows. */
  const fabricated = [6 * 0.88, 4 * 0.95, 6 * 0.96, 4 * 1.0].map((v) => v.toFixed(1));
  check(!fabricated.some((v) => d30.includes(`MEASURED P95 (${v} MW)`)),
    `no scaled figure (${fabricated.join(", ")}) is published as a measurement`);

  const loading = draw({ selected: fid, profile: { id: fid, loading: true, error: null, windows: {} } });
  check(/Measuring this window/.test(loading), "a window in flight says it is being measured, not that it is absent");

  const partial = draw({ selected: fid, profile: { id: fid, loading: false, error: "30d responded 500", windows: { 365: M(365, 4, 6, 200, 90) } } });
  check(/30d responded 500/.test(partial) && /MEASURED P95 \(6.0 MW\)/.test(partial),
    "a partial failure names the missing window and keeps the measured one");
}

/* --- 4. INV-5, and the categories that are not facilities ------------ */
console.log("\n--- INV-5 and honest categories ---");

/* `renderFrpPointGraph` is module-private, so the chart is exercised the way
   the browser reaches it: through `renderIndustrial`, with synthetic
   detections attached to a real registry row. `target` is that row. */
const target = registry.find((a) => a.name.includes("Vijayanagar")) || registry[0];
const synth = (n, p95) => Array.from({ length: n }, (_, i) => ({
  ...cases[0],
  id: `pass-${i}`,
  frp: 2 + i,
  facility: { id: target.id, name: target.name, operator: target.operator, type: target.facility_type },
  firms: { date: `2026-08-${String(1 + (i % 28)).padStart(2, "0")}`, time: i % 2 ? "0130" : "0730", satellite: "NOAA-21" },
  climatology: { median: p95 ? 5 : 0, p95, activeDays: 20, isRoutine: false },
}));

const noCell = synth(3, 0);
const el5 = { innerHTML: "" };
render.renderIndustrial(el5, noCell, target.id, "", "all", "frp", "365d", null, registry, "facility");
const trend5 = el5.innerHTML.split("Thermal Power Trend")[1] || "";
check(trend5.length > 0, "a facility with detections draws the trend chart");
check(!/MEASURED P95/.test(trend5) && !/MEASURED P50/.test(trend5),
  "no measurable envelope: no envelope line is drawn (INV-5)");
check(/no measurable P95, so no envelope is drawn/.test(trend5),
  "no measurable envelope: the chart says INV-5 rather than implying compliance");

const quiet = registry.find((a) => !cases.some((c) => c.facility?.id === a.id));
if (quiet) {
  const q = draw({ selected: quiet.id, profile: { id: quiet.id, loading: false, error: null, windows: {} } });
  check(/No detection in this window/.test(q), "a quiet facility says it had no detection");
  check(!/Every registered facility reported/.test(q), "a quiet facility does not claim the network is clean");
  check(!/Thermal Power Trend/.test(q), "a quiet facility draws no trend chart");
}

const basinKey = summary.match(/data-facility="(basin:[^"]+)"/)?.[1]?.replace(/&amp;/g, "&");
if (basinKey) {
  const b = draw({ selected: basinKey });
  check(/Not a registered facility/.test(b), "a mining basin says it is not a registered facility");
  check(!/Registry Record/.test(b) && !/Measured Baselines/.test(b),
    "a mining basin claims no registry record and no facility baseline");
} else {
  console.log("  (no basin row in this window)");
}

const noReg = draw({ registry: [] });
check(/Industrial register unavailable/.test(noReg) && !/Registered Facilities<\/p>/.test(noReg),
  "a registry outage shows no register totals rather than zeros");
check(/No register to compare against/.test(noReg), "a registry outage does not claim every facility reported");

const cement = draw({ sector: "cement" });
check(/register holds no facility of this sector/.test(cement) && !/Try clearing or changing/.test(cement),
  "a sector with no registry rows says so instead of blaming the filters");

/* --- 5. No fabricated overpasses in the trend chart ------------------ */
console.log("\n--- the trend chart ---");
const many = synth(20, 12);
const el6 = { innerHTML: "" };
render.renderIndustrial(el6, many, target.id, "", "all", "frp", "365d", null, registry, "facility");
const manyHtml = el6.innerHTML;
const trend = manyHtml.split("Thermal Power Trend")[1] || "";
check((trend.match(/pointgraph-node/g) || []).length === 12, "20 overpasses plot the last 12");
check(/8 earlier not shown/.test(trend), "the chart says how many earlier overpasses it left off");
check(!/hist-\d|10d ago|6d ago|3d ago|SNPP/.test(manyHtml), "no overpass is invented");
check(/MEASURED P95 \(12.0 MW\)/.test(trend), "the multi-pass chart draws the cell envelope it was given");

const one = synth(1, 12);
const el7 = { innerHTML: "" };
render.renderIndustrial(el7, one, target.id, "", "all", "frp", "365d", null, registry, "facility");
/* The single-overpass render is the one the old chart padded, so the scan for
   invented content is repeated here as well as on the 20-pass render. */
check(/One overpass in this window/.test(el7.innerHTML), "a single overpass is reported as a single overpass, not padded into a trend");
check(!/hist-\d|10d ago|6d ago|3d ago|SNPP/.test(el7.innerHTML), "a single overpass invents no companion points");
check((el7.innerHTML.split("Thermal Power Trend")[1] || "").match(/pointgraph-node/g)?.length === 1,
  "a single overpass plots exactly one point");

console.log(failures ? `\n${failures} FAILURE(S)` : "\nthe industry view holds its stated properties");
process.exitCode = failures ? 1 : 0;
