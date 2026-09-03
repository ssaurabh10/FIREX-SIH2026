// ==========================================================================
// FIREX Section 6: Interactive GIS Map Logic
// ==========================================================================

let map;
let baseLayers = {};
let incidents = [];
let ambientPoints = [];
let incidentMarkers = [];
let ambientLayerGroup;
let currentFilter = "all";
let activeIncidentId = null;

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  await loadData();
  setupUIEventListeners();
});

function initMap() {
  // Center map on India
  map = L.map("map", {
    center: [22.0, 79.5],
    zoom: 5,
    minZoom: 4,
    maxZoom: 18,
    zoomControl: false
  });

  // Zoom control in top right
  L.control.zoom({ position: "bottomright" }).addTo(map);

  // 1. CartoDB Dark Matter Basemap
  baseLayers.dark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap',
    subdomains: "abcd",
    maxZoom: 19
  }).addTo(map);

  // 2. Esri World Imagery (Satellite)
  baseLayers.satellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
    maxZoom: 18
  });

  ambientLayerGroup = L.layerGroup().addTo(map);
}

async function loadData() {
  try {
    const [incidentsRes, ambientRes] = await Promise.all([
      fetch("data/incidents.json"),
      fetch("data/ambient_firms.json")
    ]);
    
    incidents = await incidentsRes.json();
    ambientPoints = await ambientRes.json();

    document.getElementById("total-firms-count").innerText = ambientPoints.length;
    document.getElementById("ai-cases-count").innerText = incidents.length;

    renderIncidentMarkers();
    renderAmbientFirms();
    renderSidebarList();
  } catch (err) {
    console.error("Failed to load map data:", err);
  }
}

// Render custom pulsating markers for AI-evaluated benchmark cases
function renderIncidentMarkers() {
  // Clear existing
  incidentMarkers.forEach(m => map.removeLayer(m));
  incidentMarkers = [];

  incidents.forEach(inc => {
    let clsType = "industrial";
    const aiCls = (inc.ai_classification || "").toLowerCase();
    
    if (aiCls.includes("flare") || inc.frp > 30) clsType = "flare";
    else if (aiCls.includes("mining")) clsType = "mining";
    else if (aiCls.includes("wildfire")) clsType = "wildfire";
    else if (aiCls.includes("industrial")) clsType = "industrial";

    // Custom HTML DivIcon with pulsing rings
    const iconHtml = `
      <div class="pulsing-marker ${clsType}">
        <div class="pulse-ring"></div>
        <div class="pulse-core"></div>
      </div>
    `;

    const customIcon = L.divIcon({
      className: "custom-div-marker",
      html: iconHtml,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });

    const marker = L.marker([inc.latitude, inc.longitude], { icon: customIcon });

    // Marker Popup
    const popupContent = `
      <div style="font-family: 'Inter', sans-serif; min-width: 180px; color: #111;">
        <div style="font-weight: 700; font-size: 13px; color: #ff5500;">${inc.id.toUpperCase()}</div>
        <div style="font-size: 12px; font-weight: 600; margin: 3px 0;">${inc.ai_classification.toUpperCase()}</div>
        <div style="font-size: 11px; color: #444;">FRP: <b>${inc.frp} MW</b></div>
        <div style="font-size: 11px; color: #666;">Satellite: ${inc.satellite}</div>
        <div style="font-size: 10px; color: #888; margin-top: 4px;">Coord: ${inc.latitude.toFixed(4)}, ${inc.longitude.toFixed(4)}</div>
      </div>
    `;
    marker.bindPopup(popupContent);

    marker.on("click", () => {
      openIncidentDetails(inc.id);
    });

    marker.addTo(map);
    incidentMarkers.push({ id: inc.id, marker, data: inc });
  });
}

// Render ambient 451 FIRMS detections as subtle orange heat points
function renderAmbientFirms() {
  ambientLayerGroup.clearLayers();

  ambientPoints.forEach(pt => {
    const circle = L.circleMarker([pt.lat, pt.lon], {
      radius: Math.min(6, Math.max(2.5, pt.frp / 8)),
      color: "#ff8800",
      weight: 1,
      fillColor: "#ffaa00",
      fillOpacity: 0.45
    });

    circle.bindTooltip(`FIRMS Hotspot: ${pt.frp} MW (${pt.sat})`, {
      direction: "top",
      className: "tactical-tooltip"
    });

    ambientLayerGroup.addLayer(circle);
  });
}

// Render left sidebar list
function renderSidebarList() {
  const listEl = document.getElementById("incident-list");
  listEl.innerHTML = "";

  const filtered = incidents.filter(inc => {
    if (currentFilter === "all") return true;
    const aiCls = (inc.ai_classification || "").toLowerCase();
    if (currentFilter === "industrial") return aiCls.includes("industrial");
    if (currentFilter === "flare") return aiCls.includes("flare");
    if (currentFilter === "mining") return aiCls.includes("mining");
    if (currentFilter === "wildfire") return aiCls.includes("wildfire");
    return true;
  });

  document.getElementById("filter-count").innerText = `${filtered.length} Incidents`;

  filtered.forEach(inc => {
    const card = document.createElement("div");
    card.className = `incident-card ${activeIncidentId === inc.id ? "active" : ""}`;
    card.id = `card-${inc.id}`;

    let badgeClass = "badge-industrial";
    const aiCls = (inc.ai_classification || "").toLowerCase();
    if (aiCls.includes("flare")) badgeClass = "badge-flare";
    else if (aiCls.includes("mining")) badgeClass = "badge-mining";
    else if (aiCls.includes("wildfire")) badgeClass = "badge-wildfire";

    card.innerHTML = `
      <div class="incident-card-top">
        <span class="incident-id">${inc.id.toUpperCase()}</span>
        <span class="incident-class-badge ${badgeClass}">${inc.ai_classification}</span>
      </div>
      <div class="incident-title">${inc.location_name.split("(")[0].trim()}</div>
      <div class="incident-meta-row">
        <span>${inc.satellite} (${inc.instrument})</span>
        <span class="frp-tag">${inc.frp} MW</span>
      </div>
    `;

    card.addEventListener("click", () => {
      openIncidentDetails(inc.id);
    });

    listEl.appendChild(card);
  });
}

// Open detailed dossier drawer and pan map to coordinate
function openIncidentDetails(id) {
  activeIncidentId = id;
  const inc = incidents.find(i => i.id === id);
  if (!inc) return;

  // Fly camera to hotspot
  map.flyTo([inc.latitude, inc.longitude], 14, {
    duration: 1.2,
    easeLinearity: 0.25
  });

  // Open marker popup
  const item = incidentMarkers.find(m => m.id === id);
  if (item) item.marker.openPopup();

  // Highlight card in sidebar
  document.querySelectorAll(".incident-card").forEach(c => c.classList.remove("active"));
  const activeCard = document.getElementById(`card-${id}`);
  if (activeCard) {
    activeCard.classList.add("active");
    activeCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Populate Drawer
  document.getElementById("drawer-empty").style.display = "none";
  const contentEl = document.getElementById("drawer-content");
  contentEl.classList.remove("hidden");

  document.getElementById("drawer-case-id").innerText = inc.id.toUpperCase();
  document.getElementById("drawer-title").innerText = inc.location_name.split("(")[0].trim();
  document.getElementById("drawer-satellite-img").src = inc.image_url;
  document.getElementById("drawer-ai-class").innerText = inc.ai_classification;
  document.getElementById("drawer-ai-conf").innerText = `${Math.round(inc.ai_confidence * 100)}% Confidence (${inc.ai_uncertainty} uncertainty)`;
  document.getElementById("drawer-ai-reasoning").innerText = inc.ai_reasoning || "AI assessment completed.";
  
  // Evidence list
  const evidenceList = document.getElementById("drawer-ai-evidence");
  evidenceList.innerHTML = "";
  (inc.ai_evidence || []).forEach(ev => {
    const li = document.createElement("li");
    li.innerText = ev;
    evidenceList.appendChild(li);
  });

  // Sensor metrics
  document.getElementById("drawer-frp").innerText = `${inc.frp} MW`;
  document.getElementById("drawer-sat").innerText = `${inc.satellite} (${inc.instrument})`;
  document.getElementById("drawer-conf").innerText = inc.confidence;
  document.getElementById("drawer-time").innerText = `${inc.acq_date} ${inc.acq_time} UTC`;
  
  // Coordinates
  document.getElementById("drawer-coords").innerText = `${inc.latitude.toFixed(4)}° N, ${inc.longitude.toFixed(4)}° E`;
  document.getElementById("drawer-gmaps-link").href = `https://www.google.com/maps?q=${inc.latitude},${inc.longitude}&t=k`;
  document.getElementById("drawer-osm-name").innerText = inc.display_name || "";

}


function setupUIEventListeners() {
  // Layer Switchers
  const darkBtn = document.getElementById("layer-dark");
  const satBtn = document.getElementById("layer-satellite");

  darkBtn.addEventListener("click", () => {
    map.removeLayer(baseLayers.satellite);
    map.addLayer(baseLayers.dark);
    darkBtn.classList.add("active");
    satBtn.classList.remove("active");
  });

  satBtn.addEventListener("click", () => {
    map.removeLayer(baseLayers.dark);
    map.addLayer(baseLayers.satellite);
    satBtn.classList.add("active");
    darkBtn.classList.remove("active");
  });

  // Filter tabs
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      currentFilter = e.target.getAttribute("data-filter");
      renderSidebarList();
    });
  });

  // Ambient toggle
  const ambientBtn = document.getElementById("btn-toggle-ambient");
  const ambientStatus = document.getElementById("ambient-status");
  let ambientOn = true;

  ambientBtn.addEventListener("click", () => {
    ambientOn = !ambientOn;
    if (ambientOn) {
      map.addLayer(ambientLayerGroup);
      ambientStatus.innerText = "ON";
      ambientBtn.classList.remove("btn-secondary");
      ambientBtn.classList.add("btn-primary");
    } else {
      map.removeLayer(ambientLayerGroup);
      ambientStatus.innerText = "OFF";
      ambientBtn.classList.remove("btn-primary");
      ambientBtn.classList.add("btn-secondary");
    }
  });


  // Fit India bounds button
  document.getElementById("btn-fit-bounds").addEventListener("click", () => {
    map.flyTo([22.0, 79.5], 5, { duration: 1 });
  });


  // Close Drawer
  document.getElementById("btn-close-drawer").addEventListener("click", () => {
    document.getElementById("drawer-content").classList.add("hidden");
    document.getElementById("drawer-empty").style.display = "flex";
    document.querySelectorAll(".incident-card").forEach(c => c.classList.remove("active"));
    activeIncidentId = null;
  });

  // Launch Full Forensic Investigation Screen (Section 7)
  document.getElementById("btn-launch-investigation").addEventListener("click", () => {
    if (activeIncidentId) {
      openInvestigationModal(activeIncidentId);
    }
  });

  // Section 7 Modal Close
  document.getElementById("btn-close-modal").addEventListener("click", closeInvestigationModal);

  // Section 7 Modal Navigation
  document.getElementById("btn-prev-case").addEventListener("click", () => navigateIncident(-1));
  document.getElementById("btn-next-case").addEventListener("click", () => navigateIncident(1));

  // Keyboard shortcuts (Esc to close, Left/Right arrows to navigate)
  document.addEventListener("keydown", (e) => {
    const modal = document.getElementById("investigation-modal");
    if (modal && !modal.classList.contains("hidden")) {
      if (e.key === "Escape") closeInvestigationModal();
      else if (e.key === "ArrowLeft") navigateIncident(-1);
      else if (e.key === "ArrowRight") navigateIncident(1);
    }
  });
}

// ==========================================================================
// SECTION 7: Forensic Investigation Modal Logic
// ==========================================================================

let modalActiveIncident = null;
let currentImageView = "annotated"; // 'annotated' or 'raw'

function openInvestigationModal(id) {
  const inc = incidents.find(i => i.id === id);
  if (!inc) return;

  modalActiveIncident = inc;
  const modalEl = document.getElementById("investigation-modal");
  modalEl.classList.remove("hidden");

  // Header tags
  document.getElementById("modal-case-id").innerText = inc.id.toUpperCase();
  document.getElementById("modal-frp-alert").innerText = `FRP: ${inc.frp} MW`;
  
  // Triage status from localStorage
  const savedTriage = localStorage.getItem(`firex_triage_${inc.id}`) || "UNREVIEWED";
  updateTriageBadge(savedTriage);

  // Titles
  const mainName = inc.location_name.split("(")[0].trim();
  document.getElementById("modal-title").innerText = mainName;
  document.getElementById("modal-subtitle").innerText = `${inc.category_target.toUpperCase().replace(/_/g, ' ')} // Analyzed by MiniMax M3 Vision AI`;

  // Setup Image View
  currentImageView = "annotated";
  updateModalSatelliteImage();

  // Setup View Toggle Buttons
  const btnAnnotated = document.getElementById("btn-view-annotated");
  const btnRaw = document.getElementById("btn-view-raw");

  btnAnnotated.onclick = () => {
    currentImageView = "annotated";
    btnAnnotated.classList.add("active");
    btnRaw.classList.remove("active");
    updateModalSatelliteImage();
  };

  btnRaw.onclick = () => {
    currentImageView = "raw";
    btnRaw.classList.add("active");
    btnAnnotated.classList.remove("active");
    updateModalSatelliteImage();
  };

  // Geospatial Footprint
  document.getElementById("modal-coords").innerText = `${inc.latitude.toFixed(5)}° N, ${inc.longitude.toFixed(5)}° E`;
  document.getElementById("modal-gmaps-link").href = `https://www.google.com/maps?q=${inc.latitude},${inc.longitude}&t=k`;
  document.getElementById("modal-osm-link").href = `https://www.openstreetmap.org/?mlat=${inc.latitude}&mlon=${inc.longitude}#map=16/${inc.latitude}/${inc.longitude}`;

  // AI Classification Verdict
  const aiClass = (inc.ai_classification || "uncertain").toUpperCase().replace(/_/g, ' ');
  document.getElementById("modal-ai-class").innerText = aiClass;
  document.getElementById("modal-ai-confidence").innerText = `${Math.round(inc.ai_confidence * 100)}%`;
  
  const uncEl = document.getElementById("modal-ai-uncertainty");
  uncEl.innerText = (inc.ai_uncertainty || "MODERATE").toUpperCase();
  if (inc.ai_uncertainty === "low") uncEl.style.color = "#10b981";
  else if (inc.ai_uncertainty === "high") uncEl.style.color = "#ef4444";
  else uncEl.style.color = "#f59e0b";

  // Banner color theme based on classification
  const bannerEl = document.getElementById("modal-verdict-banner");
  if (aiClass.includes("FLARE")) {
    bannerEl.style.borderColor = "#ef4444";
    bannerEl.style.background = "linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(20, 26, 40, 0.95))";
  } else if (aiClass.includes("INDUSTRIAL")) {
    bannerEl.style.borderColor = "#ff9500";
    bannerEl.style.background = "linear-gradient(135deg, rgba(255, 149, 0, 0.2), rgba(20, 26, 40, 0.95))";
  } else if (aiClass.includes("MINING")) {
    bannerEl.style.borderColor = "#f59e0b";
    bannerEl.style.background = "linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(20, 26, 40, 0.95))";
  } else if (aiClass.includes("WILDFIRE")) {
    bannerEl.style.borderColor = "#10b981";
    bannerEl.style.background = "linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(20, 26, 40, 0.95))";
  }

  // Visual Evidence Checklist
  const evidenceList = document.getElementById("modal-evidence-list");
  evidenceList.innerHTML = "";
  if (inc.ai_evidence && inc.ai_evidence.length > 0) {
    inc.ai_evidence.forEach(ev => {
      const li = document.createElement("li");
      li.innerText = ev;
      evidenceList.appendChild(li);
    });
  } else {
    evidenceList.innerHTML = "<li>Visual evidence extracted from 1.2 km resolution optical inspection.</li>";
  }

  // Chain of Thought Analytical Reasoning
  document.getElementById("modal-reasoning-text").innerText = inc.ai_reasoning || "Analytical reasoning complete.";

  // Sensor Telemetry
  document.getElementById("modal-metric-frp").innerText = `${inc.frp} MW`;
  document.getElementById("modal-metric-sat").innerText = `${inc.satellite} (${inc.instrument})`;
  document.getElementById("modal-metric-conf").innerText = inc.confidence;
  document.getElementById("modal-metric-time").innerText = `${inc.acq_date} ${inc.acq_time} UTC`;

  // Industrial Proximity
  let facility = "Heavy Industry / Storage";
  let dist = "< 300 m";
  let landuse = "Industrial Manufacturing";
  if (aiClass.includes("FLARE")) {
    facility = "Refinery Flare Stack / Petroleum Tank Farm";
    dist = "< 180 m";
    landuse = "Petrochemical Refining";
  } else if (aiClass.includes("MINING")) {
    facility = "Open-Pit Coal Pit / Excavation Void";
    dist = "< 100 m";
    landuse = "Mining / Mineral Overburden";
  } else if (aiClass.includes("WILDFIRE")) {
    facility = "Wildlife Sanctuary Reserve / Forest Canopy";
    dist = "Wildland Interface";
    landuse = "Deciduous Forest / Scrub";
  }

  document.getElementById("modal-prox-facility").innerText = facility;
  document.getElementById("modal-prox-dist").innerText = dist;
  document.getElementById("modal-prox-landuse").innerText = landuse;
  document.getElementById("modal-prox-admin").innerText = (inc.display_name || "").split(",").slice(0, 3).join(",");


  // Triage Action Buttons
  document.querySelectorAll(".triage-btn").forEach(btn => {
    btn.onclick = () => {
      const status = btn.getAttribute("data-status");
      localStorage.setItem(`firex_triage_${inc.id}`, status);
      updateTriageBadge(status);
    };
  });
}


function updateModalSatelliteImage() {
  if (!modalActiveIncident) return;
  const imgEl = document.getElementById("modal-satellite-img");
  if (currentImageView === "annotated") {
    imgEl.src = modalActiveIncident.image_url;
  } else {
    imgEl.src = modalActiveIncident.raw_image_url;
  }
}

function updateTriageBadge(status) {
  const badge = document.getElementById("modal-triage-badge");
  badge.className = "badge-status-triage";
  
  if (status === "VERIFIED_FIRE") {
    badge.innerText = "VERIFIED FIRE";
    badge.classList.add("status-verified");
  } else if (status === "ROUTINE_FLARE") {
    badge.innerText = "ROUTINE FLARING";
    badge.classList.add("status-flare");
  } else if (status === "ESCALATED_CRITICAL") {
    badge.innerText = "ALERT ESCALATED";
    badge.classList.add("status-escalated");
  } else if (status === "FALSE_ALARM") {
    badge.innerText = "FALSE ALARM";
  } else {
    badge.innerText = "UNREVIEWED";
  }
}

function closeInvestigationModal() {
  const modalEl = document.getElementById("investigation-modal");
  if (modalEl) modalEl.classList.add("hidden");
  modalActiveIncident = null;
}

function navigateIncident(direction) {
  if (!modalActiveIncident) return;
  const currIdx = incidents.findIndex(i => i.id === modalActiveIncident.id);
  if (currIdx === -1) return;
  
  let newIdx = currIdx + direction;
  if (newIdx < 0) newIdx = incidents.length - 1;
  if (newIdx >= incidents.length) newIdx = 0;
  
  openInvestigationModal(incidents[newIdx].id);
}



