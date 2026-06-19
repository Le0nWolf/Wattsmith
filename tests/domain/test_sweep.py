"""Unit-Tests für die Sweep-Engine mit Fake-Ports — laufen OHNE GPU."""

from __future__ import annotations

import asyncio

import pytest

from gpu_efficiency_finder.config import SweepConfig
from gpu_efficiency_finder.domain.sweep import SweepEngine, SweepHooks
from gpu_efficiency_finder.models import PowerLimits, SweepRow, Telemetry, WindowMetrics


class FakeGpu:
    """Fake-GpuBackend: merkt sich gesetzte Limits und ob zurückgesetzt wurde."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.set_calls: list[float] = []
        self.reset_called = False
        self.last_watt = 300.0
        self._fail_after = fail_after

    def list_gpus(self):  # pragma: no cover - im Test ungenutzt
        return []

    def get_limits(self, idx: int) -> PowerLimits:
        return PowerLimits(default_w=300.0, min_w=100.0, max_w=350.0, current_w=300.0)

    def set_power_limit_w(self, idx: int, watt: float) -> None:
        self.set_calls.append(watt)
        if self._fail_after is not None and len(self.set_calls) > self._fail_after:
            raise RuntimeError("simulierter NVML-Fehler")
        self.last_watt = watt

    def read_telemetry(self, idx: int) -> Telemetry:
        # Verbrauch ~ gesetztes Limit; Takt skaliert mit.
        return Telemetry(
            power_w=self.last_watt * 0.95,
            clock_mhz=1000.0 + self.last_watt,
            temp_c=55.0,
            util_pct=99.0,
        )

    def reset_to_default(self, idx: int) -> None:
        self.reset_called = True


class FakePerf:
    """Fake-PerfSource: liefert eine Performance proportional zum aktuellen Limit."""

    def __init__(self, gpu: FakeGpu) -> None:
        self._gpu = gpu
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics:
        perf = self._gpu.last_watt * 0.4
        return WindowMetrics(avg_perf=perf, low_1=perf * 0.9, low_01=perf * 0.8)


def _hooks(rows: list[SweepRow], *, stop_after: int | None = None) -> SweepHooks:
    clock = {"t": 0.0}

    async def nosleep(_seconds: float) -> None:
        clock["t"] += 1.0

    def tick() -> float:
        return clock["t"]

    def should_stop() -> bool:
        return stop_after is not None and len(rows) >= stop_after

    return SweepHooks(
        on_row=rows.append,
        should_stop=should_stop,
        sleep=nosleep,
        clock=tick,
        shuffle=lambda _order: None,  # Identität → deterministische Reihenfolge
    )


def _config(**overrides: object) -> SweepConfig:
    base = dict(
        start_pct=100, end_pct=80, step_pct=10, randomize_order=False, recheck_baseline=False
    )
    base.update(overrides)
    return SweepConfig(**base)  # type: ignore[arg-type]


def test_sweep_produces_rows_and_resets() -> None:
    gpu = FakeGpu()
    perf = FakePerf(gpu)
    rows: list[SweepRow] = []
    engine = SweepEngine(gpu, perf)

    result = asyncio.run(engine.run(_config(), hooks=_hooks(rows), gpu_name="FakeGPU"))

    # Drei Stufen: 100/90/80 %.
    assert len(result.rows) == 3
    assert [r.pct for r in result.rows] == [100, 90, 80]  # sortiert absteigend
    assert gpu.reset_called
    assert perf.started and perf.stopped
    assert result.recommendation is not None
    assert result.efficiency_peak is not None


def test_sweep_resets_limit_even_on_error() -> None:
    gpu = FakeGpu(fail_after=1)  # zweites set_power_limit_w wirft
    perf = FakePerf(gpu)
    engine = SweepEngine(gpu, perf)

    with pytest.raises(RuntimeError):
        asyncio.run(engine.run(_config(), hooks=_hooks([])))

    assert gpu.reset_called  # Default-Limit MUSS trotz Exception wiederhergestellt werden
    assert perf.stopped


def test_sweep_stop_halts_early() -> None:
    gpu = FakeGpu()
    perf = FakePerf(gpu)
    rows: list[SweepRow] = []
    engine = SweepEngine(gpu, perf)

    result = asyncio.run(engine.run(_config(), hooks=_hooks(rows, stop_after=1)))

    assert len(result.rows) == 1  # nach der ersten Stufe gestoppt
    assert gpu.reset_called


def test_sweep_clamps_to_limits() -> None:
    gpu = FakeGpu()
    perf = FakePerf(gpu)
    engine = SweepEngine(gpu, perf)
    # start 100% → 300 W (innerhalb [100, 350]); 80% → 240 W.
    asyncio.run(engine.run(_config(), hooks=_hooks([])))
    assert all(100.0 <= w <= 350.0 for w in gpu.set_calls)


def test_baseline_recheck_reports_drift() -> None:
    gpu = FakeGpu()
    perf = FakePerf(gpu)
    engine = SweepEngine(gpu, perf)
    result = asyncio.run(engine.run(_config(recheck_baseline=True), hooks=_hooks([])))
    # FakePerf ist deterministisch → kein Drift.
    assert result.baseline_drift_pct == pytest.approx(0.0)
