"""Adapter: externer Benchmark als konstante GPU-Last (BenchmarkRunner-Port).

Startet einen frei konfigurierbaren Befehl (z. B. Unigine Superposition im Loop) als
Subprozess und beendet beim Stoppen den GESAMTEN Prozessbaum. Benchmark-Launcher starten
den tatsächlich rendernden Prozess häufig als Kindprozess — würde man nur den Launcher
beenden, liefe der Render-Prozess weiter. Deshalb wird über :mod:`psutil` der komplette
Baum eingesammelt und terminiert.

Ist der Befehl leer, ist :meth:`start` ein No-Op — der Nutzer startet die Last dann
manuell. Beim Import wird nichts gestartet.
"""

from __future__ import annotations

import contextlib
import shlex
import subprocess
import time

import psutil

from gpu_efficiency_finder.errors import BenchmarkLaunchError
from gpu_efficiency_finder.logging_setup import get_logger

__all__ = ["ProcessBenchmarkRunner"]

_LOG = get_logger(__name__)

# Zeit, die Kindprozesse nach terminate() zum sauberen Beenden bekommen, ehe gekillt wird.
_TERMINATE_GRACE_S = 5.0


class ProcessBenchmarkRunner:
    """Startet/beendet einen externen Benchmark-Prozess als konstante Last.

    ``command`` ist eine vollständige Kommandozeile (EXE-Pfad inkl. Argumente). Bei leerem
    Befehl macht :meth:`start` nichts — die Last wird dann manuell vom Nutzer erzeugt.
    """

    def __init__(self, command: str, warmup_s: float = 10.0) -> None:
        self._command = command
        self._warmup_s = warmup_s
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        """Startet den Benchmark und wartet die Warmup-Zeit ab (No-Op bei leerem Befehl)."""
        if not self._command or not self._command.strip():
            _LOG.info("Kein Benchmark-Befehl gesetzt — Last wird manuell erzeugt.")
            self._proc = None
            return
        # posix=False: Windows-Pfade enthalten Backslashes, die im POSIX-Modus als
        # Escape-Zeichen fehlinterpretiert würden.
        try:
            args = shlex.split(self._command, posix=False)
        except ValueError as exc:
            raise BenchmarkLaunchError(
                f"Benchmark-Befehl konnte nicht zerlegt werden: {exc}"
            ) from exc
        if not args:
            raise BenchmarkLaunchError("Benchmark-Befehl ist leer.")
        try:
            self._proc = subprocess.Popen(args)
        except (OSError, ValueError) as exc:
            self._proc = None
            raise BenchmarkLaunchError(
                f"Benchmark konnte nicht gestartet werden ({args[0]}): {exc}"
            ) from exc
        _LOG.info(
            "Benchmark gestartet (PID %d), Aufwärmphase %.1f s …",
            self._proc.pid,
            self._warmup_s,
        )
        if self._warmup_s > 0:
            time.sleep(self._warmup_s)

    def stop(self) -> None:
        """Beendet den GESAMTEN Prozessbaum des Benchmarks robust."""
        proc = self._proc
        if proc is None:
            return
        pid = proc.pid
        try:
            self._kill_tree(pid)
        except psutil.NoSuchProcess:
            _LOG.debug("Benchmark-Prozess %d war bereits beendet.", pid)
        except psutil.Error as exc:
            _LOG.warning("psutil-Beenden des Baums fehlgeschlagen (%s) — taskkill.", exc)
            self._taskkill(pid)
        finally:
            self._proc = None
            _LOG.info("Benchmark gestoppt (PID %d).", pid)

    def _kill_tree(self, pid: int) -> None:
        """Terminiert Eltern- und alle Kindprozesse, killt Überlebende nach Timeout."""
        parent = psutil.Process(pid)
        try:
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for child in children:
            self._safe_terminate(child)
        _, alive = psutil.wait_procs(children, timeout=_TERMINATE_GRACE_S)
        for survivor in alive:
            self._safe_kill(survivor)
        # Elternprozess zuletzt beenden.
        self._safe_terminate(parent)
        try:
            parent.wait(timeout=_TERMINATE_GRACE_S)
        except psutil.TimeoutExpired:
            self._safe_kill(parent)
        except psutil.NoSuchProcess:
            pass

    @staticmethod
    def _safe_terminate(process: psutil.Process) -> None:
        """terminate(), ignoriert bereits beendete oder unzugängliche Prozesse."""
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.terminate()

    @staticmethod
    def _safe_kill(process: psutil.Process) -> None:
        """kill(), ignoriert bereits beendete oder unzugängliche Prozesse."""
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.kill()

    @staticmethod
    def _taskkill(pid: int) -> None:
        """Fallback: kompletten Baum über das Windows-Bordmittel ``taskkill`` beenden."""
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
            )
        except OSError as exc:
            _LOG.warning("taskkill für PID %d fehlgeschlagen: %s", pid, exc)

    def is_running(self) -> bool:
        """True, wenn ein Prozess gestartet wurde und noch läuft."""
        proc = self._proc
        if proc is None:
            return False
        return proc.poll() is None
