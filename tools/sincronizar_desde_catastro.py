"""Sincroniza el visor local con el modelo predial vigente de Garabito.

Debe ejecutarse con python-qgis.bat. Genera el indice de atributos, un GPKG
minimo para teselas y una piramide XYZ en una carpeta de staging.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsVectorTileWriter,
)
from qgis.PyQt.QtCore import QUrl, QUrlQuery

from completar_teselas_vacias import complete_empty_tiles
from limpiar_teselas_mvt import clean_tiles


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path(
    "C:/Catastros/Catastro_garabito/13_Uso_Predios_ONT/"
    "predios_garabito_uso_probable_ont.gpkg"
)
DEFAULT_LAYER = "predios_garabito_uso_probable_ont"


def scalar(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else round(float(value), 2)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip()
    return text or None


def build_records(gdf: gpd.GeoDataFrame):
    wgs84 = gdf.to_crs("EPSG:4326")
    centers = wgs84.geometry.representative_point()
    records = []
    for pos, (_, row) in enumerate(gdf.iterrows(), start=1):
        center = centers.iloc[pos - 1]
        records.append(
            {
                "fid": pos,
                "id_predial": scalar(row.get("id_predial")),
                "numero_finca": scalar(row.get("numero_finca")),
                "plano": scalar(row.get("plano")),
                "area_m2": scalar(row.get("area_m2")),
                "valor_terreno_zh": scalar(row.get("valor_terreno_zh")),
                "pendiente_media": scalar(row.get("pendiente_media")),
                "frente_calle": bool(row.get("frente_calle"))
                if pd.notna(row.get("frente_calle"))
                else False,
                "regularidad_geom": scalar(row.get("regularidad_geom")),
                "riesgo": scalar(row.get("riesgo")),
                "prioridad_fiscalizacion": scalar(row.get("prioridad_fiscalizacion")),
                "distrito": scalar(row.get("distrito")),
                "uso_probable": scalar(row.get("uso_probable")),
                "zona_ont": scalar(row.get("zh_NOMBRE_ZONAH")),
                "center": [round(float(center.y), 7), round(float(center.x), 7)],
            }
        )
    return records


def write_tile_source(gdf: gpd.GeoDataFrame, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    tiles = gdf[["geometry"]].copy()
    tiles.insert(0, "fid_publicacion", np.arange(1, len(tiles) + 1, dtype="int64"))
    tiles.to_file(output, layer="predios_publicacion", driver="GPKG")


def write_tiles(gpkg: Path, output_dir: Path, min_zoom: int, max_zoom: int):
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"La carpeta staging no esta vacia: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    qgs = QgsApplication([], False)
    qgs.initQgis()
    try:
        layer = QgsVectorLayer(
            f"{gpkg.as_posix()}|layername=predios_publicacion",
            "predios_publicacion",
            "ogr",
        )
        if not layer.isValid():
            raise RuntimeError(f"QGIS no pudo abrir la capa para teselas: {gpkg}")

        tile_layer = QgsVectorTileWriter.Layer(layer)
        tile_layer.setLayerName("predios")
        tile_layer.setMinZoom(min_zoom)
        tile_layer.setMaxZoom(max_zoom)

        template = output_dir / "{z}" / "{x}" / "{y}.pbf"
        query = QUrlQuery()
        query.addQueryItem("type", "xyz")
        query.addQueryItem("url", QUrl.fromLocalFile(str(template)).toString())

        writer = QgsVectorTileWriter()
        writer.setDestinationUri(query.query())
        writer.setMinZoom(min_zoom)
        writer.setMaxZoom(max_zoom)
        writer.setLayers([tile_layer])
        writer.setTransformContext(QgsProject.instance().transformContext())

        web_mercator = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(layer.crs(), web_mercator, QgsProject.instance())
        writer.setExtent(transform.transformBoundingBox(layer.extent()))
        if not writer.writeTiles():
            raise RuntimeError("No se generaron teselas: " + writer.errorMessage())
    finally:
        qgs.exitQgis()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--layer", default=DEFAULT_LAYER)
    parser.add_argument("--tiles-staging", required=True)
    parser.add_argument("--min-zoom", type=int, default=10)
    parser.add_argument("--max-zoom", type=int, default=16)
    args = parser.parse_args()

    source = Path(args.source)
    gdf = gpd.read_file(source, layer=args.layer)
    if gdf.empty:
        raise RuntimeError("La capa fuente no contiene predios.")
    if gdf.crs is None:
        raise RuntimeError("La capa fuente no tiene CRS.")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise RuntimeError("La capa fuente contiene geometrias nulas o vacias.")
    if "id_predial" not in gdf.columns or gdf["id_predial"].fillna("").str.strip().eq("").any():
        raise RuntimeError("Todos los predios publicables deben tener id_predial.")

    records = build_records(gdf)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "layer": args.layer,
        "records": records,
    }
    index_path = ROOT / "data" / "predios_index.json"
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    work_gpkg = ROOT / "work" / "predios_garabito_publicacion.gpkg"
    write_tile_source(gdf, work_gpkg)
    tiles_staging = Path(args.tiles_staging)
    write_tiles(work_gpkg, tiles_staging, args.min_zoom, args.max_zoom)
    invalid_removed, corrected_tiles = clean_tiles(tiles_staging)
    existing_tiles, created_empty, coverage_tiles = complete_empty_tiles(tiles_staging)

    print(f"Predios sincronizados: {len(records):,}")
    print(f"Indice: {index_path}")
    print(f"Fuente de teselas: {work_gpkg}")
    print(f"Teselas staging: {tiles_staging}")
    print(f"Features MVT invalidas eliminadas: {invalid_removed:,} en {corrected_tiles:,} teselas")
    print(f"Teselas vacias creadas: {created_empty:,} (cobertura total {coverage_tiles:,})")


if __name__ == "__main__":
    main()
