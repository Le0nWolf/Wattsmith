"""Port: optionale GPU-Spannungsquelle (z. B. HWiNFO Shared Memory)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["VoltageSource"]


@runtime_checkable
class VoltageSource(Protocol):
    """Liefert die aktuelle GPU-Core-Spannung (mV) — NVML kann sie auf Consumer-Karten
    meist nicht; HWiNFO ist die zuverlässige Quelle. Nur lesend; rein optional."""

    def start(self) -> None:
        """Öffnet die Quelle (z. B. HWiNFO-Shared-Memory)."""
        ...

    def stop(self) -> None:
        """Gibt die Quelle wieder frei."""
        ...

    def read_voltage_mv(self) -> float | None:
        """Momentane GPU-Core-Spannung in mV, oder ``None``, wenn nicht verfügbar."""
        ...
