"""UI-Baustein: Konfigurations-Panel (Sweep-Parameter + Mess-Quelle).

Rendert alle Eingaben in einer ``ui.card`` (Dark Theme) und liest sie auf Wunsch in
validierte ``SweepConfig`` + ``SourceConfig`` ein. Validierungsfehler (pydantic) werden in
eine deutsche Meldung übersetzt; die UI zeigt sie an, statt zu crashen.

Jedes Feld hat ein hoverbares Info-Icon (ⓘ), damit auch unerfahrene Nutzer ohne Vorwissen
sofort sehen, was eine Einstellung bewirkt.

Reine Eingabe-Sammelei — keine Domain-Logik, keine Hardware.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from nicegui import ui
from pydantic import ValidationError

from gpu_efficiency_finder.config import SourceConfig, SweepConfig
from gpu_efficiency_finder.constants import (
    BENCHMARK_PRESETS,
    DEFAULT_BENCHMARK_PRESET,
    PRESENTMON_PROCESS_HINT,
    MeasurementMode,
)
from gpu_efficiency_finder.models import GpuInfo

__all__ = ["ConfigPanel"]

# Mess-Modus → Anzeigename mit echten Umlauten.
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
    "Preset wählen (füllt Optionen + EXE-Empfehlung), EXE per „Durchsuchen“ setzen. Empfohlen: ein "
    "Loop-Benchmark (Superposition), damit die Last konstant und reproduzierbar ist. "
    "Score-am-Ende-Benchmarks sind ungeeignet (durchgehende Last nötig). FurMark erzeugt eine "
    "untypische Extrem-Last → nur für „Nur Takt“ sinnvoll, nicht repräsentativ fürs Gaming. "
    "OCCT eignet sich; aber für die Messung eine KONSTANTE Last wählen — wechselnde Lasten "
    "(gut für Undervolt-Stabilität) verrauschen die Effizienzkurve. 3DMark braucht für CLI die "
    "Professional Edition. EXE-Feld leer lassen = Last manuell starten (z. B. ein Spiel)."
)

_HWINFO_HINT = (
    "HWiNFO muss mit aktivem „Shared Memory Support“ laufen; die Free-Version deaktiviert "
    "ihn nach 12 Stunden automatisch."
)

# Tooltip-Texte je Feld (echte Umlaute, anfängertauglich formuliert).
_T_GPU = "Welche NVIDIA-GPU gesteuert und gemessen wird. Bei nur einer Karte einfach GPU 0."
_T_START = (
    "Höchstes Power-Limit (in % vom Hersteller-Default), bei dem der Sweep startet, = Baseline. "
    ">100 % nutzt das Overclock-Limit der Karte. „Max“ füllt das Karten-Maximum automatisch ein."
)
_T_END = (
    "Niedrigstes Power-Limit (in % vom Default), bis zu dem heruntergefahren wird. „Min“ füllt "
    "das Karten-Minimum ein. Tiefer als der Treiber erlaubt geht nicht (wird geclampt)."
)
_T_STEP = (
    "Schrittweite zwischen den Stufen in %. Kleiner = feinere Kurve, aber längerer Lauf "
    "(mehr Stufen). 5 % ist ein guter Kompromiss. Wird ignoriert, wenn „Watt-für-Watt“ an ist."
)
_T_WATT_STEPS = (
    "Statt in %-Schritten in Watt-Schritten messen — feiner (das Knie liegt oft zwischen zwei "
    "%-Stufen), dauert aber länger. Der Bereich bleibt der Start/Ende-%-Bereich oben."
)
_T_WATT_STEP = (
    "Schrittweite in Watt, wenn „Watt-für-Watt“ aktiv ist (z. B. 5 W; 1 W = sehr fein/lang)."
)
_T_SETTLE = (
    "Sekunden, die nach JEDEM Limit-Wechsel verworfen werden, damit sich Takt und Verbrauch "
    "einschwingen. Erst danach startet der Mess-Countdown."
)
_T_MEASURE = (
    "Länge des Messfensters pro Stufe. Idealerweise = Dauer eines KOMPLETTEN Benchmark-Loops, "
    "damit jede Stufe denselben Szenen-Mix mittelt und die Kurve vergleichbar bleibt."
)
_T_AVG_TOL = (
    "Wie viel durchschnittliche FPS du gegenüber der Baseline höchstens opfern willst (in %). "
    "Die Empfehlung bleibt darunter. Default 3 %."
)
_T_LOW_TOL = (
    "Wie viel 1%-Low (Frametime-Stabilität) du höchstens opfern willst (in %). Schützt vor "
    "Rucklern. Default 5 %."
)
_T_RANDOMIZE = (
    "Misst die Stufen in zufälliger Reihenfolge, damit das Aufheizen der Karte die Kurve nicht "
    "systematisch verzerrt. Die Anzeige bleibt sortiert. Empfohlen: an. Für einen einfachen "
    "Test/Debug ausschalten → Stufen laufen dann sauber 100 % → … → 50 % der Reihe nach."
)
_T_RECHECK = (
    "Misst am Ende die höchste Stufe erneut und warnt bei Thermal-Drift. Setzt das Limit dabei "
    "kurz wieder hoch (sieht aus wie „springt zurück“ — ist Absicht). Zum Testen abschaltbar."
)
_T_COOLDOWN_ON = (
    "Wenn an: vor jeder Stufe warten, bis die GPU-Temperatur unter den Zielwert fällt. "
    "Reduziert Thermal-Drift, verlängert aber den Lauf."
)
_T_COOLDOWN_C = "Ziel-Temperatur (°C), unter die abgekühlt wird, bevor die nächste Stufe misst."
_T_FLOOR_ON = (
    "Optional: eine absolute FPS-Untergrenze erzwingen (z. B. Monitor-Hz). "
    "Aus = es zählen nur die relativen Toleranzen."
)
_T_FLOOR = (
    "Die Empfehlung sorgt dafür, dass Ø-FPS und 1%-Low NICHT unter diesen Wert fallen. Ist die "
    "Grenze bindend, zeigt das Tool, wie viel mehr Ersparnis ohne sie möglich wäre."
)
_T_PRESET = (
    "Benchmark-Vorlage wählen → füllt die Startoptionen und zeigt unten, WELCHE EXE du nehmen "
    "sollst (z. B. bei FurMark furmark.exe statt der GUI). EXE-Pfad wählst du per „Durchsuchen“."
)
_T_BENCH_EXE = (
    "Pfad zur Benchmark-EXE (Dauerlast). Über „Durchsuchen“ per Datei-Explorer wählen oder "
    "direkt eintippen. Leer lassen = Last selbst starten (z. B. ein Spiel)."
)
_T_BENCH_ARGS = (
    "Startoptionen/Argumente für die EXE (z. B. Auflösung, Loop-Modus, „kein GUI“). Optional — "
    "je nach Benchmark unterschiedlich."
)
_T_WARMUP = (
    "EINMALIGE Wartezeit direkt nach dem Start des Benchmarks, bis er geladen und im Loop ist — "
    "bevor der Sweep beginnt. Nicht zu verwechseln mit „Aufwärmen“ pro Stufe."
)
_T_PM_PATH = "Pfad zur PresentMon-Konsolen-EXE. Leer = die in der App gebündelte Version nutzen."
_T_HWINFO_MEM = "Name des HWiNFO-Shared-Memory. Leer = Standard (Global\\HWiNFO_SENS_SM2)."
_T_HWINFO_VOLTAGE = (
    "Liest die GPU-Core-Spannung (mV) pro Stufe aus HWiNFO mit — unabhängig vom Mess-Modus, "
    "ideal fürs Undervolting. Braucht laufendes HWiNFO + aktiven Shared Memory; sonst bleibt "
    "die Spalte „Spannung“ leer (NVML gibt sie auf Consumer-Karten nicht her)."
)


def _info(text: str) -> None:
    """Kleines, hoverbares Info-Icon mit Tooltip."""
    ui.icon("info", size="sm").classes("text-grey-5 cursor-help").tooltip(text)


def _num(label: str, value: float, info: str, **kwargs: float) -> ui.number:
    """Zahlen-Eingabe in einer Zeile mit nachgestelltem Info-Icon."""
    with ui.row().classes("w-full items-center no-wrap"):
        element = ui.number(label, value=value, **kwargs).classes("grow")
        _info(info)
    return element


def _txt(label: str, info: str, *, placeholder: str = "") -> ui.input:
    """Text-Eingabe in einer Zeile mit Info-Icon."""
    with ui.row().classes("w-full items-center no-wrap"):
        element = ui.input(label, placeholder=placeholder).classes("grow")
        _info(info)
    return element


def _switch(label: str, value: bool, info: str) -> ui.switch:
    """Schalter in einer Zeile mit Info-Icon."""
    with ui.row().classes("items-center no-wrap"):
        element = ui.switch(label, value=value)
        _info(info)
    return element


class ConfigPanel:
    """Sammelt alle Konfigurationswerte und liefert validierte Config-Objekte."""

    def __init__(
        self,
        gpus: Sequence[GpuInfo],
        on_pick_exe: Callable[[], Awaitable[None]] | None = None,
        on_fill_max: Callable[[], Awaitable[None]] | None = None,
        on_fill_min: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._on_pick_exe = on_pick_exe
        self._on_fill_max = on_fill_max
        self._on_fill_min = on_fill_min
        self._gpu_options = {g.index: f"GPU {g.index}: {g.name}" for g in gpus}
        default_idx = next(iter(self._gpu_options), 0)
        with ui.card().classes("w-full").props("dark"):
            ui.label("Konfiguration").classes("text-lg font-bold")
            self._gpu = self._select("GPU", self._gpu_options or {0: "GPU 0"}, default_idx, _T_GPU)
            self._mode = self._select(
                "Mess-Modus",
                {m.value: _MODE_LABELS[m] for m in MeasurementMode},
                MeasurementMode.CLOCK_PROXY.value,
                _MODE_HELP,
            )
            ui.label(_MODE_HELP).classes("text-xs text-grey")

            self._build_sweep_inputs()
            self._build_floor_inputs()
            self._build_benchmark_inputs()
            self._build_presentmon_inputs()
            self._build_hwinfo_inputs()

    @staticmethod
    def _select(
        label: str,
        options: dict[object, str],
        value: object,
        info: str,
        on_change: Callable[[], None] | None = None,
    ) -> ui.select:
        """Auswahl-Feld in einer Zeile mit Info-Icon."""
        with ui.row().classes("w-full items-center no-wrap"):
            element = ui.select(
                options=options, value=value, label=label, on_change=on_change
            ).classes("grow")
            _info(info)
        return element

    # -- Eingabe-Gruppen --------------------------------------------------

    def _build_sweep_inputs(self) -> None:
        with ui.row().classes("w-full items-center no-wrap"):
            self._start = ui.number("Start %", value=100, min=20, max=200, step=5).classes("grow")
            ui.button("Max", on_click=self._on_fill_max).props("flat dense").tooltip(
                "Auf das Power-Limit-Maximum der Karte setzen (Overclock-Limit, z. B. 117 %)"
            )
            _info(_T_START)
        with ui.row().classes("w-full items-center no-wrap"):
            self._end = ui.number("Ende %", value=50, min=5, max=100, step=5).classes("grow")
            ui.button("Min", on_click=self._on_fill_min).props("flat dense").tooltip(
                "Auf das Power-Limit-Minimum der Karte setzen"
            )
            _info(_T_END)
        self._step = _num("Schritt %", 5, _T_STEP, min=1, max=25, step=1)
        self._watt_steps = _switch("Watt-für-Watt (feiner, langsamer)", False, _T_WATT_STEPS)
        self._watt_step = _num("Watt-Schritt", 5, _T_WATT_STEP, min=1, max=50, step=1)
        self._settle = _num("Aufwärmen (s)", 8.0, _T_SETTLE, min=2, max=180, step=1)
        self._measure = _num("Messen (s)", 25.0, _T_MEASURE, min=5, max=900, step=5)
        ui.label(
            "„Aufwärmen“ = Wartezeit nach jedem Limit-Wechsel (verworfen); „Messen“ ≈ Dauer eines "
            "kompletten Benchmark-Loops wählen, damit die Stufen vergleichbar bleiben."
        ).classes("text-xs text-grey")
        self._avg_tol = _num("Toleranz Ø %", 3.0, _T_AVG_TOL, min=0, max=30, step=0.5)
        self._low_tol = _num("Toleranz Low %", 5.0, _T_LOW_TOL, min=0, max=40, step=0.5)
        self._randomize = _switch("Reihenfolge randomisieren", True, _T_RANDOMIZE)
        self._recheck = _switch("Baseline-Gegenmessung am Ende", True, _T_RECHECK)
        self._cooldown_on = _switch("Abkühlen bis Ziel-Temperatur", False, _T_COOLDOWN_ON)
        self._cooldown_c = _num("Ziel °C", 55.0, _T_COOLDOWN_C, min=20, max=90, step=1)

    def _build_floor_inputs(self) -> None:
        self._floor_on = _switch("Absolute FPS-Untergrenze", False, _T_FLOOR_ON)
        self._floor = _num("min. FPS", 60.0, _T_FLOOR, min=1, step=1)

    def _build_benchmark_inputs(self) -> None:
        ui.separator()
        ui.label("Externe Benchmark-Last (optional)").classes("font-bold")
        self._preset = self._select(
            "Benchmark-Preset",
            {name: name for name in BENCHMARK_PRESETS},
            DEFAULT_BENCHMARK_PRESET,
            _T_PRESET,
            on_change=self._apply_preset,
        )
        with ui.row().classes("w-full items-center no-wrap"):
            self._bench_exe = ui.input("Benchmark-EXE (Pfad)").classes("grow")
            ui.button(icon="folder_open", on_click=self._on_pick_exe).props("flat dense").tooltip(
                "EXE per Datei-Explorer auswählen"
            )
            _info(_T_BENCH_EXE)
        # Dynamische EXE-Empfehlung des gewählten Presets (z. B. „furmark.exe statt GUI“).
        self._preset_hint = ui.label("").classes("text-xs text-amber")
        self._bench_args = _txt(
            "Startoptionen",
            _T_BENCH_ARGS,
            placeholder="z. B. /width=2560 /height=1440 /msaa=0 /nogui",
        )
        self._warmup = _num("Benchmark-Warmup (s)", 10.0, _T_WARMUP, min=0, max=120, step=1)
        ui.label(_BENCHMARK_HINT).classes("text-xs text-grey")
        self._apply_preset()  # initialen EXE-Hinweis setzen

    def _apply_preset(self) -> None:
        """Füllt die Startoptionen und zeigt den EXE-Hinweis des gewählten Presets."""
        preset = BENCHMARK_PRESETS.get(str(self._preset.value))
        if preset is None:
            return
        self._preset_hint.set_text(preset.exe_hint)
        # „Eigener Befehl“ lässt eingetippte Optionen unangetastet.
        if str(self._preset.value) != "Eigener Befehl":
            self._bench_args.value = preset.args

    def set_benchmark_exe(self, path: str) -> None:
        """Setzt den EXE-Pfad (vom Datei-Dialog des Controllers aufgerufen)."""
        self._bench_exe.value = path

    def set_start_pct(self, pct: int) -> None:
        """Setzt Start % (vom „Max“-Button des Controllers, aus den Karten-Grenzen)."""
        self._start.value = pct

    def set_end_pct(self, pct: int) -> None:
        """Setzt Ende % (vom „Min“-Button des Controllers, aus den Karten-Grenzen)."""
        self._end.value = pct

    def _build_presentmon_inputs(self) -> None:
        ui.separator()
        ui.label("PresentMon").classes("font-bold")
        self._pm_path = _txt("PresentMon-Pfad (leer = gebündelt)", _T_PM_PATH)
        self._pm_process = _txt("Prozessname (z. B. spiel.exe)", PRESENTMON_PROCESS_HINT)
        ui.label(PRESENTMON_PROCESS_HINT).classes("text-xs text-grey")

    def _build_hwinfo_inputs(self) -> None:
        ui.separator()
        ui.label("HWiNFO").classes("font-bold")
        self._hwinfo_mem = _txt("Shared-Memory-Name (leer = Standard)", _T_HWINFO_MEM)
        self._hwinfo_voltage = _switch("Spannung aus HWiNFO mitlesen", True, _T_HWINFO_VOLTAGE)
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
                watt_steps=bool(self._watt_steps.value),
                watt_step=float(self._watt_step.value),
                recheck_baseline=bool(self._recheck.value),
                cooldown_target_c=float(self._cooldown_c.value)
                if self._cooldown_on.value
                else None,
            )
            source = SourceConfig(
                mode=MeasurementMode(self._mode.value),
                presentmon_path=_blank_to_none(self._pm_path.value),
                process_name=_blank_to_none(self._pm_process.value),
                benchmark_exe=_blank_to_none(self._bench_exe.value),
                benchmark_args=str(self._bench_args.value or "").strip(),
                benchmark_warmup_s=float(self._warmup.value),
                hwinfo_shared_mem=_blank_to_none(self._hwinfo_mem.value),
                read_hwinfo_voltage=bool(self._hwinfo_voltage.value),
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
