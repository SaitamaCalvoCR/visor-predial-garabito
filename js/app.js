/* Visor Predial â€” Garabito
 * Leaflet + Leaflet.VectorGrid sobre teselas MVT (pg_tileserv / PostGIS, vista public.v_predios).
 * Predios coloreados por DISTRITO.
 */

// ===================== ConfiguraciÃ³n =====================
const TILE_BASE = "http://127.0.0.1:7800";
const LAYER_ID  = "public.v_predios";
const TILE_URL  = "tiles/{z}/{x}/{y}.pbf";
const CENTER    = [9.7077, -84.6152];   // [lat, lon] Garabito
const ZOOM      = 12;
const MAXZOOM   = 19;

// ===================== Mapa + capas base =====================
const map = L.map("map", { minZoom: 8, maxZoom: MAXZOOM, zoomControl: true }).setView(CENTER, ZOOM);

const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: MAXZOOM, attribution: "&copy; OpenStreetMap"
});
const carto = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: MAXZOOM, subdomains: "abcd", attribution: "&copy; OpenStreetMap, &copy; CARTO"
});

// Esri (sin API key). Instancias independientes para que SatÃ©lite e HÃ­brido no se pisen.
const IMG_URL    = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ROADS_URL  = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}";
const LABELS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const ESRI_ATTR  = "ImÃ¡genes &copy; Esri, Maxar, Earthstar Geographics";

const satelite = L.tileLayer(IMG_URL, { maxZoom: MAXZOOM, attribution: ESRI_ATTR });
const hibrido  = L.layerGroup([
  L.tileLayer(IMG_URL,    { maxZoom: MAXZOOM, attribution: ESRI_ATTR }),
  L.tileLayer(ROADS_URL,  { maxZoom: MAXZOOM }),
  L.tileLayer(LABELS_URL, { maxZoom: MAXZOOM })
]);

hibrido.addTo(map);   // base por defecto: hÃ­brido (se ve mejor)

// ===================== Coloreado por distrito =====================
const DISTRITOS = {
  "01": { nombre: "JacÃ³",      color: "#f5a623" },
  "02": { nombre: "TÃ¡rcoles",  color: "#57b4e6" },
  "03": { nombre: "Lagunillas", color: "#7bbe3e" }
};
const COLOR_OTRO = "#b8bcc2";

function distritoColor(d) {
  const k = (d == null) ? "" : ("" + d).trim();
  return (DISTRITOS[k] && DISTRITOS[k].color) || COLOR_OTRO;
}

function estiloPredio(props) {
  return {
    weight: 0.5,
    color: "#2b2f36",
    fill: true,
    fillColor: distritoColor(props.distrito),
    fillOpacity: 0.6
  };
}

const HIGHLIGHT = { weight: 2.5, color: "#111827", fill: true, fillColor: "#ffffff", fillOpacity: 0.35 };

// ===================== Capa de predios (vector tiles) =====================
let selectedId = null;

const predios = L.vectorGrid.protobuf(TILE_URL, {
  rendererFactory: L.svg.tile,   // SVG: clic/tap fiable (tambiÃ©n en mÃ³vil)
  interactive: true,
  maxNativeZoom: 16,
  getFeatureId: (f) => f.properties.fid,
  vectorTileLayerStyles: { [LAYER_ID]: estiloPredio }
}).addTo(map);

predios.on("click", (e) => {
  const p = e.layer.properties;
  if (selectedId !== null) predios.resetFeatureStyle(selectedId);
  selectedId = p.fid;
  predios.setFeatureStyle(selectedId, HIGHLIGHT);
  mostrarFicha(p);
  L.DomEvent.stop(e);
});

predios.on("load", () => setStatus("Listo âœ“", "#86efac"));
predios.on("tileerror", () => setStatus("âš  Sin teselas â€” Â¿pg_tileserv activo?", "#fca5a5"));

// ===================== Ficha del predio =====================
const intCR = (v) => Math.round(Number(v)).toLocaleString("es-CR");
const fmt = (v) => (v == null || v === "") ? "â€”" : v;

const CAMPOS = [
  ["area_m2", "Ãrea (mÂ²)", (v) => v == null ? "â€”" : intCR(v)],
  ["id_predial", "CÃ³digo predial"],
  ["numero_finca", "Finca"],
  ["valor_terreno_zh", "Valor terreno por zona homogÃ©nea", (v) => v == null ? "â€”" : intCR(v)],
  ["plano", "Plano"],
  ["frente_calle", "Frente a calle", (v) => v == 1 || v === true ? "SÃ­" : (v == 0 ? "No" : "â€”")],
  ["regularidad_geom", "Regularidad geomÃ©trica"],
  ["pendiente_media", "Pendiente media", (v) => v == null ? "â€”" : Number(v).toFixed(1) + "Â°"],
  ["inclinacion", "InclinaciÃ³n"]
];

function mostrarFicha(p) {
  const dist = DISTRITOS[("" + p.distrito).trim()];
  const subtitulo = dist ? `<div class="ficha-sub"><span class="dot" style="background:${dist.color}"></span>${dist.nombre}</div>` : "";
  const rows = CAMPOS.map(([k, label, f]) => {
    const val = f ? f(p[k]) : fmt(p[k]);
    return `<div class="row"><span class="k">${label}</span><span class="v">${val}</span></div>`;
  }).join("");
  document.getElementById("ficha-body").innerHTML = subtitulo + rows;
}

document.getElementById("ficha-close").addEventListener("click", () => {
  if (selectedId !== null) { predios.resetFeatureStyle(selectedId); selectedId = null; }
  document.getElementById("ficha-body").innerHTML =
    '<p class="hint">Haz clic en un predio para ver su informaciÃ³n.</p>';
});

// ===================== Leyenda (por distrito) =====================
function buildLegend() {
  const items = [
    ["JacÃ³", "#f5a623"], ["TÃ¡rcoles", "#57b4e6"], ["Lagunillas", "#7bbe3e"], ["Otro / sin dato", COLOR_OTRO]
  ];
  document.getElementById("legend").innerHTML =
    `<div class="lg-title">Distrito</div>` +
    items.map(([t, c]) => `<div class="lg-row"><span class="sw" style="background:${c}"></span>${t}</div>`).join("");
}

// ===================== Control de capas + estado =====================
L.control.layers(
  { "HÃ­brido": hibrido, "SatÃ©lite": satelite, "OpenStreetMap": osm, "Claro (Carto)": carto },
  { "Predios": predios },
  { collapsed: false }
).addTo(map);

function setStatus(text, color) {
  const el = document.getElementById("status");
  el.textContent = text;
  if (color) el.style.color = color;
}

buildLegend();
setStatus("conectandoâ€¦");

