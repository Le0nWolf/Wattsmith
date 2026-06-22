"""Tests für das HWiNFO-Spannungs-Parsing — ohne HWiNFO/GPU, mit synthetischem Puffer.

Baut einen minimalen ``HWiNFO_SENS_SM2``-Puffer (Header + ein Reading-Element) nach dem
dokumentierten Layout und prüft, dass :meth:`HwinfoSource.read_voltage_mv` die richtigen
Offsets liest und Volt→mV skaliert.
"""

from __future__ import annotations

import struct

import pytest

from gpu_efficiency_finder.adapters.hwinfo_source import HwinfoSource

_HEADER_FORMAT = "<4sIIqIIIIII"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)


def _element(label_user: str, unit: str, value: float) -> bytes:
    """Reading-Element: type/idx/id (je 4) + labelOrig(128) + labelUser(128) + unit(16) + value(8)."""
    out = bytearray()
    out += struct.pack("<III", 0, 0, 0)
    out += b"\x00" * 128
    out += label_user.encode("latin-1").ljust(128, b"\x00")[:128]
    out += unit.encode("latin-1").ljust(16, b"\x00")[:16]
    out += struct.pack("<d", value)
    return bytes(out)


def _buffer(element: bytes) -> bytes:
    """Header (Reading-Section direkt hinter dem Header, 1 Element) + Element."""
    header = struct.pack(_HEADER_FORMAT, b"SiWH", 1, 1, 0, 0, 0, 0, _HEADER_SIZE, len(element), 1)
    return header + element


def _source_with(element: bytes) -> HwinfoSource:
    src = HwinfoSource()
    src._mmap = _buffer(element)  # type: ignore[assignment]  # bytes genügt für reines Slicing
    return src


def test_reads_gpu_core_voltage_volts_to_millivolts() -> None:
    src = _source_with(_element("GPU Core Voltage", "V", 0.9))
    assert src.read_voltage_mv() == pytest.approx(900.0)


def test_millivolt_unit_is_not_rescaled() -> None:
    src = _source_with(_element("GPU Core Voltage", "mV", 950.0))
    assert src.read_voltage_mv() == pytest.approx(950.0)


def test_non_voltage_label_returns_none() -> None:
    src = _source_with(_element("GPU Hot Spot Temperature", "°C", 65.0))
    assert src.read_voltage_mv() is None


def test_no_mapping_returns_none() -> None:
    assert HwinfoSource().read_voltage_mv() is None
