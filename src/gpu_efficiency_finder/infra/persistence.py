"""Infra: Sweep-Resultate als JSON speichern/laden und als CSV exportieren.

Bewusst KEIN NiceGUI-Persistent-Storage und kein verstecktes App-Verzeichnis: Es werden
ausschließlich Dateien geschrieben, die der Nutzer explizit auswählt (Export/Speichern).
So bleibt die portable App rückstandsfrei.

JSON erhält die vollständige :class:`SweepResult`-Struktur (Metadaten, alle Messzeilen und
die drei Betriebspunkte/Empfehlung) verlustfrei. Der CSV-Export ist eine flache
Mess-Tabelle für Tabellenkalkulationen.
"""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

from gpu_efficiency_finder.constants import OperatingPointKind
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import (
    OperatingPoint,
    Recommendation,
    SweepResult,
    SweepRow,
)

__all__ = ["export_csv", "load_run", "save_run"]

_LOG = get_logger(__name__)

# Spaltenüberschriften des flachen CSV-Exports (eine Zeile je Messpunkt).
_CSV_HEADER = (
    "set_watt",
    "pct",
    "power_w",
    "clock_mhz",
    "temp_c",
    "hotspot_c",
    "mem_temp_c",
    "voltage_mv",
    "avg_perf",
    "low_1",
    "low_01",
    "perf_per_w",
)


def save_run(result: SweepResult, path: str | Path) -> None:
    """Serialisiert ein vollständiges :class:`SweepResult` als UTF-8-JSON.

    Enums (``OperatingPointKind``) werden über ``default=str`` als ihr ``.value`` abgelegt
    (``StrEnum`` ist string-kompatibel). ``ensure_ascii=False`` erhält echte Umlaute.
    """
    target = Path(path)
    payload = dataclasses.asdict(result)
    with target.open("w", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    _LOG.info("Sweep-Resultat gespeichert: %s", target)


def load_run(path: str | Path) -> SweepResult:
    """Rekonstruiert ein :class:`SweepResult` aus einer JSON-Datei (defensiv)."""
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        data: dict[str, object] = json.load(handle)

    raw_rows = data.get("rows") or []
    rows = tuple(_row_from_dict(_as_dict(item)) for item in _as_list(raw_rows))
    result = SweepResult(
        gpu_name=str(data.get("gpu_name", "")),
        workload_name=str(data.get("workload_name", "")),
        timestamp=str(data.get("timestamp", "")),
        rows=rows,
        efficiency_peak=_point_from_dict(data.get("efficiency_peak")),
        knee=_point_from_dict(data.get("knee")),
        recommendation=_recommendation_from_dict(data.get("recommendation")),
        baseline_drift_pct=_opt_float(data.get("baseline_drift_pct")),
        config=_as_dict(data.get("config")),
    )
    _LOG.info("Sweep-Resultat geladen: %s (%d Zeilen)", source, len(rows))
    return result


def export_csv(result: SweepResult, path: str | Path) -> None:
    """Schreibt alle Messzeilen als flaches CSV (UTF-8). ``perf_per_w`` wird berechnet."""
    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_CSV_HEADER)
        for row in result.rows:
            writer.writerow(
                (
                    row.set_watt,
                    row.pct,
                    row.power_w,
                    row.clock_mhz,
                    row.temp_c,
                    _blank(row.hotspot_c),
                    _blank(row.mem_temp_c),
                    _blank(row.voltage_mv),
                    _blank(row.avg_perf),
                    _blank(row.low_1),
                    _blank(row.low_01),
                    _blank(_perf_per_w(row.avg_perf, row.power_w)),
                )
            )
    _LOG.info("CSV exportiert: %s (%d Zeilen)", target, len(result.rows))


def _perf_per_w(avg_perf: float | None, power_w: float | None) -> float | None:
    """Performance pro Watt, sofern beide Werte vorhanden und Leistung > 0 ist."""
    if avg_perf is None or power_w is None or power_w <= 0.0:
        return None
    return avg_perf / power_w


def _row_from_dict(data: dict[str, object]) -> SweepRow:
    """Baut eine :class:`SweepRow` aus einem (ggf. unvollständigen) Dict."""
    return SweepRow(
        set_watt=_req_float(data.get("set_watt")),
        pct=int(_req_float(data.get("pct"))),
        power_w=_req_float(data.get("power_w")),
        clock_mhz=_req_float(data.get("clock_mhz")),
        temp_c=_req_float(data.get("temp_c")),
        avg_perf=_opt_float(data.get("avg_perf")),
        low_1=_opt_float(data.get("low_1")),
        low_01=_opt_float(data.get("low_01")),
        voltage_mv=_opt_float(data.get("voltage_mv")),
        hotspot_c=_opt_float(data.get("hotspot_c")),
        mem_temp_c=_opt_float(data.get("mem_temp_c")),
    )


def _point_from_dict(value: object) -> OperatingPoint | None:
    """Baut einen :class:`OperatingPoint` oder ``None``."""
    if not isinstance(value, dict):
        return None
    return OperatingPoint(
        kind=OperatingPointKind(str(value.get("kind", OperatingPointKind.RECOMMENDATION))),
        set_watt=_req_float(value.get("set_watt")),
        power_w=_req_float(value.get("power_w")),
        pct_of_default=_req_float(value.get("pct_of_default")),
        savings_w=_req_float(value.get("savings_w")),
        savings_pct=_req_float(value.get("savings_pct")),
        avg_perf=_opt_float(value.get("avg_perf")),
        avg_perf_loss_pct=_opt_float(value.get("avg_perf_loss_pct")),
        low_1=_opt_float(value.get("low_1")),
        low_1_loss_pct=_opt_float(value.get("low_1_loss_pct")),
        perf_per_w=_opt_float(value.get("perf_per_w")),
    )


def _recommendation_from_dict(value: object) -> Recommendation | None:
    """Baut eine :class:`Recommendation` oder ``None``."""
    if not isinstance(value, dict):
        return None
    message = value.get("message")
    return Recommendation(
        recommended=_point_from_dict(value.get("recommended")),
        unconstrained_optimum=_point_from_dict(value.get("unconstrained_optimum")),
        floor_binding=bool(value.get("floor_binding", False)),
        extra_savings_w=_req_float(value.get("extra_savings_w")),
        extra_savings_pct=_req_float(value.get("extra_savings_pct")),
        satisfiable=bool(value.get("satisfiable", True)),
        message=str(message) if message is not None else None,
    )


def _as_dict(value: object) -> dict[str, object]:
    """Gibt ``value`` als Dict zurück, sonst ein leeres Dict (defensiv)."""
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    """Gibt ``value`` als Liste zurück, sonst eine leere Liste (defensiv)."""
    return list(value) if isinstance(value, list) else []


def _req_float(value: object) -> float:
    """Pflicht-Float: fehlende/ungültige Werte werden zu ``0.0``."""
    result = _opt_float(value)
    return result if result is not None else 0.0


def _opt_float(value: object) -> float | None:
    """Optionaler Float: ``None`` bleibt ``None``, sonst Konvertierung mit Fallback."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _blank(value: float | None) -> float | str:
    """CSV-Zelle: ``None`` wird zu leerem String, sonst der Wert selbst."""
    return "" if value is None else value
