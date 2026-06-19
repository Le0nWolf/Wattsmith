"""Ports — strukturelle Interfaces (typing.Protocol), an denen die Domain hängt."""

from __future__ import annotations

from gpu_efficiency_finder.ports.benchmark_runner import BenchmarkRunner
from gpu_efficiency_finder.ports.gpu_backend import GpuBackend
from gpu_efficiency_finder.ports.perf_source import PerfSource

__all__ = ["BenchmarkRunner", "GpuBackend", "PerfSource"]
