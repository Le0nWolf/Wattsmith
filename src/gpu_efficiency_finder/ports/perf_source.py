"""Port: Performance-/Telemetrie-Quelle."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gpu_efficiency_finder.models import WindowMetrics

__all__ = ["PerfSource"]


@runtime_checkable
class PerfSource(Protocol):
    """Liefert Performance-Metriken über ein Zeitfenster.

    Implementierungen: PresentMon (echte FPS + Lows), Compute (torch-Durchsatz),
    ClockProxy (Takt als Proxy), HWiNFO (gemittelte Telemetrie/FPS).
    """

    def start(self) -> None:
        """Startet die Messung (z. B. PresentMon-Subprozess)."""
        ...

    def stop(self) -> None:
        """Beendet die Messung und gibt Ressourcen frei."""
        ...

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Metriken für das Zeitfenster [t_start, t_end] (monotone Zeit, Sekunden).

        ``None``, wenn im Fenster keine Daten vorliegen.
        """
        ...
