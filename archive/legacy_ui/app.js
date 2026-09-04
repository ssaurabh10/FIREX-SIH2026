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

  // 1. Esri Military Dark Gray Canvas (Defense/Intelligence Grade)
  const esriDarkBase = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    maxZoom: 16
  });

  const esriDarkRef = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
    attribution: "",
    maxZoom: 16
  });

  baseLayers.dark = L.layerGroup([esriDarkBase, esriDarkRef]).addTo(map);

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
    renderOverview();
    renderInvestigationsGrid();
    renderIndustrialFacilities();
    renderAnalyticsCharts();
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

    const riskTier = (inc.risk_tier || "medium").toLowerCase();
    const riskScore = inc.risk_score || 50;
    const priorityRank = inc.priority_rank ? `#${inc.priority_rank}` : "";

    card.innerHTML = `
      <div class="incident-card-top">
        <span class="incident-id">${inc.id.toUpperCase()}</span>
        <span class="risk-pill tier-${riskTier}">RANK ${priorityRank} · ${riskScore}/100</span>
      </div>
      <div class="incident-title">${inc.location_name.split("(")[0].trim()}</div>
      <div class="incident-meta-row">
        <span class="incident-class-badge ${badgeClass}">${inc.ai_classification}</span>
        <span class="frp-tag">${inc.frp} MW</span>
      </div>
    `;

    card.addEventListener("click", () => {
      openIncidentDetails(inc.id);
    });

    listEl.appendChild(card);
  });
}

// Render Section 10 Risk Factors progress bars
function renderRiskFactorsHTML(factors) {
  if (!factors || factors.length === 0) return "";
  return factors.map(f => {
    const pct = Math.min(100, Math.round((f.score / f.max) * 100));
    return `
      <div class="risk-factor-item">
        <div class="factor-header">
          <span class="factor-name">${f.factor}</span>
          <span class="factor-val">${f.score} / ${f.max} pts</span>
        </div>
        <div class="factor-bar-bg">
          <div class="factor-bar-fill" style="width: ${pct}%"></div>
        </div>
        <div class="factor-detail">${f.detail}</div>
      </div>
    `;
  }).join("");
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

  // Section 10: Operational Threat & Priority Card
  const rankEl = document.getElementById("drawer-priority-rank");
  if (rankEl) rankEl.innerText = `PRIORITY #${inc.priority_rank || 1}`;
  const scoreEl = document.getElementById("drawer-risk-score");
  if (scoreEl) scoreEl.innerText = inc.risk_score || 50;
  const tierEl = document.getElementById("drawer-risk-tier");
  if (tierEl) {
    tierEl.innerText = `${inc.risk_tier || 'MEDIUM'} THREAT`;
    tierEl.style.color = inc.risk_color || '#ff7700';
  }
  const actionEl = document.getElementById("drawer-risk-action");
  if (actionEl) actionEl.innerText = inc.action_recommendation || 'MONITOR THERMAL ACTIVITY';
  const factorsEl = document.getElementById("drawer-risk-factors");
  if (factorsEl) factorsEl.innerHTML = renderRiskFactorsHTML(inc.risk_factors);

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

  // Section 12 Navigation Tabs
  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
      const targetTab = e.currentTarget.getAttribute("data-tab");
      switchAppTab(targetTab);
    });
  });

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

  // Section 10 Risk Badge in Top Bar
  const modalRiskBadge = document.getElementById("modal-risk-badge");
  if (modalRiskBadge) {
    modalRiskBadge.innerText = `PRIORITY #${inc.priority_rank || 1} · THREAT ${inc.risk_score || 50}/100`;
    modalRiskBadge.style.color = inc.risk_color || "#ff7700";
    modalRiskBadge.style.borderColor = inc.risk_color || "rgba(255,119,0,0.4)";
  }

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

  // Section 10: Deterministic Risk & Priority Audit Card in Modal
  const auditTierEl = document.getElementById("modal-audit-tier");
  if (auditTierEl) {
    auditTierEl.innerText = `${inc.risk_tier || 'MEDIUM'} RISK · ${inc.risk_score || 50}/100`;
    auditTierEl.style.color = inc.risk_color || "#ff7700";
    auditTierEl.style.borderColor = inc.risk_color || "rgba(255,119,0,0.4)";
  }
  const modalRiskScore = document.getElementById("modal-risk-score");
  if (modalRiskScore) modalRiskScore.innerText = inc.risk_score || 50;
  const modalRiskRec = document.getElementById("modal-risk-recommendation");
  if (modalRiskRec) modalRiskRec.innerText = inc.action_recommendation || 'MONITOR INCIDENT';
  const modalBreakdown = document.getElementById("modal-factor-breakdown");
  if (modalBreakdown) modalBreakdown.innerHTML = renderRiskFactorsHTML(inc.risk_factors);

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

// ==========================================================================
// SECTION 12: Multi-View Platform Renderers & Tab Switcher
// ==========================================================================

function switchAppTab(tabName) {
  document.querySelectorAll(".nav-tab").forEach(t => {
    t.classList.toggle("active", t.getAttribute("data-tab") === tabName);
  });
  document.querySelectorAll(".view-panel").forEach(p => {
    p.classList.toggle("active", p.id === `view-${tabName}`);
  });

  if (tabName === "map") {
    setTimeout(() => {
      if (map) map.invalidateSize();
    }, 100);
  }
}

// 1. Render Overview Tab
function renderOverview() {
  const queueEl = document.getElementById("overview-queue-list");
  if (!queueEl) return;
  queueEl.innerHTML = "";

  // Update counts
  const criticalCount = incidents.filter(i => (i.risk_score || 0) >= 70).length;
  const indCount = incidents.filter(i => (i.ai_classification || "").includes("industrial")).length;
  const flareCount = incidents.filter(i => (i.ai_classification || "").includes("flare")).length;
  const miningCount = incidents.filter(i => (i.ai_classification || "").includes("mining")).length;

  const critEl = document.getElementById("overview-critical-count");
  if (critEl) critEl.innerText = criticalCount;
  const indEl = document.getElementById("overview-industrial-count");
  if (indEl) indEl.innerText = indCount;
  const flareEl = document.getElementById("overview-flare-count");
  if (flareEl) flareEl.innerText = flareCount;
  const miningEl = document.getElementById("overview-mining-count");
  if (miningEl) miningEl.innerText = miningCount;

  // Render sorted priority queue
  incidents.forEach(inc => {
    const item = document.createElement("div");
    item.className = "queue-item";
    const tier = (inc.risk_tier || "medium").toLowerCase();

    item.innerHTML = `
      <div class="queue-left">
        <span class="queue-rank">#${inc.priority_rank || 1}</span>
        <div class="queue-info">
          <h4>${inc.location_name.split("(")[0].trim()}</h4>
          <p>${inc.ai_classification.toUpperCase().replace(/_/g, ' ')} • ${inc.frp} MW • ${inc.satellite}</p>
        </div>
      </div>
      <div class="queue-right">
        <span class="risk-pill tier-${tier}">THREAT ${inc.risk_score || 50}/100</span>
        <button class="queue-action-btn btn-inspect" data-id="${inc.id}">Inspect Map 🗺️</button>
        <button class="queue-action-btn btn-dossier" data-id="${inc.id}">Dossier ⚡</button>
      </div>
    `;

    item.querySelector(".btn-inspect").addEventListener("click", (e) => {
      e.stopPropagation();
      switchAppTab("map");
      openIncidentDetails(inc.id);
    });

    item.querySelector(".btn-dossier").addEventListener("click", (e) => {
      e.stopPropagation();
      openInvestigationModal(inc.id);
    });

    item.addEventListener("click", () => {
      switchAppTab("map");
      openIncidentDetails(inc.id);
    });

    queueEl.appendChild(item);
  });
}

// 2. Render Investigations Grid Tab
function renderInvestigationsGrid() {
  const gridEl = document.getElementById("investigations-grid");
  if (!gridEl) return;
  gridEl.innerHTML = "";

  incidents.forEach(inc => {
    const card = document.createElement("div");
    card.className = "inv-card";
    const tier = (inc.risk_tier || "medium").toLowerCase();

    card.innerHTML = `
      <div class="inv-card-thumb">
        <img src="${inc.image_url}" alt="Satellite View" loading="lazy">
        <div class="inv-thumb-overlay">
          <span class="case-tag">${inc.id.toUpperCase()}</span>
          <span class="risk-pill tier-${tier}">THREAT ${inc.risk_score || 50}/100</span>
        </div>
      </div>
      <div class="inv-card-body">
        <h4 class="inv-card-title">${inc.location_name.split("(")[0].trim()}</h4>
        <div class="inv-card-meta">
          <span>${inc.ai_classification.replace(/_/g, ' ')}</span>
          <span class="frp-highlight">${inc.frp} MW</span>
        </div>
        <p class="ai-reasoning" style="font-size:11px; line-height:1.4; margin:0; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
          ${inc.ai_reasoning || "AI assessment completed."}
        </p>
        <div class="inv-btn-suite">
          <button class="btn btn-primary btn-open-modal" data-id="${inc.id}">⚡ Launch Dossier</button>
          <button class="btn btn-secondary btn-locate" data-id="${inc.id}">📍 Locate</button>
        </div>
      </div>
    `;

    card.querySelector(".btn-open-modal").addEventListener("click", () => {
      openInvestigationModal(inc.id);
    });

    card.querySelector(".btn-locate").addEventListener("click", () => {
      switchAppTab("map");
      openIncidentDetails(inc.id);
    });

    gridEl.appendChild(card);
  });
}

// 3. Render Industrial Facilities Catalog Tab
function renderIndustrialFacilities() {
  const catalogEl = document.getElementById("industrial-facilities-list");
  if (!catalogEl) return;
  catalogEl.innerHTML = "";

  const facilities = [
    {
      name: "HMEL Guru Gobind Singh Refinery",
      zone: "Talwandi Sabo, Bathinda, Punjab",
      type: "Petroleum Refinery & Tank Farm",
      caseId: "case_004",
      coords: "29.9098° N, 74.9519° E",
      frp: "48.91 MW",
      hazard: "HIGH FLARING OUTPUT",
      buffer: "< 180 m to crude storage tanks"
    },
    {
      name: "Hazira Petrochemical & LNG Complex",
      zone: "Chorasi Taluka, Surat, Gujarat",
      type: "ONGC / AM-NS Heavy Industry Hub",
      caseId: "case_001",
      coords: "21.1234° N, 72.6789° E",
      frp: "9.08 MW",
      hazard: "STRUCTURAL ANOMALY",
      buffer: "< 250 m to manufacturing core"
    },
    {
      name: "NTPC Ramagundam Super Thermal Power",
      zone: "Peddapalli, Telangana",
      type: "Coal-Fired Power Station (2,600 MW)",
      caseId: "case_006",
      coords: "18.7562° N, 79.5143° E",
      frp: "10.97 MW",
      hazard: "TURBINE/ASH HEAT DISCHARGE",
      buffer: "< 350 m to power generator blocks"
    },
    {
      name: "Talcher Open-Cast Coal Belt",
      zone: "MCL Concession, Angul, Odisha",
      type: "Extensive Surface Coal Extraction",
      caseId: "case_002",
      coords: "20.9521° N, 85.2145° E",
      frp: "8.87 MW",
      hazard: "COAL SEAM HEAT ANOMALY",
      buffer: "Inside operational extraction void"
    },
    {
      name: "Korba Coal Mining & Smelter Complex",
      zone: "SECL Belt, Korba, Chhattisgarh",
      type: "Coal Extraction & Aluminum Smelting",
      caseId: "case_003",
      coords: "22.3596° N, 82.7501° E",
      frp: "16.09 MW",
      hazard: "OVERBURDEN HEAT ACCUMULATION",
      buffer: "Active coal pit boundary"
    },
    {
      name: "Singrauli Energy & Mining Corridor",
      zone: "NCL / NTPC Hub, MP-UP Border",
      type: "Mega Power & Coal Mining Belt",
      caseId: "case_007",
      coords: "24.1994° N, 82.6651° E",
      frp: "8.24 MW",
      hazard: "COAL STORAGE PYROLYSIS",
      buffer: "< 400 m to thermal conveyor system"
    },
    {
      name: "Bastar Southern Forest Reserve Interface",
      zone: "Bastar Plateau, Chhattisgarh",
      type: "Deciduous Wildland Forest Canopy",
      caseId: "case_005",
      coords: "19.0741° N, 81.9612° E",
      frp: "11.23 MW",
      hazard: "CANOPY BIOMASS COMBUSTION",
      buffer: "> 5.4 km to nearest industrial facility"
    }
  ];

  facilities.forEach(fac => {
    const card = document.createElement("div");
    card.className = "ind-facility-card";

    card.innerHTML = `
      <div class="ind-facility-header">
        <div>
          <h4 class="ind-facility-title">${fac.name}</h4>
          <span class="ind-facility-zone">${fac.zone}</span>
        </div>
        <span class="ind-facility-type-badge">${fac.type.split(" ")[0]}</span>
      </div>
      <div class="ind-metrics-row">
        <div><span>COORDINATES</span><strong>${fac.coords}</strong></div>
        <div><span>ACTIVE THERMAL</span><strong class="frp-highlight">${fac.frp}</strong></div>
        <div><span>HAZARD PROFILE</span><strong>${fac.hazard}</strong></div>
        <div><span>PROXIMITY BUFFER</span><strong>${fac.buffer}</strong></div>
      </div>
      <button class="btn-locate-map" data-id="${fac.caseId}">
        🗺️ Inspect on Live GIS Map
      </button>
    `;

    card.querySelector(".btn-locate-map").addEventListener("click", () => {
      switchAppTab("map");
      openIncidentDetails(fac.caseId);
    });

    catalogEl.appendChild(card);
  });
}

// 4. Render Analytics Tab
function renderAnalyticsCharts() {
  // Classification Bars
  const classBarsEl = document.getElementById("analytics-class-bars");
  if (classBarsEl) {
    const classes = [
      { name: "Gas Flare / Flaring Stack", count: 1, pct: 14, color: "#ef4444" },
      { name: "Industrial Fire Candidate", count: 2, pct: 29, color: "#ff9500" },
      { name: "Mining / Coal Anomaly", count: 3, pct: 43, color: "#f59e0b" },
      { name: "Wildfire / Forest Burning", count: 1, pct: 14, color: "#10b981" }
    ];

    classBarsEl.innerHTML = classes.map(c => `
      <div class="stat-bar-item">
        <div class="stat-bar-header">
          <span>${c.name}</span>
          <strong style="color:${c.color}">${c.count} cases (${c.pct}%)</strong>
        </div>
        <div class="factor-bar-bg">
          <div class="factor-bar-fill" style="width:${c.pct}%; background:${c.color}"></div>
        </div>
      </div>
    `).join("");
  }

  // FRP Bars
  const frpBarsEl = document.getElementById("analytics-frp-bars");
  if (frpBarsEl) {
    const maxFRP = 50.0;
    frpBarsEl.innerHTML = incidents.map(inc => {
      const pct = Math.min(100, Math.round((inc.frp / maxFRP) * 100));
      return `
        <div class="stat-bar-item">
          <div class="stat-bar-header">
            <span>${inc.id.toUpperCase()}: ${inc.location_name.split("(")[0].trim()}</span>
            <strong class="frp-highlight">${inc.frp} MW</strong>
          </div>
          <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width:${pct}%; background:linear-gradient(90deg, #ff7700, #ef4444)"></div>
          </div>
        </div>
      `;
    }).join("");
  }

  // Threat Scores Bars
  const threatBarsEl = document.getElementById("analytics-threat-bars");
  if (threatBarsEl) {
    threatBarsEl.innerHTML = incidents.map(inc => `
      <div class="stat-bar-item">
        <div class="stat-bar-header">
          <span>RANK #${inc.priority_rank || 1} • ${inc.location_name.split("(")[0].trim()}</span>
          <strong style="color:${inc.risk_color || '#ff7700'}">${inc.risk_score || 50}/100 (${inc.risk_tier || 'MEDIUM'})</strong>
        </div>
        <div class="factor-bar-bg">
          <div class="factor-bar-fill" style="width:${inc.risk_score || 50}%; background:${inc.risk_color || '#ff7700'}"></div>
        </div>
      </div>
    `).join("");
  }
}



