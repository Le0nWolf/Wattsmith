"""Adapter: Präzisions-Performance-Quelle über PresentMon (GameTechDev, MIT).

Startet die PresentMon-Konsolen-EXE als Subprozess, liest die v1-CSV vom STDOUT in
einem Hintergrund-Thread und speichert pro Frame ``(Empfangszeit, Frametime_ms)``.
Die Empfangszeit wird beim EINLESEN der Zeile mit :func:`time.monotonic` gesetzt —
PresentMons interne Zeitstempel werden bewusst NICHT verwendet, da sie nicht zur
monotonen Fensterachse der Sweep-Engine passen.

Die FPS-/Low-Berechnung wird vollständig an :mod:`domain.analysis` delegiert (DRY).
Kein Subprozess wird beim Import gestartet.
"""

from __future__ import annotations

import csv
import subprocess
import threading
import time

from gpu_efficiency_finder.domain import analysis
from gpu_efficiency_finder.errors import PresentMonError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import WindowMetrics

__all__ = ["PresentMonSource", "find_frametime_column"]

_LOG = get_logger(__name__)

# Bevorzugte und alternative Spaltennamen für die Frametime (Millisekunden je Frame).
_PREFERRED_FRAMETIME_COLUMN = "msbetweenpresents"
_ALTERNATIVE_FRAMETIME_COLUMNS = ("frametime", "msbetweenpresents")


def find_frametime_column(header: list[str]) -> int | None:
    """Sucht in einem PresentMon-v1-CSV-Header (case-insensitiv) die Frametime-Spalte.

    Bevorzugt ``MsBetweenPresents``; akzeptiert alternativ ``FrameTime`` /
    ``msBetweenPresents``. Gibt den Spaltenindex zurück oder ``None``, wenn keine
    passende Spalte gefunden wurde.
    """
    normalized = [col.strip().lower() for col in header]
    if _PREFERRED_FRAMETIME_COLUMN in normalized:
        return normalized.index(_PREFERRED_FRAMETIME_COLUMN)
    for alternative in _ALTERNATIVE_FRAMETIME_COLUMNS:
        if alternative in normalized:
            return normalized.index(alternative)
    return None


class PresentMonSource:
    """PerfSource über PresentMon: echte FPS sowie 1%/0.1% Low.

    PresentMon nutzt ETW und braucht Administrator-Rechte. Die zu messende Anwendung
    muss bereits rendern; ``process_name`` ist der tatsächlich rendernde Prozess.
    """

    def __init__(self, exe_path: str, process_name: str) -> None:
        self._exe_path = exe_path
        self._process_name = process_name
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._samples: list[tuple[float, float]] = []
        self._frametime_col: int | None = None

    def start(self) -> None:
        """Startet PresentMon und liest STDOUT in einem Hintergrund-Thread."""
        args = [
            self._exe_path,
            "--output_stdout",
            "--process_name",
            self._process_name,
            "--v1_metrics",
            "--no_console_stats",
            "--stop_existing_session",
        ]
        with self._lock:
            self._samples.clear()
        self._frametime_col = None
        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise PresentMonError(
                f"PresentMon konnte nicht gestartet werden ({self._exe_path}): {exc}"
            ) from exc
        self._reader = threading.Thread(
            target=self._read_loop, name="presentmon-reader", daemon=True
        )
        self._reader.start()
        _LOG.info("PresentMon gestartet für Prozess '%s'", self._process_name)

    def _read_loop(self) -> None:
        """Liest jede STDOUT-Zeile, parst sie defensiv und speichert die Frametime."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        reader = csv.reader(iter(proc.stdout.readline, ""))
        for row in reader:
            recv_time = time.monotonic()
            if not row:
                continue
            if self._frametime_col is None:
                self._frametime_col = find_frametime_column(row)
                if self._frametime_col is None:
                    _LOG.debug("PresentMon-Header ohne Frametime-Spalte: %r", row)
                # Header-Zeile selbst enthält keine Messwerte.
                continue
            self._record_row(row, recv_time)

    def _record_row(self, row: list[str], recv_time: float) -> None:
        """Extrahiert die Frametime einer Datenzeile und speichert sie thread-sicher."""
        col = self._frametime_col
        if col is None or col >= len(row):
            return
        try:
            frametime_ms = float(row[col])
        except (ValueError, TypeError):
            return
        if frametime_ms <= 0.0:
            return
        with self._lock:
            self._samples.append((recv_time, frametime_ms))

    def stop(self) -> None:
        """Beendet den Subprozess und wartet auf den Reader-Thread."""
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5.0)
            except OSError as exc:
                _LOG.warning("PresentMon-Stop fehlgeschlagen: %s", exc)
        if self._reader is not None:
            self._reader.join(timeout=5.0)
        self._proc = None
        self._reader = None
        _LOG.info("PresentMon gestoppt")

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Baut die Metriken aus allen Frametimes mit ``recv_time`` in [t_start, t_end]."""
        with self._lock:
            frametimes = [ft for (recv_time, ft) in self._samples if t_start <= recv_time <= t_end]
        if not frametimes:
            return None
        avg = analysis.avg_fps(frametimes)
        if avg is None:
            return None
        return WindowMetrics(
            avg_perf=avg,
            low_1=analysis.low_fps(frametimes, 1.0),
            low_01=analysis.low_fps(frametimes, 0.1),
        )
