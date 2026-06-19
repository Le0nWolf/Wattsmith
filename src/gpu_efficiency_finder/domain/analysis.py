"""Reine Analysefunktionen — KEINE I/O, kein Hardware-Zugriff, vollständig testbar ohne GPU.

Begriffe:
- ``avg_perf``  : generischer Performance-Skalar (Ø-FPS, Iterationen/s oder Takt).
- ``power_w``   : tatsächlich gemessener Verbrauch (x-Achse).
- Baseline      : Stufe mit der höchsten Ø-Performance (Referenz für alle Verluste).
- Knie          : Punkt des abnehmenden Grenznutzens (Kneedle) auf Perf über Watt.
- Effizienz-Peak: Punkt mit dem höchsten Perf/Watt.
- Empfehlung    : niedrigstes Limit, das relative Toleranzen UND (optional) die absolute
                  FPS-Untergrenze hält → maximale Ersparnis ohne spürbaren Verlust.
"""

from __future__ import annotations

from collections.abc import Sequence

from gpu_efficiency_finder.constants import OperatingPointKind
from gpu_efficiency_finder.models import OperatingPoint, Recommendation, SweepRow

__all__ = [
    "avg_fps",
    "efficiency_peak",
    "knee_point",
    "low_fps",
    "recommend",
]


def avg_fps(frametimes_ms: Sequence[float]) -> float | None:
    """Durchschnittliche FPS = Anzahl Frames / Gesamtzeit (Sekunden).

    Gibt ``None`` zurück, wenn keine gültigen Frametimes vorliegen.
    """
    fts = [ft for ft in frametimes_ms if ft > 0]
    if not fts:
        return None
    total_s = sum(fts) / 1000.0
    return len(fts) / total_s


def low_fps(frametimes_ms: Sequence[float], pct: float) -> float | None:
    """Zeitgewichtetes x% Low (Afterburner/CapFrameX-Definition).

    Der FPS-Wert, unter dem x% der GESAMTZEIT verbracht wurde: Frames nach Frametime
    absteigend sortieren (langsamste zuerst), aufsummieren bis x% der Gesamtzeit erreicht
    sind; die FPS des dann erreichten Frames ist das x% Low.

    Gibt ``None`` zurück bei leerer/ungültiger Eingabe.
    """
    fts = [ft for ft in frametimes_ms if ft > 0]
    if not fts:
        return None
    total = sum(fts)
    threshold = total * pct / 100.0
    acc = 0.0
    for ft in sorted(fts, reverse=True):
        acc += ft
        if acc >= threshold:
            return 1000.0 / ft
    return 1000.0 / max(fts)


def _baseline(rows: Sequence[SweepRow]) -> SweepRow | None:
    """Stufe mit der höchsten Ø-Performance (Referenz für Verluste)."""
    scored = [r for r in rows if r.avg_perf is not None]
    if not scored:
        return None
    return max(scored, key=lambda r: r.avg_perf or 0.0)


def _loss_pct(value: float | None, baseline: float | None) -> float | None:
    """Relativer Verlust in % gegenüber der Baseline (positiv = schlechter)."""
    if value is None or baseline is None or baseline <= 0:
        return None
    return (baseline - value) / baseline * 100.0


def _operating_point(
    row: SweepRow,
    baseline: SweepRow | None,
    default_w: float,
    kind: OperatingPointKind,
) -> OperatingPoint:
    """Baut einen OperatingPoint aus einer Zeile relativ zu Baseline und Default-Limit."""
    base_perf = baseline.avg_perf if baseline else None
    base_low = baseline.low_1 if baseline else None
    perf_per_w = (
        row.avg_perf / row.power_w if row.avg_perf is not None and row.power_w > 0 else None
    )
    return OperatingPoint(
        kind=kind,
        set_watt=row.set_watt,
        power_w=row.power_w,
        pct_of_default=(row.set_watt / default_w * 100.0) if default_w > 0 else 0.0,
        savings_w=default_w - row.power_w,
        savings_pct=((default_w - row.power_w) / default_w * 100.0) if default_w > 0 else 0.0,
        avg_perf=row.avg_perf,
        avg_perf_loss_pct=_loss_pct(row.avg_perf, base_perf),
        low_1=row.low_1,
        low_1_loss_pct=_loss_pct(row.low_1, base_low),
        perf_per_w=perf_per_w,
    )


def efficiency_peak(
    rows: Sequence[SweepRow], default_w: float | None = None
) -> OperatingPoint | None:
    """Betriebspunkt mit dem höchsten Perf/Watt (absolut effizientester Punkt)."""
    candidates = [r for r in rows if r.avg_perf is not None and r.power_w > 0]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: (r.avg_perf or 0.0) / r.power_w)
    base = _baseline(rows)
    dflt = default_w if default_w is not None else _default_from_rows(rows)
    return _operating_point(best, base, dflt, OperatingPointKind.EFFICIENCY_PEAK)


def knee_point(rows: Sequence[SweepRow], default_w: float | None = None) -> OperatingPoint | None:
    """Knie (Kneedle, concave/increasing) auf Perf über Watt — Punkt des abnehmenden
    Grenznutzens. Robust gegen <4 Punkte, fehlendes kneed oder kein erkennbares Knie (None).
    """
    pts = sorted(
        ((r.power_w, r.avg_perf, r) for r in rows if r.avg_perf is not None and r.power_w > 0),
        key=lambda t: t[0],
    )
    if len(pts) < 4:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # Streng monotone x-Werte sind für KneeLocator nötig.
    if len(set(xs)) < 4:
        return None
    try:
        from kneed import KneeLocator
    except ImportError:
        return None
    try:
        locator = KneeLocator(xs, ys, curve="concave", direction="increasing")
    except (ValueError, RuntimeError):
        return None
    knee_x = locator.knee
    if knee_x is None:
        return None
    knee_row = min(pts, key=lambda t: abs(t[0] - knee_x))[2]
    base = _baseline(rows)
    dflt = default_w if default_w is not None else _default_from_rows(rows)
    return _operating_point(knee_row, base, dflt, OperatingPointKind.KNEE)


def _default_from_rows(rows: Sequence[SweepRow]) -> float:
    """Fallback-Default-Limit: höchstes gesetztes Limit im Sweep."""
    if not rows:
        return 0.0
    return max(r.set_watt for r in rows)


def _within_relative_tolerances(
    row: SweepRow,
    baseline: SweepRow,
    avg_tol_pct: float,
    low_tol_pct: float,
) -> bool:
    """True, wenn Ø-Perf-Verlust ≤ avg_tol UND 1%-Low-Verlust ≤ low_tol (falls Lows vorhanden)."""
    avg_loss = _loss_pct(row.avg_perf, baseline.avg_perf)
    if avg_loss is None or avg_loss > avg_tol_pct:
        return False
    low_loss = _loss_pct(row.low_1, baseline.low_1)
    return not (low_loss is not None and low_loss > low_tol_pct)


def _above_floor(row: SweepRow, floor: float | None) -> bool:
    """True, wenn Ø-Perf UND (falls vorhanden) 1% Low nicht unter die Untergrenze fallen."""
    if floor is None:
        return True
    if row.avg_perf is None or row.avg_perf < floor:
        return False
    return not (row.low_1 is not None and row.low_1 < floor)


def recommend(
    rows: Sequence[SweepRow],
    avg_tol_pct: float,
    low_tol_pct: float,
    min_fps_floor: float | None = None,
    default_w: float | None = None,
) -> Recommendation:
    """Niedrigstes Limit (= maximale Ersparnis), das ggü. der Baseline sowohl den
    Ø-Perf-Verlust ≤ ``avg_tol_pct`` als auch den 1%-Low-Verlust ≤ ``low_tol_pct`` hält —
    und, falls gesetzt, die absolute Ø-Perf (und 1% Low) nicht unter ``min_fps_floor`` drückt.

    Gibt zusätzlich das UNBESCHRÄNKTE Optimum (ohne Untergrenze) samt Delta zurück, damit der
    Nutzer den Preis seiner min-FPS-Vorgabe sieht.
    """
    baseline = _baseline(rows)
    if baseline is None:
        return Recommendation(
            recommended=None,
            unconstrained_optimum=None,
            satisfiable=False,
            message="Keine Performance-Daten vorhanden — Empfehlung nicht möglich.",
        )
    dflt = default_w if default_w is not None else _default_from_rows(rows)

    in_tol = [r for r in rows if _within_relative_tolerances(r, baseline, avg_tol_pct, low_tol_pct)]

    # Unbeschränktes Optimum: nur relative Toleranzen, niedrigster Verbrauch.
    unconstrained_row = min(in_tol, key=lambda r: r.power_w) if in_tol else None
    unconstrained = (
        _operating_point(unconstrained_row, baseline, dflt, OperatingPointKind.RECOMMENDATION)
        if unconstrained_row
        else None
    )

    # Beschränkte Empfehlung: zusätzlich die FPS-Untergrenze.
    in_floor = [r for r in in_tol if _above_floor(r, min_fps_floor)]
    recommended_row = min(in_floor, key=lambda r: r.power_w) if in_floor else None
    recommended = (
        _operating_point(recommended_row, baseline, dflt, OperatingPointKind.RECOMMENDATION)
        if recommended_row
        else None
    )

    if recommended is None:
        msg = "Kein Limit erfüllt alle Bedingungen — Toleranzen lockern" + (
            " oder FPS-Untergrenze senken." if min_fps_floor is not None else "."
        )
        return Recommendation(
            recommended=None,
            unconstrained_optimum=unconstrained,
            satisfiable=False,
            message=msg,
        )

    floor_binding = (
        min_fps_floor is not None
        and unconstrained is not None
        and unconstrained.power_w < recommended.power_w - 1e-9
    )
    extra_w = (
        recommended.power_w - unconstrained.power_w if floor_binding and unconstrained else 0.0
    )
    extra_pct = (extra_w / dflt * 100.0) if floor_binding and dflt > 0 else 0.0
    message = None
    if floor_binding:
        message = (
            f"Dies ist NICHT der effizienteste Punkt der Karte: Die FPS-Untergrenze von "
            f"{min_fps_floor:.0f} ist bindend. Ohne sie wären weitere {extra_w:.0f} W "
            f"({extra_pct:.0f}% vom Default) Ersparnis möglich."
        )

    return Recommendation(
        recommended=recommended,
        unconstrained_optimum=unconstrained,
        floor_binding=floor_binding,
        extra_savings_w=extra_w,
        extra_savings_pct=extra_pct,
        satisfiable=True,
        message=message,
    )
