"""Geteilte, unveränderliche Value Objects — die Single Source of Truth für Daten.

Diese Modelle leben EINMAL hier und werden von Domain, Adaptern, Persistenz und UI
gemeinsam genutzt. Keine Logik, keine I/O — nur Daten.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gpu_efficiency_finder.constants import OperatingPointKind

__all__ = [
    "GpuInfo",
    "OperatingPoint",
    "PowerLimits",
    "Recommendation",
    "SweepResult",
    "SweepRow",
    "Telemetry",
    "WindowMetrics",
]


@dataclass(frozen=True, slots=True)
class GpuInfo:
    """Eine erkannte GPU."""

    index: int
    name: str


@dataclass(frozen=True, slots=True)
class PowerLimits:
    """Power-Limit-Grenzen einer GPU, in Watt (NVML liefert mW — Adapter rechnet um)."""

    default_w: float
    min_w: float
    max_w: float
    current_w: float


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Momentane Telemetrie einer GPU."""

    power_w: float
    clock_mhz: float
    temp_c: float
    util_pct: float
    # Zusatzsensoren aus HWiNFO (NVML liefert sie nicht): Core-Spannung in mV, Hot-Spot- und
    # Speicher-(Junction-)Temperatur in °C. ``None``, wenn keine HWiNFO-Quelle verfügbar.
    voltage_mv: float | None = None
    hotspot_c: float | None = None
    mem_temp_c: float | None = None


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Performance-Metriken einer PerfSource über ein Zeitfenster.

    ``avg_perf`` ist der generische Performance-Skalar (FPS, Iterationen/s oder Takt-MHz,
    je nach Quelle). ``low_1``/``low_01`` sind nur bei frame-basierten Quellen (PresentMon)
    gesetzt; sonst ``None``.
    """

    avg_perf: float
    low_1: float | None = None
    low_01: float | None = None
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class SweepRow:
    """Ein gemessener Sweep-Punkt (eine Power-Limit-Stufe).

    ``set_watt`` ist das gesetzte Limit, ``power_w`` der TATSÄCHLICH gemessene Verbrauch
    (x-Achse der Analyse — oben zieht die Karte oft nicht die vollen Watt).
    ``avg_perf`` ist der Performance-Skalar der gewählten Quelle.
    """

    set_watt: float
    pct: int
    power_w: float
    clock_mhz: float
    temp_c: float
    avg_perf: float | None = None
    low_1: float | None = None
    low_01: float | None = None
    voltage_mv: float | None = None
    hotspot_c: float | None = None
    mem_temp_c: float | None = None


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    """Ein ausgezeichneter Betriebspunkt (Effizienz-Peak, Knie oder Empfehlung).

    Alle Verluste sind relativ zur Baseline (Stufe mit höchster Ø-Performance).
    """

    kind: OperatingPointKind
    set_watt: float
    power_w: float
    pct_of_default: float
    savings_w: float
    savings_pct: float
    avg_perf: float | None
    avg_perf_loss_pct: float | None
    low_1: float | None
    low_1_loss_pct: float | None
    perf_per_w: float | None


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Ergebnis von :func:`analysis.recommend`.

    ``recommended`` ist die (ggf. durch die FPS-Untergrenze beschränkte) stutter-sichere
    Empfehlung. ``unconstrained_optimum`` ist die Empfehlung OHNE Untergrenze. Ist die
    Untergrenze bindend (``floor_binding``), zeigt ``extra_savings_w/pct`` an, wie viel mehr
    man ohne sie sparen könnte.
    """

    recommended: OperatingPoint | None
    unconstrained_optimum: OperatingPoint | None
    floor_binding: bool = False
    extra_savings_w: float = 0.0
    extra_savings_pct: float = 0.0
    satisfiable: bool = True
    message: str | None = None


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Vollständiges Resultat eines Sweeps inkl. aller Betriebspunkte und Metadaten."""

    gpu_name: str
    workload_name: str
    timestamp: str
    rows: tuple[SweepRow, ...]
    efficiency_peak: OperatingPoint | None = None
    knee: OperatingPoint | None = None
    recommendation: Recommendation | None = None
    baseline_drift_pct: float | None = None
    config: dict[str, object] = field(default_factory=dict)
