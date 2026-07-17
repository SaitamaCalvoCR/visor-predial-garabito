"""Completa la piramide MVT con teselas vacias.

Leaflet.VectorGrid intenta cargar todas las teselas dentro de los bounds del
visor. Si una tesela no existe porque no contiene predios, GitHub Pages devuelve
404 y VectorGrid puede lanzar errores internos. Este script crea PBF de cero
bytes para esos huecos: el navegador recibe HTTP 200, pero VectorGrid no crea
capas internas sin features que luego fallen al hacer zoom.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TILES_DIR = ROOT / "tiles"
MIN_ZOOM = 10
MAX_ZOOM = 16
BOUNDS = {
    "south": 9.5145,
    "west": -84.7237,
    "north": 9.9008,
    "east": -84.5066,
}


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


def expected_tile_paths(tiles_dir: Path = TILES_DIR) -> list[Path]:
    paths: list[Path] = []
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        min_x = lon_to_x(BOUNDS["west"], zoom)
        max_x = lon_to_x(BOUNDS["east"], zoom)
        min_y = lat_to_y(BOUNDS["north"], zoom)
        max_y = lat_to_y(BOUNDS["south"], zoom)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                paths.append(tiles_dir / str(zoom) / str(x) / f"{y}.pbf")
    return paths


def complete_empty_tiles(tiles_dir: Path = TILES_DIR) -> tuple[int, int, int]:
    expected = expected_tile_paths(tiles_dir)
    created = 0
    existing = 0
    for path in expected:
        if path.exists():
            existing += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        created += 1
    return existing, created, len(expected)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiles-dir", default=str(TILES_DIR))
    args = parser.parse_args()

    existing, created, total = complete_empty_tiles(Path(args.tiles_dir))
    print(f"teselas existentes={existing:,} creadas={created:,} total_cobertura={total:,}")


if __name__ == "__main__":
    main()
