# Visor Predial — Garabito

Visor web local de predios catastrales sobre Leaflet, con datos servidos como teselas
vectoriales desde PostGIS vía pg_tileserv. Clic en un predio → ficha con su información
(código predial, finca, plano, área, distrito, uso, zona homogénea, riesgo, prioridad…).

## Requisitos (ya instalados en esta máquina)

- PostgreSQL 17 + PostGIS 3.5 (BD `visor_predial` ya creada y cargada con Garabito).
- `tools\pg_tileserv\pg_tileserv.exe` (incluido).
- Un navegador moderno.

## Uso (un clic)

Clic derecho en `tools\start_visor.ps1` → **Ejecutar con PowerShell**. El script:

1. Arranca **pg_tileserv** (teselas) en `http://127.0.0.1:7800`.
2. Arranca el **servidor del visor** en `http://localhost:5500`.
3. Abre el visor en el navegador automáticamente.

El indicador arriba a la derecha mostrará **"Listo ✓"** cuando carguen las teselas.
Si dice **"Sin teselas"**, revisa que las ventanas minimizadas (pg_tileserv y el visor) sigan abiertas.

Para **detener**, cierra esas dos ventanas minimizadas.

> Alternativa sin servidor estático: abrir `frontend\index.html` con doble clic (file://).
> Funciona porque las teselas vienen de `127.0.0.1:7800` con CORS abierto, pero algunos navegadores
> son quisquillosos con `file://`; si no carga, usa el lanzador de arriba.

## Estructura

```
Visor_Predial/
├── frontend/            # Visor (Leaflet + VectorGrid)
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js
│   └── layers/          # capas auxiliares listas para el visor estático
├── tools/
│   ├── start_visor.ps1     # lanzador de un clic (teselas + visor + navegador)
│   ├── preparar_capas_auxiliares_garabito.py
│   ├── serve_frontend.cmd  # servidor estático del frontend (puerto 5500)
│   └── pg_tileserv/        # binario + config
├── CLAUDE.md            # guía técnica del proyecto
└── README.md
```

## Capas auxiliares SNIT y análisis

Para regenerar vías, drenaje SNIT y las capas DEM, hidrología, uso de suelo y riesgo:

```powershell
& "C:\OSGeo4W\bin\python-qgis.bat" "tools\preparar_capas_auxiliares_garabito.py" --solo todo
```

El script descarga vías y drenaje desde el WFS de SNIT, recorta contra Garabito y copia los
GeoJSON/PNG a `frontend\layers` y `dist\layers`. También genera un GPKG y una simbología QGIS
en `C:\Catastros\Catastro_garabito\13_Visor_Capas`.

## Recargar datos (si regeneras el GPKG)

```powershell
$env:PGPASSWORD = "VisorPredial2026"
$ogr = "C:\Program Files\QGIS 3.44.2\bin\ogr2ogr.exe"
$pg  = "PG:host=localhost port=5432 dbname=visor_predial user=postgres password=VisorPredial2026"
& $ogr -f PostgreSQL $pg "C:\Catastros\Catastro_garabito\12_Modelo_predial\predios_garabito_modelo_predial.gpkg" `
   -nln predios_modelo -nlt PROMOTE_TO_MULTI -lco GEOMETRY_NAME=geom -lco FID=fid -lco SPATIAL_INDEX=GIST -overwrite
```
(Luego repetir el saneo de geometría a MultiPolygon y recrear la vista `v_predios` — ver `CLAUDE.md`.)
