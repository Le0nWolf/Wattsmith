"""Adapter: optionale Telemetrie-/FPS-/Spannungsquelle über HWiNFOs Shared Memory.

HWiNFO veröffentlicht seine Sensorwerte über ein benanntes Shared-Memory-Mapping
(``Global\\HWiNFO_SENS_SM2``). Das Mapping wird von einem ANDEREN Prozess erzeugt — der
kanonische Weg zum Anhängen ist ``OpenFileMapping`` + ``MapViewOfFile`` (per ctypes).
Pythons ``mmap`` (intern ``CreateFileMapping``) hängt sich an fremde Mappings nicht
zuverlässig an; daher ctypes als Primärweg und ``mmap`` nur als Fallback.

Layout (reverse-engineert, verifiziert): Header mit Signatur ``SiWH`` + Offsets/Größen/
Anzahl der Sensor- und Reading-Elemente; Reading-Element: 3×DWORD + labelOrig(128) +
labelUser(128) + unit(16) + value(double) …

Fallstricke: HWiNFO muss laufen, „Shared Memory Support“ aktiv (Free-Version: nach 12 h aus).
FPS nur, wenn HWiNFO sie von RTSS bezieht (gemittelt → keine Lows). Nur lesend.
"""

from __future__ import annotations

import ctypes
import struct

from gpu_efficiency_finder.constants import HWINFO_SHARED_MEM_NAME
from gpu_efficiency_finder.errors import HwinfoError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import WindowMetrics

__all__ = ["HwinfoSource"]

_LOG = get_logger(__name__)

# Signatur im Speicher (little-endian Bytes). Die Spec nennt den DWORD-Wert „SiWH“; roh
# liegen die Bytes umgekehrt als „HWiS“ vor — genau das liest struct mit ``4s``.
_SIGNATURE = b"HWiS"
# dwSignature(4) dwVersion(4) dwRevision(4) poll_time(8)
# dwOffsetOfSensorSection(4) dwSizeOfSensorElement(4) dwNumSensorElements(4)
# dwOffsetOfReadingSection(4) dwSizeOfReadingElement(4) dwNumReadingElements(4)
_HEADER_FORMAT = "<4sIIqIIIIII"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

# Reading-Element: dwType(4) dwSensorIndex(4) dwReadingID(4) szLabelOrig(128)
# szLabelUser(128) szUnit(16) Value(double) … (Rest ignoriert).
_LABEL_USER_OFFSET = 4 + 4 + 4 + 128
_LABEL_LEN = 128
_UNIT_OFFSET = _LABEL_USER_OFFSET + _LABEL_LEN
_UNIT_LEN = 16
_VALUE_OFFSET = _UNIT_OFFSET + _UNIT_LEN
_VALUE_FORMAT = "<d"
_VALUE_SIZE = struct.calcsize(_VALUE_FORMAT)

_FPS_LABEL_HINTS = ("framerate", "fps", "frames per second")
_VOLTAGE_LABEL_HINTS = (
    "gpu core voltage",
    "core voltage",
    "kern-spannung",
    "kernspannung",
    "gpu vid",
    "vddc",
)

_FILE_MAP_READ = 0x0004


class HwinfoSource:
    """Liest HWiNFO-Shared-Memory (Telemetrie/FPS/Spannung). Nur lesend, rein optional."""

    def __init__(self, mem_name: str = HWINFO_SHARED_MEM_NAME) -> None:
        self._mem_name = mem_name
        self._handle: int | None = None
        self._view: int | None = None
        self._total = 0
        # Test-Injektion: ein statischer Puffer ersetzt das echte Mapping.
        self._static: bytes | None = None

    # -- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Öffnet das Mapping über ctypes ``OpenFileMapping`` (Namens-Fallback + Logging)."""
        if self._static is not None:
            return
        last_exc: Exception | None = None
        for name in self._candidate_names():
            try:
                self._open(name)
            except (OSError, HwinfoError) as exc:
                last_exc = exc
                _LOG.warning("HWiNFO via '%s' fehlgeschlagen: %s", name, exc)
                continue
            self._mem_name = name
            _LOG.info("HWiNFO-Shared-Memory geöffnet (%s, %d Bytes)", name, self._total)
            return
        raise HwinfoError(
            "HWiNFO-Shared-Memory nicht verfügbar — läuft HWiNFO und ist "
            "„Shared Memory Support“ aktiv? (Free-Version: nach 12 h automatisch aus)."
        ) from last_exc

    def stop(self) -> None:
        """Gibt View und Handle frei (idempotent)."""
        if self._view or self._handle:
            try:
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if self._view:
                    k32.UnmapViewOfFile(ctypes.c_void_p(self._view))
                if self._handle:
                    k32.CloseHandle(ctypes.c_void_p(self._handle))
            except OSError as exc:
                _LOG.warning("HWiNFO-Freigabe fehlgeschlagen: %s", exc)
            self._view = None
            self._handle = None
            _LOG.info("HWiNFO-Shared-Memory geschlossen")

    def _candidate_names(self) -> list[str]:
        """Konfigurierter Name + Variante mit/ohne ``Global\\``-Präfix (dedupliziert)."""
        prefix = "Global\\"
        names = [self._mem_name]
        if self._mem_name.startswith(prefix):
            names.append(self._mem_name[len(prefix) :])
        else:
            names.append(prefix + self._mem_name)
        return list(dict.fromkeys(names))

    def _open(self, name: str) -> None:
        """OpenFileMapping + MapViewOfFile (ganze Region) und Header validieren."""
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_size_t,
        ]
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]

        handle = k32.OpenFileMappingW(_FILE_MAP_READ, 0, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "OpenFileMapping fehlgeschlagen")
        view = k32.MapViewOfFile(ctypes.c_void_p(handle), _FILE_MAP_READ, 0, 0, 0)
        if not view:
            err = ctypes.get_last_error()
            k32.CloseHandle(ctypes.c_void_p(handle))
            raise OSError(err, "MapViewOfFile fehlgeschlagen")
        raw = ctypes.string_at(view, _HEADER_SIZE)
        fields = struct.unpack(_HEADER_FORMAT, raw)
        if fields[0] != _SIGNATURE:
            k32.UnmapViewOfFile(ctypes.c_void_p(view))
            k32.CloseHandle(ctypes.c_void_p(handle))
            raise HwinfoError(f"Signatur {fields[0]!r} != {_SIGNATURE!r}")
        total = max(
            fields[4] + fields[5] * fields[6],
            fields[7] + fields[8] * fields[9],
            _HEADER_SIZE,
        )
        # Sicherheitsnetz: bei absurder Größe (defektes Layout) nicht über die Region
        # hinaus lesen — string_at würde sonst eine Access Violation auslösen.
        if total <= 0 or total > 64 * 1024 * 1024:
            k32.UnmapViewOfFile(ctypes.c_void_p(view))
            k32.CloseHandle(ctypes.c_void_p(handle))
            raise HwinfoError(f"Unplausible Mapping-Größe ({total} Bytes)")
        self._handle = int(handle)
        self._view = int(view)
        self._total = total

    # -- Lesen ------------------------------------------------------------

    def _snapshot(self) -> bytes | None:
        """Aktueller Speicherinhalt als bytes (live) oder der injizierte Test-Puffer."""
        if self._static is not None:
            return self._static
        if self._view:
            return ctypes.string_at(self._view, self._total)
        return None

    @staticmethod
    def _read_header(buf: bytes) -> tuple[int, int, int]:
        """Gibt ``(reading_offset, reading_element_size, reading_count)`` aus dem Header."""
        if len(buf) < _HEADER_SIZE:
            raise HwinfoError("HWiNFO-Header unvollständig.")
        fields = struct.unpack(_HEADER_FORMAT, buf[:_HEADER_SIZE])
        if fields[0] != _SIGNATURE:
            raise HwinfoError("HWiNFO-Signatur fehlt.")
        return fields[7], fields[8], fields[9]

    @staticmethod
    def _decode(raw: bytes) -> str:
        """Dekodiert ein nullterminiertes Feld (Label/Unit)."""
        end = raw.find(b"\x00")
        if end >= 0:
            raw = raw[:end]
        return raw.decode("latin-1", errors="replace").strip()

    def _find_value(self, hints: tuple[str, ...]) -> tuple[float, str] | None:
        """Erstes Reading, dessen User-Label einen der ``hints`` enthält → (Wert, Einheit)."""
        buf = self._snapshot()
        if buf is None:
            return None
        try:
            reading_offset, reading_size, reading_count = self._read_header(buf)
        except HwinfoError:
            return None
        if reading_size < _VALUE_OFFSET + _VALUE_SIZE:
            return None
        for i in range(reading_count):
            base = reading_offset + i * reading_size
            if base + _VALUE_OFFSET + _VALUE_SIZE > len(buf):
                break
            label = self._decode(buf[base + _LABEL_USER_OFFSET : base + _UNIT_OFFSET]).lower()
            if not any(hint in label for hint in hints):
                continue
            unit = self._decode(buf[base + _UNIT_OFFSET : base + _VALUE_OFFSET])
            (value,) = struct.unpack(
                _VALUE_FORMAT, buf[base + _VALUE_OFFSET : base + _VALUE_OFFSET + _VALUE_SIZE]
            )
            if value > 0.0:
                return float(value), unit
        return None

    def read_voltage_mv(self) -> float | None:
        """Aktuelle GPU-Core-Spannung in mV (best-effort) oder ``None`` (wirft nie)."""
        found = self._find_value(_VOLTAGE_LABEL_HINTS)
        if found is None:
            return None
        value, unit = found
        return value if "mv" in unit.lower() else value * 1000.0

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Aktueller (gemittelter) FPS-Wert von HWiNFO, falls vorhanden — keine Lows."""
        found = self._find_value(_FPS_LABEL_HINTS)
        if found is None:
            return None
        return WindowMetrics(avg_perf=found[0], low_1=None, low_01=None)
