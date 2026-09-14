/* ==========================================================================
   dossier - detail drawer and full investigation modal
   The drawer answers "what is this"; the modal answers "can I act on it".
   Both read the same case record, so they can never disagree.
   ========================================================================== */

import { TRIAGE_ACTIONS, triageOf, fmt, icon, escapeHtml } from "./config.js";
import { getTriage, setTriage } from "./data.js";
import { wireThumbs } from "./render.js";

export const dossier = {
  drawer: null,
  scrim: null,
  modal: null,
  current: null,
  mode: "annotated",     // which crop the modal is showing
  rendered: "",          // what the two surfaces are currently showing
  returnFocus: null,
  returnAnchor: null,    // selector for the opener, in case its node is replaced
  onTriage: () => {},
  onStep: () => {},      // -1 previous case, +1 next case
  onClose: () => {},
};

/* --- Shared fragments ----------------------------------------------------- */

function tierTag(c) {
  return `<span class="tag tag--tier">${c.risk.tier} ${c.risk.score}</span>`;
}

function confTag(c) {
  return c.confirmed
    ? `<span class="tag"><span class="tag__dot"></span>Visually confirmed</span>`
    : `<span class="tag tag--unconfirmed">Not confirmed</span>`;
}

function kv(pairs) {
  return `<dl class="kv kv--wide well tile">${pairs
    .map(([k, v]) => `<dt class="kv__k">${escapeHtml(k)}</dt><dd class="kv__v">${v}</dd>`)
    .join("")}</dl>`;
}

function sect(title, aside, body) {
  return `
    <section class="sect">
      <div class="sect__head">
        <h3 class="u-label">${escapeHtml(title)}</h3>
        ${aside || ""}
      </div>
      ${body}
    </section>`;
}

function shot(src, label, cls = "shot") {
  return `
    <figure class="bezel ${cls}"${src ? "" : ' data-missing="1"'}>
      <div class="bezel__core">
        ${src ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(label)}" loading="lazy" decoding="async">` : ""}
        <span class="shot__tag tag">${escapeHtml(src ? label : "No crop")}</span>
      </div>
    </figure>`;
}

/* Numbered so an observation can be cited by index in a written report. */
function evidence(list, limit) {
  const items = limit ? list.slice(0, limit) : list;
  if (!items.length) {
    return `<p class="prose well">The vision model returned no itemised observations for this detection.</p>`;
  }
  return `<ol class="ev well">${items.map((line, i) => `
    <li class="ev__item">
      <span class="ev__n">${String(i + 1).padStart(2, "0")}</span>
      <span>${escapeHtml(line)}</span>
    </li>`).join("")}${
    limit && list.length > limit
      ? `<li class="ev__item"><span class="ev__n"></span><span class="u-micro">${list.length - limit} more in the full dossier</span></li>`
      : ""}</ol>`;
}

function factors(c) {
  if (!c.risk.factors.length) {
    return `<p class="prose well">The record carries a score of ${c.risk.score} but no factor breakdown.</p>`;
  }
  return `<div class="stack-5">${c.risk.factors.map((f) => {
    const pct = f.max ? Math.round((f.score / f.max) * 100) : 0;
    return `
      <div class="bullet">
        <div class="bullet__top">
          <span class="bullet__name">${escapeHtml(f.name)}</span>
          <span class="bullet__score">${f.score}<span class="bullet__max"> of ${f.max}</span></span>
        </div>
        <div class="meter"><span class="meter__fill" style="--v:${pct}%"></span></div>
        ${f.detail ? `<p class="bullet__detail">${escapeHtml(f.detail)}</p>` : ""}
      </div>`;
  }).join("")}</div>`;
}

/* The vision model reports its own confidence separately from the satellite's.
   Keeping the two apart is the point: a certain model reading a low confidence
   pixel is not the same as agreement. */
function classification(c) {
  const raw = Number(c.aiConfidence);
  const pct = Number.isFinite(raw) ? Math.round(raw <= 1 ? raw * 100 : raw) : null;
  return `
    <div class="well tile stack">
      <div class="row">
        ${icon(c.cls.icon, "i i--lg")}
        <span>${escapeHtml(c.cls.label)}</span>
        <span class="spacer"></span>
        <span class="u-num u-micro">${pct === null ? "unreported" : `${pct}%`}</span>
      </div>
      <div class="meter meter--signal"><span class="meter__fill" style="--v:${pct ?? 0}%"></span></div>
      <p class="u-micro">Model certainty ${pct === null ? "was not reported" : `${pct}%`}, stated uncertainty ${escapeHtml(c.uncertainty || "unreported")}. Satellite confidence ${escapeHtml(c.firms.confidence.display)}.</p>
    </div>`;
}

function detection(c) {
  return kv([
    ["Radiative power", `${fmt.dec(c.frp)} MW`],
    ["Satellite", escapeHtml(c.firms.satellite)],
    ["Instrument", escapeHtml(c.firms.instrument)],
    ["Product", escapeHtml(c.firms.product)],
    ["Acquired", escapeHtml(fmt.stamp(c.firms.date, c.firms.time))],
    ["Sensor confidence", escapeHtml(c.firms.confidence.display)],
    ["Coordinates", escapeHtml(fmt.coord(c.lat, c.lon))],
  ]);
}

function persistence(c) {
  if (!c.persistence) return "";
  const p = c.persistence;
  const isIndustrial = p.pattern === "RECURRING_INDUSTRIAL_FLARE";
  const isNew = p.pattern === "NEW_IGNITION";
  const badgeClass = isIndustrial ? "tag--signal" : isNew ? "tag--unconfirmed" : "tag--muted";

  return kv([
    ["Multi-Pass Pattern", `<span class="tag ${badgeClass}">${escapeHtml(p.pattern.replace(/_/g, " "))}</span>`],
    ["Overpass Profile", escapeHtml(p.dayNightStatus)],
    ["Active Tracking", `${p.daysActive} day${p.daysActive > 1 ? "s" : ""} (${p.detections} satellite hits)`],
    ["Persistence Intel", `<span class="u-micro">${escapeHtml(p.description)}</span>`],
  ]);
}

function statusTag(c) {
  const status = getTriage(c.id);
  return status === "UNREVIEWED"
    ? `<span class="tag tag--unconfirmed">Unreviewed</span>`
    : `<span class="tag tag--signal">${escapeHtml(triageOf(status).label)}</span>`;
}

/* Ways out to the two places an analyst actually checks a coordinate against.
   Shared by the drawer and the modal: the section 6 console offers this from
   the drawer too, and it is the one action that needs no data we do not have. */
function links(c) {
  const q = `${c.lat},${c.lon}`;
  const pairs = [
    ["Google Maps", `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`],
    ["OpenStreetMap", `https://www.openstreetmap.org/?mlat=${c.lat}&mlon=${c.lon}#map=15/${c.lat}/${c.lon}`],
  ];
  return `<div class="row row--wrap">${pairs.map(([label, href]) => `
    <a class="btn btn--sm" href="${escapeHtml(href)}" target="_blank" rel="noreferrer noopener">
      ${icon("i-external", "i i--sm")}${label}
    </a>`).join("")}</div>`;
}

/* --- Drawer ---------------------------------------------------------------
   Docked as the third column of the live map view. Two states, one shell. */

/* Shown when nothing is selected. The dock is always on screen, so leaving it
   blank would read as a broken panel; it says what to do instead, and states
   the two things a reader needs before they click anything. */
function drawerEmptyHtml() {
  return `
    <div class="state drawer__empty">
      <span class="state__icon">${icon("i-crosshair", "i i--xl")}</span>
      <p class="state__title">No detection selected</p>
      <p class="state__body">Pick a row in the priority spine, or a marker on the map. The dossier opens here, beside the map, so the location stays in view.</p>
      <dl class="drawer__hint">
        <dt>Arrow keys</dt>
        <dd>Step through the filtered list in rank order.</dd>
        <dt>Ranking</dt>
        <dd>Deterministic, from five weighted factors. No model is asked to sort the list.</dd>
      </dl>
    </div>`;
}

function drawerHtml(c) {
  const where = c.site || c.address || fmt.coord(c.lat, c.lon);
  return `
    <div class="drawer__head">
      <div class="drawer__top">
        <div style="min-width:0">
          <p class="drawer__id">${escapeHtml(c.id)}, rank ${c.rank}</p>
          <h2 class="drawer__title">${escapeHtml(c.place)}</h2>
          <p class="drawer__where">${escapeHtml(where)}</p>
        </div>
        <button class="icon-btn" type="button" data-act="close-drawer" aria-label="Clear the selection">
          ${icon("i-x")}
        </button>
      </div>
      <div class="row row--wrap">${tierTag(c)}${confTag(c)}${statusTag(c)}</div>
    </div>

    <div class="drawer__body u-scroll">
      ${shot(c.images.annotated || c.images.raw, c.images.annotated ? "Annotated" : "Raw crop")}
      ${sect("Classification", "", classification(c))}
      ${sect("Detection", `<span class="u-micro">As published by FIRMS</span>`, detection(c))}
      ${c.persistence ? sect("Multi-Pass Persistence", `<span class="u-micro">Historical DB</span>`, persistence(c)) : ""}
      ${sect("Verify on the ground", "", links(c))}
      ${sect("Risk", `<span class="u-num u-micro">${c.risk.score} of 100</span>`, factors(c))}
      ${c.risk.action ? sect("Recommended action", "", `<p class="prose well">${escapeHtml(c.risk.action)}</p>`) : ""}
      ${sect("Model observations", `<span class="u-micro u-num">${c.evidence.length}</span>`, evidence(c.evidence, 3))}
    </div>

    <div class="drawer__foot">
      <button class="btn btn--sm" type="button" data-act="step" data-step="-1" aria-label="Previous case by rank">
        ${icon("i-chev-left", "i i--sm")}
      </button>
      <button class="btn btn--sm" type="button" data-act="step" data-step="1" aria-label="Next case by rank">
        ${icon("i-chev-right", "i i--sm")}
      </button>
      <span class="spacer"></span>
      <button class="btn btn--sm btn--primary" type="button" data-act="open-modal">
        ${icon("i-expand", "i i--sm")}Full dossier
      </button>
    </div>`;
}

/* --- Modal ---------------------------------------------------------------- */

function modeSeg(c, mode) {
  const opts = [["annotated", "Annotated", c.images.annotated], ["raw", "Raw", c.images.raw]]
    .filter(([, , src]) => Boolean(src));
  if (opts.length < 2) return "";
  return `<div class="seg" role="radiogroup" aria-label="Which crop to show">${opts
    .map(([id, label]) => `<button class="seg__opt" type="button" role="radio"
      aria-checked="${id === mode}" data-act="mode" data-mode="${id}">${label}</button>`)
    .join("")}</div>`;
}

function modalHtml(c, mode) {
  const src = mode === "raw" ? (c.images.raw || c.images.annotated) : (c.images.annotated || c.images.raw);
  const where = [c.site, c.address].filter(Boolean).join(", ") || fmt.coord(c.lat, c.lon);

  return `
    <div class="modal__head">
      <div style="min-width:0">
        <p class="modal__eyebrow">${escapeHtml(c.id)}, priority rank ${c.rank}</p>
        <h2 class="modal__title" id="modal-title">${escapeHtml(c.place)}</h2>
        <p class="modal__where">${escapeHtml(where)}</p>
      </div>
      <div class="row row--wrap" style="justify-content:flex-end">
        ${tierTag(c)}${confTag(c)}
        <button class="icon-btn" type="button" data-act="close-modal" aria-label="Close the dossier">
          ${icon("i-x")}
        </button>
      </div>
    </div>

    <div class="modal__body">
      <div class="modal__col">
        <section class="sect">
          <div class="sect__head">
            <h3 class="u-label">What the model looked at</h3>
            ${modeSeg(c, mode)}
          </div>
          ${shot(src, mode === "raw" ? "Raw crop" : "Annotated", "modal__shot")}
          <p class="u-micro">${escapeHtml(c.categoryTarget
            ? `Crop pulled for the ${c.categoryTarget} category target at ${fmt.coord(c.lat, c.lon)}.`
            : `Crop centred on ${fmt.coord(c.lat, c.lon)}.`)}</p>
        </section>
        ${sect("Model observations", `<span class="u-micro u-num">${c.evidence.length}</span>`, evidence(c.evidence))}
        ${c.reasoning ? sect("Model reasoning", "", `<p class="prose well">${escapeHtml(c.reasoning)}</p>`) : ""}
      </div>

      <div class="modal__col">
        ${sect("Classification", "", classification(c))}
        ${sect("Detection", `<span class="u-micro">As published by FIRMS</span>`, detection(c))}
        ${c.persistence ? sect("Multi-Pass Persistence", `<span class="u-micro">Historical DB</span>`, persistence(c)) : ""}
        ${sect("Risk", `<span class="u-num u-micro">${c.risk.score} of 100</span>`, factors(c))}
        ${c.risk.action ? sect("Recommended action", "", `<p class="prose well">${escapeHtml(c.risk.action)}</p>`) : ""}
        ${sect("Verify on the ground", "", links(c))}
      </div>
    </div>

    <div class="modal__foot">
      ${statusTag(c)}
      <div class="triage">${TRIAGE_ACTIONS.map((k) => `
        <button class="btn btn--sm" type="button" data-act="triage" data-status="${k}"
                aria-pressed="${getTriage(c.id) === k}">${escapeHtml(triageOf(k).label)}</button>`).join("")}
      </div>
      <span class="spacer"></span>
      <button class="btn btn--sm btn--ghost" type="button" data-act="triage" data-status="UNREVIEWED">
        Clear decision
      </button>
    </div>`;
}

/* --- Behaviour ------------------------------------------------------------ */

const FOCUSABLE = 'a[href],button:not(:disabled),input,select,textarea,[tabindex]:not([tabindex="-1"])';

/* A rebuild loses the reading position the same way it loses focus, and for the
   same reason. Re-rendering the same case is a data update, so the position is
   carried across; a different case is a different document and starts at the
   top. Without this, typing in the search box or taking a triage decision threw
   the reader back to the crop while they were part way down the evidence. */
const scrollTopOf = (host, sel) => host?.querySelector(sel)?.scrollTop || 0;

function restoreScroll(host, sel, top) {
  if (!top) return;
  const box = host?.querySelector(sel);
  if (box) box.scrollTop = top;
}

export function isModalOpen() {
  return dossier.scrim?.getAttribute("data-open") === "1";
}

export function isDrawerOpen() {
  return dossier.drawer?.getAttribute("data-open") === "1";
}

/* Everything the two surfaces read that can change while one of them is open.
   Case records are built once by load and never written to, so the only moving
   parts are the triage decision and which crop the modal is showing: a window, a
   class filter and a query cannot alter either panel. refresh compares this, so
   a render pass that changed none of it rebuilds nothing. */
function renderKey(c) {
  if (!c) return "";
  return `${c.id}|${getTriage(c.id)}|${dossier.mode}|${isDrawerOpen()}|${isModalOpen()}`;
}

export function showDrawer(c) {
  if (!c) return;
  const same = dossier.current?.id === c.id;
  const top = same ? scrollTopOf(dossier.drawer, ".drawer__body") : 0;

  dossier.current = c;
  dossier.drawer.innerHTML = drawerHtml(c);
  dossier.drawer.setAttribute("data-open", "1");
  restoreScroll(dossier.drawer, ".drawer__body", top);
  wireThumbs(dossier.drawer);
  if (isModalOpen()) showModal(c);
  dossier.rendered = renderKey(c);
}

/* Not a close, since the dock does not go away: this clears the selection and
   puts the prompt back. aria-hidden is deliberately not set. Docked, the panel
   still says something worth reading; floating, CSS visibility already takes it
   out of the accessibility tree. */
export function hideDrawer() {
  if (dossier.drawer) {
    dossier.drawer.innerHTML = drawerEmptyHtml();
    dossier.drawer.setAttribute("data-open", "0");
  }
  dossier.current = null;
  dossier.rendered = "";
  dossier.onClose();
}

/* Every render replaces the whole dialog, including the control that was just
   pressed, so focus has to be put back by identity rather than by reference.
   data-act with its qualifier survives the rebuild; anything else inside the
   dialog falls back to the close button, which is always there. Focus already
   outside the dialog is left alone. */
function focusTarget(node) {
  if (!node || !dossier.modal?.contains(node)) return null;
  const act = node.closest("[data-act]");
  if (!act) return '[data-act="close-modal"]';
  const d = act.dataset;
  return `[data-act="${d.act}"]`
    + (d.status ? `[data-status="${d.status}"]` : "")
    + (d.step ? `[data-step="${d.step}"]` : "")
    + (d.mode ? `[data-mode="${d.mode}"]` : "");
}

/* Same problem one layer out: the drawer that opened the dialog is rebuilt by
   the same decision, so the node held in returnFocus is detached by the time
   the dialog closes and focus has nowhere to go back to. */
function focusAnchor(node) {
  if (!(node instanceof Element)) return null;
  const act = node.closest("[data-act]");
  if (act?.dataset.act) return `[data-act="${act.dataset.act}"]`;
  const hit = node.closest("[data-case]");
  if (hit?.dataset.case) return `[data-case="${hit.dataset.case}"]`;
  return null;
}

/* A triage decision re-renders through the host's onTriage, so this runs on the
   dialog's principal action and not only on open. Without the restore, focus
   fell to <body>, where the trap below stops engaging because it only acts on
   the first and last control, and the next Tab left the dialog for the page
   behind it. */
export function showModal(c) {
  if (!c) return;
  const first = !isModalOpen();
  if (first) {
    dossier.returnFocus = document.activeElement;
    dossier.returnAnchor = focusAnchor(document.activeElement);
  }
  const restore = first ? null : focusTarget(document.activeElement);
  const top = !first && dossier.current?.id === c.id
    ? scrollTopOf(dossier.modal, ".modal__body") : 0;

  dossier.current = c;
  dossier.modal.innerHTML = modalHtml(c, dossier.mode);
  dossier.scrim.setAttribute("data-open", "1");
  dossier.modal.setAttribute("aria-hidden", "false");
  restoreScroll(dossier.modal, ".modal__body", top);
  wireThumbs(dossier.modal);

  if (first) {
    dossier.modal.querySelector('[data-act="close-modal"]')?.focus();
  } else if (restore) {
    (dossier.modal.querySelector(restore)
      || dossier.modal.querySelector('[data-act="close-modal"]'))?.focus();
  }
  dossier.rendered = renderKey(c);
}

export function hideModal() {
  dossier.scrim?.setAttribute("data-open", "0");
  dossier.modal?.setAttribute("aria-hidden", "true");
  dossier.mode = "annotated";
  /* The drawer behind it is still showing the same case, correctly, so the key is
     brought up to date rather than left stale. Closing the dialog is not a reason
     to rebuild the panel that did not close. */
  dossier.rendered = renderKey(dossier.current);

  const back = dossier.returnFocus;
  const anchor = dossier.returnAnchor;
  dossier.returnFocus = null;
  dossier.returnAnchor = null;

  /* The live opener if it survived, otherwise its replacement, otherwise the
     dossier button that is there whenever a case is selected. Anything is
     better than leaving focus on <body>, which restarts Tab at the skip link. */
  const target = (back?.isConnected && back !== document.body && back)
    || (anchor && document.querySelector(anchor))
    || dossier.drawer?.querySelector('[data-act="open-modal"]');
  target?.focus();
}

/* Re-render whatever is open, unless it would come out identical. A triage
   decision arrives here twice: the host renders through onTriage, and the click
   handler below asks again so the module still works for a host that wires
   nothing to it. Every other render pass arrives with nothing this panel reads
   having changed at all. The key settles all three without either caller having
   to know about the other, and it is the only reason showDrawer can be called
   from a render pass without the dialog above it flickering. */
export function refresh() {
  if (!dossier.current || renderKey(dossier.current) === dossier.rendered) return;
  if (isDrawerOpen()) showDrawer(dossier.current);
  else if (isModalOpen()) showModal(dossier.current);
}

function handleClick(event) {
  const hit = event.target.closest("[data-act]");
  if (!hit) return;
  const c = dossier.current;

  switch (hit.dataset.act) {
    case "close-drawer":
      hideDrawer();
      break;
    case "close-modal":
      hideModal();
      break;
    case "open-modal":
      if (c) showModal(c);
      break;
    case "mode":
      dossier.mode = hit.dataset.mode === "raw" ? "raw" : "annotated";
      if (c) showModal(c);
      break;
    case "triage":
      if (c) {
        setTriage(c.id, hit.dataset.status);
        dossier.onTriage(c.id, hit.dataset.status);
        /* The host renders the console, which refreshes this panel on the way
           through, so by here there is usually nothing left to do. Kept because
           onTriage defaults to a no-op: a host that wires nothing still gets a
           panel that agrees with the decision it just took. */
        refresh();
      }
      break;
    case "step":
      dossier.onStep(Number(hit.dataset.step) || 0);
      break;
    default:
      break;
  }
}

/* Modal focus trap. The drawer deliberately does not trap: it sits beside the
   console rather than over it, so tabbing back out to the map is correct. */
function trapTab(event) {
  const nodes = [...dossier.modal.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  /* Clicking the dialog's own prose, or anything else that parks activeElement
     on <body>, leaves focus outside the list above, where neither branch below
     matches. Tab has to come back in rather than walk the page behind. */
  if (!dossier.modal.contains(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function handleKeydown(event) {
  if (event.key === "Escape") {
    if (isModalOpen()) { hideModal(); return; }
    if (isDrawerOpen()) hideDrawer();
    return;
  }
  if (event.key === "Tab" && isModalOpen()) trapTab(event);
}

export function initDossier({ onTriage, onStep, onClose } = {}) {
  dossier.drawer = document.getElementById("drawer");
  dossier.scrim = document.getElementById("scrim");
  dossier.modal = document.getElementById("modal");
  if (onTriage) dossier.onTriage = onTriage;
  if (onStep) dossier.onStep = onStep;
  if (onClose) dossier.onClose = onClose;

  /* Written here rather than by calling hideDrawer, which would fire onClose
     and ask the app to re-render before the feed has landed. */
  dossier.drawer.innerHTML = drawerEmptyHtml();

  dossier.drawer.addEventListener("click", handleClick);
  dossier.modal.addEventListener("click", handleClick);
  dossier.scrim.addEventListener("mousedown", (e) => {
    if (e.target === dossier.scrim) hideModal();
  });
  document.addEventListener("keydown", handleKeydown);
}
