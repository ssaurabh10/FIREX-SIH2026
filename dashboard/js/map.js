/* ==========================================================================
   map - Leaflet setup, marker layers, selection
   ========================================================================== */

import { MAP_HOME, fmt, icon, escapeHtml } from "./config.js";

const ESRI = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  darkRef: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
  imagery: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
};

const CREDIT = "Esri, Maxar, Earthstar Geographics | NASA FIRMS";

export const mapState = {
  map: null,
  base: "dark",
  layers: {},
  markers: new Map(),   // case id -> L.Marker
  ambient: null,
  ambientLayers: [],    // [{ marker, frp }]
  selected: null,
  error: "",            // why there is no map, when there is no map
  onSelect: () => {},
  onViewChange: () => {},
};

function getAmbientRadius(frp, zoom = 5) {
  // Moderate base size: 2.2px for low FRP up to 3.5px for high FRP at overview
  const base = Math.min(3.5, Math.max(2.2, (frp || 10) / 28));
  // Moderate zoom factor scaling (smoothly reaches ~6-8px at close zoom)
  const zoomFactor = Math.max(1, 1 + (zoom - 5) * 0.22);
  return Math.min(10, Math.max(2.2, Math.round(base * zoomFactor * 10) / 10));
}

function updateAmbientSizes() {
  if (!mapState.map || !mapState.ambientLayers || !mapState.ambientLayers.length) return;
  const zoom = mapState.map.getZoom();
  for (let i = 0; i < mapState.ambientLayers.length; i++) {
    const item = mapState.ambientLayers[i];
    item.marker.setRadius(getAmbientRadius(item.frp, zoom));
  }
}

/* Leaflet is the one dependency this console fetches from a CDN, so it is the
   one that can be missing on a slow, filtered or offline network. It used to be
   called into unguarded from the first line of boot, which meant a missing global
   threw before any of the wiring ran: no tabs, no search, no data, no message,
   just a dark page. Reporting the failure instead of raising it lets the caller
   bring up everything that does not need a map. */
export function initMap() {
  if (typeof L === "undefined") {
    mapState.error = "Leaflet did not load from the CDN, so the map cannot be drawn.";
    return null;
  }

  try {
    const map = L.map("map", {
      center: MAP_HOME.center,
      zoom: MAP_HOME.zoom,
      minZoom: 4,
      maxZoom: 18,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
      worldCopyJump: false,
    });

    mapState.layers.dark = L.layerGroup([
      L.tileLayer(ESRI.dark, { maxZoom: 16, attribution: CREDIT }),
      L.tileLayer(ESRI.darkRef, { maxZoom: 16, pane: "overlayPane", opacity: 0.7 }),
    ]);
    mapState.layers.satellite = L.tileLayer(ESRI.imagery, { maxZoom: 18, attribution: CREDIT });

    mapState.layers.dark.addTo(map);
    mapState.ambient = L.layerGroup().addTo(map);
    mapState.pins = L.layerGroup().addTo(map);

    map.on("zoomend", updateAmbientSizes);
    map.on("moveend zoomend", () => mapState.onViewChange(countInView()));
    mapState.map = map;
    return map;
  } catch (err) {
    /* Half a map is worse than none: leave mapState.map null so every guard in
       this module holds, and let the console come up without it. */
    mapState.map = null;
    mapState.error = `The map did not start: ${err && err.message ? err.message : err}`;
    return null;
  }
}

export function setBase(id) {
  const { map, layers } = mapState;
  if (!map || !layers[id] || id === mapState.base) return;
  map.removeLayer(layers[mapState.base]);
  layers[id].addTo(map);
  layers[id].bringToBack?.();
  mapState.base = id;
  document.getElementById("mapframe")?.setAttribute("data-base", id);
}

/* --- Incident markers ----------------------------------------------------
   Two visual channels: the glyph states the classification, the ring colour
   states the risk tier, and a dashed ring means the source was not visually
   confirmable. Nothing on this map is an anonymous red dot. */

function markerHtml(c) {
  return [
    `<div class="mk" data-tier="${c.risk.tier}" data-confirmed="${c.confirmed ? 1 : 0}"`,
    ` data-lead="${c.rank === 1 ? 1 : 0}" data-case="${escapeHtml(c.id)}">`,
    icon(c.cls.icon, "i i--sm"),
    `<span class="mk__rank">${c.rank}</span>`,
    `</div>`,
  ].join("");
}

function popupHtml(c) {
  const conf = c.firms.confidence;
  return `
    <div class="pop" data-tier="${c.risk.tier}">
      <div class="pop__top">
        <span class="pop__id">${escapeHtml(c.id)}</span>
        <span class="tag tag--tier">${c.risk.tier} ${c.risk.score}</span>
      </div>
      <div>
        <p class="pop__name">${escapeHtml(c.place)}</p>
        <p class="u-micro" style="margin-top:4px">
          ${escapeHtml(c.cls.label)}${c.confirmed ? "" : ", not visually confirmed"}
        </p>
      </div>
      <dl class="pop__grid">
        <div class="pop__cell"><dt>FRP</dt><dd>${fmt.dec(c.frp)} MW</dd></div>
        <div class="pop__cell"><dt>Sensor</dt><dd>${escapeHtml(c.firms.instrument)}</dd></div>
        <div class="pop__cell"><dt>Conf</dt><dd>${escapeHtml(conf.display)}</dd></div>
      </dl>
    </div>`;
}

/* Both draw calls run on every render pass, so both have to survive a console
   that came up without a map. They report zero in view rather than returning
   silently, because the readout above the map is written from what they say. */
export function drawCases(cases) {
  if (!mapState.map) { mapState.onViewChange(countInView()); return; }
  mapState.pins.clearLayers();
  mapState.markers.clear();

  cases.forEach((c) => {
    if (!Number.isFinite(c.lat) || !Number.isFinite(c.lon)) return;
    const marker = L.marker([c.lat, c.lon], {
      icon: L.divIcon({ html: markerHtml(c), className: "", iconSize: [28, 28], iconAnchor: [14, 14] }),
      keyboard: true,
      title: `${c.id}: ${c.place}`,
      riseOnHover: true,
    });
    marker.bindPopup(popupHtml(c), { closeButton: false, offset: [0, -6], autoPanPadding: [40, 40] });
    marker.on("click", () => mapState.onSelect(c.id));
    marker.addTo(mapState.pins);
    mapState.markers.set(c.id, marker);
  });

  if (mapState.selected) select(mapState.selected, { fly: false });
  mapState.onViewChange(countInView());
}

export function drawAmbient(points, visible) {
  if (!mapState.map) { mapState.onViewChange(countInView()); return; }
  mapState.ambient.clearLayers();
  mapState.ambientLayers = [];
  mapState.ambientVisible = visible;
  mapState.ambientPoints = visible ? points : [];
  if (!visible) { mapState.onViewChange(countInView()); return; }

  const currentZoom = mapState.map.getZoom();
  // Canvas-optimized batch rendering with dynamic zoom-scaled radius & interactive tooltips
  points.forEach((p) => {
    const r = getAmbientRadius(p.frp, currentZoom);
    const satName = p.sat === "N20" ? "VIIRS NOAA-20" : p.sat === "NPP" ? "VIIRS Suomi-NPP" : p.sat === "MOD" ? "MODIS Aqua/Terra" : (p.sat || "NASA FIRMS");
    const confLabel = p.conf === "h" ? "High" : p.conf === "n" ? "Nominal" : p.conf === "l" ? "Low" : (p.conf ? String(p.conf) : "Unreported");
    const timeFormatted = p.time ? `${String(p.time).padStart(4, "0").slice(0, 2)}:${String(p.time).padStart(4, "0").slice(2)} UTC` : "";
    const dateFormatted = p.date || "";

    const tipContent = `
      <div class="amb-tip">
        <div class="amb-tip__title">NASA FIRMS HOTSPOT</div>
        <div class="amb-tip__row"><span>FRP:</span> <b>${p.frp} MW</b></div>
        <div class="amb-tip__row"><span>Satellite:</span> <b>${escapeHtml(satName)}</b></div>
        <div class="amb-tip__row"><span>Confidence:</span> <b>${escapeHtml(confLabel)}</b></div>
        ${dateFormatted ? `<div class="amb-tip__row"><span>Acquired:</span> <b>${escapeHtml(dateFormatted)} ${escapeHtml(timeFormatted)}</b></div>` : ""}
        <div class="amb-tip__row"><span>Coord:</span> <b>${p.lat.toFixed(4)}°, ${p.lon.toFixed(4)}°</b></div>
      </div>
    `;

    const marker = L.circleMarker([p.lat, p.lon], {
      radius: r,
      stroke: true,
      color: "#ffc233",
      weight: 1,
      opacity: 0.85,
      fillColor: "#ff9900",
      fillOpacity: 0.65,
      interactive: true,
    }).addTo(mapState.ambient);

    marker.bindTooltip(tipContent, {
      direction: "top",
      offset: [0, -r],
      sticky: true,
      className: "amb-tip-box"
    });

    marker.bindPopup(tipContent, {
      className: "amb-popup-box",
      closeButton: false,
      offset: [0, -r]
    });

    mapState.ambientLayers.push({ marker, frp: p.frp });
  });
  mapState.onViewChange(countInView());
}

/* --- Selection -----------------------------------------------------------
   Selection is one piece of state shared by the map, the spine and the
   dossier. The marker element carries it as a data attribute so the styling
   stays in CSS and nothing here writes inline style. */

function markerEl(id) {
  const m = mapState.markers.get(id);
  return m?.getElement()?.querySelector(".mk") || null;
}

export function select(id, { fly = true, zoom = 11 } = {}) {
  if (mapState.selected && mapState.selected !== id) {
    markerEl(mapState.selected)?.setAttribute("data-selected", "0");
  }
  mapState.selected = id || null;
  if (!id) return;

  const marker = mapState.markers.get(id);
  markerEl(id)?.setAttribute("data-selected", "1");
  if (marker && fly) {
    const target = Math.max(mapState.map.getZoom(), zoom);
    mapState.map.flyTo(marker.getLatLng(), target, { duration: 0.9 });
  }
}

export function clearSelection() {
  if (mapState.selected) markerEl(mapState.selected)?.setAttribute("data-selected", "0");
  mapState.selected = null;
  mapState.map?.closePopup();
}

/* Hover pre-highlight, driven by the spine and the queue. Cheap on purpose:
   one attribute flip, no layer rebuild. */
export function hover(id, on) {
  markerEl(id)?.setAttribute("data-hover", on ? "1" : "0");
}

/* There is deliberately no openPopup here. Clicking a marker opens its own popup
   through bindPopup, and a selection made from the spine or the queue is answered
   by the dossier, so opening a popup as well would cover the ground the reader
   just asked to look at. The export existed and nothing called it. */

/* --- Camera and counting -------------------------------------------------- */

export function countInView() {
  const { map, markers, ambientPoints, ambientVisible } = mapState;
  if (!map) return { cases: 0, ambient: 0 };
  const bounds = map.getBounds();
  let cases = 0;
  markers.forEach((m) => { if (bounds.contains(m.getLatLng())) cases += 1; });
  let amb = 0;
  if (ambientVisible && ambientPoints && ambientPoints.length) {
    const s = bounds.getSouth(), n = bounds.getNorth(), w = bounds.getWest(), e = bounds.getEast();
    for (let i = 0; i < ambientPoints.length; i++) {
      const p = ambientPoints[i];
      if (p.lat >= s && p.lat <= n && p.lon >= w && p.lon <= e) amb++;
    }
  }
  return { cases, ambient: amb };
}

export function fitAll() {
  const { map, markers } = mapState;
  if (!map || !markers.size) return;
  const bounds = L.latLngBounds([...markers.values()].map((m) => m.getLatLng()));
  map.flyToBounds(bounds, { padding: [88, 88], maxZoom: 9, duration: 0.9 });
}

export function home() {
  mapState.map?.flyTo(MAP_HOME.center, MAP_HOME.zoom, { duration: 0.9 });
}

export function zoomBy(delta) {
  const map = mapState.map;
  if (map) map.setZoom(map.getZoom() + delta);
}

/* Leaflet measures its container on init. The map lives in a hidden view when
   another tab is active, so it has to be re-measured whenever the map view is
   shown again or it renders as a 0-height grey box. */
export function resize() {
  mapState.map?.invalidateSize({ animate: false });
}
