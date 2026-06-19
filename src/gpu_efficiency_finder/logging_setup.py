"""Zentrale Logging-Konfiguration."""

from __future__ import annotations

import logging

__all__ = ["get_logger", "setup_logging"]

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Konfiguriert das Root-Logging einmalig (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Liefert einen Logger; stellt sicher, dass Logging konfiguriert ist."""
    setup_logging()
    return logging.getLogger(name)
