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


def _split_args(args: str) -> list[str]:
    """Zerlegt die Startoptionen in Tokens; etwaige Anführungszeichen werden entfernt."""
    text = (args or "").strip()
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    return [t.strip('"') for t in tokens]


class ProcessBenchmarkRunner:
    """Startet/beendet einen externen Benchmark-Prozess als konstante Last.

    ``exe`` ist der reine Pfad zur Benchmark-EXE (eigenes Argument → keine Quoting-Probleme
    mit Leerzeichen im Pfad), ``args`` die optionalen Startoptionen. Bei leerem ``exe`` macht
    :meth:`start` nichts — die Last wird dann manuell vom Nutzer erzeugt.
    """

    def __init__(self, exe: str, args: str = "", warmup_s: float = 10.0) -> None:
        self._exe = exe
        self._args = args
        self._warmup_s = warmup_s
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        """Startet den Benchmark und wartet die Warmup-Zeit ab (No-Op bei leerer EXE)."""
        exe = (self._exe or "").strip()
        if not exe:
            _LOG.info("Keine Benchmark-EXE gesetzt — Last wird manuell erzeugt.")
            self._proc = None
            return
        # EXE als eigenes Listenelement übergeben (Popen quotet selbst korrekt, auch bei
        # Leerzeichen im Pfad); die Startoptionen separat parsen.
        cmd = [exe, *_split_args(self._args)]
        try:
            self._proc = subprocess.Popen(cmd)
        except (OSError, ValueError) as exc:
            self._proc = None
            raise BenchmarkLaunchError(
                f"Benchmark konnte nicht gestartet werden ({exe}): {exc}"
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
