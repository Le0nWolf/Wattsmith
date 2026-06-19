"""Adapter: GPU-Steuerung über ``nvidia-smi`` (Fallback, wenn NVML scheitert).

Schält per :mod:`subprocess` zu ``nvidia-smi`` aus. Lesen braucht keine
Admin-Rechte; das Setzen des Power-Limits (``-pl``) jedoch schon. Dünn — parst
CSV und übersetzt in die Domain-Modelle. Keine Geschäftslogik.
"""

from __future__ import annotations

import subprocess

from gpu_efficiency_finder.errors import GpuEfficiencyError, GpuPermissionError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import GpuInfo, PowerLimits, Telemetry

__all__ = ["NvidiaSmiBackend"]

_LOG = get_logger(__name__)

_SMI = "nvidia-smi"
_CSV_FORMAT = "--format=csv,noheader,nounits"


class NvidiaSmiBackend:
    """GpuBackend-Implementierung über die ``nvidia-smi``-Kommandozeile."""

    def _run(self, args: list[str]) -> str:
        """Führt ``nvidia-smi`` aus, gibt stdout zurück, übersetzt Fehler."""
        try:
            result = subprocess.run(
                [_SMI, *args],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise GpuEfficiencyError(
                "nvidia-smi wurde nicht gefunden — ist der NVIDIA-Treiber installiert?"
            ) from exc
        except subprocess.CalledProcessError as exc:
            output = f"{exc.stdout or ''}\n{exc.stderr or ''}".lower()
            if "permission" in output or "insufficient" in output or "admin" in output:
                raise GpuPermissionError(
                    "Keine Berechtigung zum Setzen des Power-Limits — "
                    "bitte als Administrator starten."
                ) from exc
            raise GpuEfficiencyError(
                f"nvidia-smi schlug fehl: {exc.stderr or exc.stdout or exc}"
            ) from exc
        return result.stdout

    def _query(self, fields: str, idx: int) -> list[str]:
        """Fragt CSV-Felder für eine GPU ab und gibt sie getrimmt zurück."""
        out = self._run([f"--query-gpu={fields}", _CSV_FORMAT, "-i", str(idx)])
        line = out.strip().splitlines()[0]
        return [cell.strip() for cell in line.split(",")]

    def list_gpus(self) -> list[GpuInfo]:
        out = self._run(["--query-gpu=index,name", _CSV_FORMAT])
        gpus: list[GpuInfo] = []
        for line in out.strip().splitlines():
            if not line.strip():
                continue
            index_str, name = (cell.strip() for cell in line.split(",", 1))
            gpus.append(GpuInfo(index=int(index_str), name=name))
        return gpus

    def get_limits(self, idx: int) -> PowerLimits:
        default_w, min_w, max_w, current_w = self._query(
            "power.default_limit,power.min_limit,power.max_limit,power.limit", idx
        )
        return PowerLimits(
            default_w=float(default_w),
            min_w=float(min_w),
            max_w=float(max_w),
            current_w=float(current_w),
        )

    def set_power_limit_w(self, idx: int, watt: float) -> None:
        limits = self.get_limits(idx)
        clamped = min(max(watt, limits.min_w), limits.max_w)
        limit_w = round(clamped)
        self._run(["-i", str(idx), "-pl", str(limit_w)])
        _LOG.info("Power-Limit gesetzt (nvidia-smi): GPU %d → %d W", idx, limit_w)

    def read_telemetry(self, idx: int) -> Telemetry:
        power_w, clock_mhz, temp_c, util_pct = self._query(
            "power.draw,clocks.gr,temperature.gpu,utilization.gpu", idx
        )
        return Telemetry(
            power_w=float(power_w),
            clock_mhz=float(clock_mhz),
            temp_c=float(temp_c),
            util_pct=float(util_pct),
        )

    def reset_to_default(self, idx: int) -> None:
        limits = self.get_limits(idx)
        default_w = round(limits.default_w)
        self._run(["-i", str(idx), "-pl", str(default_w)])
        _LOG.info(
            "Power-Limit auf Default zurückgesetzt (nvidia-smi): GPU %d → %d W",
            idx,
            default_w,
        )
