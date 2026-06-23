from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import gdal, ogr, osr


gdal.UseExceptions()
ogr.UseExceptions()


DEFAULT_CATASTRO = Path("C:/Catastros/Catastro_garabito")
DEFAULT_VISOR = Path(__file__).resolve().parents[1]
WFS_URL = "https://geos.snitcr.go.cr/be/IGN_200/wfs"
WMS_URL = "https://geos.snitcr.go.cr/be/IGN_200/wms"
ROAD_LAYER = "IGN_200:redvial_200k"
DRAINAGE_LAYER = "IGN_200:reddrenaje_200k"
WEB_SRS = "EPSG:4326"
WORK_SRS = "EPSG:8908"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_text(value) -> str:
    return str(value or "").strip()


def make_srs(epsg: int) -> osr.SpatialReference:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def open_limit(limit_path: Path, layer_name: str | None):
    ds = ogr.Open(str(limit_path))
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el limite: {limit_path}")
    layer = ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    if layer is None:
        raise RuntimeError(f"No se pudo abrir la capa del limite: {limit_path}")
    srs = layer.GetSpatialRef()
    if srs is None:
        raise RuntimeError("El limite no tiene CRS.")
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    union = None
    for feat in layer:
        geom = feat.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            continue
        geom = geom.Clone()
        union = geom if union is None else union.Union(geom)
    if union is None or union.IsEmpty():
        raise RuntimeError("No se pudo construir el limite cantonal.")
    return ds, union, srs


def envelope_to_wgs84(geom: ogr.Geometry, source_srs: osr.SpatialReference):
    wgs84 = make_srs(4326)
    tx = osr.CoordinateTransformation(source_srs, wgs84)
    geom_wgs = geom.Clone()
    geom_wgs.Transform(tx)
    minx, maxx, miny, maxy = geom_wgs.GetEnvelope()
    return minx, miny, maxx, maxy


def wfs_url(layer_name: str, bbox_wgs84):
    minx, miny, maxx, maxy = bbox_wgs84
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typename": layer_name,
        "outputFormat": "application/json",
        "srsName": WEB_SRS,
        "bbox": f"{minx},{miny},{maxx},{maxy},{WEB_SRS}",
    }
    return WFS_URL + "?" + urllib.parse.urlencode(params)


def download(url: str, output: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "VisorPredial/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
    output.write_bytes(data)
    if output.stat().st_size == 0:
        raise RuntimeError(f"Descarga vacia: {url}")


def road_class(props: dict) -> str:
    text = " ".join(
        normalize_text(props.get(key)).upper()
        for key in ("categoria", "tipo", "jerarquia", "nombre", "layer")
    )
    route = normalize_text(props.get("num_ruta"))
    if "PUENTE" in text:
        return "Puente"
    if "VEREDA" in text:
        return "Vereda"
    if route or "RUTA" in text or "CARRETERA" in text:
        return "Ruta nacional"
    if "CAMINO" in text:
        return "Camino"
    return "Vía local"


def road_style(via_class: str):
    styles = {
        "Ruta nacional": ("#f97316", 5.2, "", "#7c2d12", 8.4),
        "Camino": ("#facc15", 3.4, "", "#854d0e", 5.6),
        "Vereda": ("#8b5cf6", 2.2, "4 4", "#ffffff", 4.2),
        "Puente": ("#111827", 6.0, "2 2", "#ffffff", 8.2),
        "Vía local": ("#64748b", 2.4, "", "#ffffff", 4.2),
    }
    return styles.get(via_class, styles["Vía local"])


def drainage_style():
    return "#0284c7", 2.3, "6 4", "#e0f2fe", 4.1


def create_output_layer(ds, name: str, srs: osr.SpatialReference, geom_type=ogr.wkbMultiLineString):
    layer = ds.CreateLayer(name, srs=srs, geom_type=geom_type)
    fields = [
        ("fuente", ogr.OFTString, 32),
        ("categoria", ogr.OFTString, 160),
        ("codigo", ogr.OFTString, 48),
        ("num_ruta", ogr.OFTString, 48),
        ("nombre", ogr.OFTString, 180),
        ("longitud_m", ogr.OFTReal, 0),
        ("via_clase", ogr.OFTString, 64),
        ("stroke", ogr.OFTString, 16),
        ("stroke_width", ogr.OFTReal, 0),
        ("stroke_dasharray", ogr.OFTString, 24),
        ("stroke_outline", ogr.OFTString, 16),
        ("stroke_outline_width", ogr.OFTReal, 0),
    ]
    for field_name, field_type, width in fields:
        field = ogr.FieldDefn(field_name, field_type)
        if width:
            field.SetWidth(width)
        layer.CreateField(field)
    return layer


def geom_to_multiline(geom: ogr.Geometry) -> ogr.Geometry | None:
    if geom is None or geom.IsEmpty():
        return None
    name = geom.GetGeometryName().upper()
    if name == "LINESTRING":
        multi = ogr.Geometry(ogr.wkbMultiLineString)
        multi.AddGeometry(geom)
        return multi
    if name == "MULTILINESTRING":
        return geom
    if name == "GEOMETRYCOLLECTION":
        multi = ogr.Geometry(ogr.wkbMultiLineString)
        for i in range(geom.GetGeometryCount()):
            child = geom.GetGeometryRef(i)
            child_multi = geom_to_multiline(child)
            if child_multi:
                for j in range(child_multi.GetGeometryCount()):
                    multi.AddGeometry(child_multi.GetGeometryRef(j))
        return multi if multi.GetGeometryCount() else None
    return None


def clip_wfs_lines(
    raw_geojson: Path,
    output_gpkg: Path,
    output_geojson: Path,
    output_layer: str,
    limit_geom_work: ogr.Geometry,
    limit_srs: osr.SpatialReference,
    mode: str,
):
    raw_ds = ogr.Open(str(raw_geojson))
    if raw_ds is None:
        raise RuntimeError(f"No se pudo abrir WFS descargado: {raw_geojson}")
    raw_layer = raw_ds.GetLayer(0)
    raw_srs = raw_layer.GetSpatialRef() or make_srs(4326)
    raw_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_work = osr.CoordinateTransformation(raw_srs, limit_srs)
    to_web = osr.CoordinateTransformation(limit_srs, make_srs(4326))

    for path in (output_gpkg, output_geojson):
        if path.exists():
            path.unlink()

    gpkg_driver = ogr.GetDriverByName("GPKG")
    json_driver = ogr.GetDriverByName("GeoJSON")
    gpkg_ds = gpkg_driver.CreateDataSource(str(output_gpkg))
    json_ds = json_driver.CreateDataSource(str(output_geojson))
    gpkg_layer = create_output_layer(gpkg_ds, output_layer, limit_srs)
    json_layer = create_output_layer(json_ds, output_layer, make_srs(4326))

    count = 0
    class_count: dict[str, int] = {}
    for feat in raw_layer:
        geom = feat.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            continue
        work_geom = geom.Clone()
        work_geom.Transform(to_work)
        if not work_geom.Intersects(limit_geom_work):
            continue
        clipped = work_geom.Intersection(limit_geom_work)
        clipped = geom_to_multiline(clipped)
        if clipped is None or clipped.IsEmpty():
            continue

        props = {feat.GetFieldDefnRef(i).GetName(): feat.GetField(i) for i in range(feat.GetFieldCount())}
        if mode == "roads":
            cls = road_class(props)
            stroke, width, dash, outline, outline_width = road_style(cls)
        else:
            cls = "Red de drenaje"
            stroke, width, dash, outline, outline_width = drainage_style()
        class_count[cls] = class_count.get(cls, 0) + 1

        web_geom = clipped.Clone()
        web_geom.Transform(to_web)
        length = clipped.Length()
        for layer, out_geom in ((gpkg_layer, clipped), (json_layer, web_geom)):
            out_feat = ogr.Feature(layer.GetLayerDefn())
            out_feat.SetGeometry(out_geom)
            out_feat.SetField("fuente", "SNIT IGN_200 WFS")
            out_feat.SetField("categoria", normalize_text(props.get("categoria")))
            out_feat.SetField("codigo", normalize_text(props.get("codigo")))
            out_feat.SetField("num_ruta", normalize_text(props.get("num_ruta")))
            out_feat.SetField("nombre", normalize_text(props.get("nombre")))
            out_feat.SetField("longitud_m", float(length))
            out_feat.SetField("via_clase", cls)
            out_feat.SetField("stroke", stroke)
            out_feat.SetField("stroke_width", float(width))
            out_feat.SetField("stroke_dasharray", dash)
            out_feat.SetField("stroke_outline", outline)
            out_feat.SetField("stroke_outline_width", float(outline_width))
            layer.CreateFeature(out_feat)
        count += 1

    gpkg_layer.SyncToDisk()
    json_layer.SyncToDisk()
    gpkg_ds = None
    json_ds = None
    raw_ds = None
    return count, class_count


def write_roads_qml(path: Path):
    path.write_text(
        """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44" styleCategories="Symbology">
  <renderer-v2 type="categorizedSymbol" attr="via_clase" enableorderby="0">
    <categories>
      <category value="Ruta nacional" label="Ruta nacional" symbol="0"/>
      <category value="Camino" label="Camino" symbol="1"/>
      <category value="Vereda" label="Vereda" symbol="2"/>
      <category value="Puente" label="Puente" symbol="3"/>
      <category value="Vía local" label="Vía local" symbol="4"/>
    </categories>
    <symbols>
      <symbol name="0" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="124,45,18,255"/><Option name="line_width" value="1.85"/><Option name="line_width_unit" value="MM"/></Option></layer><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="249,115,22,255"/><Option name="line_width" value="1.15"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="1" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="133,77,14,255"/><Option name="line_width" value="1.25"/><Option name="line_width_unit" value="MM"/></Option></layer><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="250,204,21,255"/><Option name="line_width" value="0.75"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="2" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="255,255,255,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="0.9"/><Option name="line_width_unit" value="MM"/></Option></layer><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="139,92,246,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="0.5"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="3" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="255,255,255,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="1.75"/><Option name="line_width_unit" value="MM"/></Option></layer><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="17,24,39,255"/><Option name="line_style" value="dash"/><Option name="line_width" value="1.25"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
      <symbol name="4" type="line"><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="255,255,255,255"/><Option name="line_width" value="0.9"/><Option name="line_width_unit" value="MM"/></Option></layer><layer class="SimpleLine"><Option type="Map"><Option name="line_color" value="100,116,139,255"/><Option name="line_width" value="0.5"/><Option name="line_width_unit" value="MM"/></Option></layer></symbol>
    </symbols>
  </renderer-v2>
</qgis>
""",
        encoding="utf-8",
    )


def raster_stats(path: Path):
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"No se pudo abrir raster: {path}")
    band = ds.GetRasterBand(1)
    stats = band.GetStatistics(True, True)
    ds = None
    return stats


def raster_bounds_wgs84(path: Path):
    ds = gdal.Open(str(path))
    gt = ds.GetGeoTransform()
    width = ds.RasterXSize
    height = ds.RasterYSize
    minx = gt[0]
    maxy = gt[3]
    maxx = minx + gt[1] * width
    miny = maxy + gt[5] * height
    ds = None
    return [[miny, minx], [maxy, maxx]]


def write_color_file(path: Path, rows):
    text = "\n".join(" ".join(map(str, row)) for row in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def colorize_raster(src: Path, out_png: Path, color_rows, tmp_dir: Path, max_size=2400):
    wgs = tmp_dir / f"{src.stem}_wgs84.tif"
    rgba = tmp_dir / f"{src.stem}_rgba.tif"
    colors = tmp_dir / f"{src.stem}_colors.txt"
    write_color_file(colors, color_rows)

    gdal.Warp(
        str(wgs),
        str(src),
        dstSRS=WEB_SRS,
        format="GTiff",
        multithread=True,
        creationOptions=["COMPRESS=LZW", "TILED=YES"],
    )
    gdal.DEMProcessing(str(rgba), str(wgs), "color-relief", colorFilename=str(colors), addAlpha=True)

    ds = gdal.Open(str(rgba))
    width = ds.RasterXSize
    height = ds.RasterYSize
    scale = min(1.0, max_size / max(width, height))
    out_width = max(1, int(width * scale))
    out_height = max(1, int(height * scale))
    ds = None
    gdal.Translate(
        str(out_png),
        str(rgba),
        format="PNG",
        width=out_width,
        height=out_height,
    )
    return raster_bounds_wgs84(rgba)


def dem_colors(src: Path):
    minimum, maximum, mean, std = raster_stats(src)
    if not math.isfinite(minimum) or not math.isfinite(maximum) or math.isclose(minimum, maximum):
        minimum, maximum = 0, 100
    p1 = minimum
    p2 = minimum + (maximum - minimum) * 0.25
    p3 = minimum + (maximum - minimum) * 0.50
    p4 = minimum + (maximum - minimum) * 0.75
    return [
        ("nv", 0, 0, 0, 0),
        (round(p1, 3), 33, 102, 84, 180),
        (round(p2, 3), 102, 145, 84, 185),
        (round(p3, 3), 201, 168, 94, 190),
        (round(p4, 3), 151, 103, 65, 195),
        (round(maximum, 3), 242, 238, 218, 200),
    ]


def raster_layer_specs(catastro: Path):
    susc = catastro / "11_Susceptibilidad"
    return [
        {
            "id": "dem",
            "title": "DEM / MDE",
            "path": susc / "02_MDE" / "03_Recorte" / "mde_garabito_recortado.tif",
            "opacity": 0.58,
            "colors": None,
            "legend": [
                ["Bajo", "#216654"],
                ["Medio", "#c9a85e"],
                ["Alto", "#f2eeda"],
            ],
        },
        {
            "id": "hidrologia",
            "title": "Hidrología",
            "path": susc / "04_Hidrologia" / "red_drenaje_umbral.tif",
            "opacity": 0.86,
            "max_size": 2800,
            "colors": [("nv", 0, 0, 0, 0), (0, 0, 0, 0, 0), (1, 2, 132, 199, 245)],
            "legend": [["Red de drenaje modelada", "#0e74bf"]],
        },
        {
            "id": "uso_suelo",
            "title": "Uso de suelo",
            "path": susc / "05_Uso_Cobertura" / "04_Reclasificado" / "MC24_garabito_grupos.tif",
            "opacity": 0.82,
            "max_size": 3200,
            "colors": [
                ("nv", 0, 0, 0, 0),
                (0, 0, 0, 0, 0),
                (1, 27, 120, 55, 238),
                (2, 0, 109, 44, 245),
                (3, 116, 196, 118, 238),
                (4, 65, 182, 196, 238),
                (5, 253, 174, 97, 238),
                (6, 244, 109, 67, 238),
                (7, 215, 48, 39, 242),
                (8, 184, 160, 106, 238),
                (9, 127, 0, 0, 242),
                (10, 194, 165, 207, 238),
                (254, 189, 189, 189, 190),
                (255, 255, 255, 0),
            ],
            "legend": [
                ["Bosque / cobertura arbórea", "#1b7837"],
                ["Manglar", "#006d2c"],
                ["Yolillal", "#74c476"],
                ["Humedales", "#41b6c4"],
                ["Cultivos", "#fdae61"],
                ["Pastizales", "#f46d43"],
                ["Urbano / construido", "#d73027"],
                ["Otras tierras naturales", "#b8a06a"],
                ["Otras tierras artificiales", "#7f0000"],
                ["Páramo / alta montaña", "#c2a5cf"],
            ],
        },
        {
            "id": "riesgo",
            "title": "Riesgo / susceptibilidad",
            "path": susc / "09_Indice_Susceptibilidad" / "susceptibilidad_garabito_clases_1_5.tif",
            "opacity": 0.76,
            "max_size": 3200,
            "colors": [
                ("nv", 0, 0, 0, 0),
                (0, 0, 0, 0, 0),
                (1, 26, 152, 80, 235),
                (2, 145, 207, 96, 235),
                (3, 254, 224, 139, 240),
                (4, 252, 141, 89, 242),
                (5, 215, 48, 39, 245),
            ],
            "legend": [
                ["Muy baja", "#16a34a"],
                ["Baja", "#84cc16"],
                ["Media", "#eab308"],
                ["Alta", "#f97316"],
                ["Muy alta", "#dc2626"],
            ],
        },
    ]


def prepare_rasters(catastro: Path, output_layers: Path, copy_targets: list[Path]):
    rasters_dir = ensure_dir(output_layers / "rasters")
    manifest = {"rasters": []}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for spec in raster_layer_specs(catastro):
            src = spec["path"]
            if not src.exists():
                print(f"Aviso: no existe raster {src}")
                continue
            png = rasters_dir / f"{spec['id']}.png"
            colors = spec["colors"] if spec["colors"] is not None else dem_colors(src)
            print(f"Preparando raster {spec['title']}: {src}")
            bounds = colorize_raster(src, png, colors, tmp_dir, max_size=spec.get("max_size", 2400))
            manifest["rasters"].append(
                {
                    "id": spec["id"],
                    "title": spec["title"],
                    "type": "image",
                    "url": f"layers/rasters/{png.name}",
                    "bounds": bounds,
                    "opacity": spec["opacity"],
                    "legend": spec["legend"],
                }
            )
    manifest_path = rasters_dir / "rasters_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for target in copy_targets:
        target_rasters = ensure_dir(target / "layers" / "rasters")
        for item in rasters_dir.iterdir():
            if item.is_file() and (item.suffix.lower() == ".png" or item.name == "rasters_manifest.json"):
                shutil.copy2(item, target_rasters / item.name)


def prepare_vectors(catastro: Path, output_layers: Path, copy_targets: list[Path]):
    limit_path = catastro / "01_Insumos" / "limite_garabito_8908_fix.gpkg"
    limit_layer = "limite_garabito_8908_fix"
    _, limit_geom, limit_srs = open_limit(limit_path, limit_layer)
    bbox = envelope_to_wgs84(limit_geom, limit_srs)
    raw_dir = ensure_dir(output_layers / "raw")
    vector_dir = ensure_dir(output_layers / "vector")
    analysis_dir = ensure_dir(output_layers / "gpkg")

    vector_specs = [
        ("roads", ROAD_LAYER, "vias_garabito", "vias_garabito", "roads"),
        ("drainage", DRAINAGE_LAYER, "drenaje_snit_garabito", "drenaje_snit_garabito", "drainage"),
    ]
    manifest = {"wfs": WFS_URL, "wms": WMS_URL, "bbox_wgs84": bbox, "vectors": []}
    for key, layer_name, base_name, out_layer, mode in vector_specs:
        raw = raw_dir / f"{base_name}_raw.geojson"
        print(f"Descargando {layer_name} por WFS...")
        download(wfs_url(layer_name, bbox), raw)
        gpkg = analysis_dir / f"{base_name}.gpkg"
        geojson = vector_dir / f"{base_name}.geojson"
        count, class_count = clip_wfs_lines(raw, gpkg, geojson, out_layer, limit_geom, limit_srs, mode)
        manifest["vectors"].append(
            {
                "id": key,
                "title": "Vías SNIT" if key == "roads" else "Drenaje SNIT",
                "url": f"layers/vector/{geojson.name}",
                "features": count,
                "classes": class_count,
            }
        )
        print(f"  {count} elementos recortados -> {geojson}")

    write_roads_qml(analysis_dir / "vias_garabito.qml")
    (output_layers / "capas_auxiliares_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for target in copy_targets:
        target_vector = ensure_dir(target / "layers" / "vector")
        for item in vector_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, target_vector / item.name)
        shutil.copy2(output_layers / "capas_auxiliares_manifest.json", target / "layers" / "capas_auxiliares_manifest.json")


def main():
    parser = argparse.ArgumentParser(
        description="Prepara vías SNIT y capas auxiliares raster para el Visor Predial de Garabito."
    )
    parser.add_argument("--base-catastro", default=str(DEFAULT_CATASTRO))
    parser.add_argument("--visor-root", default=str(DEFAULT_VISOR))
    parser.add_argument("--solo", choices=["todo", "vias", "rasters"], default="todo")
    parser.add_argument("--no-sync-visor", action="store_true")
    args = parser.parse_args()

    catastro = Path(args.base_catastro)
    visor = Path(args.visor_root)
    output_layers = ensure_dir(catastro / "13_Visor_Capas")
    copy_targets = [] if args.no_sync_visor else [visor / "frontend", visor / "dist"]

    if args.solo in ("todo", "vias"):
        prepare_vectors(catastro, output_layers, copy_targets)
    if args.solo in ("todo", "rasters"):
        prepare_rasters(catastro, output_layers, copy_targets)

    print("\nCapas auxiliares listas:")
    print(output_layers)
    if copy_targets:
        print("Copiadas al visor:")
        for target in copy_targets:
            print(target / "layers")


if __name__ == "__main__":
    main()
