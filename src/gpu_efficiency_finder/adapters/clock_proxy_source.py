"""Adapter: Performance-Proxy über den effektiven GPU-Grafiktakt (MHz).

Schnellster Mess-Modus: braucht weder PresentMon noch torch. Pollt die Telemetrie der
GPU in einem Hintergrund-Thread und nutzt den effektiven Grafiktakt als generischen
Performance-Skalar. Sinnvoll nur, wenn eine EXTERNE Last läuft (Benchmark/Spiel) — ohne
Last taktet die GPU herunter und der Proxy ist aussagelos.

Liefert KEINE Lows (``low_1``/``low_01`` sind ``None``): Takt ist keine Frame-Metrik.
Das Setzen des Power-Limits bleibt beim ``GpuBackend`` — diese Quelle ist rein lesend.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import WindowMetrics

if TYPE_CHECKING:
    from gpu_efficiency_finder.ports.gpu_backend import GpuBackend

__all__ = ["ClockProxySource"]

_LOG = get_logger(__name__)

# Abtastintervall der Takt-Telemetrie (Sekunden).
_POLL_INTERVAL_S = 0.5


class ClockProxySource:
    """PerfSource, die den GPU-Grafiktakt (MHz) als Performance-Proxy mittelt.

    Eine externe Last muss während der Messung laufen, sonst spiegelt der Takt nur den
    Leerlauf wider.
    """

    def __init__(self, gpu: GpuBackend, gpu_index: int) -> None:
        self._gpu = gpu
        self._gpu_index = gpu_index
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._samples: list[tuple[float, float]] = []

    def start(self) -> None:
        """Startet das Telemetrie-Polling in einem Hintergrund-Thread."""
        with self._lock:
            self._samples.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="clock-proxy-poll", daemon=True
        )
        self._thread.start()
        _LOG.info("Clock-Proxy-Messung gestartet (GPU %d)", self._gpu_index)

    def _poll_loop(self) -> None:
        """Liest periodisch den Grafiktakt und speichert ``(monotone Zeit, MHz)``."""
        while not self._stop_event.is_set():
            sample_time = time.monotonic()
            try:
                telemetry = self._gpu.read_telemetry(self._gpu_index)
            except Exception as exc:
                _LOG.warning("Takt-Telemetrie fehlgeschlagen: %s", exc)
            else:
                with self._lock:
                    self._samples.append((sample_time, telemetry.clock_mhz))
            self._stop_event.wait(_POLL_INTERVAL_S)

    def stop(self) -> None:
        """Stoppt das Polling und wartet auf den Hintergrund-Thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        _LOG.info("Clock-Proxy-Messung gestoppt (GPU %d)", self._gpu_index)

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Mittelt den Takt über alle Samples mit Zeit in [t_start, t_end]."""
        with self._lock:
            clocks = [
                mhz for (sample_time, mhz) in self._samples if t_start <= sample_time <= t_end
            ]
        if not clocks:
            return None
        avg_clock = sum(clocks) / len(clocks)
        return WindowMetrics(avg_perf=avg_clock, low_1=None, low_01=None)
