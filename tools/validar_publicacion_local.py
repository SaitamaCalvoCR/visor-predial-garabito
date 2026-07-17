"""Valida los artefactos locales del visor antes de publicar."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import struct
from pathlib import Path
from urllib.request import urlopen

from limpiar_teselas_mvt import feature_is_valid, read_field, read_varint


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_PREDIOS = 18_884
EXPECTED_ZOOMS = set(range(10, 17))
PREDIOS_BOUNDS = {
    "south": 9.5145,
    "west": -84.7237,
    "north": 9.9008,
    "east": -84.5066,
}


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def load_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def lon_to_x(lon: float, zoom: int) -> int:
    return int(math.floor((lon + 180.0) / 360.0 * (2**zoom)))


def lat_to_y(lat: float, zoom: int) -> int:
    lat_rad = math.radians(lat)
    return int(
        math.floor(
            (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi)
            / 2.0
            * (2**zoom)
        )
    )


def expected_tile_paths():
    for zoom in EXPECTED_ZOOMS:
        min_x = lon_to_x(PREDIOS_BOUNDS["west"], zoom)
        max_x = lon_to_x(PREDIOS_BOUNDS["east"], zoom)
        min_y = lat_to_y(PREDIOS_BOUNDS["north"], zoom)
        max_y = lat_to_y(PREDIOS_BOUNDS["south"], zoom)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                yield ROOT / "tiles" / str(zoom) / str(x) / f"{y}.pbf"


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    require(header[:8] == b"\x89PNG\r\n\x1a\n", f"PNG invalido: {path}")
    return struct.unpack(">II", header[16:24])


def count_invalid_mvt_features(path: Path) -> int:
    data = path.read_bytes()
    if not data:
        return 0

    invalid = 0
    pos = 0
    while pos < len(data):
        field_no, wire_type, value_start, end, _ = read_field(data, pos)
        if field_no == 3 and wire_type == 2:
            size, layer_start = read_varint(data, value_start)
            layer_payload = data[layer_start : layer_start + size]
            layer_pos = 0
            while layer_pos < len(layer_payload):
                layer_field, layer_wire, layer_value_start, layer_end, _ = read_field(layer_payload, layer_pos)
                if layer_field == 2 and layer_wire == 2:
                    feature_size, feature_start = read_varint(layer_payload, layer_value_start)
                    feature_payload = layer_payload[feature_start : feature_start + feature_size]
                    if not feature_is_valid(feature_payload):
                        invalid += 1
                layer_pos = layer_end
        pos = end
    return invalid


def validate_http(base_url: str, paths: list[str]):
    for path in paths:
        with urlopen(f"{base_url.rstrip('/')}/{path}", timeout=20) as response:
            require(response.status == 200, f"HTTP {response.status}: {path}")
            require(int(response.headers.get("Content-Length", "1")) > 0, f"Vacio: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="URL del servidor local, por ejemplo http://127.0.0.1:8025")
    args = parser.parse_args()

    index = load_json("data/predios_index.json")
    records = index["records"]
    fids = [record.get("fid") for record in records]
    ids = [str(record.get("id_predial") or "").strip() for record in records]
    require(len(records) == EXPECTED_PREDIOS, f"Predios: {len(records)}")
    require(len(set(fids)) == EXPECTED_PREDIOS, "Hay FID duplicados")
    require(all(ids), "Hay identificadores prediales vacios")
    require(len(set(ids)) == EXPECTED_PREDIOS, "Hay identificadores prediales duplicados")

    fiscal_fields = {
        "impuesto_predial_estado",
        "deuda_predial_crc",
        "patente_estado",
        "licencia_estado",
        "licencia_vigencia_hasta",
    }
    require(fiscal_fields <= set(records[0]), "Faltan campos fiscales")

    stats = load_json("data/stats_index.json")
    require(stats["total"] == EXPECTED_PREDIOS, "El resumen no coincide con el indice")

    publication_gpkg = ROOT / "work" / "predios_garabito_publicacion.gpkg"
    require(publication_gpkg.is_file(), "Falta el GeoPackage usado para teselas")
    with sqlite3.connect(publication_gpkg) as db:
        layer = db.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' LIMIT 1"
        ).fetchone()[0]
        count, unique_ids, blank_ids = db.execute(
            f'SELECT COUNT(*), COUNT(DISTINCT fid_publicacion), '
            f'SUM(CASE WHEN fid_publicacion IS NULL OR TRIM(CAST(fid_publicacion AS TEXT)) = \'\' '
            f'THEN 1 ELSE 0 END) FROM "{layer}"'
        ).fetchone()
    require(count == EXPECTED_PREDIOS, "El GeoPackage de teselas no coincide")
    require(unique_ids == EXPECTED_PREDIOS and blank_ids == 0, "Identificadores de teselas invalidos")

    raster_manifest = load_json("layers/rasters/rasters_manifest.json")
    auxiliary_manifest = load_json("layers/capas_auxiliares_manifest.json")
    raster_ids = {item["id"] for item in raster_manifest["rasters"]}
    require({"dem", "hidrologia", "uso_suelo", "riesgo"} <= raster_ids, "Faltan rasteres")
    risk = next(item for item in raster_manifest["rasters"] if item["id"] == "riesgo")
    require(risk["title"] == "Susceptibilidad preliminar relativa", "Rotulo de susceptibilidad incorrecto")
    vector_titles = {item["id"]: item["title"] for item in auxiliary_manifest["vectors"]}
    require(vector_titles.get("roads") == "Vías Garabito", "Rotulo de vias incorrecto")
    require(vector_titles.get("drainage") == "Drenaje Garabito", "Rotulo de drenaje incorrecto")
    require(all("SNIT" not in title.upper() for title in vector_titles.values()), "Quedan fuentes en nombres visibles")

    app_js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    require('const LAYER_ID = "predios";' in app_js, "El estilo no apunta a la capa MVT predios")
    require('"public.v_predios": estiloPredio' in app_js, "Falta compatibilidad con teselas anteriores")
    require('color: "#000000"' in app_js, "El limite predial no es negro")
    require("patchVectorGridSvgTileRemoval" in app_js, "Falta parche de estabilidad de VectorGrid")

    asset_paths = [item["url"] for item in raster_manifest["rasters"]]
    asset_paths += [item["url"] for item in auxiliary_manifest["vectors"]]
    for relative in asset_paths:
        path = ROOT / relative
        require(path.is_file() and path.stat().st_size > 0, f"Falta activo: {relative}")
        if path.suffix.lower() == ".png":
            width, height = png_dimensions(path)
            require(width > 1 and height > 1, f"PNG sin dimensiones utiles: {relative}")

    tiles = list((ROOT / "tiles").rglob("*.pbf"))
    zooms = {int(tile.relative_to(ROOT / "tiles").parts[0]) for tile in tiles}
    missing_tiles = [path for path in expected_tile_paths() if not path.exists()]
    require(not missing_tiles, f"Faltan teselas vacias para evitar 404: {len(missing_tiles)}")
    require(len(tiles) >= 1_463, f"Teselas: {len(tiles)}")
    require(zooms == EXPECTED_ZOOMS, f"Zooms: {sorted(zooms)}")
    require(any(tile.stat().st_size > 0 for tile in tiles), "No hay teselas con predios")
    invalid_features = sum(count_invalid_mvt_features(tile) for tile in tiles)
    require(invalid_features == 0, f"Features MVT invalidas: {invalid_features}")

    if args.url:
        sample_tile = next(tile for tile in tiles if tile.stat().st_size > 0).relative_to(ROOT).as_posix()
        validate_http(
            args.url,
            [
                "index.html",
                "data/predios_index.json",
                "data/stats_index.json",
                "layers/rasters/rasters_manifest.json",
                risk["url"],
                sample_tile,
            ],
        )

    patents = sum(record.get("patente_estado") not in (None, "Sin patente") for record in records)
    print(f"OK predios={len(records):,} patentes={patents:,} tiles={len(tiles):,}")
    print(f"OK zooms={min(zooms)}-{max(zooms)} capas={len(asset_paths)} http={'si' if args.url else 'no'}")


if __name__ == "__main__":
    main()
