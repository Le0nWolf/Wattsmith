"""Unit-Tests für die reinen Analysefunktionen — laufen OHNE GPU."""

from __future__ import annotations

import math

import pytest

from gpu_efficiency_finder.constants import OperatingPointKind
from gpu_efficiency_finder.domain import analysis
from gpu_efficiency_finder.models import SweepRow


def _row(set_watt: float, power_w: float, avg: float, low: float | None = None) -> SweepRow:
    return SweepRow(
        set_watt=set_watt,
        pct=round(set_watt),
        power_w=power_w,
        clock_mhz=1800.0,
        temp_c=60.0,
        avg_perf=avg,
        low_1=low,
    )


# -- avg_fps / low_fps --------------------------------------------------------


def test_avg_fps_uniform_frametimes() -> None:
    # 10 Frames à 10 ms → 100 ms gesamt → 100 FPS.
    assert analysis.avg_fps([10.0] * 10) == pytest.approx(100.0)


def test_avg_fps_empty_is_none() -> None:
    assert analysis.avg_fps([]) is None
    assert analysis.avg_fps([0.0, -5.0]) is None


def test_low_fps_uniform_is_constant() -> None:
    assert analysis.low_fps([10.0] * 100, 1.0) == pytest.approx(100.0)


def test_low_fps_time_weighted_single_slow_frame() -> None:
    # Neun schnelle (10 ms) + ein langsamer Frame (100 ms). Der langsame Frame allein
    # belegt 100/190 der Zeit → dominiert das 1% Low: 1000/100 = 10 FPS.
    frametimes = [10.0] * 9 + [100.0]
    assert analysis.low_fps(frametimes, 1.0) == pytest.approx(10.0)


def test_low_fps_empty_is_none() -> None:
    assert analysis.low_fps([], 1.0) is None


# -- efficiency_peak ----------------------------------------------------------


def test_efficiency_peak_picks_max_perf_per_watt() -> None:
    rows = [
        _row(300, 300, 100),  # 0.333 perf/W
        _row(250, 240, 95),  # 0.396 perf/W  ← Peak
        _row(200, 195, 85),  # 0.436 perf/W  ← noch höher
        _row(150, 150, 60),  # 0.400 perf/W
    ]
    peak = analysis.efficiency_peak(rows, default_w=300)
    assert peak is not None
    assert peak.kind is OperatingPointKind.EFFICIENCY_PEAK
    assert peak.set_watt == 200
    assert peak.perf_per_w == pytest.approx(85 / 195)


def test_efficiency_peak_no_perf_is_none() -> None:
    rows = [SweepRow(300, 100, 290, 1800, 60, avg_perf=None)]
    assert analysis.efficiency_peak(rows, default_w=300) is None


# -- knee_point ---------------------------------------------------------------


def test_knee_point_on_concave_increasing_curve() -> None:
    # Konkav steigend: stark steigend, dann abflachend → Knie im unteren Bereich.
    rows = [
        _row(150, 150, 60),
        _row(200, 200, 90),
        _row(250, 250, 105),
        _row(300, 300, 112),
        _row(350, 350, 115),
    ]
    knee = analysis.knee_point(rows, default_w=350)
    assert knee is not None
    assert knee.kind is OperatingPointKind.KNEE
    # Das Knie liegt im Bereich des Übergangs, nicht am äußersten Rand.
    assert 150 < knee.power_w < 350


def test_knee_point_too_few_points_is_none() -> None:
    rows = [_row(300, 300, 100), _row(250, 240, 95), _row(200, 195, 85)]
    assert analysis.knee_point(rows, default_w=300) is None


# -- recommend ----------------------------------------------------------------


def _recommend_rows() -> list[SweepRow]:
    # Baseline = A (höchste Ø-Perf). Verluste relativ zu avg=120 / low=110.
    return [
        _row(300, 290, 120, 110),  # A baseline
        _row(250, 240, 118, 108),  # B: avg -1.7%, low -1.8%
        _row(200, 190, 116, 100),  # C: avg -3.3%, low -9.1%
        _row(160, 155, 112, 96),  # D: avg -6.7%, low -12.7%
    ]


def test_recommend_picks_lowest_power_within_tolerances() -> None:
    rec = analysis.recommend(_recommend_rows(), avg_tol_pct=5, low_tol_pct=10, default_w=300)
    assert rec.satisfiable
    assert rec.recommended is not None
    # A, B, C halten die Toleranzen; C hat den niedrigsten Verbrauch → maximale Ersparnis.
    assert rec.recommended.set_watt == 200
    assert rec.recommended.power_w == pytest.approx(190)
    assert not rec.floor_binding


def test_recommend_floor_excludes_lower_point() -> None:
    # FPS-Untergrenze 105: schließt C (low 100) aus, B (low 108) bleibt → Empfehlung B.
    rec = analysis.recommend(
        _recommend_rows(), avg_tol_pct=5, low_tol_pct=10, min_fps_floor=105, default_w=300
    )
    assert rec.satisfiable
    assert rec.recommended is not None
    assert rec.recommended.set_watt == 250
    assert rec.unconstrained_optimum is not None
    assert rec.unconstrained_optimum.set_watt == 200
    assert rec.floor_binding
    assert rec.extra_savings_w == pytest.approx(240 - 190)
    assert rec.message is not None


def test_recommend_no_candidate_when_tolerances_too_tight() -> None:
    rec = analysis.recommend(_recommend_rows(), avg_tol_pct=0.1, low_tol_pct=0.1, default_w=300)
    # Nur die Baseline selbst hat 0% Verlust → sie ist der einzige "Kandidat".
    assert rec.recommended is not None
    assert rec.recommended.set_watt == 300


def test_recommend_no_perf_data_is_unsatisfiable() -> None:
    rows = [SweepRow(300, 100, 290, 1800, 60, avg_perf=None)]
    rec = analysis.recommend(rows, avg_tol_pct=3, low_tol_pct=5, default_w=300)
    assert not rec.satisfiable
    assert rec.recommended is None
    assert rec.message is not None


def test_low_fps_definition_matches_manual_calc() -> None:
    # Sanity: 0.1% Low über viele gleiche Frames bleibt der Frame-FPS-Wert.
    fts = [8.0] * 1000
    assert analysis.low_fps(fts, 0.1) == pytest.approx(125.0)
    assert math.isclose(analysis.avg_fps(fts) or 0.0, 125.0, rel_tol=1e-6)
