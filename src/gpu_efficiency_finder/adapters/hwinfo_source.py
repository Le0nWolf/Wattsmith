"""Adapter: optionale Telemetrie-/FPS-Quelle über HWiNFOs Shared Memory.

HWiNFO veröffentlicht seine Sensorwerte über ein benanntes Shared-Memory-Mapping
(``Global\\HWiNFO_SENS_SM2``, siehe :data:`constants.HWINFO_SHARED_MEM_NAME`). Dieser
Adapter liest das dokumentierte ``HWiNFO_SENS_SM2``-Layout best-effort per ``mmap`` und
stellt die Sensor-Readings nach Label bereit.

Wichtige Fallstricke (recherchiert):
- HWiNFO muss laufen und „Shared Memory Support“ muss aktiv sein.
- In der FREE-Version wird Shared Memory nach 12 Stunden automatisch deaktiviert und
  muss manuell neu aktiviert werden; die Pro-Version hebt das auf.
- FPS erscheint nur, wenn HWiNFO sie von RTSS bezieht — und ist dort i. d. R. nur
  GEMITTELT. Daher gibt es keine sauberen Lows: ``low_1``/``low_01`` bleiben ``None``.
- HWiNFO ist NUR LESEND; das Setzen des Power-Limits bleibt beim ``GpuBackend``.

``mmap`` ist Teil der Standardbibliothek (Import auf jeder Plattform unbedenklich); das
Mapping selbst wird erst in :meth:`start` geöffnet, nie beim Modul-Import.
"""

from __future__ import annotations

import mmap
import struct

from gpu_efficiency_finder.constants import HWINFO_SHARED_MEM_NAME
from gpu_efficiency_finder.errors import HwinfoError
from gpu_efficiency_finder.logging_setup import get_logger
from gpu_efficiency_finder.models import WindowMetrics

__all__ = ["HwinfoSource"]

_LOG = get_logger(__name__)

# HWiNFO_SENS_SM2-Header: Signatur "SiWH" + version/revision, dann Offsets/Größen/Anzahl
# der Sensor- und Reading-Elemente. Layout laut HWiNFO-SDK (alle Felder little-endian).
_SIGNATURE = b"SiWH"
# dwSignature(4) dwVersion(4) dwRevision(4) poll_time(8)
# dwOffsetOfSensorSection(4) dwSizeOfSensorElement(4) dwNumSensorElements(4)
# dwOffsetOfReadingSection(4) dwSizeOfReadingSection(4) dwNumReadingElements(4)
_HEADER_FORMAT = "<4sIIqIIIIII"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

# Reading-Element-Felder (Anfang): dwType(4) dwSensorIndex(4) dwReadingID(4)
# szLabelOrig(128) szLabelUser(128) szUnit(16) Value(double) … (Rest ignoriert).
_LABEL_USER_OFFSET = 4 + 4 + 4 + 128
_LABEL_LEN = 128
_UNIT_OFFSET = _LABEL_USER_OFFSET + _LABEL_LEN
_UNIT_LEN = 16
_VALUE_OFFSET = _UNIT_OFFSET + _UNIT_LEN
_VALUE_FORMAT = "<d"

# Label-Teilstrings, die auf eine FPS-/Framerate-Sensorzeile hindeuten (case-insensitiv).
_FPS_LABEL_HINTS = ("framerate", "fps", "frames per second")
# Label-Teilstrings für die GPU-Core-Spannung (case-insensitiv), DE + EN. Bewusst spezifisch
# (Kern/Core), damit nicht versehentlich eine Rail-Spannung wie „GPU-Leistungsspannungen“ trifft.
_VOLTAGE_LABEL_HINTS = (
    "gpu core voltage",
    "core voltage",
    "kern-spannung",
    "kernspannung",
    "gpu vid",
    "vddc",
)


class HwinfoSource:
    """PerfSource über HWiNFO Shared Memory — primär Telemetrie, FPS nur falls vorhanden."""

    def __init__(self, mem_name: str = HWINFO_SHARED_MEM_NAME) -> None:
        self._mem_name = mem_name
        self._mmap: mmap.mmap | None = None

    def start(self) -> None:
        """Öffnet das HWiNFO-Shared-Memory-Mapping (lesend).

        Unter Windows muss beim Anhängen an ein BESTEHENDES benanntes Mapping eine Länge > 0
        angegeben werden (Länge 0 schlägt fehl). Daher: erst den Header mappen, daraus die
        Gesamtgröße berechnen und dann mit dieser Länge neu mappen. Zusätzlich Namens-Fallback
        mit/ohne ``Global\\``-Präfix.
        """
        last_exc: Exception | None = None
        for name in self._candidate_names():
            try:
                self._mmap = self._open_mapping(name)
            except (OSError, ValueError, HwinfoError) as exc:
                last_exc = exc
                continue
            self._mem_name = name
            _LOG.info("HWiNFO-Shared-Memory geöffnet (%s)", name)
            return
        raise HwinfoError(
            "HWiNFO-Shared-Memory nicht verfügbar — läuft HWiNFO und ist "
            "„Shared Memory Support“ aktiv? (Free-Version: nach 12 h automatisch aus)."
        ) from last_exc

    def _candidate_names(self) -> list[str]:
        """Konfigurierter Name + Variante mit/ohne ``Global\\``-Präfix (dedupliziert)."""
        prefix = "Global\\"
        names = [self._mem_name]
        if self._mem_name.startswith(prefix):
            names.append(self._mem_name[len(prefix) :])
        else:
            names.append(prefix + self._mem_name)
        return list(dict.fromkeys(names))

    def _open_mapping(self, name: str) -> mmap.mmap:
        """Liest den Header (kleines Mapping), bestimmt die Gesamtgröße und mappt diese."""
        head = mmap.mmap(-1, _HEADER_SIZE, tagname=name, access=mmap.ACCESS_READ)
        try:
            fields = struct.unpack(_HEADER_FORMAT, head[:_HEADER_SIZE])
        finally:
            head.close()
        if fields[0] != _SIGNATURE:
            raise HwinfoError("HWiNFO-Signatur fehlt — unerwartetes Shared-Memory-Format.")
        sensor_end = fields[4] + fields[5] * fields[6]
        reading_end = fields[7] + fields[8] * fields[9]
        total = max(sensor_end, reading_end, _HEADER_SIZE)
        return mmap.mmap(-1, total, tagname=name, access=mmap.ACCESS_READ)

    def stop(self) -> None:
        """Schließt das Mapping (idempotent)."""
        if self._mmap is not None:
            try:
                self._mmap.close()
            except (OSError, ValueError) as exc:
                _LOG.warning("HWiNFO-Mapping-Schließen fehlgeschlagen: %s", exc)
            self._mmap = None
            _LOG.info("HWiNFO-Shared-Memory geschlossen")

    def _read_header(self, buf: mmap.mmap) -> tuple[int, int, int]:
        """Parst den SM2-Header. Gibt ``(reading_offset, reading_size, reading_count)``."""
        raw = buf[:_HEADER_SIZE]
        if len(raw) < _HEADER_SIZE:
            raise HwinfoError("HWiNFO-Header unvollständig — Shared Memory zu klein.")
        fields = struct.unpack(_HEADER_FORMAT, raw)
        if fields[0] != _SIGNATURE:
            raise HwinfoError("HWiNFO-Signatur fehlt — unerwartetes Shared-Memory-Format.")
        reading_offset = fields[7]
        reading_size = fields[8]
        reading_count = fields[9]
        return reading_offset, reading_size, reading_count

    def _decode_label(self, raw: bytes) -> str:
        """Dekodiert ein nullterminiertes Label aus dem Reading-Element."""
        end = raw.find(b"\x00")
        if end >= 0:
            raw = raw[:end]
        return raw.decode("latin-1", errors="replace").strip()

    def _read_fps(self) -> float | None:
        """Sucht das erste FPS-/Framerate-Reading und gibt seinen (gemittelten) Wert."""
        buf = self._mmap
        if buf is None:
            return None
        try:
            reading_offset, reading_size, reading_count = self._read_header(buf)
        except HwinfoError:
            raise
        if reading_size < _VALUE_OFFSET + struct.calcsize(_VALUE_FORMAT):
            return None
        for i in range(reading_count):
            base = reading_offset + i * reading_size
            label_raw = buf[base + _LABEL_USER_OFFSET : base + _LABEL_USER_OFFSET + _LABEL_LEN]
            label = self._decode_label(label_raw).lower()
            if not any(hint in label for hint in _FPS_LABEL_HINTS):
                continue
            value_raw = buf[
                base + _VALUE_OFFSET : base + _VALUE_OFFSET + struct.calcsize(_VALUE_FORMAT)
            ]
            if len(value_raw) < struct.calcsize(_VALUE_FORMAT):
                continue
            (value,) = struct.unpack(_VALUE_FORMAT, value_raw)
            if value > 0.0:
                return float(value)
        return None

    def read_voltage_mv(self) -> float | None:
        """Aktuelle GPU-Core-Spannung in mV (best-effort) oder ``None``.

        Scannt die Readings nach einem Spannungs-Label der GPU. HWiNFO liefert die Spannung
        i. d. R. in Volt → wird zu mV skaliert (Einheit „mV“ wird nicht erneut skaliert).
        Wirft nie — bei Problemen/fehlendem Mapping ``None``.
        """
        buf = self._mmap
        if buf is None:
            return None
        try:
            reading_offset, reading_size, reading_count = self._read_header(buf)
        except HwinfoError:
            return None
        value_size = struct.calcsize(_VALUE_FORMAT)
        if reading_size < _VALUE_OFFSET + value_size:
            return None
        for i in range(reading_count):
            base = reading_offset + i * reading_size
            label = self._decode_label(
                buf[base + _LABEL_USER_OFFSET : base + _LABEL_USER_OFFSET + _LABEL_LEN]
            ).lower()
            if not any(hint in label for hint in _VOLTAGE_LABEL_HINTS):
                continue
            unit = self._decode_label(buf[base + _UNIT_OFFSET : base + _UNIT_OFFSET + _UNIT_LEN])
            value_raw = buf[base + _VALUE_OFFSET : base + _VALUE_OFFSET + value_size]
            if len(value_raw) < value_size:
                continue
            (value,) = struct.unpack(_VALUE_FORMAT, value_raw)
            if value <= 0.0:
                continue
            return float(value) if "mv" in unit.lower() else float(value) * 1000.0
        return None

    def window_metrics(self, t_start: float, t_end: float) -> WindowMetrics | None:
        """Aktueller, von HWiNFO gemittelter FPS-Wert (falls vorhanden), sonst ``None``.

        Das Zeitfenster ist hier ohne Wirkung: HWiNFO liefert nur den aktuellen Mittelwert,
        keine frame-genaue Historie — daher auch keine Lows.
        """
        if self._mmap is None:
            raise HwinfoError("HWiNFO-Shared-Memory ist nicht geöffnet — bitte start() aufrufen.")
        fps = self._read_fps()
        if fps is None:
            return None
        return WindowMetrics(avg_perf=fps, low_1=None, low_01=None)
