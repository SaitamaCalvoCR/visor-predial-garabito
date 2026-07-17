"""Elimina features MVT invalidas que rompen Leaflet.VectorGrid.

QGIS puede emitir features con tipo 0 y geometria vacia en teselas de borde.
Leaflet.VectorGrid 1.3.0 no las ignora y falla al hacer zoom. Este limpiador
reescribe solo los mensajes Feature invalidos y conserva el resto de la tesela.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TILES_DIR = ROOT / "tiles"
VALID_GEOM_TYPES = {1, 2, 3}


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if pos >= len(data):
            raise EOFError("varint incompleto")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def skip_field(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:
        return read_varint(data, pos)[1]
    if wire_type == 1:
        return pos + 8
    if wire_type == 2:
        size, pos = read_varint(data, pos)
        return pos + size
    if wire_type == 5:
        return pos + 4
    raise ValueError(f"wire type no soportado: {wire_type}")


def read_field(data: bytes, pos: int) -> tuple[int, int, int, int, int]:
    start = pos
    key, pos = read_varint(data, pos)
    field_no = key >> 3
    wire_type = key & 7
    value_start = pos
    end = skip_field(data, pos, wire_type)
    return field_no, wire_type, value_start, end, start


def feature_is_valid(payload: bytes) -> bool:
    pos = 0
    geom_type = None
    geom_len = 0
    while pos < len(payload):
        field_no, wire_type, value_start, end, _ = read_field(payload, pos)
        if field_no == 3 and wire_type == 0:
            geom_type, _ = read_varint(payload, value_start)
        elif field_no == 4 and wire_type == 2:
            geom_len, _ = read_varint(payload, value_start)
        pos = end
    return geom_type in VALID_GEOM_TYPES and geom_len > 0


def clean_layer(payload: bytes) -> tuple[bytes, int]:
    out = bytearray()
    removed = 0
    pos = 0
    while pos < len(payload):
        field_no, wire_type, value_start, end, start = read_field(payload, pos)
        if field_no == 2 and wire_type == 2:
            size, feature_start = read_varint(payload, value_start)
            feature_payload = payload[feature_start : feature_start + size]
            if not feature_is_valid(feature_payload):
                removed += 1
                pos = end
                continue
        out += payload[start:end]
        pos = end
    return bytes(out), removed


def length_delimited(field_no: int, payload: bytes) -> bytes:
    return varint((field_no << 3) | 2) + varint(len(payload)) + payload


def clean_tile(path: Path) -> int:
    data = path.read_bytes()
    if not data:
        return 0

    out = bytearray()
    removed = 0
    pos = 0
    while pos < len(data):
        field_no, wire_type, value_start, end, start = read_field(data, pos)
        if field_no == 3 and wire_type == 2:
            size, layer_start = read_varint(data, value_start)
            layer_payload = data[layer_start : layer_start + size]
            cleaned_layer, layer_removed = clean_layer(layer_payload)
            out += length_delimited(3, cleaned_layer)
            removed += layer_removed
        else:
            out += data[start:end]
        pos = end

    if removed:
        path.write_bytes(bytes(out))
    return removed


def clean_tiles(tiles_dir: Path = TILES_DIR) -> tuple[int, int]:
    removed = 0
    changed = 0
    for path in tiles_dir.rglob("*.pbf"):
        count = clean_tile(path)
        if count:
            changed += 1
            removed += count
    return removed, changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiles-dir", default=str(TILES_DIR))
    args = parser.parse_args()

    removed, changed = clean_tiles(Path(args.tiles_dir))
    print(f"features_invalidas_eliminadas={removed:,} teselas_corregidas={changed:,}")


if __name__ == "__main__":
    main()
