"""UI-Baustein: Ergebnis-Tabelle der gemessenen Sweep-Stufen.

Dünne Hülle um ``ui.table`` — zeigt pro Stufe das gesetzte Limit, den tatsächlich
gemessenen Verbrauch, Takt/Temperatur und die Performance-Metriken. ``perf_per_w`` wird
hier aus ``avg_perf / power_w`` berechnet (Anzeige-Detail, keine Domain-Logik).
"""

from __future__ import annotations

from nicegui import ui

from gpu_efficiency_finder.models import SweepRow

__all__ = ["ResultsTable"]

# Spalten-Definition: name (interner Key) + deutsches Label mit echten Umlauten.
_COLUMNS: list[dict[str, object]] = [
    {
        "name": "set_watt",
        "label": "Limit (W)",
        "field": "set_watt",
        "align": "right",
        "sortable": True,
    },
    {"name": "pct", "label": "gesetzt %", "field": "pct", "align": "right", "sortable": True},
    {
        "name": "power_w",
        "label": "gemessen W",
        "field": "power_w",
        "align": "right",
        "sortable": True,
    },
    {
        "name": "clock_mhz",
        "label": "Takt MHz",
        "field": "clock_mhz",
        "align": "right",
        "sortable": True,
    },
    {"name": "temp_c", "label": "Temp °C", "field": "temp_c", "align": "right", "sortable": True},
    {
        "name": "hotspot_c",
        "label": "Hotspot °C",
        "field": "hotspot_c",
        "align": "right",
        "sortable": True,
    },
    {
        "name": "mem_temp_c",
        "label": "Speicher °C",
        "field": "mem_temp_c",
        "align": "right",
        "sortable": True,
    },
    {
        "name": "voltage_mv",
        "label": "Spannung mV",
        "field": "voltage_mv",
        "align": "right",
        "sortable": True,
    },
    {
        "name": "avg_perf",
        "label": "Ø-Perf",
        "field": "avg_perf",
        "align": "right",
        "sortable": True,
    },
    {"name": "low_1", "label": "1% Low", "field": "low_1", "align": "right", "sortable": True},
    {"name": "low_01", "label": "0.1% Low", "field": "low_01", "align": "right", "sortable": True},
    {
        "name": "perf_per_w",
        "label": "Perf/W",
        "field": "perf_per_w",
        "align": "right",
        "sortable": True,
    },
]


def _fmt(value: float | None, digits: int = 1) -> str:
    """Formatiert eine optionale Zahl; leere Zelle (``–``) bei ``None``."""
    if value is None:
        return "–"
    return f"{value:.{digits}f}"


class ResultsTable:
    """Tabellarische Sicht auf alle gemessenen Sweep-Stufen."""

    def __init__(self) -> None:
        self._table = ui.table(
            columns=_COLUMNS,
            rows=[],
            row_key="set_watt",
        ).classes("w-full")
        self._table.props("dense flat dark")

    def update(self, rows: list[SweepRow]) -> None:
        """Übernimmt die Sweep-Zeilen in die Tabelle (absteigend nach gesetztem Limit)."""
        ordered = sorted(rows, key=lambda r: r.set_watt, reverse=True)
        self._table.rows = [self._to_row(r) for r in ordered]
        self._table.update()

    def clear(self) -> None:
        """Leert die Tabelle."""
        self._table.rows = []
        self._table.update()

    @staticmethod
    def _to_row(row: SweepRow) -> dict[str, str]:
        """Wandelt eine ``SweepRow`` in eine darstellbare Zeile (alle Werte als Strings)."""
        perf_per_w: float | None = None
        if row.avg_perf is not None and row.power_w > 0:
            perf_per_w = row.avg_perf / row.power_w
        return {
            "set_watt": _fmt(row.set_watt, 0),
            "pct": f"{row.pct}",
            "power_w": _fmt(row.power_w, 0),
            "clock_mhz": _fmt(row.clock_mhz, 0),
            "temp_c": _fmt(row.temp_c, 0),
            "hotspot_c": _fmt(row.hotspot_c, 0),
            "mem_temp_c": _fmt(row.mem_temp_c, 0),
            "voltage_mv": _fmt(row.voltage_mv, 0),
            "avg_perf": _fmt(row.avg_perf, 1),
            "low_1": _fmt(row.low_1, 1),
            "low_01": _fmt(row.low_01, 1),
            "perf_per_w": _fmt(perf_per_w, 3),
        }
