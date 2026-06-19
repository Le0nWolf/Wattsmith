"""Infra: Pfad zur gebündelten PresentMon-Konsolen-EXE auflösen.

PresentMon wird in die portable App-EXE gepackt (PyInstaller ``datas``). Im gefrorenen
Zustand entpackt PyInstaller die Inhalte in einen temporären Ordner unterhalb von
``%TEMP%`` und legt dessen Pfad in ``sys._MEIPASS`` ab; dieser Ordner wird beim Beenden
der App automatisch wieder gelöscht — es bleibt also nichts liegen. Im Entwicklungsbetrieb
(nicht gefroren) liegt die EXE stattdessen im Repo unter ``assets/presentmon/``.

Reine Pfadauflösung ohne Seiteneffekte; startet nichts und ist überall importierbar.
"""

from __future__ import annotations

import sys
from pathlib import Path

from gpu_efficiency_finder.logging_setup import get_logger

__all__ = ["resolve_presentmon_path"]

_LOG = get_logger(__name__)

# Dateinamensmuster der gebündelten Konsolen-EXE (z. B. ``PresentMon-2.3.0-x64.exe``).
_PRESENTMON_GLOB = "PresentMon*.exe"
# Unterordner im Repo bzw. im entpackten Bundle, der die EXE enthält.
_BUNDLE_SUBDIR = ("assets", "presentmon")


def _base_dir() -> Path:
    """Basisverzeichnis: ``sys._MEIPASS`` (gefroren) oder die Repo-Wurzel (Entwicklung)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # presentmon_bundle.py liegt in src/gpu_efficiency_finder/infra/ → drei Ebenen hoch
    # zur Paketwurzel, dann eine weitere zum Repo-Root (über src/).
    return Path(__file__).resolve().parents[3]


def resolve_presentmon_path(override: str | None = None) -> str | None:
    """Liefert den Pfad zur PresentMon-EXE oder ``None``, wenn keine gefunden wurde.

    Reihenfolge:
    1. ``override`` — falls angegeben und existent, wird er direkt zurückgegeben.
    2. Gebündelte EXE im PresentMon-Verzeichnis (gefroren: ``sys._MEIPASS``, sonst
       ``assets/presentmon/`` im Repo). Der erste Treffer auf ``PresentMon*.exe``
       (case-insensitiv) wird verwendet.
    """
    if override:
        override_path = Path(override)
        if override_path.is_file():
            _LOG.debug("PresentMon-Override verwendet: %s", override_path)
            return str(override_path)
        _LOG.warning("PresentMon-Override existiert nicht: %s", override)

    bundle_dir = _base_dir().joinpath(*_BUNDLE_SUBDIR)
    if not bundle_dir.is_dir():
        _LOG.debug("PresentMon-Bundle-Verzeichnis fehlt: %s", bundle_dir)
        return None

    for candidate in sorted(bundle_dir.iterdir()):
        if candidate.is_file() and _matches_presentmon(candidate.name):
            _LOG.debug("PresentMon gefunden: %s", candidate)
            return str(candidate)

    _LOG.debug("Keine PresentMon-EXE in %s gefunden.", bundle_dir)
    return None


def _matches_presentmon(filename: str) -> bool:
    """Case-insensitiver Abgleich gegen ``PresentMon*.exe``."""
    return Path(filename.lower()).match(_PRESENTMON_GLOB.lower())
