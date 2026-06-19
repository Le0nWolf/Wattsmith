"""Port: GPU-Steuerung und -Telemetrie."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gpu_efficiency_finder.models import GpuInfo, PowerLimits, Telemetry

__all__ = ["GpuBackend"]


@runtime_checkable
class GpuBackend(Protocol):
    """Abstraktion über die GPU. NVML ist die Standard-Implementierung;
    ein ``AmdSysfsBackend`` (Linux) lässt sich später ergänzen, ohne die Domain anzufassen.

    Das Setzen des Limits bleibt IMMER bei diesem Port (NVML/nvidia-smi) —
    rein lesende Quellen wie HWiNFO dürfen es nicht.
    """

    def list_gpus(self) -> list[GpuInfo]:
        """Alle verfügbaren GPUs."""
        ...

    def get_limits(self, idx: int) -> PowerLimits:
        """Default/Min/Max/aktuelles Power-Limit in Watt."""
        ...

    def set_power_limit_w(self, idx: int, watt: float) -> None:
        """Setzt das Power-Limit (Watt). Clampt auf [min, max]. Braucht ggf. Admin."""
        ...

    def read_telemetry(self, idx: int) -> Telemetry:
        """Momentane Telemetrie (Power, Takt, Temp, Auslastung)."""
        ...

    def reset_to_default(self, idx: int) -> None:
        """Setzt das Power-Limit auf den Hersteller-Default zurück."""
        ...
