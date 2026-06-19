"""NiceGUI-Koordinator: komponiert UI-Bausteine, wirt Adapter und fährt den Sweep.

Dies ist der Composition Root für die UI: ``build_backend`` / ``build_perf_source`` /
``build_benchmark`` erzeugen die konkreten Adapter, der Rest delegiert an die Domain
(``SweepEngine``) und die UI-Bausteine. Aller Zustand lebt im Speicher (keine
``app.storage.*`` — Portabilität: nichts bleibt liegen).
"""

from __future__ import annotations

import asyncio
import datetime as _dt

from nicegui import run, ui

from gpu_efficiency_finder.adapters.clock_proxy_source import ClockProxySource
from gpu_efficiency_finder.adapters.compute_load_source import ComputeLoadSource
from gpu_efficiency_finder.adapters.hwinfo_source import HwinfoSource
from gpu_efficiency_finder.adapters.nvidia_smi_backend import NvidiaSmiBackend
from gpu_efficiency_finder.adapters.nvml_backend import NvmlBackend
from gpu_efficiency_finder.adapters.presentmon_source import PresentMonSource
from gpu_efficiency_finder.adapters.process_benchmark_runner import ProcessBenchmarkRunner
from gpu_efficiency_finder.config import SourceConfig, SweepConfig
from gpu_efficiency_finder.constants import APP_TITLE, MeasurementMode
from gpu_efficiency_finder.domain.sweep import SweepEngine, SweepHooks
from gpu_efficiency_finder.errors import GpuEfficiencyError, GpuPermissionError
from gpu_efficiency_finder.infra.persistence import export_csv, load_run, save_run
from gpu_efficiency_finder.infra.presentmon_bundle import resolve_presentmon_path
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import GpuInfo, SweepResult, SweepRow, Telemetry
from gpu_efficiency_finder.ports import BenchmarkRunner, GpuBackend, PerfSource
from gpu_efficiency_finder.ui.chart import EfficiencyChart
from gpu_efficiency_finder.ui.config_panel import ConfigPanel
from gpu_efficiency_finder.ui.results_table import ResultsTable

__all__ = ["AppController", "build_backend", "build_benchmark", "build_perf_source", "create_ui"]

_LOG = get_logger(__name__)
_ACCENT = "#26a69a"


def build_backend() -> GpuBackend:
    """Versucht NVML; fällt bei fehlender Berechtigung/Init-Fehler auf nvidia-smi zurück."""
    nvml = NvmlBackend()
    try:
        nvml.list_gpus()
    except (GpuPermissionError, GpuEfficiencyError) as exc:
        _LOG.warning("NVML nicht nutzbar (%s) — Fallback auf nvidia-smi.", exc)
        return NvidiaSmiBackend()
    return nvml


def build_perf_source(source_config: SourceConfig, backend: GpuBackend) -> PerfSource:
    """Wählt die PerfSource nach Mess-Modus aus."""
    mode = source_config.mode
    if mode is MeasurementMode.PRESENTMON:
        exe = resolve_presentmon_path(source_config.presentmon_path)
        if exe is None:
            raise GpuEfficiencyError(
                "Keine PresentMon-EXE gefunden — Pfad angeben oder gebündelte EXE bereitstellen."
            )
        return PresentMonSource(exe, source_config.process_name or "")
    if mode is MeasurementMode.COMPUTE:
        return ComputeLoadSource(gpu_index=0)
    if mode is MeasurementMode.HWINFO:
        if source_config.hwinfo_shared_mem:
            return HwinfoSource(source_config.hwinfo_shared_mem)
        return HwinfoSource()
    return ClockProxySource(backend, 0)


def build_benchmark(source_config: SourceConfig) -> BenchmarkRunner | None:
    """Erzeugt einen ProcessBenchmarkRunner oder ``None``, wenn kein Befehl gesetzt ist."""
    command = source_config.benchmark_command
    if not command or not command.strip():
        return None
    return ProcessBenchmarkRunner(command, source_config.benchmark_warmup_s)


class AppController:
    """Hält den UI-Zustand im Speicher und koordiniert Sweep-Lauf und Aktionen."""

    def __init__(self, gpus: list[GpuInfo], backend: GpuBackend) -> None:
        self._gpus = gpus
        self._backend = backend
        self._rows: list[SweepRow] = []
        self._result: SweepResult | None = None
        self._stop_flag = False
        self._running = False
        self._build_layout()

    # -- Layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        ui.dark_mode(True)
        ui.colors(primary=_ACCENT)
        with ui.header().classes("items-center"):
            ui.label(APP_TITLE).classes("text-xl font-bold")
        with ui.row().classes("w-full no-wrap"):
            with ui.column().classes("w-1/3"):
                self._panel = ConfigPanel(self._gpus)
                self._build_buttons()
            with ui.column().classes("w-2/3"):
                self._status = ui.label("Bereit.").classes("text-sm")
                self._telemetry = ui.label("").classes("text-xs text-grey")
                self._chart = EfficiencyChart()
                self._table = ResultsTable()
                self._recommendation = ui.label("").classes("text-sm")
                self._path = ui.input("Datei-Pfad (CSV/JSON)").classes("w-full")

    def _build_buttons(self) -> None:
        with ui.row().classes("w-full"):
            self._start_btn = ui.button("Sweep starten", on_click=self._on_start)
            self._stop_btn = ui.button("Stop", on_click=self._on_stop)
            self._stop_btn.disable()
        with ui.row().classes("w-full"):
            ui.button("Empfehlung anwenden", on_click=self._on_apply)
            ui.button("Reset Default", on_click=self._on_reset)
        with ui.row().classes("w-full"):
            ui.button("CSV-Export", on_click=self._on_export_csv)
            ui.button("Run speichern", on_click=self._on_save)
            ui.button("Run laden", on_click=self._on_load)

    # -- Sweep ------------------------------------------------------------

    async def _on_start(self) -> None:
        if self._running:
            return
        configs = self._panel.read_configs()
        if isinstance(configs, str):
            ui.notify(configs, type="negative", multi_line=True)
            return
        sweep_config, source_config = configs
        try:
            perf = build_perf_source(source_config, self._backend)
            benchmark = build_benchmark(source_config)
        except GpuEfficiencyError as exc:
            ui.notify(str(exc), type="negative")
            return
        self._begin_run()
        try:
            await run.io_bound(self._run_sweep_sync, sweep_config, source_config, perf, benchmark)
        except GpuPermissionError:
            ui.notify("Bitte die App als Administrator starten.", type="negative")
        except GpuEfficiencyError as exc:
            ui.notify(str(exc), type="negative")
        except Exception as exc:
            _LOG.exception("Sweep fehlgeschlagen")
            ui.notify(f"Sweep fehlgeschlagen: {exc}", type="negative")
        finally:
            self._end_run()

    def _run_sweep_sync(
        self,
        sweep_config: SweepConfig,
        source_config: SourceConfig,
        perf: PerfSource,
        benchmark: BenchmarkRunner | None,
    ) -> None:
        """Läuft im Worker-Thread (run.io_bound); fährt die async Engine über asyncio.run."""
        gpu_name = next((g.name for g in self._gpus if g.index == sweep_config.gpu_index), "")
        engine = SweepEngine(self._backend, perf, benchmark)
        hooks = SweepHooks(
            on_row=self._on_row,
            on_status=self._on_status,
            should_stop=lambda: self._stop_flag,
        )
        result = asyncio.run(
            engine.run(
                sweep_config,
                gpu_name=gpu_name,
                workload_name=source_config.mode.value,
                timestamp=_dt.datetime.now().isoformat(timespec="seconds"),
                hooks=hooks,
            )
        )
        self._result = result
        ui.timer(0.1, lambda: self._render_result(result), once=True)

    def _on_row(self, row: SweepRow) -> None:
        self._rows.append(row)
        snapshot = list(self._rows)
        ui.timer(0.05, lambda: self._render_live(snapshot), once=True)

    def _on_status(self, message: str, telem: Telemetry | None) -> None:
        text = (
            f"{telem.power_w:.0f} W · {telem.clock_mhz:.0f} MHz · {telem.temp_c:.0f} °C"
            if telem is not None
            else ""
        )
        ui.timer(0.05, lambda: self._render_status(message, text), once=True)

    # -- UI-Updates (im Event-Loop) ---------------------------------------

    def _render_status(self, message: str, telem: str) -> None:
        self._status.set_text(message)
        self._telemetry.set_text(telem)

    def _render_live(self, rows: list[SweepRow]) -> None:
        self._table.update(rows)
        self._chart.update(rows)

    def _render_result(self, result: SweepResult) -> None:
        rows = list(result.rows)
        self._rows = rows
        self._table.update(rows)
        floor = float(result.config.get("min_fps_floor") or 0) or None
        self._chart.update(
            rows,
            peak=result.efficiency_peak,
            knee=result.knee,
            recommendation=result.recommendation,
            fps_floor=floor,
        )
        self._recommendation.set_text(self._format_recommendation(result))

    @staticmethod
    def _format_recommendation(result: SweepResult) -> str:
        rec = result.recommendation
        if rec is None or rec.recommended is None:
            return rec.message if rec and rec.message else "Keine Empfehlung verfügbar."
        op = rec.recommended
        text = (
            f"Empfehlung: {op.set_watt:.0f} W ({op.pct_of_default:.0f}% vom Default) — "
            f"spart {op.savings_w:.0f} W ({op.savings_pct:.0f}%)."
        )
        if rec.floor_binding and rec.message:
            text += "  " + rec.message
        return text

    # -- Aktionen ---------------------------------------------------------

    def _on_stop(self) -> None:
        self._stop_flag = True
        self._status.set_text("Stop angefordert — Default-Limit wird wiederhergestellt …")

    async def _on_apply(self) -> None:
        rec = self._result.recommendation if self._result else None
        if rec is None or rec.recommended is None:
            ui.notify("Keine Empfehlung vorhanden.", type="warning")
            return
        idx = int(self._panel.read_gpu_index())
        await self._safe_backend(
            lambda: self._backend.set_power_limit_w(idx, rec.recommended.set_watt),
            f"Limit gesetzt: {rec.recommended.set_watt:.0f} W.",
        )

    async def _on_reset(self) -> None:
        idx = int(self._panel.read_gpu_index())
        await self._safe_backend(
            lambda: self._backend.reset_to_default(idx),
            "Default-Limit wiederhergestellt.",
        )

    async def _safe_backend(self, action: object, success_msg: str) -> None:
        try:
            await run.io_bound(action)  # type: ignore[arg-type]
        except GpuPermissionError:
            ui.notify("Bitte die App als Administrator starten.", type="negative")
        except GpuEfficiencyError as exc:
            ui.notify(str(exc), type="negative")
        else:
            ui.notify(success_msg, type="positive")

    def _on_export_csv(self) -> None:
        if self._result is None:
            ui.notify("Kein Ergebnis zum Exportieren.", type="warning")
            return
        path = (self._path.value or "").strip()
        if not path:
            ui.notify("Bitte einen Datei-Pfad angeben.", type="warning")
            return
        try:
            export_csv(self._result, path)
        except OSError as exc:
            ui.notify(f"Export fehlgeschlagen: {exc}", type="negative")
        else:
            ui.notify(f"CSV exportiert: {path}", type="positive")

    def _on_save(self) -> None:
        if self._result is None:
            ui.notify("Kein Ergebnis zum Speichern.", type="warning")
            return
        path = (self._path.value or "").strip()
        if not path:
            ui.notify("Bitte einen Datei-Pfad angeben.", type="warning")
            return
        try:
            save_run(self._result, path)
        except OSError as exc:
            ui.notify(f"Speichern fehlgeschlagen: {exc}", type="negative")
        else:
            ui.notify(f"Run gespeichert: {path}", type="positive")

    def _on_load(self) -> None:
        path = (self._path.value or "").strip()
        if not path:
            ui.notify("Bitte einen Datei-Pfad angeben.", type="warning")
            return
        try:
            result = load_run(path)
        except (OSError, ValueError) as exc:
            ui.notify(f"Laden fehlgeschlagen: {exc}", type="negative")
            return
        self._result = result
        self._render_result(result)
        ui.notify(f"Run geladen: {path}", type="positive")

    # -- Button-Zustand ---------------------------------------------------

    def _begin_run(self) -> None:
        self._running = True
        self._stop_flag = False
        self._rows = []
        self._table.clear()
        self._recommendation.set_text("")
        self._start_btn.disable()
        self._stop_btn.enable()

    def _end_run(self) -> None:
        self._running = False
        self._start_btn.enable()
        self._stop_btn.disable()


def create_ui() -> AppController:
    """Baut die Seite (ruft NICHT ``ui.run``). Erzeugt Backend + GPU-Liste und das Layout."""
    backend = build_backend()
    try:
        gpus = backend.list_gpus()
    except GpuEfficiencyError as exc:
        _LOG.warning("GPU-Liste konnte nicht gelesen werden: %s", exc)
        gpus = []
    return AppController(gpus, backend)
