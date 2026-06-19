"""Konstanten und Enums — keine Magic Strings im restlichen Code."""

from __future__ import annotations

import enum

__all__ = [
    "APP_TITLE",
    "DEFAULT_BENCHMARK_PLACEHOLDER",
    "HWINFO_SHARED_MEM_NAME",
    "PRESENTMON_PROCESS_HINT",
    "MeasurementMode",
    "OperatingPointKind",
]

APP_TITLE = "GPU Efficiency Finder"

# Globaler Name des HWiNFO-Shared-Memory-Mapped-File.
HWINFO_SHARED_MEM_NAME = r"Global\HWiNFO_SENS_SM2"

# Platzhalter für das Benchmark-Befehlsfeld in der UI (Superposition-Loop).
DEFAULT_BENCHMARK_PLACEHOLDER = (
    r'"C:\Program Files\Unigine Superposition\bin\superposition.exe" '
    "-sound 0 -shaders_quality 1 -preset 0"
)

PRESENTMON_PROCESS_HINT = (
    "Name des tatsächlich rendernden Prozesses (bei Benchmark-Launchern oft ein Kindprozess, "
    "nicht der Launcher selbst)."
)


class MeasurementMode(enum.StrEnum):
    """Gestaffelte Mess-/Telemetrie-Modi, alle über denselben PerfSource-Port."""

    CLOCK_PROXY = "clock"
    PRESENTMON = "presentmon"
    COMPUTE = "compute"
    HWINFO = "hwinfo"


class OperatingPointKind(enum.StrEnum):
    """Art eines berechneten Betriebspunkts."""

    EFFICIENCY_PEAK = "efficiency_peak"
    KNEE = "knee"
    RECOMMENDATION = "recommendation"
