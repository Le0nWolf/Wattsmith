"""Port: optionale GPU-Spannungsquelle (z. B. HWiNFO Shared Memory)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["VoltageSource"]


@runtime_checkable
class VoltageSource(Protocol):
    """Liefert GPU-Zusatzsensoren, die NVML auf Consumer-Karten nicht hergibt: Core-Spannung
    (mV) sowie Hot-Spot- und Speicher-(Junction-)Temperatur (°C). HWiNFO ist die Quelle.
    Nur lesend; rein optional — jede Methode darf ``None`` liefern."""

    def start(self) -> None:
        """Öffnet die Quelle (z. B. HWiNFO-Shared-Memory)."""
        ...

    def stop(self) -> None:
        """Gibt die Quelle wieder frei."""
        ...

    def read_voltage_mv(self) -> float | None:
        """Momentane GPU-Core-Spannung in mV, oder ``None``."""
        ...

    def read_hotspot_c(self) -> float | None:
        """GPU-Hot-Spot-Temperatur in °C, oder ``None``."""
        ...

    def read_mem_temp_c(self) -> float | None:
        """GPU-Speicher-(Junction-)Temperatur in °C, oder ``None``."""
        ...
