"""Einstieg + Composition Root.

Konfiguriert das Logging, baut die NiceGUI-Seite (``app.create_ui``) und startet den
Webserver, der die App im **Standard-Browser** öffnet. Registriert zusätzlich einen
``atexit``-Handler, der das GPU-Power-Limit als letztes Sicherheitsnetz auf den Default
zurücksetzt.

Bewusst KEIN eingebettetes Fenster (pywebview/WebView2): Browser-Modus ist deutlich
robuster und hat keine WebView2-Laufzeit-Abhängigkeit.

WICHTIG: ``ui.run`` darf NICHT beim Import laufen — daher der Guard unten.
"""

from __future__ import annotations

import atexit
import logging

from nicegui import ui

from gpu_efficiency_finder import app
from gpu_efficiency_finder.adapters.nvidia_smi_backend import NvidiaSmiBackend
from gpu_efficiency_finder.adapters.nvml_backend import NvmlBackend
from gpu_efficiency_finder.constants import APP_TITLE
from gpu_efficiency_finder.logging_setup import get_logger, setup_logging

__all__ = ["main"]

_LOG = get_logger(__name__)


def _reset_power_limit_safety_net() -> None:
    """Best-effort: setzt das Power-Limit aller GPUs auf den Default zurück.

    Die SweepEngine setzt das Default-Limit bereits in ``try/finally`` zurück; dies ist
    das Belt-and-Suspenders-Netz für harte Programm-Abbrüche (atexit). Fehler werden
    bewusst geschluckt — beim Beenden darf nichts mehr werfen.
    """
    for backend_factory in (NvmlBackend, NvidiaSmiBackend):
        try:
            backend = backend_factory()
            for gpu in backend.list_gpus():
                backend.reset_to_default(gpu.index)
            return
        except Exception:
            continue


def main() -> None:
    """Richtet Logging ein, baut die UI und startet das native Fenster."""
    setup_logging(logging.INFO)
    _LOG.info("%s startet …", APP_TITLE)
    atexit.register(_reset_power_limit_safety_net)
    app.create_ui()
    ui.run(
        native=False,
        show=True,  # öffnet automatisch den Standard-Browser
        reload=False,
        title=APP_TITLE,
    )


# Guard: PyInstaller/Multiprocessing kann dieses Modul in Subprozessen erneut importieren.
# Ohne diesen Guard (inkl. "__mp_main__") würde der Server mehrfach gestartet bzw. der
# Build hängen.
if __name__ in {"__main__", "__mp_main__"}:
    main()
