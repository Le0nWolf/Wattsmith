"""UI-Baustein: plotly-Diagramm der Effizienzkurve.

Zeigt die Performance über dem TATSÄCHLICH gemessenen Verbrauch (``power_w``, x-Achse):
``avg_perf`` als durchgezogene, ``low_1`` als gestrichelte Linie. Markiert Effizienz-Peak,
Knie und Empfehlung; optional eine horizontale Linie für die FPS-Untergrenze. Die x-Achse
trägt Watt; die Betriebspunkte zeigen zusätzlich ``% vom Default`` im Hover/Label.

Dünne Hülle um ``ui.plotly`` — keine Domain-Logik, nur Darstellung.
"""

from __future__ import annotations

from nicegui import ui

from gpu_efficiency_finder.models import OperatingPoint, Recommendation, SweepRow

__all__ = ["EfficiencyChart"]

_ACCENT = "#26a69a"
_LOW_COLOR = "#ffa726"
_PEAK_COLOR = "#42a5f5"
_KNEE_COLOR = "#ab47bc"
_REC_COLOR = "#66bb6a"
_PAPER_BG = "#1d1d1d"
_PLOT_BG = "#1d1d1d"
_FONT_COLOR = "#e0e0e0"


def _base_layout() -> dict[str, object]:
    """Gemeinsames, dunkles Layout für leere und gefüllte Diagramme."""
    return {
        "paper_bgcolor": _PAPER_BG,
        "plot_bgcolor": _PLOT_BG,
        "font": {"color": _FONT_COLOR},
        "margin": {"l": 60, "r": 20, "t": 40, "b": 50},
        "xaxis": {"title": "gemessener Verbrauch (W)", "gridcolor": "#333"},
        "yaxis": {"title": "Performance (Ø-Perf / Lows)", "gridcolor": "#333"},
        "legend": {"orientation": "h", "y": 1.12},
        "title": "Effizienzkurve",
    }


def _marker(
    point: OperatingPoint | None,
    color: str,
    label: str,
    *,
    size: int,
    symbol: str,
) -> dict[str, object] | None:
    """Erzeugt eine plotly-Trace (einzelner Punkt) für einen Betriebspunkt.

    Unterschiedliche Größen/Symbole, damit zusammenfallende Punkte (z. B. Knie == Peak)
    sichtbar bleiben (der große Ring umschließt das kleinere Symbol).
    """
    if point is None or point.avg_perf is None:
        return None
    text = f"{label}<br>{point.set_watt:.0f} W ({point.pct_of_default:.0f}% vom Default)"
    return {
        "x": [point.power_w],
        "y": [point.avg_perf],
        "mode": "markers",
        "type": "scatter",
        "name": label,
        "marker": {
            "size": size,
            "color": color,
            "symbol": symbol,
            "line": {"width": 2, "color": "#fff"},
        },
        "hovertext": [text],
        "hoverinfo": "text",
    }


class EfficiencyChart:
    """plotly-Diagramm der Sweep-Ergebnisse mit ausgezeichneten Betriebspunkten."""

    def __init__(self) -> None:
        self._plot = ui.plotly(self._empty_figure()).classes("w-full").style("height: 420px")

    def _empty_figure(self) -> dict[str, object]:
        """Leeres, beschriftetes Diagramm (vor dem ersten Sweep)."""
        layout = _base_layout()
        layout["annotations"] = [
            {
                "text": "Noch keine Messdaten — „Sweep starten“ klicken.",
                "showarrow": False,
                "font": {"color": "#888"},
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
            }
        ]
        return {"data": [], "layout": layout}

    def update(
        self,
        rows: list[SweepRow],
        *,
        peak: OperatingPoint | None = None,
        knee: OperatingPoint | None = None,
        recommendation: Recommendation | None = None,
        fps_floor: float | None = None,
    ) -> None:
        """Aktualisiert das Diagramm mit Messzeilen und Betriebspunkten."""
        scored = sorted(
            (r for r in rows if r.avg_perf is not None and r.power_w > 0),
            key=lambda r: r.power_w,
        )
        if not scored:
            self._plot.figure = self._empty_figure()
            self._plot.update()
            return
        self._plot.figure = self._build_figure(scored, peak, knee, recommendation, fps_floor)
        self._plot.update()

    def _build_figure(
        self,
        scored: list[SweepRow],
        peak: OperatingPoint | None,
        knee: OperatingPoint | None,
        recommendation: Recommendation | None,
        fps_floor: float | None,
    ) -> dict[str, object]:
        xs = [r.power_w for r in scored]
        avg = [r.avg_perf for r in scored]
        data: list[dict[str, object]] = [
            {
                "x": xs,
                "y": avg,
                "mode": "lines+markers",
                "type": "scatter",
                "name": "Ø-Perf",
                "line": {"color": _ACCENT, "width": 2},
            }
        ]
        lows = [r.low_1 for r in scored]
        if any(v is not None for v in lows):
            data.append(
                {
                    "x": xs,
                    "y": lows,
                    "mode": "lines+markers",
                    "type": "scatter",
                    "name": "1% Low",
                    "line": {"color": _LOW_COLOR, "width": 2, "dash": "dash"},
                }
            )
        recommended = recommendation.recommended if recommendation else None
        # Großer offener Ring (Peak) zuerst, damit kleinere Symbole darauf sichtbar bleiben.
        for point, color, label, size, symbol in (
            (peak, _PEAK_COLOR, "Effizienz-Peak", 22, "circle-open"),
            (knee, _KNEE_COLOR, "Knie", 13, "diamond"),
            (recommended, _REC_COLOR, "Empfehlung", 12, "star"),
        ):
            trace = _marker(point, color, label, size=size, symbol=symbol)
            if trace is not None:
                data.append(trace)

        layout = _base_layout()
        if fps_floor is not None:
            layout["shapes"] = [
                {
                    "type": "line",
                    "xref": "paper",
                    "x0": 0,
                    "x1": 1,
                    "yref": "y",
                    "y0": fps_floor,
                    "y1": fps_floor,
                    "line": {"color": "#ef5350", "width": 1, "dash": "dot"},
                }
            ]
            layout["annotations"] = [
                {
                    "text": f"FPS-Untergrenze {fps_floor:.0f}",
                    "showarrow": False,
                    "xref": "paper",
                    "x": 0.0,
                    "yref": "y",
                    "y": fps_floor,
                    "font": {"color": "#ef5350"},
                    "yshift": 10,
                }
            ]
        return {"data": data, "layout": layout}
