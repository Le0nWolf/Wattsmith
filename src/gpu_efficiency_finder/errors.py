"""Sprechende Domain-Exceptions — keine nackten Strings, von der UI verständlich anzeigbar."""

from __future__ import annotations

__all__ = [
    "BenchmarkLaunchError",
    "GpuEfficiencyError",
    "GpuPermissionError",
    "HwinfoError",
    "NoLoadRunningError",
    "PresentMonError",
    "SweepAbortedError",
]


class GpuEfficiencyError(Exception):
    """Basisklasse aller fachlichen Fehler dieser Anwendung."""


class GpuPermissionError(GpuEfficiencyError):
    """NVML ``NoPermission`` beim Setzen des Limits → App als Administrator starten."""


class PresentMonError(GpuEfficiencyError):
    """PresentMon-Konsolenprozess konnte nicht gestartet/gelesen werden."""


class HwinfoError(GpuEfficiencyError):
    """HWiNFO-Shared-Memory nicht verfügbar (HWiNFO nicht aktiv / Shared Memory aus)."""


class BenchmarkLaunchError(GpuEfficiencyError):
    """Der externe Benchmark-Befehl konnte nicht gestartet werden."""


class NoLoadRunningError(GpuEfficiencyError):
    """Während der Messung lag keine GPU-Last an (Auslastung zu niedrig)."""


class SweepAbortedError(GpuEfficiencyError):
    """Der Sweep wurde vom Nutzer gestoppt."""
