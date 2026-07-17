"""Agrega datos fiscales ficticios al indice del visor predial de Garabito.

Los valores son sinteticos y reproducibles. No representan informacion municipal
real; sirven para demostrar capacidades de integracion catastro + cobro +
patentes/licencias en el visor estatico.

Uso:
    py -3 tools/generar_demo_fiscal.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "predios_index.json"
STATS_PATH = ROOT / "data" / "stats_index.json"

FISCAL_FIELDS = [
    "impuesto_predial_estado",
    "impuesto_predial_periodo",
    "deuda_predial_crc",
    "ultimo_pago_predial",
    "patente_estado",
    "patente_numero",
    "patente_actividad",
    "deuda_patente_crc",
    "licencia_estado",
    "licencia_vigencia_hasta",
    "fiscal_score",
    "fiscal_alertas",
]

ACTIVIDADES = [
    "Alojamiento turistico",
    "Restaurante / soda",
    "Comercio al detalle",
    "Servicios profesionales",
    "Supermercado / abastecedor",
    "Tour operador",
    "Bar / entretenimiento",
    "Alquiler vacacional",
]


def stable_random(record: dict, seed: str) -> random.Random:
    key = f"{seed}|{record.get('fid')}|{record.get('id_predial')}|{record.get('numero_finca')}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def as_number(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def weighted_choice(rng: random.Random, choices: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in choices)
    pick = rng.random() * total
    running = 0.0
    for value, weight in choices:
        running += weight
        if pick <= running:
            return value
    return choices[-1][0]


def commercial_probability(record: dict) -> float:
    area = as_number(record.get("area_m2"))
    value = as_number(record.get("valor_terreno_zh"))
    distrito = str(record.get("distrito") or "")
    priority = str(record.get("prioridad_fiscalizacion") or "")
    p = 0.08
    if distrito == "01":
        p += 0.10
    if bool(record.get("frente_calle")):
        p += 0.08
    if area > 700:
        p += 0.05
    if area > 5000:
        p += 0.04
    if value >= 30000:
        p += 0.07
    if value >= 100000:
        p += 0.08
    if priority == "Alta":
        p += 0.04
    return min(p, 0.68)


def money_round(value: float) -> int:
    return int(round(value / 1000.0) * 1000)


def fake_recent_date(rng: random.Random, today: date, max_days: int) -> str:
    return (today - timedelta(days=rng.randint(2, max_days))).isoformat()


def fake_future_date(rng: random.Random, today: date, min_days: int, max_days: int) -> str:
    return (today + timedelta(days=rng.randint(min_days, max_days))).isoformat()


def build_fiscal_record(record: dict, rng: random.Random, today: date) -> dict:
    area = max(as_number(record.get("area_m2")), 1.0)
    value = max(as_number(record.get("valor_terreno_zh"), 12000.0), 1.0)
    base_value = area * value

    predial_estado = weighted_choice(
        rng,
        [
            ("Al dia", 0.66),
            ("Moroso", 0.23),
            ("Arreglo de pago", 0.08),
            ("Exonerado / especial", 0.03),
        ],
    )
    yearly_tax = max(base_value * 0.0025, 18000)
    if predial_estado == "Al dia":
        deuda_predial = 0
        ultimo_pago = fake_recent_date(rng, today, 120)
    elif predial_estado == "Exonerado / especial":
        deuda_predial = 0
        ultimo_pago = fake_recent_date(rng, today, 240)
    elif predial_estado == "Arreglo de pago":
        deuda_predial = money_round(yearly_tax * rng.uniform(0.25, 1.1))
        ultimo_pago = fake_recent_date(rng, today, 210)
    else:
        deuda_predial = money_round(yearly_tax * rng.uniform(0.45, 2.8))
        ultimo_pago = fake_recent_date(rng, today, 720)

    has_patente = rng.random() < commercial_probability(record)
    if has_patente:
        patente_estado = weighted_choice(
            rng,
            [("Patente al dia", 0.62), ("Patente morosa", 0.25), ("Patente suspendida", 0.13)],
        )
        actividad = rng.choice(ACTIVIDADES)
        patente_numero = f"PAT-GRB-{int(record.get('fid') or 0):05d}"
        if patente_estado == "Patente al dia":
            deuda_patente = 0
        elif patente_estado == "Patente suspendida":
            deuda_patente = money_round(rng.uniform(90000, 650000))
        else:
            deuda_patente = money_round(rng.uniform(45000, 420000))

        licencia_estado = weighted_choice(
            rng,
            [("Vigente", 0.70), ("Por vencer", 0.12), ("Vencida", 0.18)],
        )
        if licencia_estado == "Vigente":
            vigencia = fake_future_date(rng, today, 60, 720)
        elif licencia_estado == "Por vencer":
            vigencia = fake_future_date(rng, today, 1, 59)
        else:
            vigencia = (today - timedelta(days=rng.randint(1, 540))).isoformat()
    else:
        patente_estado = "Sin patente"
        actividad = None
        patente_numero = None
        deuda_patente = 0
        licencia_estado = "Sin licencia"
        vigencia = None

    alertas = []
    score = 0
    if predial_estado == "Moroso":
        alertas.append("Impuesto predial moroso")
        score += 45
    elif predial_estado == "Arreglo de pago":
        alertas.append("Arreglo de pago activo")
        score += 22
    if deuda_predial >= 500000:
        alertas.append("Deuda predial alta")
        score += 20
    if patente_estado in {"Patente morosa", "Patente suspendida"}:
        alertas.append(patente_estado)
        score += 35
    if deuda_patente >= 250000:
        alertas.append("Deuda de patente alta")
        score += 16
    if licencia_estado == "Vencida":
        alertas.append("Licencia vencida")
        score += 30
    elif licencia_estado == "Por vencer":
        alertas.append("Licencia por vencer")
        score += 12

    return {
        "impuesto_predial_estado": predial_estado,
        "impuesto_predial_periodo": "2026",
        "deuda_predial_crc": deuda_predial,
        "ultimo_pago_predial": ultimo_pago,
        "patente_estado": patente_estado,
        "patente_numero": patente_numero,
        "patente_actividad": actividad,
        "deuda_patente_crc": deuda_patente,
        "licencia_estado": licencia_estado,
        "licencia_vigencia_hasta": vigencia,
        "fiscal_score": min(score, 100),
        "fiscal_alertas": alertas,
    }


def summarize(records: list[dict], generated_at: str) -> dict:
    predial = Counter(r.get("impuesto_predial_estado") or "Sin dato" for r in records)
    patente = Counter(r.get("patente_estado") or "Sin dato" for r in records)
    licencia = Counter(r.get("licencia_estado") or "Sin dato" for r in records)
    alertas = Counter()
    for record in records:
        alertas.update(record.get("fiscal_alertas") or [])

    total_deuda_predial = sum(int(r.get("deuda_predial_crc") or 0) for r in records)
    total_deuda_patente = sum(int(r.get("deuda_patente_crc") or 0) for r in records)
    con_patente = sum(1 for r in records if r.get("patente_estado") != "Sin patente")
    casos_criticos = sum(1 for r in records if int(r.get("fiscal_score") or 0) >= 60)

    return {
        "generated_at": generated_at,
        "note": "Datos fiscales sinteticos para demostracion; no son datos oficiales.",
        "total": len(records),
        "predial": dict(predial),
        "patentes": dict(patente),
        "licencias": dict(licencia),
        "total_deuda_predial_crc": total_deuda_predial,
        "total_deuda_patente_crc": total_deuda_patente,
        "predios_con_patente": con_patente,
        "casos_criticos": casos_criticos,
        "alertas": alertas.most_common(10),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera demo fiscal ficticio para el visor Garabito.")
    parser.add_argument("--index", default=str(INDEX_PATH))
    parser.add_argument("--stats", default=str(STATS_PATH))
    parser.add_argument("--seed", default="garabito-demo-fiscal-2026")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    index_path = Path(args.index)
    stats_path = Path(args.stats)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    today = date.today()

    if not args.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(index_path, index_path.with_suffix(f".backup_demo_fiscal_{stamp}.json"))
        if stats_path.exists():
            shutil.copy2(stats_path, stats_path.with_suffix(f".backup_demo_fiscal_{stamp}.json"))

    for record in records:
        rng = stable_random(record, args.seed)
        record.update(build_fiscal_record(record, rng, today))

    fields = payload.setdefault("fields", [])
    for field in FISCAL_FIELDS:
        if field not in fields:
            fields.append(field)
    payload["demo_fiscal"] = {
        "enabled": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "note": "Datos fiscales sinteticos para demostracion; no son datos oficiales.",
    }

    index_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    stats_payload = {}
    if stats_path.exists():
        stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
    stats_payload["fiscal"] = summarize(records, payload["demo_fiscal"]["generated_at"])
    stats_path.write_text(json.dumps(stats_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    fiscal = stats_payload["fiscal"]
    print(f"Predios enriquecidos: {len(records):,}")
    print(f"Con patente ficticia: {fiscal['predios_con_patente']:,}")
    print(f"Casos criticos ficticios: {fiscal['casos_criticos']:,}")
    print(f"Deuda predial ficticia: {fiscal['total_deuda_predial_crc']:,} CRC")
    print(f"Deuda patente ficticia: {fiscal['total_deuda_patente_crc']:,} CRC")


if __name__ == "__main__":
    main()
