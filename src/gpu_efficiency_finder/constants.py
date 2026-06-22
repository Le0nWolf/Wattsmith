"""Konstanten und Enums — keine Magic Strings im restlichen Code."""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = [
    "APP_TITLE",
    "BENCHMARK_PRESETS",
    "DEFAULT_BENCHMARK_PRESET",
    "HWINFO_SHARED_MEM_NAME",
    "PRESENTMON_PROCESS_HINT",
    "BenchmarkPreset",
    "MeasurementMode",
    "OperatingPointKind",
]

APP_TITLE = "GPU Efficiency Finder"

# Globaler Name des HWiNFO-Shared-Memory-Mapped-File.
HWINFO_SHARED_MEM_NAME = r"Global\HWiNFO_SENS_SM2"

PRESENTMON_PROCESS_HINT = (
    "Name des tatsächlich rendernden Prozesses (bei Benchmark-Launchern oft ein Kindprozess, "
    "nicht der Launcher selbst)."
)


@dataclass(frozen=True, slots=True)
class BenchmarkPreset:
    """Vorlage für einen Benchmark: empfohlene Startoptionen + Hinweis, WELCHE EXE zu wählen ist."""

    args: str
    exe_hint: str


# Benchmark-Presets: Auswahl füllt die Startoptionen und zeigt eine EXE-Empfehlung. Den
# EXE-Pfad wählt der Nutzer per „Durchsuchen“ — Pfade/Argumente ggf. an die Installation/
# Version anpassen (insb. FurMark/OCCT-CLI variieren je nach Version).
DEFAULT_BENCHMARK_PRESET = "Spiel / manuell (kein Befehl)"

BENCHMARK_PRESETS: dict[str, BenchmarkPreset] = {
    DEFAULT_BENCHMARK_PRESET: BenchmarkPreset(
        args="",
        exe_hint=(
            "EXE-Feld leer lassen — Spiel/Last selbst starten und während des Sweeps laufen lassen."
        ),
    ),
    "Unigine Superposition (Loop)": BenchmarkPreset(
        args="-preset 0 -mode 2 -sound 0 -shaders_quality 1 -textures_quality 1",
        exe_hint=(
            "EXE wählen: bin\\superposition_cli.exe (die CLI-Variante, "
            "NICHT die GUI superposition.exe)."
        ),
    ),
    "Unigine Heaven (Loop)": BenchmarkPreset(
        args="",
        exe_hint=(
            "EXE wählen: bin\\browser_x64.exe; im Heaven-Fenster dann „Benchmark“ als Loop starten."
        ),
    ),
    "Unigine Valley (Loop)": BenchmarkPreset(
        args="",
        exe_hint=(
            "EXE wählen: bin\\browser_x64.exe; im Valley-Fenster dann „Benchmark“ als Loop starten."
        ),
    ),
    "FurMark (nur Modus „Nur Takt“)": BenchmarkPreset(
        args="--demo furmark-gl --width 2560 --height 1440 --max-time 0 --no-score-box",
        exe_hint=(
            "EXE wählen: furmark.exe (NICHT FurMark_GUI.exe / _fm2-gui.exe). "
            "Args sind FurMark-2-Stil (--demo/--width …); --max-time 0 = läuft ohne Limit weiter."
        ),
    ),
    "OCCT (konstante 3D-Last)": BenchmarkPreset(
        args="",
        exe_hint=(
            "EXE wählen: OCCT.exe; in OCCT einen KONSTANTEN 3D-Test starten "
            "(nicht den variablen Stabilitätstest)."
        ),
    ),
    "Eigener Befehl": BenchmarkPreset(
        args="",
        exe_hint="Eigene EXE per „Durchsuchen“ wählen und Startoptionen frei eintragen.",
    ),
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
