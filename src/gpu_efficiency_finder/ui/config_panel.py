"""UI-Baustein: Konfigurations-Panel (Sweep-Parameter + Mess-Quelle).

Rendert alle Eingaben in einer ``ui.card`` (Dark Theme) und liest sie auf Wunsch in
validierte ``SweepConfig`` + ``SourceConfig`` ein. Validierungsfehler (pydantic) werden in
eine deutsche Meldung übersetzt; die UI zeigt sie an, statt zu crashen.

Reine Eingabe-Sammelei — keine Domain-Logik, keine Hardware.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui
from pydantic import ValidationError

from gpu_efficiency_finder.config import SourceConfig, SweepConfig
from gpu_efficiency_finder.constants import (
    DEFAULT_BENCHMARK_PLACEHOLDER,
    PRESENTMON_PROCESS_HINT,
    MeasurementMode,
)
from gpu_efficiency_finder.models import GpuInfo

__all__ = ["ConfigPanel"]

# Mess-Modus → (Anzeigename, Hilfetext) mit echten Umlauten.
_MODE_LABELS: dict[MeasurementMode, str] = {
    MeasurementMode.CLOCK_PROXY: "Nur Takt (schnell, Default)",
    MeasurementMode.PRESENTMON: "PresentMon (FPS + Lows)",
    MeasurementMode.COMPUTE: "Compute (eigene Last, torch)",
    MeasurementMode.HWINFO: "HWiNFO (Shared Memory)",
}

_MODE_HELP = (
    "Staffelung: „Nur Takt“ braucht nichts Zusätzliches (Default, schnell), eine externe "
    "Last muss laufen. „PresentMon (FPS)“ liefert präzise FPS und 1%/0.1%-Lows. "
    "„Compute“ und „HWiNFO“ sind optional."
)

_BENCHMARK_HINT = (
    "3DMark startet nur in der Professional Edition per CLI; Score-am-Ende-Benchmarks sind "
    "ungeeignet (durchgehende Last nötig); FurMark wird nicht empfohlen."
)

_HWINFO_HINT = (
    "HWiNFO muss mit aktivem „Shared Memory Support“ laufen; die Free-Version deaktiviert "
    "ihn nach 12 Stunden automatisch."
)


class ConfigPanel:
    """Sammelt alle Konfigurationswerte und liefert validierte Config-Objekte."""

    def __init__(self, gpus: Sequence[GpuInfo]) -> None:
        self._gpu_options = {g.index: f"GPU {g.index}: {g.name}" for g in gpus}
        default_idx = next(iter(self._gpu_options), 0)
        with ui.card().classes("w-full").props("dark"):
            ui.label("Konfiguration").classes("text-lg font-bold")
            self._gpu = ui.select(
                options=self._gpu_options or {0: "GPU 0"},
                value=default_idx,
                label="GPU",
            ).classes("w-full")

            self._mode = ui.select(
                options={m.value: _MODE_LABELS[m] for m in MeasurementMode},
                value=MeasurementMode.CLOCK_PROXY.value,
                label="Mess-Modus",
            ).classes("w-full")
            ui.label(_MODE_HELP).classes("text-xs text-grey")

            self._build_sweep_inputs()
            self._build_floor_inputs()
            self._build_benchmark_inputs()
            self._build_presentmon_inputs()
            self._build_hwinfo_inputs()

    # -- Eingabe-Gruppen --------------------------------------------------

    def _build_sweep_inputs(self) -> None:
        with ui.row().classes("w-full"):
            self._start = ui.number("Start %", value=100, min=20, max=100, step=5)
            self._end = ui.number("Ende %", value=50, min=20, max=100, step=5)
            self._step = ui.number("Schritt %", value=5, min=1, max=25, step=1)
        with ui.row().classes("w-full"):
            self._settle = ui.number("Aufwärmen (s)", value=8.0, min=2, max=60, step=1)
            self._measure = ui.number("Messen (s)", value=25.0, min=5, max=120, step=1)
        with ui.row().classes("w-full"):
            self._avg_tol = ui.number("Toleranz Ø %", value=3.0, min=0, max=30, step=0.5)
            self._low_tol = ui.number("Toleranz Low %", value=5.0, min=0, max=40, step=0.5)
        with ui.row().classes("w-full items-center"):
            self._randomize = ui.switch("Reihenfolge randomisieren", value=True)
            self._cooldown_on = ui.switch("Abkühlen bis", value=False)
            self._cooldown_c = ui.number("Ziel °C", value=55.0, min=20, max=90, step=1)

    def _build_floor_inputs(self) -> None:
        with ui.row().classes("w-full items-center"):
            self._floor_on = ui.switch("Absolute FPS-Untergrenze", value=False)
            self._floor = ui.number("min. FPS", value=60.0, min=1, step=1)

    def _build_benchmark_inputs(self) -> None:
        ui.separator()
        ui.label("Externe Benchmark-Last (optional)").classes("font-bold")
        self._benchmark = ui.input(
            "Benchmark-Befehl",
            placeholder=DEFAULT_BENCHMARK_PLACEHOLDER,
        ).classes("w-full")
        self._warmup = ui.number("Warmup (s)", value=10.0, min=0, max=120, step=1)
        ui.label(_BENCHMARK_HINT).classes("text-xs text-grey")

    def _build_presentmon_inputs(self) -> None:
        ui.separator()
        ui.label("PresentMon").classes("font-bold")
        self._pm_path = ui.input(
            "PresentMon-Pfad (leer = gebündelt)",
        ).classes("w-full")
        self._pm_process = ui.input("Prozessname (z. B. spiel.exe)").classes("w-full")
        ui.label(PRESENTMON_PROCESS_HINT).classes("text-xs text-grey")

    def _build_hwinfo_inputs(self) -> None:
        ui.separator()
        ui.label("HWiNFO").classes("font-bold")
        self._hwinfo_mem = ui.input(
            "Shared-Memory-Name (leer = Standard)",
        ).classes("w-full")
        ui.label(_HWINFO_HINT).classes("text-xs text-grey")

    # -- Auslesen ---------------------------------------------------------

    def read_gpu_index(self) -> int:
        """Aktuell gewählter GPU-Index (für Limit-Aktionen unabhängig vom Sweep)."""
        return int(self._gpu.value)

    def read_configs(self) -> tuple[SweepConfig, SourceConfig] | str:
        """Liest und validiert die Eingaben.

        Gibt ``(SweepConfig, SourceConfig)`` zurück oder bei Validierungsfehler eine
        deutsche Fehlermeldung als ``str``.
        """
        try:
            sweep = SweepConfig(
                gpu_index=int(self._gpu.value),
                start_pct=int(self._start.value),
                end_pct=int(self._end.value),
                step_pct=int(self._step.value),
                settle_s=float(self._settle.value),
                measure_s=float(self._measure.value),
                avg_tol_pct=float(self._avg_tol.value),
                low_tol_pct=float(self._low_tol.value),
                min_fps_floor=float(self._floor.value) if self._floor_on.value else None,
                randomize_order=bool(self._randomize.value),
                cooldown_target_c=float(self._cooldown_c.value)
                if self._cooldown_on.value
                else None,
            )
            source = SourceConfig(
                mode=MeasurementMode(self._mode.value),
                presentmon_path=_blank_to_none(self._pm_path.value),
                process_name=_blank_to_none(self._pm_process.value),
                benchmark_command=_blank_to_none(self._benchmark.value),
                benchmark_warmup_s=float(self._warmup.value),
                hwinfo_shared_mem=_blank_to_none(self._hwinfo_mem.value),
            )
        except ValidationError as exc:
            return _format_validation_error(exc)
        return sweep, source


def _blank_to_none(value: object) -> str | None:
    """Leerer/whitespace-String → ``None``, sonst getrimmter String."""
    text = str(value or "").strip()
    return text or None


def _format_validation_error(exc: ValidationError) -> str:
    """Übersetzt pydantic-Fehler in eine knappe, deutsche Mehrzeilen-Meldung."""
    lines = [f"• {err.get('msg', 'ungültiger Wert')}" for err in exc.errors()]
    return "Ungültige Konfiguration:\n" + "\n".join(lines)
