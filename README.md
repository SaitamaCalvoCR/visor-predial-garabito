# Visor Predial — Garabito

Sitio estático publicado con GitHub Pages: consulta de predios catastrales del cantón
de Garabito sobre Leaflet, con las teselas vectoriales ya exportadas como archivos
`.pbf` (no depende de un servidor PostGIS/pg_tileserv en producción). Clic en un
predio → ficha con su información (código predial, finca, plano, área, distrito,
zona homogénea, riesgo, prioridad de fiscalización…).

URL publicada: https://saitamacalvocr.github.io/visor-predial-garabito/

## Estructura

```
visor-predial-garabito/
├── index.html
├── css/style.css
├── js/app.js
├── data/
│   ├── predios_index.json     # atributos por predio (18 906 registros)
│   └── stats_index.json       # resumen agregado precalculado (dashboard instantáneo)
├── layers/
│   ├── capas_auxiliares_manifest.json   # vías y drenaje SNIT
│   ├── vector/*.geojson
│   └── rasters/                          # DEM, hidrología, uso de suelo, riesgo (PNG)
├── tiles/{z}/{x}/{y}.pbf      # pirámide de teselas vectoriales estática (z10–z16)
├── tools/
│   ├── preparar_capas_auxiliares_garabito.py   # regenera layers/ (vías, drenaje, rasters)
│   └── optimizar_predios_index.py              # recompacta data/ (ver más abajo)
└── .nojekyll
```

No hay backend: todo lo que sirve GitHub Pages es contenido estático de este repo.

## Ejecutar en local

Cualquier servidor estático sirve. Por ejemplo:

```powershell
python -m http.server 8025 --bind 127.0.0.1
```

y abrir `http://127.0.0.1:8025/`. Abrir `index.html` directamente por `file://` no
funciona bien en todos los navegadores porque los `fetch()` a `data/` y `layers/`
quedan bloqueados por CORS en ese esquema.

## Regenerar `data/predios_index.json` y `data/stats_index.json`

Estos dos archivos se generan a partir del catastro modelado de Garabito
(`predios_garabito_modelo_predial.gpkg`, ver
`C:\Automatizacion_Catastro\scripts\11_generar_modelo_predial.py`) en un paso externo
a este repo que exporta el GPKG a `data/predios_index.json`. Una vez tengas ese
archivo actualizado, corre:

```powershell
python tools\optimizar_predios_index.py
```

El script:
- Quita de cada registro los campos que el frontend no necesita en el índice
  (`observaciones`, que no se muestra en ninguna vista, y `issues`/`issue_score`/
  `priority`/`estado`/`distrito_nombre`, que `js/app.js` recalcula siempre en el
  cliente a partir de los demás campos).
- Calcula `data/stats_index.json`: un resumen agregado (~1 KB) con los KPIs de
  calidad, el ranking de alertas y las estadísticas por distrito. El visor lo carga
  en paralelo al índice completo y pinta el Dashboard al instante mientras el resto
  de los predios sigue descargando.

Última corrida: `predios_index.json` bajó de 9.37 MB a ~6.3 MB (-33 %).

## Regenerar capas auxiliares (vías, drenaje, DEM, hidrología, uso de suelo, riesgo)

```powershell
& "C:\OSGeo4W\bin\python-qgis.bat" "tools\preparar_capas_auxiliares_garabito.py" --solo todo
```

Descarga vías y drenaje desde el WFS de SNIT, recorta contra el límite de Garabito y
escribe los GeoJSON/PNG en `layers/`. También deja una copia en
`C:\Catastros\Catastro_garabito\13_Visor_Capas`.

## Regenerar `tiles/`

La pirámide de teselas `.pbf` **no se genera desde este repo**: se exportó una vez
desde una base PostGIS con pg_tileserv/tippecanoe hacia `tiles/{z}/{x}/{y}.pbf`
estático. Si necesitas regenerarla (por ejemplo tras actualizar el catastro),
hacelo desde esa base y volvé a copiar el árbol `tiles/` completo aquí.

**Nota de optimización pendiente:** cada tesela actual embebe las ~19 columnas del
predio (`riesgo`, `distrito`, `uso`, `area_m2`, `susc_mean`, `dist_red_vial_m`, etc.),
repetidas en cada uno de los 7 niveles de zoom (z10–z16). El frontend nunca necesita
esos atributos en la tesela: al hacer clic, `mergeWithIndex()` en `js/app.js` siempre
completa el predio desde `data/predios_index.json`, así que la tesela solo necesita
la propiedad `fid` para identificar el feature (y la geometría). Medido sobre
`tiles/10/271/484.pbf`: el 40 % de los bytes del archivo son esos atributos
redundantes. Si el pipeline de exportación permite limitar las columnas del layer a
`SELECT fid, geom`, el peso de `tiles/` (hoy ~55 MB) debería bajar sustancialmente sin
tocar el frontend.

## 404 esperados en `tiles/*.pbf`

El exportador de teselas omite los tiles sin features (fuera del polígono del cantón
o en huecos internos), así que un `404` aislado al hacer *pan* cerca del borde de
cobertura es normal, no un error real. El visor:
- Limita el `VectorGrid` con `bounds`/`minNativeZoom` al rectángulo real cubierto por
  `tiles/`, así que paniar lejos del cantón ya no dispara ráfagas de 404.
- Solo cambia el indicador de estado a "Sin teselas" si nunca llegó a cargar ninguna
  tesela con éxito; un 404 puntual en un borde no lo hace, evitando falsos positivos.

## Dependencias del visor

- [Leaflet](https://leafletjs.com/) 1.9.4 y [Leaflet.VectorGrid](https://github.com/Leaflet/Leaflet.VectorGrid) 1.3.0, cargados desde unpkg.
- Capas base: Esri World Imagery/Transportation/Boundaries, OpenStreetMap, CARTO.
- Sin build step ni dependencias de Node: `js/app.js` es JavaScript plano.

## Contexto del pipeline completo

Este repo es solo el visor. El pipeline catastral completo (descarga SIRI, limpieza,
modelo predial, susceptibilidad/riesgo) vive en
`C:\Automatizacion_Catastro\scripts` y sus salidas en
`C:\Catastros\Catastro_garabito`.
