"""Compacta data/predios_index.json y separa un resumen agregado ligero.

Quita de cada registro los campos que el frontend nunca lee (`observaciones`) o que
recalcula siempre en el cliente como fallback (`issues`, `issue_score`, `priority`,
`estado`, `distrito_nombre` en js/app.js -> normalizeRecord/detectIssues/classifyPriority),
usando los valores ya presentes en el archivo actual (misma fuente de verdad, sin
reimplementar las reglas de negocio) para construir data/stats_index.json: un resumen
agregado (KPIs de calidad, ranking de alertas, estadisticas por distrito) que el visor
puede pintar de inmediato mientras el archivo completo de predios sigue cargando.

Uso:
    python tools/optimizar_predios_index.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "predios_index.json"
STATS_PATH = ROOT / "data" / "stats_index.json"

FIELDS_TO_DROP = ["observaciones", "issues", "issue_score", "priority", "estado", "distrito_nombre"]

DISTRICT_COLORS = {
    "Jacó": "#f59e0b",
    "Tárcoles": "#0ea5e9",
    "Lagunillas": "#65a30d",
}
HIGH_SLOPE = 25
SMALL_AREA = 25


def has_value(value):
    return value is not None and str(value).strip() != ""


def enrich_for_stats(records):
    duplicate_fields = ["id_predial", "numero_finca", "plano"]
    counts = {field: defaultdict(int) for field in duplicate_fields}
    for record in records:
        for field in duplicate_fields:
            value = str(record.get(field) or "").strip()
            if value:
                counts[field][value] += 1

    district_names = {"01": "Jaco", "02": "Tarcoles", "03": "Lagunillas"}
    for record in records:
        issues = []
        for field, missing_label, duplicate_label in [
            ("id_predial", "Sin codigo predial", "Codigo predial duplicado"),
            ("numero_finca", "Sin finca", "Finca duplicada"),
            ("plano", "Sin plano", "Plano duplicado"),
        ]:
            value = str(record.get(field) or "").strip()
            if not value:
                issues.append(missing_label)
            elif counts[field][value] > 1:
                issues.append(duplicate_label)

        area = record.get("area_m2")
        if not isinstance(area, (int, float)) or area <= 0 or area < SMALL_AREA:
            issues.append("Area sospechosa")
        if not has_value(record.get("distrito")):
            issues.append("Sin distrito")
        slope = record.get("pendiente_media")
        if isinstance(slope, (int, float)) and slope >= HIGH_SLOPE:
            issues.append("Pendiente alta")
        if "irregular" in str(record.get("regularidad_geom") or "").lower():
            issues.append("Geometria irregular")
        if record.get("frente_calle") in (False, 0):
            issues.append("Sin frente a calle")

        score = 0
        for issue in issues:
            if issue in ("Sin codigo predial", "Sin finca"):
                score += 5
            elif "duplicado" in issue.lower():
                score += 4
            elif issue in ("Sin plano", "Sin distrito"):
                score += 3
            elif issue in ("Pendiente alta", "Area sospechosa", "Geometria irregular"):
                score += 2
            else:
                score += 1

        district = str(record.get("distrito") or "").strip().zfill(2)
        record["distrito_nombre"] = district_names.get(district, "Otro / sin dato")
        record["issues"] = issues
        record["issue_score"] = score
        record["estado"] = "Completo" if score == 0 else "Incompleto"
        record["priority"] = (
            "Alta" if score >= 7 else "Media" if score >= 3 else "Baja" if score else "Sin alertas"
        )


def build_stats(records, generated_at):
    enrich_for_stats(records)
    quality = dict(missingCode=0, missingFinca=0, missingPlano=0, duplicates=0, highSlope=0, complete=0, review=0)
    issue_counts = defaultdict(int)
    districts = {}

    for record in records:
        if not has_value(record.get("id_predial")):
            quality["missingCode"] += 1
        if not has_value(record.get("numero_finca")):
            quality["missingFinca"] += 1
        if not has_value(record.get("plano")):
            quality["missingPlano"] += 1
        if record.get("issues"):
            for issue in record["issues"]:
                issue_counts[issue] += 1
        slope = record.get("pendiente_media")
        if isinstance(slope, (int, float)) and slope >= HIGH_SLOPE:
            quality["highSlope"] += 1
        if record.get("estado") == "Completo":
            quality["complete"] += 1
        elif record.get("estado") == "Requiere revisión":
            quality["review"] += 1

        name = record.get("distrito_nombre") or "Otro / sin dato"
        g = districts.setdefault(name, dict(
            name=name, color=DISTRICT_COLORS.get(name, "#94a3b8"),
            count=0, area=0.0, areaCount=0, missingFinca=0, missingCode=0, missingPlano=0,
            highSlope=0, valueSum=0.0, valueCount=0, problems=0,
        ))
        g["count"] += 1
        area = record.get("area_m2")
        if isinstance(area, (int, float)):
            g["area"] += area
            g["areaCount"] += 1
        if not has_value(record.get("numero_finca")):
            g["missingFinca"] += 1
        if not has_value(record.get("id_predial")):
            g["missingCode"] += 1
        if not has_value(record.get("plano")):
            g["missingPlano"] += 1
        if isinstance(slope, (int, float)) and slope >= HIGH_SLOPE:
            g["highSlope"] += 1
        value = record.get("valor_terreno_zh")
        if isinstance(value, (int, float)):
            g["valueSum"] += value
            g["valueCount"] += 1
        if record.get("issues"):
            g["problems"] += 1

    quality["complete"] = sum(1 for r in records if r.get("issue_score", 0) == 0)
    quality["review"] = sum(
        1
        for r in records
        if r.get("issue_score", 0) >= 7 or len(r.get("issues") or []) >= 3
    )

    # duplicates: quality["duplicates"] contado por-ocurrencia arriba duplicaria el conteo
    # de predios; recalcular como cantidad de predios con alguna alerta de duplicado.
    quality["duplicates"] = sum(
        1 for r in records
        if any("duplicad" in issue for issue in (r.get("issues") or []))
    )

    issue_ranking = sorted(issue_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "generated_at": generated_at,
        "total": len(records),
        "quality": quality,
        "issue_ranking": issue_ranking,
        "districts": sorted(districts.values(), key=lambda g: g["count"], reverse=True),
    }


def main():
    with open(INDEX_PATH, encoding="utf-8") as f:
        payload = json.load(f)

    records = payload["records"]
    before_bytes = INDEX_PATH.stat().st_size

    stats = build_stats(records, payload.get("generated_at"))
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))

    for record in records:
        for field in FIELDS_TO_DROP:
            record.pop(field, None)

    payload["records"] = records
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    after_bytes = INDEX_PATH.stat().st_size
    stats_bytes = STATS_PATH.stat().st_size
    print(f"predios_index.json: {before_bytes:,} -> {after_bytes:,} bytes "
          f"({100 * (1 - after_bytes / before_bytes):.1f}% menos)")
    print(f"stats_index.json: {stats_bytes:,} bytes")


if __name__ == "__main__":
    main()
