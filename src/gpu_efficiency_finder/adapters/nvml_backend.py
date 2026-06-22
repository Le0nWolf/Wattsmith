"""Adapter: GPU-Steuerung über NVML (``nvidia-ml-py``, Import-Name ``pynvml``).

Standard-Implementierung des :class:`GpuBackend`-Ports. Dünn — übersetzt nur
zwischen NVML (Milliwatt/Bytes) und den Domain-Modellen (Watt). ``pynvml`` wird
LAZY importiert, damit dieses Modul auch ohne GPU/Treiber importierbar bleibt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gpu_efficiency_finder.errors import GpuEfficiencyError, GpuPermissionError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import GpuInfo, PowerLimits, Telemetry

if TYPE_CHECKING:
    from types import ModuleType

__all__ = ["NvmlBackend"]

_LOG = get_logger(__name__)


def _watt_to_mw(watt: float) -> int:
    """Watt → Milliwatt (int), wie NVML es beim Setzen erwartet."""
    return round(watt * 1000.0)


def _mw_to_watt(mw: float) -> float:
    """Milliwatt → Watt."""
    return float(mw) / 1000.0


class NvmlBackend:
    """GpuBackend-Implementierung über NVML. Limit-Setzen braucht Administrator."""

    def __init__(self) -> None:
        self._pynvml: ModuleType | None = None
        self._initialized: bool = False

    def _ensure_init(self) -> ModuleType:
        """Importiert ``pynvml`` lazy und ruft ``nvmlInit`` einmalig (idempotent)."""
        if self._pynvml is None:
            try:
                import pynvml
            except ImportError as exc:
                raise GpuEfficiencyError("NVML (nvidia-ml-py) ist nicht installiert.") from exc
            self._pynvml = pynvml
        if not self._initialized:
            try:
                self._pynvml.nvmlInit()
            except self._pynvml.NVMLError as exc:
                raise GpuEfficiencyError(f"NVML konnte nicht initialisiert werden: {exc}") from exc
            self._initialized = True
            _LOG.info("NVML initialisiert")
        return self._pynvml

    def _handle(self, idx: int) -> object:
        """Geräte-Handle für den GPU-Index."""
        nvml = self._ensure_init()
        return nvml.nvmlDeviceGetHandleByIndex(idx)

    def list_gpus(self) -> list[GpuInfo]:
        nvml = self._ensure_init()
        gpus: list[GpuInfo] = []
        for idx in range(nvml.nvmlDeviceGetCount()):
            handle = nvml.nvmlDeviceGetHandleByIndex(idx)
            name = nvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            gpus.append(GpuInfo(index=idx, name=name))
        return gpus

    def get_limits(self, idx: int) -> PowerLimits:
        nvml = self._ensure_init()
        handle = nvml.nvmlDeviceGetHandleByIndex(idx)
        default_mw = nvml.nvmlDeviceGetPowerManagementDefaultLimit(handle)
        min_mw, max_mw = nvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)
        current_mw = nvml.nvmlDeviceGetPowerManagementLimit(handle)
        return PowerLimits(
            default_w=_mw_to_watt(default_mw),
            min_w=_mw_to_watt(min_mw),
            max_w=_mw_to_watt(max_mw),
            current_w=_mw_to_watt(current_mw),
        )

    def set_power_limit_w(self, idx: int, watt: float) -> None:
        nvml = self._ensure_init()
        handle = nvml.nvmlDeviceGetHandleByIndex(idx)
        limits = self.get_limits(idx)
        clamped = min(max(watt, limits.min_w), limits.max_w)
        limit_mw = _watt_to_mw(clamped)
        try:
            nvml.nvmlDeviceSetPowerManagementLimit(handle, limit_mw)
        except nvml.NVMLError_NoPermission as exc:
            _LOG.warning("NVML NoPermission beim Setzen des Power-Limits (GPU %d)", idx)
            raise GpuPermissionError(
                "Keine Berechtigung zum Setzen des Power-Limits — bitte als Administrator starten."
            ) from exc
        except nvml.NVMLError as exc:
            raise GpuEfficiencyError(
                f"Power-Limit konnte nicht gesetzt werden (GPU {idx}): {exc}"
            ) from exc
        _LOG.info("Power-Limit gesetzt: GPU %d → %.1f W", idx, clamped)

    def read_telemetry(self, idx: int) -> Telemetry:
        nvml = self._ensure_init()
        handle = nvml.nvmlDeviceGetHandleByIndex(idx)
        power_w = _mw_to_watt(nvml.nvmlDeviceGetPowerUsage(handle))
        clock_mhz = float(nvml.nvmlDeviceGetClockInfo(handle, nvml.NVML_CLOCK_GRAPHICS))
        temp_c = float(nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
        util_pct = float(nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
        return Telemetry(
            power_w=power_w,
            clock_mhz=clock_mhz,
            temp_c=temp_c,
            util_pct=util_pct,
            voltage_mv=self._read_voltage_mv(nvml, handle),
        )

    @staticmethod
    def _read_voltage_mv(nvml: ModuleType, handle: object) -> float | None:
        """Best-effort GPU-Core-Spannung (mV) über NVML-Field-Values.

        Das Feld ist in NVML nicht offiziell für Consumer-GPUs dokumentiert und fehlt auf
        vielen Karten/Treibern — daher getattr-Guard und großzügiges Abfangen: nicht
        verfügbar → ``None`` (zuverlässig kommt die Spannung aus HWiNFO).
        """
        field_id = getattr(nvml, "NVML_FI_DEV_VOLTAGE", None)
        get_fields = getattr(nvml, "nvmlDeviceGetFieldValues", None)
        if field_id is None or get_fields is None:
            return None
        try:
            values = get_fields(handle, [field_id])
            value = values[0]
            if getattr(value, "nvmlReturn", 1) != 0:
                return None
            millivolts = float(value.value.uiVal)
        except Exception:
            return None
        return millivolts if millivolts > 0 else None

    def reset_to_default(self, idx: int) -> None:
        limits = self.get_limits(idx)
        self.set_power_limit_w(idx, limits.default_w)
        _LOG.info("Power-Limit auf Default zurückgesetzt: GPU %d", idx)

    def close(self) -> None:
        """Fährt NVML herunter (idempotent)."""
        if self._pynvml is not None and self._initialized:
            try:
                self._pynvml.nvmlShutdown()
            except self._pynvml.NVMLError as exc:
                _LOG.warning("NVML-Shutdown fehlgeschlagen: %s", exc)
            finally:
                self._initialized = False
            _LOG.info("NVML heruntergefahren")

    def shutdown(self) -> None:
        """Alias für :meth:`close`."""
        self.close()
