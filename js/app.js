/* Visor Predial — Garabito
 * Leaflet + Leaflet.VectorGrid sobre teselas MVT (pg_tileserv / PostGIS, vista public.v_predios).
 * Predios coloreados por DISTRITO.
 */

// ===================== Configuración =====================
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

// Esri (sin API key). Instancias independientes para que Satélite e Híbrido no se pisen.
const IMG_URL    = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ROADS_URL  = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}";
const LABELS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const ESRI_ATTR  = "Imágenes &copy; Esri, Maxar, Earthstar Geographics";

const satelite = L.tileLayer(IMG_URL, { maxZoom: MAXZOOM, attribution: ESRI_ATTR });
const hibrido  = L.layerGroup([
  L.tileLayer(IMG_URL,    { maxZoom: MAXZOOM, attribution: ESRI_ATTR }),
  L.tileLayer(ROADS_URL,  { maxZoom: MAXZOOM }),
  L.tileLayer(LABELS_URL, { maxZoom: MAXZOOM })
]);

hibrido.addTo(map);   // base por defecto: híbrido (se ve mejor)

// ===================== Coloreado por distrito =====================
const DISTRITOS = {
  "01": { nombre: "Jacó",      color: "#f5a623" },
  "02": { nombre: "Tárcoles",  color: "#57b4e6" },
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
  rendererFactory: L.svg.tile,   // SVG: clic/tap fiable (también en móvil)
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

predios.on("load", () => setStatus("Listo ✓", "#86efac"));
predios.on("tileerror", () => setStatus("⚠ Sin teselas — ¿pg_tileserv activo?", "#fca5a5"));

// ===================== Ficha del predio =====================
const intCR = (v) => Math.round(Number(v)).toLocaleString("es-CR");
const fmt = (v) => (v == null || v === "") ? "—" : v;

const CAMPOS = [
  ["area_m2", "Área (m²)", (v) => v == null ? "—" : intCR(v)],
  ["id_predial", "Código predial"],
  ["numero_finca", "Finca"],
  ["valor_terreno_zh", "Valor terreno por zona homogénea", (v) => v == null ? "—" : intCR(v)],
  ["plano", "Plano"],
  ["frente_calle", "Frente a calle", (v) => v == 1 || v === true ? "Sí" : (v == 0 ? "No" : "—")],
  ["regularidad_geom", "Regularidad geométrica"],
  ["pendiente_media", "Pendiente media", (v) => v == null ? "—" : Number(v).toFixed(1) + "°"],
  ["inclinacion", "Inclinación"]
