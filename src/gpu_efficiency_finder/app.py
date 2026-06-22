"""NiceGUI-Koordinator: komponiert UI-Bausteine, wirt Adapter und fährt den Sweep.

Dies ist der Composition Root für die UI: ``build_backend`` / ``build_perf_source`` /
``build_benchmark`` erzeugen die konkreten Adapter, der Rest delegiert an die Domain
(``SweepEngine``) und die UI-Bausteine. Aller Zustand lebt im Speicher (keine
``app.storage.*`` — Portabilität: nichts bleibt liegen).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import time

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

# In-App-Kurzanleitung (aufklappbar). Bewusst knapp und handlungsorientiert.
_HELP_MD = """
**Idee:** Das Tool senkt das Power-Limit Stufe für Stufe automatisch ab, misst pro Stufe
Verbrauch und Performance und empfiehlt am Ende das sparsamste Limit ohne spürbaren Verlust.
Du musst nur für **konstante GPU-Last** sorgen — den Rest macht das Tool allein.

**In 6 Schritten:**
1. **Last vorbereiten** — entweder unten die *Benchmark-EXE* wählen (Button „Durchsuchen“) und
   optional *Startoptionen* eintragen (Loop-Benchmark wie Unigine Superposition, läuft endlos)
   **oder** ein Spiel manuell starten und es während des ganzen Sweeps laufen lassen.
2. **Mess-Modus wählen** — *Nur Takt* (schnell, kein Setup) · *PresentMon (FPS)* (echte FPS +
   1%/0.1%-Lows, braucht den Prozessnamen) · *Compute* (eigene Last) · *HWiNFO*.
3. **Bereich/Dauern/Toleranzen** prüfen — die Defaults (100→50 %, 3 % Ø-FPS, 5 % 1%-Low) passen
   meist. *Reihenfolge randomisieren* bleibt an (gegen Aufheiz-Verzerrung; Anzeige bleibt sortiert).
   - **Wichtig bei Loop-Benchmarks mit wechselnden Szenen** (3DMark, Superposition): „Messen (s)“
     auf die **Dauer eines kompletten Loops** (oder ein Vielfaches) setzen. Der Sweep ist
     zeitbasiert (er fährt das Limit nach fester Zeit weiter, NICHT pro Benchmark-Run). Ist das
     Fenster genau einen ganzen Loop lang, deckt jede Stufe denselben Szenen-Satz ab → vergleichbar,
     egal wo im Loop das Fenster beginnt.
4. **Sweep starten** — das Tool fährt die Stufen vollautomatisch ab. Einfach die Last weiterlaufen
   lassen / weiterspielen. Mit **Stop** brichst du jederzeit ab (Default-Limit wird sofort gesetzt).
5. **Ergebnis lesen** — Chart + Tabelle + Empfehlung (Sweet-Spot, Effizienz-Peak, Knie).
6. **Anwenden/Exportieren** — *Empfehlung anwenden* setzt das Limit, *Reset Default* stellt zurück;
   *CSV-Export* / *Run speichern* sichern den Lauf (die JSON-Datei kannst du auch Claude zur
   Auswertung schicken).

**Vorher an/aus stellen:**
- **V-Sync und FPS-Limit AUS** — sonst deckelt der Cap die Kurve und das Ergebnis stimmt nicht.
- **GPU-lastige, reproduzierbare Szene** — beim Spielen möglichst immer dieselbe Stelle/Last.
- **Afterburner:** nur die Undervolt-/V-F-Kurve nutzen, den **Power-Limit-Regler dort auf Default**
  lassen (sonst Schreibkonflikt — dieses Tool soll das Power-Limit allein besitzen).
- **PresentMon-Modus:** als **Administrator** starten; Prozessname = der tatsächlich rendernde
  Prozess (bei Launchern oft ein Kindprozess).
- **HWiNFO-Modus:** HWiNFO läuft + „Shared Memory Support" an (Free-Version: nach 12 h neu
  aktivieren); FPS nur, wenn HWiNFO sie von RTSS bekommt.

**Buttons:** *Sweep starten* / *Stop* · *Empfehlung anwenden* (setzt das empfohlene Limit) ·
*Reset Default* (Hersteller-Default) · *CSV-Export* · *Run speichern* / *Run laden* (JSON).
"""


def _format_mmss(seconds: float) -> str:
    """Sekunden als ``m:ss`` formatieren."""
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


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
    """Erzeugt einen ProcessBenchmarkRunner oder ``None``, wenn keine EXE gesetzt ist."""
    exe = source_config.benchmark_exe
    if not exe or not exe.strip():
        return None
    return ProcessBenchmarkRunner(
        exe, source_config.benchmark_args, source_config.benchmark_warmup_s
    )


_FileTypes = list[tuple[str, str]]


def _open_dialog(filetypes: _FileTypes, title: str) -> str | None:
    """Nativer „Öffnen“-Dialog (tkinter), serverseitig auf demselben Rechner. ``None`` bei
    Abbruch oder wenn tkinter nicht verfügbar ist."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
    except Exception:
        return None
    return path or None


def _save_dialog(initialfile: str, defaultextension: str, filetypes: _FileTypes) -> str | None:
    """Nativer „Speichern unter“-Dialog (tkinter). ``None`` bei Abbruch/Nichtverfügbarkeit."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.asksaveasfilename(
            title="Speichern unter",
            initialfile=initialfile,
            defaultextension=defaultextension,
            filetypes=filetypes,
        )
        root.destroy()
    except Exception:
        return None
    return path or None


class AppController:
    """Hält den UI-Zustand im Speicher und koordiniert Sweep-Lauf und Aktionen."""

    def __init__(self, gpus: list[GpuInfo], backend: GpuBackend) -> None:
        self._gpus = gpus
        self._backend = backend
        self._rows: list[SweepRow] = []
        self._result: SweepResult | None = None
        self._stop_flag = False
        self._running = False
        self._eta_timer: ui.timer | None = None
        self._eta_total_s = 0.0
        self._eta_start = 0.0
        self._planned_steps = 0
        # Vom Worker-Thread beschrieben, vom UI-Timer gelesen (keine UI-Calls im Thread!).
        self._status_msg = ""
        self._telem_str = ""
        self._last_rendered_count = -1
        self._build_layout()

    # -- Layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        ui.dark_mode(True)
        ui.colors(primary=_ACCENT)
        with ui.header().classes("items-center"):
            ui.label(APP_TITLE).classes("text-xl font-bold")
        self._build_no_gpu_banner()
        with ui.expansion("So funktioniert's — kurze Anleitung", icon="help_outline").classes(
            "w-full"
        ):
            ui.markdown(_HELP_MD)
        with ui.row().classes("w-full no-wrap"):
            with ui.column().classes("w-1/3"):
                self._panel = ConfigPanel(
                    self._gpus,
                    on_pick_exe=self._pick_exe,
                    on_fill_max=self._fill_max_pct,
                    on_fill_min=self._fill_min_pct,
                )
                self._build_buttons()
            with ui.column().classes("w-2/3"):
                self._status = ui.label("Bereit.").classes("text-sm")
                self._telemetry = ui.label("").classes("text-xs text-grey")
                self._progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
                self._progress.visible = False
                self._eta = ui.label("").classes("text-xs text-grey")
                self._chart = EfficiencyChart()
                self._table = ResultsTable()
                self._recommendation = ui.label("").classes("text-sm")
        if not self._gpus:
            # Keine NVIDIA-GPU/Treiber: Sweep deaktivieren statt später eine Exception
            # zu werfen. Der Hinweis-Banner erklärt es; die UI bleibt voll bedienbar.
            self._start_btn.disable()

    def _build_no_gpu_banner(self) -> None:
        """Zeigt einen klaren Hinweis, wenn keine GPU erkannt wurde — kein Fehler/Traceback."""
        if self._gpus:
            return
        with ui.element("div").classes("w-full bg-orange-9 text-white q-pa-sm rounded-borders"):
            ui.label("Keine NVIDIA-GPU gefunden").classes("font-bold")
            ui.label(
                "Auf diesem Rechner ist kein NVIDIA-Treiber/keine NVIDIA-GPU verfügbar — "
                "der Sweep ist deaktiviert. Die App startet trotzdem normal; zum Messen auf "
                "einem System mit NVIDIA-GPU und Administrator-Rechten ausführen."
            ).classes("text-sm")

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
        self._begin_run(sweep_config)
        try:
            await run.io_bound(self._run_sweep_sync, sweep_config, source_config, perf, benchmark)
        except GpuPermissionError:
            ui.notify("Bitte die App als Administrator starten.", type="negative")
        except GpuEfficiencyError as exc:
            ui.notify(str(exc), type="negative")
        except Exception as exc:
            _LOG.exception("Sweep fehlgeschlagen")
            ui.notify(f"Sweep fehlgeschlagen: {exc}", type="negative")
        else:
            # Endgültiges Rendern HIER (zurück im Event-Loop, gültiger UI-Kontext).
            if self._result is not None:
                self._render_result(self._result)
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
        # WICHTIG: Dieser Code läuft im Worker-Thread — KEINE ui.*-Aufrufe hier (kein Slot-Kontext).
        # Die Callbacks schreiben nur Daten; das Rendern macht der UI-Timer (_tick) im Event-Loop.
        self._result = asyncio.run(
            engine.run(
                sweep_config,
                gpu_name=gpu_name,
                workload_name=source_config.mode.value,
                timestamp=_dt.datetime.now().isoformat(timespec="seconds"),
                hooks=hooks,
            )
        )

    def _on_row(self, row: SweepRow) -> None:
        # Worker-Thread: nur Daten anhängen, kein UI-Zugriff.
        self._rows.append(row)

    def _on_status(self, message: str, telem: Telemetry | None) -> None:
        # Worker-Thread: nur Strings ablegen, kein UI-Zugriff.
        self._status_msg = message
        if telem is None:
            self._telem_str = ""
            return
        parts = [
            f"{telem.power_w:.0f} W",
            f"{telem.clock_mhz:.0f} MHz",
            f"{telem.temp_c:.0f} °C",
        ]
        if telem.voltage_mv is not None:
            parts.append(f"{telem.voltage_mv:.0f} mV")
        self._telem_str = " · ".join(parts)

    # -- UI-Updates (im Event-Loop) ---------------------------------------

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
        # In _status_msg schreiben, damit der Poll-Timer (_tick) die Meldung nicht überschreibt.
        self._status_msg = "Stop angefordert — Sweep wird abgebrochen, Default wird gesetzt …"
        self._status.set_text(self._status_msg)

    async def _pick_exe(self) -> None:
        """Öffnet den Datei-Dialog (im Worker-Thread, da blockierend) und setzt den EXE-Pfad."""
        path = await run.io_bound(
            _open_dialog,
            [("Programme", "*.exe"), ("Alle Dateien", "*.*")],
            "Benchmark-EXE auswählen",
        )
        if path:
            self._panel.set_benchmark_exe(path)
            ui.notify(f"Benchmark-EXE gewählt: {path}", type="positive")
        else:
            ui.notify(
                "Keine Datei gewählt (oder Dialog nicht verfügbar — Pfad bitte manuell eintippen).",
                type="warning",
            )

    def _limit_pcts(self) -> tuple[int, int] | None:
        """(max %, min %) der gewählten GPU aus den NVML-Grenzen; None, wenn nicht lesbar."""
        try:
            limits = self._backend.get_limits(self._panel.read_gpu_index())
        except Exception:
            return None
        if limits.default_w <= 0:
            return None
        return (
            round(limits.max_w / limits.default_w * 100),
            round(limits.min_w / limits.default_w * 100),
        )

    async def _fill_max_pct(self) -> None:
        pcts = self._limit_pcts()
        if pcts is None:
            ui.notify("Karten-Grenzen nicht lesbar (keine GPU?).", type="warning")
            return
        self._panel.set_start_pct(pcts[0])
        ui.notify(f"Start auf Karten-Maximum gesetzt: {pcts[0]} %.", type="positive")

    async def _fill_min_pct(self) -> None:
        pcts = self._limit_pcts()
        if pcts is None:
            ui.notify("Karten-Grenzen nicht lesbar (keine GPU?).", type="warning")
            return
        self._panel.set_end_pct(pcts[1])
        ui.notify(f"Ende auf Karten-Minimum gesetzt: {pcts[1]} %.", type="positive")

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

    async def _on_export_csv(self) -> None:
        if self._result is None:
            ui.notify("Kein Ergebnis zum Exportieren.", type="warning")
            return
        path = await run.io_bound(
            _save_dialog, "wattsmith_sweep.csv", ".csv", [("CSV", "*.csv"), ("Alle Dateien", "*.*")]
        )
        if not path:
            return  # Abgebrochen.
        try:
            export_csv(self._result, path)
        except OSError as exc:
            ui.notify(f"Export fehlgeschlagen: {exc}", type="negative")
        else:
            ui.notify(f"CSV exportiert: {path}", type="positive")

    async def _on_save(self) -> None:
        if self._result is None:
            ui.notify("Kein Ergebnis zum Speichern.", type="warning")
            return
        path = await run.io_bound(
            _save_dialog,
            "wattsmith_sweep.json",
            ".json",
            [("Run-JSON", "*.json"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return  # Abgebrochen.
        try:
            save_run(self._result, path)
        except OSError as exc:
            ui.notify(f"Speichern fehlgeschlagen: {exc}", type="negative")
        else:
            ui.notify(f"Run gespeichert: {path}", type="positive")

    async def _on_load(self) -> None:
        path = await run.io_bound(
            _open_dialog, [("Run-JSON", "*.json"), ("Alle Dateien", "*.*")], "Run laden"
        )
        if not path:
            return  # Abgebrochen.
        try:
            result = load_run(path)
        except (OSError, ValueError) as exc:
            ui.notify(f"Laden fehlgeschlagen: {exc}", type="negative")
            return
        self._result = result
        self._render_result(result)
        ui.notify(f"Run geladen: {path}", type="positive")

    # -- Button-Zustand ---------------------------------------------------

    def _begin_run(self, sweep_config: SweepConfig) -> None:
        self._running = True
        self._stop_flag = False
        self._rows = []
        self._result = None
        self._status_msg = ""
        self._telem_str = ""
        self._last_rendered_count = -1
        self._table.clear()
        self._recommendation.set_text("")
        self._start_btn.disable()
        self._stop_btn.enable()
        self._start_polling(sweep_config)

    def _start_polling(self, sweep_config: SweepConfig) -> None:
        """Schätzt die Gesamtdauer und startet den UI-Timer, der den Worker-Zustand rendert.

        Schätzung = (Stufen + ggf. Baseline-Gegenmessung) × (Aufwärm- + Messdauer);
        Abkühlpausen sind nicht enthalten (variabel) — daher untere Schranke.
        Der Timer läuft im Event-Loop (gültiger UI-Kontext) und pollt die vom Worker-Thread
        geschriebenen Daten — so werden UI-Elemente NIE aus dem Background-Thread erzeugt.
        """
        default_w: float | None = None
        try:
            # Nur für die Dauer-Schätzung; falls es fehlschlägt, läuft der Sweep trotzdem.
            default_w = self._backend.get_limits(sweep_config.gpu_index).default_w
        except Exception:
            default_w = None
        per_step = sweep_config.settle_s + sweep_config.measure_s
        extra = 1 if sweep_config.recheck_baseline else 0
        self._planned_steps = sweep_config.planned_step_count(default_w)
        self._eta_total_s = (self._planned_steps + extra) * per_step
        self._eta_start = time.monotonic()
        self._progress.value = 0.0
        self._progress.visible = True
        ui.notify(
            f"Sweep gestartet — {self._planned_steps} Stufen, geschätzt ca. "
            f"{self._eta_total_s / 60.0:.1f} min (ohne Abkühlpausen).",
            type="info",
        )
        self._eta_timer = ui.timer(0.5, self._tick)

    def _tick(self) -> None:
        """Läuft im Event-Loop: spiegelt den Worker-Zustand in die UI (Status, Tabelle, ETA)."""
        if not self._running:
            return
        self._status.set_text(self._status_msg)
        self._telemetry.set_text(self._telem_str)
        count = len(self._rows)
        if count != self._last_rendered_count:
            self._render_live(list(self._rows))
            self._last_rendered_count = count
        if self._eta_total_s > 0:
            elapsed = time.monotonic() - self._eta_start
            remaining = max(0.0, self._eta_total_s - elapsed)
            self._progress.value = min(1.0, elapsed / self._eta_total_s)
            self._eta.set_text(
                f"{count}/{self._planned_steps} Stufen gemessen · "
                f"noch ca. {_format_mmss(remaining)} (Schätzung)"
            )

    def _end_run(self) -> None:
        self._running = False
        self._start_btn.enable()
        self._stop_btn.disable()
        if self._eta_timer is not None:
            self._eta_timer.cancel()
            self._eta_timer = None
        self._progress.visible = False
        self._eta.set_text("")


def create_ui() -> None:
    """Registriert die Seite unter ``/`` (ruft NICHT ``ui.run``).

    Die UI wird bewusst in einem **expliziten** ``@ui.page("/")``-Handler aufgebaut, NICHT
    auf der Auto-Index-Seite. Das ist für den PyInstaller-Build zwingend: Für die
    Auto-Index-Seite führt NiceGUI das Einstiegsskript via ``runpy.run_path(sys.argv[0])``
    erneut aus — in der gepackten ``.exe`` ist ``sys.argv[0]`` aber eine Binärdatei
    (Null-Bytes) → ``SyntaxError: source code string cannot contain null bytes``. Ein
    expliziter Seiten-Handler wird hingegen direkt aufgerufen.

    Backend und GPU-Liste werden einmalig beim Start ermittelt; der Handler baut pro
    Client (im nativen Fenster genau einer) das Layout.
    """
    backend = build_backend()
    try:
        gpus = backend.list_gpus()
    except GpuEfficiencyError as exc:
        _LOG.warning("GPU-Liste konnte nicht gelesen werden: %s", exc)
        gpus = []

    @ui.page("/")
    def _index() -> None:
        AppController(gpus, backend)
