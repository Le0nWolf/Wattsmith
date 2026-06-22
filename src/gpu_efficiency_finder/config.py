"""User-Eingaben/Settings als pydantic-Modelle — validiert, typsicher an die Domain übergeben."""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, Field, model_validator

from gpu_efficiency_finder.constants import MeasurementMode

__all__ = ["SourceConfig", "SweepConfig"]


class SweepConfig(BaseModel):
    """Numerische Sweep-Parameter und Toleranzen."""

    gpu_index: int = Field(0, ge=0)
    start_pct: int = Field(100, ge=20, le=100)
    end_pct: int = Field(50, ge=20, le=100)
    step_pct: int = Field(5, ge=1, le=25)
    settle_s: float = Field(8.0, ge=2, le=180)
    # Obergrenze großzügig, damit das Messfenster die Dauer eines kompletten Benchmark-Loops
    # abdecken kann (z. B. ein voller 3DMark-Speed-Way-/Time-Spy-Durchlauf).
    measure_s: float = Field(25.0, ge=5, le=900)
    avg_tol_pct: float = Field(3.0, ge=0, le=30)
    low_tol_pct: float = Field(5.0, ge=0, le=40)
    min_fps_floor: float | None = Field(None, ge=1)  # optional, abschaltbar
    randomize_order: bool = True
    cooldown_target_c: float | None = Field(None, ge=20, le=90)
    recheck_baseline: bool = True
    baseline_drift_warn_pct: float = Field(3.0, ge=0, le=50)

    @model_validator(mode="after")
    def _start_above_end(self) -> SweepConfig:
        if self.start_pct <= self.end_pct:
            raise ValueError("start_pct muss größer als end_pct sein")
        return self

    def steps(self) -> list[int]:
        """Liefert die Prozent-Stufen (absteigend, inkl. start_pct und ggf. end_pct)."""
        out: list[int] = []
        pct = self.start_pct
        while pct >= self.end_pct:
            out.append(pct)
            pct -= self.step_pct
        if out[-1] != self.end_pct:
            out.append(self.end_pct)
        return out

    def iter_steps(self) -> Iterator[int]:
        yield from self.steps()


class SourceConfig(BaseModel):
    """Konfiguration der Mess-Quelle und der externen Benchmark-Last."""

    mode: MeasurementMode = MeasurementMode.CLOCK_PROXY

    # PresentMon
    presentmon_path: str | None = None  # None → gebündelte EXE verwenden
    process_name: str | None = None

    # Externe Benchmark-Last (optional — Last kann auch manuell gestartet werden).
    # EXE-Pfad und Startoptionen getrennt: kein Quoting-Problem bei Leerzeichen im Pfad.
    benchmark_exe: str | None = None
    benchmark_args: str = ""
    benchmark_warmup_s: float = Field(10.0, ge=0, le=120)

    # HWiNFO
    hwinfo_shared_mem: str | None = None  # None → Standardname

    @model_validator(mode="after")
    def _presentmon_needs_process(self) -> SourceConfig:
        if self.mode is MeasurementMode.PRESENTMON and not (self.process_name or "").strip():
            raise ValueError("Für den PresentMon-Modus muss ein Prozessname angegeben werden.")
        return self
