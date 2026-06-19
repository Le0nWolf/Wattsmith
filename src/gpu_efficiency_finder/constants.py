"""Konstanten und Enums — keine Magic Strings im restlichen Code."""

from __future__ import annotations

import enum

__all__ = [
    "APP_TITLE",
    "BENCHMARK_PRESETS",
    "DEFAULT_BENCHMARK_PLACEHOLDER",
    "DEFAULT_BENCHMARK_PRESET",
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

# Benchmark-Presets: Anzeigename → Befehls-Template. Die Pfade sind übliche Standard-
# Installationsorte und müssen ggf. an die eigene Installation angepasst werden. Leerer
# Befehl = Last wird manuell gestartet (z. B. ein Spiel).
DEFAULT_BENCHMARK_PRESET = "Spiel / manuell (kein Befehl)"

BENCHMARK_PRESETS: dict[str, str] = {
    DEFAULT_BENCHMARK_PRESET: "",
    "Unigine Superposition (Loop)": (
        r'"C:\Program Files\Unigine Superposition\bin\superposition_cli.exe"'
        " -preset 0 -mode 2 -sound 0 -shaders_quality 1 -textures_quality 1"
    ),
    "Unigine Heaven (Loop)": (
        r'"C:\Program Files (x86)\Unigine\Heaven Benchmark 4.0\bin\browser_x64.exe"'
    ),
    "Unigine Valley (Loop)": (
        r'"C:\Program Files (x86)\Unigine\Valley Benchmark 1.0\bin\browser_x64.exe"'
    ),
    "FurMark (nur für Modus „Nur Takt“)": (
        r'"C:\Program Files\Geeks3D\Benchmarks\FurMark\furmark.exe"'
        " /width=2560 /height=1440 /msaa=0 /nogui /nomenubar"
    ),
    "OCCT (konstante 3D-Last)": r'"C:\Program Files\OCCT\OCCT.exe"',
    "Eigener Befehl": "",
}


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
