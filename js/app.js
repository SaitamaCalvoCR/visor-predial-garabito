/* Visor Predial - Garabito
 * Leaflet + Leaflet.VectorGrid sobre teselas MVT.
 * Paneles de calidad calculados desde data/predios_index.json.
 */

// ===================== Configuración =====================
const TILE_BASE = "http://127.0.0.1:7800";
const LAYER_ID = "public.v_predios";
const TILE_URL = "tiles/{z}/{x}/{y}.pbf";
const DATA_URL = "data/predios_index.json";
const AUX_VECTOR_MANIFEST_URL = "layers/capas_auxiliares_manifest.json";
const AUX_RASTER_MANIFEST_URL = "layers/rasters/rasters_manifest.json";
const CENTER = [9.7077, -84.6152];
const ZOOM = 12;
const MAXZOOM = 19;
const HIGH_SLOPE = 25;
const SMALL_AREA = 25;

const DISTRITOS = {
  "01": { nombre: "Jacó", color: "#f59e0b" },
  "02": { nombre: "Tárcoles", color: "#0ea5e9" },
  "03": { nombre: "Lagunillas", color: "#65a30d" }
};
const COLOR_OTRO = "#94a3b8";
const PRIORITY_COLORS = {
  Alta: "#dc2626",
  Media: "#d97706",
  Baja: "#2563eb",
  "Sin alertas": "#16a34a"
};
const QUALITY_COLORS = {
  Completo: "#16a34a",
  Incompleto: "#d97706",
  "Requiere revisión": "#dc2626"
};

// ===================== Estado global =====================
let records = [];
let recordsByFid = new Map();
let duplicateMaps = {};
let selectedId = null;
let activeBaseKey = "hibrido";
let activeStyleMode = "district";
let layerOpacity = 0.6;
let filteredProblems = [];
let auxLayerDefs = new Map();
let auxLayers = new Map();
let activeAuxLayers = new Set();

// ===================== Utilidades =====================
const numberCR = new Intl.NumberFormat("es-CR", { maximumFractionDigits: 0 });
const decimalCR = new Intl.NumberFormat("es-CR", { maximumFractionDigits: 1 });
const currencyCR = new Intl.NumberFormat("es-CR", {
  maximumFractionDigits: 0,
  style: "currency",
  currency: "CRC"
});

function $(id) {
  return document.getElementById(id);
}

function hasValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function asKey(value) {
  return hasValue(value) ? String(value).trim() : "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmt(value, fallback = "Sin dato") {
  return hasValue(value) ? escapeHtml(value) : fallback;
}

function fmtNumber(value, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Sin dato";
  return `${numberCR.format(n)}${suffix}`;
}

function fmtDecimal(value, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Sin dato";
  return `${decimalCR.format(n)}${suffix}`;
}

function fmtMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Sin dato";
  return currencyCR.format(n).replace("CRC", "₡").trim();
}

function distritoInfo(code) {
  const key = asKey(code).padStart(2, "0");
  return DISTRITOS[key] || { nombre: "Otro / sin dato", color: COLOR_OTRO };
}

function normalizeRecord(source = {}) {
  const fid = source.fid ?? source.id;
  const record = {
    ...source,
    fid,
    distrito_nombre: source.distrito_nombre || distritoInfo(source.distrito).nombre
  };
  if (!record.issues) record.issues = detectIssues(record).issues;
  if (!record.priority) record.priority = classifyPriority(record).priority;
  if (!record.estado) record.estado = classifyPriority(record).estado;
  return record;
}

function mergeWithIndex(props = {}) {
  const fid = props.fid ?? props.id;
  const indexed = recordsByFid.get(String(fid));
  return indexed ? { ...indexed, ...props, issues: indexed.issues, priority: indexed.priority, estado: indexed.estado } : normalizeRecord(props);
}

function countByValue(items, field) {
  const counts = new Map();
  items.forEach((item) => {
    const key = asKey(item[field]);
    if (!key) return;
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
}

function isDuplicate(record, field) {
  const key = asKey(record[field]);
  return key && duplicateMaps[field]?.get(key) > 1;
}

function classifyPriority(record) {
  let score = 0;
  const issues = detectIssues(record).issues;
  issues.forEach((issue) => {
    if (issue === "Sin código predial" || issue === "Sin finca") score += 5;
    else if (issue.includes("duplicad")) score += 4;
    else if (issue === "Sin plano" || issue === "Sin distrito") score += 3;
    else if (issue === "Pendiente alta" || issue === "Área sospechosa" || issue === "Geometría irregular") score += 2;
    else score += 1;
  });
  let priority = "Sin alertas";
  if (score >= 7) priority = "Alta";
  else if (score >= 3) priority = "Media";
  else if (score > 0) priority = "Baja";
  const estado = score >= 7 || issues.length >= 3 ? "Requiere revisión" : score > 0 ? "Incompleto" : "Completo";
  return { priority, score, estado };
}

function detectIssues(record) {
  const issues = [];
  if (!hasValue(record.id_predial)) issues.push("Sin código predial");
  else if (isDuplicate(record, "id_predial")) issues.push("Código predial duplicado");

  if (!hasValue(record.numero_finca)) issues.push("Sin finca");
  else if (isDuplicate(record, "numero_finca")) issues.push("Finca duplicada");

  if (!hasValue(record.plano)) issues.push("Sin plano");
  else if (isDuplicate(record, "plano")) issues.push("Plano duplicado");

  const area = Number(record.area_m2);
  if (!Number.isFinite(area) || area <= 0 || area < SMALL_AREA) issues.push("Área sospechosa");

  if (!hasValue(record.distrito)) issues.push("Sin distrito");

  const slope = Number(record.pendiente_media);
  if (Number.isFinite(slope) && slope >= HIGH_SLOPE) issues.push("Pendiente alta");

  const regularidad = String(record.regularidad_geom || "").toLowerCase();
  if (regularidad.includes("irregular")) issues.push("Geometría irregular");

  if (record.frente_calle === false || record.frente_calle === 0) issues.push("Sin frente a calle");

  return { issues };
}

function enrichRecords(rawRecords) {
  duplicateMaps = {
    id_predial: countByValue(rawRecords, "id_predial"),
    numero_finca: countByValue(rawRecords, "numero_finca"),
    plano: countByValue(rawRecords, "plano")
  };
  return rawRecords.map((record) => {
    const normalized = normalizeRecord(record);
    const detected = detectIssues(normalized).issues;
    const classified = classifyPriority({ ...normalized, issues: detected });
    return {
      ...normalized,
      issues: record.issues || detected,
      issue_score: record.issue_score ?? classified.score,
      priority: record.priority || classified.priority,
      estado: record.estado || classified.estado
    };
  });
}

function setStatus(text, color) {
  const el = $("status");
  if (!el) return;
  el.textContent = text;
  if (color) el.style.color = color;
}

// ===================== Mapa + capas base =====================
const map = L.map("map", { minZoom: 8, maxZoom: MAXZOOM, zoomControl: true }).setView(CENTER, ZOOM);
map.createPane("aux-raster");
map.getPane("aux-raster").style.zIndex = 360;
map.createPane("aux-vector");
map.getPane("aux-vector").style.zIndex = 620;

const baseLayers = {
  osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: MAXZOOM,
    attribution: "&copy; OpenStreetMap"
  }),
  carto: L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    maxZoom: MAXZOOM,
    subdomains: "abcd",
    attribution: "&copy; OpenStreetMap, &copy; CARTO"
  }),
  satelite: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: MAXZOOM,
    attribution: "Imágenes &copy; Esri, Maxar, Earthstar Geographics"
  }),
  hibrido: L.layerGroup([
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: MAXZOOM,
      attribution: "Imágenes &copy; Esri, Maxar, Earthstar Geographics"
    }),
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: MAXZOOM
    }),
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: MAXZOOM
    })
  ])
};
baseLayers.hibrido.addTo(map);

function distritoColor(value) {
  return distritoInfo(value).color;
}

function qualityColor(record) {
  return QUALITY_COLORS[record.estado] || QUALITY_COLORS.Incompleto;
}

function slopeColor(record) {
  const slope = Number(record.pendiente_media);
  if (!Number.isFinite(slope)) return "#94a3b8";
  if (slope >= 35) return "#dc2626";
  if (slope >= HIGH_SLOPE) return "#f97316";
  if (slope >= 15) return "#eab308";
  return "#16a34a";
}

function featureFill(props) {
  const record = mergeWithIndex(props);
  if (activeStyleMode === "quality") return qualityColor(record);
  if (activeStyleMode === "priority") return PRIORITY_COLORS[record.priority] || PRIORITY_COLORS["Sin alertas"];
  if (activeStyleMode === "slope") return slopeColor(record);
  return distritoColor(record.distrito);
}

function estiloPredio(props) {
  return {
    weight: 0.55,
    color: "#1f2937",
    fill: true,
    fillColor: featureFill(props || {}),
    fillOpacity: layerOpacity
  };
}

const HIGHLIGHT = {
  weight: 2.8,
  color: "#0f172a",
  fill: true,
  fillColor: "#ffffff",
  fillOpacity: 0.45
};

const predios = L.vectorGrid.protobuf(TILE_URL, {
  rendererFactory: L.svg.tile,
  interactive: true,
  maxNativeZoom: 16,
  getFeatureId: (feature) => feature.properties.fid,
  vectorTileLayerStyles: { [LAYER_ID]: estiloPredio }
}).addTo(map);

predios.on("click", (event) => {
  const record = mergeWithIndex(event.layer.properties);
  selectRecord(record, { centerMap: false });
  L.DomEvent.stop(event);
});
predios.on("load", () => setStatus(records.length ? "Listo" : "Cargando datos", "#86efac"));
predios.on("tileerror", () => setStatus("Sin teselas", "#fca5a5"));

function redrawPredios() {
  if (typeof predios.redraw === "function") {
    predios.redraw();
  } else if (map.hasLayer(predios)) {
    map.removeLayer(predios);
    predios.addTo(map);
  }
  if (selectedId !== null) predios.setFeatureStyle(selectedId, HIGHLIGHT);
}

// ===================== Capas auxiliares SNIT y análisis =====================
const AUX_VECTOR_LEGENDS = {
  roads: [
    ["Ruta nacional", "#e11d48", 4.2, ""],
    ["Camino", "#f59e0b", 2.5, ""],
    ["Vereda", "#7c3aed", 1.8, "4 4"],
    ["Puente", "#111827", 5.0, "2 3"],
    ["Vía local", "#475569", 2.0, ""]
  ],
  drainage: [["Red de drenaje", "#0284c7", 2.0, "6 4"]]
};

function setAuxStatus(text, tone = "") {
  const el = $("aux-layer-status");
  if (!el) return;
  el.textContent = text;
  el.className = tone ? `tone-${tone}` : "";
}

async function fetchOptionalJson(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    console.warn(`No se pudo cargar ${url}`, error);
    return null;
  }
}

function registerAuxDefinitions(vectorManifest, rasterManifest) {
  auxLayerDefs = new Map();
  (vectorManifest?.vectors || []).forEach((item) => {
    auxLayerDefs.set(item.id, {
      ...item,
      type: "vector",
      opacity: item.id === "drainage" ? 0.85 : 0.95
    });
  });
  (rasterManifest?.rasters || []).forEach((item) => {
    auxLayerDefs.set(item.id, {
      ...item,
      type: "raster",
      opacity: Number(item.opacity || 0.6)
    });
  });
}

function renderAuxLayerControls() {
  const list = $("aux-layer-list");
  if (!list) return;
  const defs = [...auxLayerDefs.values()];
  if (!defs.length) {
    list.innerHTML = `<div class="empty-state">No encontré capas auxiliares. Ejecuta el script de preparación para generarlas.</div>`;
    setAuxStatus("sin capas", "warn");
    return;
  }
  list.innerHTML = defs.map((def) => {
    const detail = def.type === "vector"
      ? `${numberCR.format(def.features || 0)} elementos`
      : "raster georreferenciado";
    const value = Math.round(Number(def.opacity || 0.65) * 100);
    return `
      <div class="aux-layer-item">
        <label class="check-row aux-check">
          <input type="checkbox" data-aux-toggle="${escapeHtml(def.id)}" />
          <span><strong>${escapeHtml(def.title)}</strong><small>${escapeHtml(detail)}</small></span>
        </label>
        <label class="aux-opacity">
          <span>Opacidad</span>
          <input type="range" min="15" max="100" value="${value}" data-aux-opacity="${escapeHtml(def.id)}" />
        </label>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-aux-toggle]").forEach((input) => {
    input.addEventListener("change", (event) => toggleAuxLayer(event.target.dataset.auxToggle, event.target.checked));
  });
  list.querySelectorAll("[data-aux-opacity]").forEach((input) => {
    input.addEventListener("input", (event) => setAuxLayerOpacity(event.target.dataset.auxOpacity, Number(event.target.value) / 100));
  });
  setAuxStatus(`${defs.length} disponibles`, "ok");
}

function auxFeatureStyle(feature, def) {
  const props = feature?.properties || {};
  const width = Number(props.stroke_width || (def.id === "drainage" ? 2 : 2.4));
  return {
    color: props.stroke || (def.id === "drainage" ? "#0284c7" : "#475569"),
    weight: width,
    opacity: Number(def.opacity || 0.9),
    dashArray: props.stroke_dasharray || "",
    lineCap: "round",
    lineJoin: "round"
  };
}

function auxPopup(feature, def) {
  const p = feature?.properties || {};
  if (def.id === "drainage") {
    return `<strong>Drenaje SNIT</strong><br>${fmt(p.nombre || p.categoria || "Red de drenaje")}`;
  }
  const route = hasValue(p.num_ruta) ? `Ruta ${escapeHtml(p.num_ruta)}` : fmt(p.via_clase || "Vía");
  const rows = [
    ["Clase", fmt(p.via_clase)],
    ["Categoría", fmt(p.categoria)],
    ["Nombre", fmt(p.nombre)],
    ["Longitud", fmtNumber(p.longitud_m, " m")]
  ];
  return `<strong>${route}</strong>` + rows.map(([label, value]) => `<br><span>${escapeHtml(label)}:</span> ${value}`).join("");
}

async function ensureAuxLayer(id) {
  if (auxLayers.has(id)) return auxLayers.get(id);
  const def = auxLayerDefs.get(id);
  if (!def) return null;

  if (def.type === "raster") {
    const layer = L.imageOverlay(def.url, def.bounds, {
      pane: "aux-raster",
      opacity: Number(def.opacity || 0.6),
      interactive: false
    });
    auxLayers.set(id, layer);
    return layer;
  }

  const response = await fetch(def.url, { cache: "no-store" });
  if (!response.ok) throw new Error(`No se pudo cargar ${def.url}`);
  const data = await response.json();
  const layer = L.geoJSON(data, {
    pane: "aux-vector",
    style: (feature) => auxFeatureStyle(feature, def),
    onEachFeature: (feature, featureLayer) => featureLayer.bindPopup(auxPopup(feature, def))
  });
  auxLayers.set(id, layer);
  return layer;
}

async function toggleAuxLayer(id, enabled) {
  const def = auxLayerDefs.get(id);
  if (!def) return;
  try {
    if (enabled) {
      setAuxStatus(`cargando ${def.title.toLowerCase()}...`, "warn");
      const layer = await ensureAuxLayer(id);
      if (!layer) return;
      layer.addTo(map);
      if (typeof layer.bringToFront === "function") layer.bringToFront();
      activeAuxLayers.add(id);
    } else {
      const layer = auxLayers.get(id);
      if (layer && map.hasLayer(layer)) map.removeLayer(layer);
      activeAuxLayers.delete(id);
    }
    setAuxStatus(`${activeAuxLayers.size || auxLayerDefs.size} ${activeAuxLayers.size ? "activas" : "disponibles"}`, activeAuxLayers.size ? "ok" : "");
    buildLegend();
  } catch (error) {
    console.error(error);
    setAuxStatus(`error en ${def.title}`, "danger");
  }
}

function setAuxLayerOpacity(id, opacity) {
  const def = auxLayerDefs.get(id);
  if (!def) return;
  def.opacity = opacity;
  const layer = auxLayers.get(id);
  if (!layer) return;
  if (typeof layer.setOpacity === "function") {
    layer.setOpacity(opacity);
  } else if (typeof layer.setStyle === "function") {
    layer.setStyle((feature) => auxFeatureStyle(feature, def));
  }
  buildLegend();
}

async function loadAuxiliaryLayers() {
  const [vectorManifest, rasterManifest] = await Promise.all([
    fetchOptionalJson(AUX_VECTOR_MANIFEST_URL),
    fetchOptionalJson(AUX_RASTER_MANIFEST_URL)
  ]);
  registerAuxDefinitions(vectorManifest, rasterManifest);
  renderAuxLayerControls();
}

// ===================== Render de dashboard =====================
function computeStats(items) {
  const duplicatedIds = new Set();
  items.forEach((record) => {
    if (isDuplicate(record, "id_predial") || isDuplicate(record, "numero_finca") || isDuplicate(record, "plano")) {
      duplicatedIds.add(String(record.fid));
    }
  });
  return {
    total: items.length,
    missingCode: items.filter((r) => !hasValue(r.id_predial)).length,
    missingFinca: items.filter((r) => !hasValue(r.numero_finca)).length,
    missingPlano: items.filter((r) => !hasValue(r.plano)).length,
    duplicates: duplicatedIds.size,
    highSlope: items.filter((r) => Number(r.pendiente_media) >= HIGH_SLOPE).length,
    complete: items.filter((r) => r.estado === "Completo").length,
    review: items.filter((r) => r.estado === "Requiere revisión").length
  };
}

function renderDashboard(meta = {}) {
  const stats = computeStats(records);
  $("metric-total-top").textContent = numberCR.format(stats.total);
  $("metric-updated-top").textContent = meta.generated_at ? new Date(meta.generated_at).toLocaleDateString("es-CR") : "Sin dato";

  const cards = [
    ["Total de predios", stats.total, "Cantidad general de predios cargados.", "good"],
    ["Sin código predial", stats.missingCode, "Registros sin identificador predial.", stats.missingCode ? "critical" : "good"],
    ["Sin finca", stats.missingFinca, "Registros sin número de finca.", stats.missingFinca ? "critical" : "good"],
    ["Sin plano", stats.missingPlano, "Predios sin plano catastrado asociado.", stats.missingPlano ? "warning" : "good"],
    ["Duplicados", stats.duplicates, "Código predial, finca o plano repetido.", stats.duplicates ? "critical" : "good"],
    ["Pendiente alta", stats.highSlope, `Pendiente media igual o mayor a ${HIGH_SLOPE}°`, stats.highSlope ? "warning" : "good"]
  ];
  $("quality-cards").innerHTML = cards.map(([label, value, help, tone]) => `
    <article class="stat-card ${tone}" title="${escapeHtml(help)}">
      <p class="stat-label">${escapeHtml(label)}</p>
      <p class="stat-value">${numberCR.format(value)}</p>
      <p class="stat-help">${escapeHtml(help)}</p>
    </article>
  `).join("");

  const completePct = stats.total ? Math.round((stats.complete / stats.total) * 100) : 0;
  $("completeness-donut").style.setProperty("--complete", completePct);
  $("completeness-label").textContent = `${completePct}% completos`;
  $("completeness-legend").innerHTML = `
    <div class="legend-row"><span>Completos</span><strong>${numberCR.format(stats.complete)}</strong></div>
    <div class="legend-row"><span>Incompletos</span><strong>${numberCR.format(stats.total - stats.complete - stats.review)}</strong></div>
    <div class="legend-row"><span>Requieren revisión</span><strong>${numberCR.format(stats.review)}</strong></div>
  `;

  const issueCounts = new Map();
  records.forEach((record) => record.issues.forEach((issue) => issueCounts.set(issue, (issueCounts.get(issue) || 0) + 1)));
  const ranking = [...issueCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7);
  $("issue-ranking").innerHTML = ranking.length ? ranking.map(([issue, count]) => `
    <div class="rank-row"><span>${escapeHtml(issue)}</span><strong>${numberCR.format(count)}</strong></div>
  `).join("") : `<div class="empty-state">No se detectaron alertas con los criterios actuales.</div>`;
}

// ===================== Tabla de problemas =====================
function populateFilters() {
  const districtOptions = ["Todos", ...new Set(records.map((r) => r.distrito_nombre || "Otro / sin dato"))];
  $("problem-district").innerHTML = districtOptions.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");

  const issueOptions = ["Todos", ...new Set(records.flatMap((r) => r.issues))].sort((a, b) => a.localeCompare(b, "es"));
  $("problem-type").innerHTML = issueOptions.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");

  const priorities = ["Todas", "Alta", "Media", "Baja"];
  $("problem-priority").innerHTML = priorities.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
}

function getProblemRows() {
  const query = $("problem-search").value.trim().toLowerCase();
  const district = $("problem-district").value;
  const issue = $("problem-type").value;
  const priority = $("problem-priority").value;

  return records.filter((record) => {
    if (!record.issues.length) return false;
    if (district !== "Todos" && record.distrito_nombre !== district) return false;
    if (issue !== "Todos" && !record.issues.includes(issue)) return false;
    if (priority !== "Todas" && record.priority !== priority) return false;
    if (!query) return true;
    return [record.id_predial, record.numero_finca, record.plano, record.distrito_nombre]
      .some((value) => String(value || "").toLowerCase().includes(query));
  }).sort((a, b) => (b.issue_score || 0) - (a.issue_score || 0));
}

function renderProblemsTable() {
  filteredProblems = getProblemRows();
  const maxRows = 350;
  const shown = filteredProblems.slice(0, maxRows);
  $("problem-count").textContent = `${numberCR.format(filteredProblems.length)} predios con problemas${filteredProblems.length > maxRows ? ` (${maxRows} visibles)` : ""}`;
  const tbody = $("problem-table").querySelector("tbody");
  tbody.innerHTML = shown.length ? shown.map((record) => `
    <tr data-fid="${escapeHtml(record.fid)}">
      <td>${fmt(record.id_predial)}</td>
      <td>${fmt(record.numero_finca)}</td>
      <td>${fmt(record.plano)}</td>
      <td>${fmt(record.distrito_nombre)}</td>
      <td class="num">${fmtNumber(record.area_m2)}</td>
      <td>${record.issues.map(escapeHtml).join(", ")}</td>
      <td>${priorityPill(record.priority)}</td>
    </tr>
  `).join("") : `<tr><td colspan="7"><div class="empty-state">No hay registros para los filtros activos.</div></td></tr>`;

  tbody.querySelectorAll("tr[data-fid]").forEach((row) => {
    row.addEventListener("click", () => {
      const record = recordsByFid.get(row.dataset.fid);
      if (record) selectRecord(record, { centerMap: true });
    });
  });
}

function priorityPill(priority) {
  const tone = priority === "Alta" ? "danger" : priority === "Media" ? "warn" : priority === "Baja" ? "info" : "ok";
  return `<span class="chip ${tone}">${escapeHtml(priority)}</span>`;
}

function exportProblemsCsv() {
  const header = ["Código predial", "Finca", "Plano", "Distrito", "Área m²", "Problema detectado", "Prioridad"];
  const rows = filteredProblems.map((record) => [
    record.id_predial || "",
    record.numero_finca || "",
    record.plano || "",
    record.distrito_nombre || "",
    Number(record.area_m2 || 0),
    record.issues.join("; "),
    record.priority || ""
  ]);
  const csv = [header, ...rows].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "predios_con_problemas.csv";
  link.click();
  URL.revokeObjectURL(url);
}

// ===================== Estadísticas por distrito =====================
function groupByDistrict() {
  const groups = new Map();
  records.forEach((record) => {
    const name = record.distrito_nombre || "Otro / sin dato";
    if (!groups.has(name)) {
      groups.set(name, {
        name,
        color: distritoInfo(record.distrito).color,
        count: 0,
        area: 0,
        areaCount: 0,
        missingFinca: 0,
        missingCode: 0,
        missingPlano: 0,
        highSlope: 0,
        valueSum: 0,
        valueCount: 0,
        problems: 0
      });
    }
    const g = groups.get(name);
    g.count += 1;
    const area = Number(record.area_m2);
    if (Number.isFinite(area)) {
      g.area += area;
      g.areaCount += 1;
    }
    if (!hasValue(record.numero_finca)) g.missingFinca += 1;
    if (!hasValue(record.id_predial)) g.missingCode += 1;
    if (!hasValue(record.plano)) g.missingPlano += 1;
    if (Number(record.pendiente_media) >= HIGH_SLOPE) g.highSlope += 1;
    const value = Number(record.valor_terreno_zh);
    if (Number.isFinite(value)) {
      g.valueSum += value;
      g.valueCount += 1;
    }
    if (record.issues.length) g.problems += 1;
  });
  return [...groups.values()].sort((a, b) => b.count - a.count);
}

function renderDistrictStats() {
  const groups = groupByDistrict();
  const max = Math.max(...groups.map((g) => g.count), 1);
  $("district-bars").innerHTML = groups.map((g) => `
    <div class="bar-row">
      <strong>${escapeHtml(g.name)}</strong>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.max(4, (g.count / max) * 100)}%;background:${g.color}"></span></span>
      <span>${numberCR.format(g.count)}</span>
    </div>
  `).join("");

  $("district-table").querySelector("tbody").innerHTML = groups.map((g) => `
    <tr>
      <td>${escapeHtml(g.name)}</td>
      <td class="num">${numberCR.format(g.count)}</td>
      <td class="num">${fmtNumber(g.area, " m²")}</td>
      <td class="num">${g.areaCount ? fmtNumber(g.area / g.areaCount, " m²") : "Sin dato"}</td>
      <td class="num">${numberCR.format(g.missingFinca)}</td>
      <td class="num">${numberCR.format(g.missingCode)}</td>
      <td class="num">${numberCR.format(g.missingPlano)}</td>
      <td class="num">${numberCR.format(g.highSlope)}</td>
      <td class="num">${g.valueCount ? fmtMoney(g.valueSum / g.valueCount) : "Sin dato"}</td>
    </tr>
  `).join("");
}

// ===================== Búsqueda, capas y leyenda =====================
function renderSearchResults() {
  const query = $("global-search").value.trim().toLowerCase();
  if (!query) {
    $("search-results").innerHTML = `<div class="empty-state">Escribe un código, finca, plano o distrito para buscar.</div>`;
    return;
  }
  const results = records.filter((record) => [record.id_predial, record.numero_finca, record.plano, record.distrito_nombre]
    .some((value) => String(value || "").toLowerCase().includes(query))).slice(0, 12);
  $("search-results").innerHTML = results.length ? results.map((record) => `
    <button class="search-row" type="button" data-fid="${escapeHtml(record.fid)}">
      <span><strong>${fmt(record.id_predial)}</strong><br>${fmt(record.distrito_nombre)} · finca ${fmt(record.numero_finca)}</span>
      <span>${priorityPill(record.priority)}</span>
    </button>
  `).join("") : `<div class="empty-state">No encontré predios con ese texto.</div>`;

  $("search-results").querySelectorAll("[data-fid]").forEach((button) => {
    button.addEventListener("click", () => {
      const record = recordsByFid.get(button.dataset.fid);
      if (record) selectRecord(record, { centerMap: true });
    });
  });
}

function switchBaseLayer(key) {
  if (key === activeBaseKey) return;
  map.removeLayer(baseLayers[activeBaseKey]);
  activeBaseKey = key;
  baseLayers[activeBaseKey].addTo(map);
}

function buildLegend() {
  let title = "Distrito";
  let items = [
    ["Jacó", DISTRITOS["01"].color],
    ["Tárcoles", DISTRITOS["02"].color],
    ["Lagunillas", DISTRITOS["03"].color],
    ["Otro / sin dato", COLOR_OTRO]
  ];
  if (activeStyleMode === "quality") {
    title = "Calidad de datos";
    items = Object.entries(QUALITY_COLORS);
  } else if (activeStyleMode === "priority") {
    title = "Prioridad";
    items = Object.entries(PRIORITY_COLORS);
  } else if (activeStyleMode === "slope") {
    title = "Pendiente";
    items = [["< 15°", "#16a34a"], ["15° - 24,9°", "#eab308"], ["25° - 34,9°", "#f97316"], [">= 35°", "#dc2626"], ["Sin dato", "#94a3b8"]];
  }
  let html = `<div class="lg-title">${escapeHtml(title)}</div>` +
    items.map(([label, color]) => `<div class="lg-row"><span class="sw" style="background:${color}"></span>${escapeHtml(label)}</div>`).join("");

  activeAuxLayers.forEach((id) => {
    const def = auxLayerDefs.get(id);
    if (!def) return;
    const vectorItems = AUX_VECTOR_LEGENDS[id];
    html += `<div class="lg-title aux-title">${escapeHtml(def.title)}</div>`;
    if (vectorItems) {
      html += vectorItems.map(([label, color, weight, dash]) => `
        <div class="lg-row"><span class="sw line-sw" style="border-top:${weight}px ${dash ? "dashed" : "solid"} ${color}"></span>${escapeHtml(label)}</div>
      `).join("");
    } else if (Array.isArray(def.legend)) {
      html += def.legend.map(([label, color]) => `<div class="lg-row"><span class="sw" style="background:${color}"></span>${escapeHtml(label)}</div>`).join("");
    }
  });
  $("legend").innerHTML = html;
}

// ===================== Ficha del predio =====================
function statusPill(estado) {
  const tone = estado === "Completo" ? "ok" : estado === "Requiere revisión" ? "danger" : "warn";
  return `<span class="status-pill ${tone}">Estado del predio: ${escapeHtml(estado)}</span>`;
}

function fieldRow(label, value) {
  return `<div class="field-row"><span class="field-label">${escapeHtml(label)}</span><span class="field-value">${value}</span></div>`;
}

function renderFicha(record) {
  const enriched = mergeWithIndex(record);
  const issues = enriched.issues || [];
  const estimatedValue = Number(enriched.area_m2) * Number(enriched.valor_terreno_zh);
  $("ficha-body").innerHTML = `
    <div class="ficha-section">
      ${statusPill(enriched.estado)}
    </div>
    <div class="ficha-section">
      <h3>Identificación</h3>
      ${fieldRow("Código predial", fmt(enriched.id_predial))}
      ${fieldRow("Finca", fmt(enriched.numero_finca))}
      ${fieldRow("Plano", fmt(enriched.plano))}
      ${fieldRow("Distrito", fmt(enriched.distrito_nombre))}
    </div>
    <div class="ficha-section">
      <h3>Características físicas</h3>
      ${fieldRow("Área", fmtNumber(enriched.area_m2, " m²"))}
      ${fieldRow("Frente a calle", enriched.frente_calle === true || enriched.frente_calle === 1 ? "Sí" : enriched.frente_calle === false || enriched.frente_calle === 0 ? "No" : "Sin dato")}
      ${fieldRow("Regularidad geométrica", fmt(enriched.regularidad_geom))}
      ${fieldRow("Pendiente media", fmtDecimal(enriched.pendiente_media, "°"))}
      ${fieldRow("Inclinación", fmt(enriched.inclinacion))}
    </div>
    <div class="ficha-section">
      <h3>Valoración</h3>
      ${fieldRow("Zona homogénea", fmt(enriched.zona_homogenea))}
      ${fieldRow("Valor terreno por zona homogénea", fmtMoney(enriched.valor_terreno_zh))}
      ${fieldRow("Valor estimado del predio", Number.isFinite(estimatedValue) ? fmtMoney(estimatedValue) : "Sin dato")}
      ${fieldRow("Riesgo", fmt(enriched.riesgo))}
      ${fieldRow("Prioridad fiscalización", fmt(enriched.prioridad_fiscalizacion))}
    </div>
    <div class="ficha-section">
      <h3>Alertas</h3>
      <div class="chip-list">
        ${issues.length ? issues.map((issue) => `<span class="chip ${issue.includes("duplicad") || issue.includes("Sin código") || issue.includes("Sin finca") ? "danger" : "warn"}">${escapeHtml(issue)}</span>`).join("") : `<span class="chip ok">Sin alertas</span>`}
      </div>
    </div>
  `;
}

function selectRecord(record, options = {}) {
  const fid = record?.fid;
  if (!hasValue(fid)) return;
  if (selectedId !== null) predios.resetFeatureStyle(selectedId);
  selectedId = fid;
  predios.setFeatureStyle(selectedId, HIGHLIGHT);
  renderFicha(record);
  if (options.centerMap && Array.isArray(record.center)) {
    map.setView(record.center, Math.max(map.getZoom(), 17), { animate: true });
  }
}

function clearSelection() {
  if (selectedId !== null) {
    predios.resetFeatureStyle(selectedId);
    selectedId = null;
  }
  $("ficha-body").innerHTML = `<p class="hint">Haz clic en un predio o selecciona un registro de la tabla.</p>`;
}

// ===================== Eventos de UI =====================
function bindUi() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      document.querySelectorAll(".module-view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      $(`view-${button.dataset.view}`).classList.add("active");
    });
  });

  $("left-panel-toggle").addEventListener("click", () => {
    $("left-panel").classList.toggle("collapsed");
    setTimeout(() => map.invalidateSize(), 260);
  });
  $("ficha-close").addEventListener("click", clearSelection);

  ["problem-search", "problem-district", "problem-type", "problem-priority"].forEach((id) => {
    $(id).addEventListener("input", renderProblemsTable);
    $(id).addEventListener("change", renderProblemsTable);
  });
  $("clear-filters").addEventListener("click", () => {
    $("problem-search").value = "";
    $("problem-district").value = "Todos";
    $("problem-type").value = "Todos";
    $("problem-priority").value = "Todas";
    renderProblemsTable();
  });
  $("export-csv").addEventListener("click", exportProblemsCsv);
  $("global-search").addEventListener("input", renderSearchResults);
  $("base-layer-select").addEventListener("change", (event) => switchBaseLayer(event.target.value));
  $("predios-toggle").addEventListener("change", (event) => {
    if (event.target.checked) predios.addTo(map);
    else map.removeLayer(predios);
  });
  $("style-mode").addEventListener("change", (event) => {
    activeStyleMode = event.target.value;
    buildLegend();
    redrawPredios();
  });
  $("opacity-range").addEventListener("input", (event) => {
    layerOpacity = Number(event.target.value) / 100;
    redrawPredios();
  });
}

// ===================== Inicialización =====================
async function loadDataIndex() {
  setStatus("Cargando índice", "#fde68a");
  const response = await fetch(DATA_URL, { cache: "no-store" });
  if (!response.ok) throw new Error(`No se pudo cargar ${DATA_URL}`);
  const payload = await response.json();
  records = enrichRecords(payload.records || []);
  recordsByFid = new Map(records.map((record) => [String(record.fid), record]));
  renderDashboard(payload);
  populateFilters();
  renderProblemsTable();
  renderDistrictStats();
  renderSearchResults();
  buildLegend();
  redrawPredios();
  setStatus("Listo", "#86efac");
}

bindUi();
buildLegend();
setStatus("conectando...");
loadAuxiliaryLayers().catch((error) => {
  console.error(error);
  setAuxStatus("error al cargar", "danger");
});
loadDataIndex().catch((error) => {
  console.error(error);
  setStatus("Mapa sin índice", "#fca5a5");
  $("quality-cards").innerHTML = `<div class="empty-state">No se pudo cargar el índice de predios. El mapa puede seguir funcionando, pero los paneles de calidad no estarán disponibles.</div>`;
});

