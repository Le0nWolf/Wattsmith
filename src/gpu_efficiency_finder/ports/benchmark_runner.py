"""Port: externer Benchmark als Dauerlast."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["BenchmarkRunner"]


@runtime_checkable
class BenchmarkRunner(Protocol):
    """Startet/beendet eine externe, konstante GPU-Last für die Dauer des Sweeps."""

    def start(self) -> None:
        """Startet den Benchmark-Prozess und wartet optional die Warmup-Zeit ab."""
        ...

    def stop(self) -> None:
        """Beendet den GESAMTEN Prozessbaum des Benchmarks (Kindprozesse inklusive)."""
        ...

    def is_running(self) -> bool:
        """Ob der Benchmark-Prozess (noch) läuft."""
        ...
