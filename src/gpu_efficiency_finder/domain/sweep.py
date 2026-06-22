"""Sweep-Engine — orchestriert Backend + Last + Perf-Quelle. Hängt NUR an Ports (DI),
kennt keine konkrete Hardware und ist mit Fakes ohne GPU testbar.

Sicherheits-Invariante: Das Default-Limit wird in JEDEM Pfad wiederhergestellt
(normales Ende, Stop, Exception) — via ``try/finally``.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from gpu_efficiency_finder.domain import analysis
from gpu_efficiency_finder.errors import SweepAbortedError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import (
    SweepResult,
    SweepRow,
    Telemetry,
)
from gpu_efficiency_finder.ports import BenchmarkRunner, GpuBackend, PerfSource

__all__ = ["SweepEngine", "SweepHooks"]

_log = get_logger(__name__)

_TELEMETRY_SAMPLES = 3  # schnelle Mittelung des Verbrauchs am Fensterende
_COOLDOWN_POLL_S = 2.0
_COOLDOWN_MAX_WAIT_S = 120.0
_STOP_POLL_S = 0.25  # Auflösung, mit der während der Wartezeiten auf Stop geprüft wird

RowCallback = Callable[[SweepRow], None]
StatusCallback = Callable[[str, Telemetry | None], None]
SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]
ShuffleFn = Callable[[list[int]], None]


@dataclass(slots=True)
class SweepHooks:
    """Optionale Callbacks/Injektionspunkte (für UI-Live-Updates und Tests)."""

    on_row: RowCallback | None = None
    on_status: StatusCallback | None = None
    should_stop: Callable[[], bool] | None = None
    sleep: SleepFn = asyncio.sleep
    clock: ClockFn = time.monotonic
    shuffle: ShuffleFn = random.shuffle


class SweepEngine:
    """Fährt das Power-Limit stufenweise ab und misst pro Stufe Verbrauch + Performance."""

    def __init__(
        self,
        gpu: GpuBackend,
        perf: PerfSource,
        benchmark: BenchmarkRunner | None = None,
    ) -> None:
        self._gpu = gpu
        self._perf = perf
        self._benchmark = benchmark

    async def run(
        self,
        config: object,
        *,
        gpu_name: str = "",
        workload_name: str = "",
        timestamp: str = "",
        hooks: SweepHooks | None = None,
    ) -> SweepResult:
        """Führt den kompletten Sweep aus. ``config`` ist eine ``SweepConfig`` (typisiert
        per Duck-Typing gehalten, damit die Domain nicht an pydantic hängt)."""
        h = hooks or SweepHooks()
        idx: int = config.gpu_index  # type: ignore[attr-defined]
        limits = self._gpu.get_limits(idx)

        watt_by_pct = {
            pct: _clamp(limits.default_w * pct / 100.0, limits.min_w, limits.max_w)
            for pct in config.steps()  # type: ignore[attr-defined]
        }
        order = list(watt_by_pct.keys())
        if config.randomize_order:  # type: ignore[attr-defined]
            h.shuffle(order)

        rows: list[SweepRow] = []
        aborted = False
        self._benchmark_start(h)
        self._perf.start()
        try:
            for pct in order:
                if h.should_stop and h.should_stop():
                    aborted = True
                    break
                try:
                    row = await self._measure_step(idx, pct, watt_by_pct[pct], config, h)
                except SweepAbortedError:
                    aborted = True
                    break
                rows.append(row)
                if h.on_row:
                    h.on_row(row)

            baseline_drift = None
            if not aborted and config.recheck_baseline and rows:  # type: ignore[attr-defined]
                try:
                    baseline_drift = await self._recheck_baseline(idx, watt_by_pct, config, rows, h)
                except SweepAbortedError:
                    aborted = True
        finally:
            self._teardown(idx, h)

        rows_sorted = tuple(sorted(rows, key=lambda r: r.set_watt, reverse=True))
        return self._build_result(
            rows_sorted,
            limits.default_w,
            gpu_name,
            workload_name,
            timestamp,
            baseline_drift,
            config,
        )

    # -- interne Schritte -------------------------------------------------

    async def _measure_step(
        self, idx: int, pct: int, watt: float, config: object, h: SweepHooks
    ) -> SweepRow:
        self._gpu.set_power_limit_w(idx, watt)
        _status(h, f"Stufe {pct}% ({watt:.0f} W): Aufwärmen…", None)
        await self._sleep(config.settle_s, h)  # type: ignore[attr-defined]
        await self._cooldown_if_needed(idx, config, h)

        t_start = h.clock()
        _status(h, f"Stufe {pct}% ({watt:.0f} W): Messen…", self._safe_telemetry(idx))
        await self._sleep(config.measure_s, h)  # type: ignore[attr-defined]
        t_end = h.clock()

        telem = self._averaged_telemetry(idx)
        metrics = self._perf.window_metrics(t_start, t_end)
        return SweepRow(
            set_watt=watt,
            pct=pct,
            power_w=telem.power_w,
            clock_mhz=telem.clock_mhz,
            temp_c=telem.temp_c,
            avg_perf=metrics.avg_perf if metrics else None,
            low_1=metrics.low_1 if metrics else None,
            low_01=metrics.low_01 if metrics else None,
        )

    async def _cooldown_if_needed(self, idx: int, config: object, h: SweepHooks) -> None:
        target: float | None = config.cooldown_target_c  # type: ignore[attr-defined]
        if target is None:
            return
        waited = 0.0
        while waited < _COOLDOWN_MAX_WAIT_S:
            if h.should_stop and h.should_stop():
                raise SweepAbortedError
            telem = self._safe_telemetry(idx)
            if telem is None or telem.temp_c <= target:
                return
            _status(h, f"Abkühlen auf ≤ {target:.0f} °C (aktuell {telem.temp_c:.0f} °C)…", telem)
            await h.sleep(_COOLDOWN_POLL_S)
            waited += _COOLDOWN_POLL_S

    async def _sleep(self, seconds: float, h: SweepHooks) -> None:
        """Unterbrechbarer Sleep: prüft regelmäßig ``should_stop`` und bricht via
        ``SweepAbortedError`` ab — so wirkt Stop sofort, nicht erst nach der Stufe."""
        remaining = float(seconds)
        while remaining > 0:
            if h.should_stop and h.should_stop():
                raise SweepAbortedError
            chunk = min(_STOP_POLL_S, remaining)
            await h.sleep(chunk)
            remaining -= chunk

    async def _recheck_baseline(
        self,
        idx: int,
        watt_by_pct: dict[int, float],
        config: object,
        rows: list[SweepRow],
        h: SweepHooks,
    ) -> float | None:
        """Misst die höchste Stufe erneut; gibt die Abweichung der Ø-Perf in % zurück."""
        top_pct = max(watt_by_pct)
        first = next((r for r in rows if r.pct == top_pct), None)
        if first is None or first.avg_perf is None:
            return None
        _status(h, "Baseline-Gegenmessung (Thermal-Drift)…", None)
        recheck = await self._measure_step(idx, top_pct, watt_by_pct[top_pct], config, h)
        if recheck.avg_perf is None or first.avg_perf <= 0:
            return None
        drift = (first.avg_perf - recheck.avg_perf) / first.avg_perf * 100.0
        if abs(drift) > config.baseline_drift_warn_pct:  # type: ignore[attr-defined]
            _log.warning("Baseline-Drift %.1f%% > Schwelle — Ergebnis evtl. verzerrt.", drift)
        return drift

    # -- Hardware-Helfer (kapseln Port-Aufrufe, fangen Telemetriefehler ab) ---

    def _averaged_telemetry(self, idx: int) -> Telemetry:
        samples = [self._gpu.read_telemetry(idx) for _ in range(_TELEMETRY_SAMPLES)]
        n = len(samples)
        return Telemetry(
            power_w=sum(s.power_w for s in samples) / n,
            clock_mhz=sum(s.clock_mhz for s in samples) / n,
            temp_c=sum(s.temp_c for s in samples) / n,
            util_pct=sum(s.util_pct for s in samples) / n,
        )

    def _safe_telemetry(self, idx: int) -> Telemetry | None:
        try:
            return self._gpu.read_telemetry(idx)
        except Exception:
            return None

    def _benchmark_start(self, h: SweepHooks) -> None:
        if self._benchmark is None:
            return
        _status(h, "Starte Benchmark-Last…", None)
        self._benchmark.start()

    def _teardown(self, idx: int, h: SweepHooks) -> None:
        try:
            self._perf.stop()
        except Exception:
            _log.exception("PerfSource.stop() fehlgeschlagen")
        if self._benchmark is not None:
            try:
                self._benchmark.stop()
            except Exception:
                _log.exception("BenchmarkRunner.stop() fehlgeschlagen")
        # WICHTIG: Default-Limit IMMER wiederherstellen.
        self._gpu.reset_to_default(idx)
        _status(h, "Default-Limit wiederhergestellt.", None)
        _log.info("Default-Limit wiederhergestellt (GPU %d).", idx)

    def _build_result(
        self,
        rows: tuple[SweepRow, ...],
        default_w: float,
        gpu_name: str,
        workload_name: str,
        timestamp: str,
        baseline_drift: float | None,
        config: object,
    ) -> SweepResult:
        peak = analysis.efficiency_peak(rows, default_w)
        knee = analysis.knee_point(rows, default_w)
        rec = analysis.recommend(
            rows,
            avg_tol_pct=config.avg_tol_pct,  # type: ignore[attr-defined]
            low_tol_pct=config.low_tol_pct,  # type: ignore[attr-defined]
            min_fps_floor=config.min_fps_floor,  # type: ignore[attr-defined]
            default_w=default_w,
        )
        return SweepResult(
            gpu_name=gpu_name,
            workload_name=workload_name,
            timestamp=timestamp,
            rows=rows,
            efficiency_peak=peak,
            knee=knee,
            recommendation=rec,
            baseline_drift_pct=baseline_drift,
            config=_config_to_dict(config),
        )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _status(h: SweepHooks, message: str, telem: Telemetry | None) -> None:
    if h.on_status:
        h.on_status(message, telem)


def _config_to_dict(config: object) -> dict[str, object]:
    dump = getattr(config, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return {}
