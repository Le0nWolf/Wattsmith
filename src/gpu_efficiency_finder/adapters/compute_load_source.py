"""Adapter: erzeugt EIGENE GPU-Last über torch-CUDA und misst den Durchsatz.

Im Compute-Modus braucht es keinen externen Benchmark: ein Hintergrund-Thread führt
in einer Schleife große Matrix-Multiplikationen auf der GPU aus und zählt die
Iterationen. Der Performance-Skalar ist ``Iterationen/Sekunde`` im Zeitfenster.

``torch`` ist OPTIONAL und wird NICHT mit der EXE gebündelt (GB-groß). Der Import
erfolgt daher LAZY in :meth:`start`; fehlt torch oder CUDA, wird eine
:class:`GpuEfficiencyError` mit deutscher Meldung geworfen. Dieses Modul ist auch ohne
installiertes torch importierbar.

Liefert KEINE Lows (``low_1``/``low_01`` sind ``None``).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from gpu_efficiency_finder.errors import GpuEfficiencyError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import WindowMetrics

if TYPE_CHECKING:
    from types import ModuleType

__all__ = ["ComputeLoadSource"]

_LOG = get_logger(__name__)

# Kantenlänge der quadratischen Matrizen je Iteration (genug Last für moderne GPUs).
_MATRIX_SIZE = 4096


class ComputeLoadSource:
    """PerfSource, die selbst GPU-Last (torch-Matmul) erzeugt und Iterationen/s misst."""

    def __init__(self, gpu_index: int = 0, matrix_size: int = _MATRIX_SIZE) -> None:
        self._gpu_index = gpu_index
        self._matrix_size = matrix_size
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._timestamps: list[float] = []
        self._torch: ModuleType | None = None

    def start(self) -> None:
        """Importiert torch lazy, prüft CUDA und startet die Last-Schleife."""
        try:
            import torch
        except ImportError as exc:
            raise GpuEfficiencyError(
                "torch ist nicht installiert — Compute-Modus nicht verfügbar."
            ) from exc
        if not torch.cuda.is_available():
            raise GpuEfficiencyError(
                "Keine CUDA-fähige GPU für torch gefunden — Compute-Modus nicht verfügbar."
            )
        self._torch = torch
        with self._lock:
            self._timestamps.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._load_loop, name="compute-load", daemon=True)
        self._thread.start()
        _LOG.info("Compute-Last gestartet (GPU %d)", self._gpu_index)

    def _load_loop(self) -> None:
        """Führt fortlaufend Matmuls aus und speichert nach jeder Iteration die Zeit."""
        torch = self._torch
        if torch is None:
            return
        device = torch.device(f"cuda:{self._gpu_index}")
        size = self._matrix_size
        mat_a = torch.randn(size, size, device=device)
        mat_b = torch.randn(size, size, device=device)
        while not self._stop_event.is_set():
            result = mat_a @ mat_b
            torch.cuda.synchronize(device)
            # Ergebnis weiterverwenden, damit der Compiler die Matmul nicht wegoptimiert.
            mat_a = result * 0.0 + mat_a
            with self._lock:
                self._timestamps.append(time.monotonic())

    def stop(self) -> None:
        """Stoppt die Last-Schleife und wartet auf den Hintergrund-Thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._thread = None
        _LOG.info("Compute-Last gestoppt (GPU %d)", self._gpu_index)

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Iterationen/Sekunde aus allen Iterationszeitpunkten in [t_start, t_end]."""
        with self._lock:
            in_window = [t for t in self._timestamps if t_start <= t <= t_end]
        if len(in_window) < 2:
            return None
        span_s = max(in_window) - min(in_window)
        if span_s <= 0.0:
            return None
        iterations_per_second = (len(in_window) - 1) / span_s
        return WindowMetrics(avg_perf=iterations_per_second, low_1=None, low_01=None)
