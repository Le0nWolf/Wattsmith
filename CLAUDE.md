# GPU Efficiency Finder

## Projektbeschreibung

**GPU Efficiency Finder** ist ein portables Windows-Tool, das den Effizienz-Sweet-Spot einer
NVIDIA-GPU findet: Es senkt das Power-Limit schrittweise ab, misst pro Stufe Stromverbrauch und
Performance (Ø-FPS, 1% Low, 0.1% Low) und empfiehlt am Ende ein Power-Limit, mit dem man viel
Strom spart, ohne spürbar Leistung oder Frametime-Stabilität zu verlieren — automatisch, statt
jede Stufe manuell durchzuklicken.

- **Plattform:** Windows (NVIDIA). Architektur ist so gebaut, dass Linux/AMD später als weitere
  Adapter ergänzt werden können, ohne die Kern-Logik anzufassen.
- **Auslieferung:** eine einzelne, portable `.exe` (PyInstaller `--onefile`, natives Fenster via
  pywebview). Kein Python-Install nötig, keine zurückbleibenden Dateien.
- **Lizenz:** MIT.

## Hinweis zur Kommunikation

- Die Prompts werden per **Wispr Flow** transkribiert (Speech-to-Text). Wörter können phonetisch
  falsch geschrieben sein (z. B. „Ban" statt „Bun", „Veed" statt „Vite"). Aus dem Kontext
  ableiten, was gemeint ist.
- Antworten auf **Deutsch**, direkt und pragmatisch.
- Bei Unsicherheit **fragen statt raten**.

---

## Oberste Prinzipien

### 1. Enterprise Code Quality

- **Single Responsibility** — jedes Modul/jede Funktion hat genau EINE Aufgabe.
- **Wartbarkeit** — Code muss in 6 Monaten ohne Kontext verständlich sein.
- **Effizienz** — kein blockierendes I/O im UI-Thread; `asyncio` bzw. Threads, wo nötig.
- **Bestehende Patterns respektieren** — Ports-&-Adapters-Struktur beibehalten (siehe Architektur).

### 2. DRY — Don't Repeat Yourself

- Vor neuer Funktionalität: **prüfen, ob Ähnliches schon existiert**.
- Geteilte Value Objects/Modelle leben **einmal** in `models.py` — NICHT in UI, Domain und
  Persistenz getrennt definieren.
- Logik, die sich an 2+ Stellen wiederholt → sofort extrahieren (Domain oder `infra/`).

### 3. Tests sind Pflicht

- Die **gesamte Domänen-Logik** (`domain/analysis.py`, `domain/sweep.py`) ist rein und muss
  **ohne GPU** testbar sein — über Fake-Adapter. Keine Ausnahme.
- Adapter (`adapters/`) bekommen Tests für ihre reine Parsing-/Mapping-Logik (z. B. PresentMon-CSV
  → Frametimes) mit Sample-Daten.
- Erfolgs- UND Fehlerfälle abdecken. `pytest` muss grün sein. Features ohne Tests sind nicht fertig.

### 4. Keine neuen Dependencies ohne Absprache

### 5. Domänen-Logik = Single Source of Truth

- Die fachliche Wahrheit (Knie, FPS/W-Peak, Empfehlung, Sweep-Ablauf) lebt **ausschließlich** in
  `domain/`. Sie kennt **keine Hardware, kein NiceGUI, keine Dateien** — nur abstrakte Ports.
- UI, Adapter und Persistenz sind **Konsumenten** der Domäne. Reihenfolge beim Bauen:
  Modelle → Domain-Logik (+ Tests) → Ports → Adapter → UI.
- So lässt sich die komplette Logik testen, ohne eine GPU zu besitzen, und ein zweiter Adapter
  (AMD/Linux) oder eine zweite Oberfläche (CLI) ändert nichts an der Domäne.

### 6. Checkliste: Neues Feature implementieren

1. **Verstehen** — Anforderung klären, bestehenden Code lesen, prüfen ob Ähnliches existiert.
2. **Modelle** — falls neue Value Objects nötig: in `models.py`, als `@dataclass(frozen=True)`.
3. **Domain** — reine Logik in `domain/`, keine I/O, nur Ports.
4. **Tests** — Unit-Tests für die Logik (Fake-Ports), Erfolgs- und Fehlerfälle.
5. **Port** — falls neue Außenwelt-Abhängigkeit: Interface (`Protocol`) in `ports/`.
6. **Adapter** — konkrete Implementierung in `adapters/`, dünn, delegiert an Bibliothek/CLI.
7. **UI** — Anbindung in `app.py`/`ui/`.
8. **Qualitätscheck** — Kein doppelter Code? Modelle geteilt? Tests grün? `ruff` + `pyright` sauber?

---

## Tech Stack

| Komponente            | Technologie                                                        |
| --------------------- | ------------------------------------------------------------------ |
| **Sprache**           | Python 3.12 (vollständige Type Hints, kein `Any`)                  |
| **Paket-/Env-Mgmt**   | **uv** (Astral) — `pyproject.toml` + `uv.lock` (pip als Fallback)  |
| **Lint + Format**     | **ruff** (ersetzt black, flake8, isort, pyupgrade)                 |
| **Typecheck**         | **pyright** (strict) — oder mypy strict                            |
| **Tests**             | **pytest**                                                         |
| **UI**                | **NiceGUI** als **natives Fenster** (pywebview, `native=True`)     |
| **GPU-Steuerung**     | **nvidia-ml-py** (NVML, import `pynvml`); `nvidia-smi` als Fallback |
| **FPS/Frametimes**    | **PresentMon** (Konsolen-EXE, in die App-EXE gebündelt)            |
| **Knie-Erkennung**    | **kneed** (Kneedle-Algorithmus)                                    |
| **Charts**            | **plotly** (über NiceGUI)                                          |
| **Config-Validierung**| **pydantic v2** (User-Eingaben/Settings)                          |
| **Value Objects**     | `dataclasses` (`frozen=True, slots=True`)                          |
| **Prozess-Handling**  | **psutil** (Benchmark-Prozessbaum sauber beenden)                  |
| **Verpackung**        | **PyInstaller** / **nicegui-pack** (`--onefile`)                   |
| **CI/Build**          | GitHub Actions (`windows-latest`-Runner baut die EXE)              |
| Optional              | **torch** (Compute-Last, NICHT in der EXE), HWiNFO-Shared-Memory-Reader |

---

## Projektstruktur

```
gpu-efficiency-finder/
├── CLAUDE.md
├── README.md                       # Self-Use-Guide
├── LICENSE                         # MIT
├── pyproject.toml                  # uv + ruff + pytest + pyright Config
├── uv.lock
├── .gitignore
├── .github/
│   └── workflows/
│       └── build-windows.yml       # baut die EXE auf windows-latest
├── assets/
│   └── presentmon/                 # gebündelte PresentMon-Konsolen-EXE (in die EXE gepackt)
│
├── src/
│   └── gpu_efficiency_finder/
│       ├── __init__.py
│       ├── __main__.py             # Einstieg + Composition Root (Adapter wiren, ui.run native)
│       ├── app.py                  # NiceGUI-UI (orchestriert, delegiert an Domain)
│       ├── models.py               # geteilte Value Objects (SweepRow, OperatingPoint, ...)
│       ├── config.py               # pydantic: SweepConfig / AppSettings
│       ├── constants.py            # keine Magic Strings
│       ├── errors.py               # Domain-Exceptions (GpuPermissionError, PresentMonError, ...)
│       ├── logging_setup.py        # logging-Konfiguration
│       │
│       ├── domain/                 # PURE Logik — keine I/O, kein UI, nur Ports
│       │   ├── __init__.py
│       │   ├── analysis.py         # low_fps, efficiency_peak, knee_point, recommend
│       │   └── sweep.py            # Sweep-Orchestrierung (nutzt ausschließlich Ports)
│       │
│       ├── ports/                  # Interfaces (typing.Protocol) — die "Steckdosen"
│       │   ├── __init__.py
│       │   ├── gpu_backend.py      # GpuBackend
│       │   ├── perf_source.py      # PerfSource
│       │   └── benchmark_runner.py # BenchmarkRunner
│       │
│       ├── adapters/               # konkrete I/O-Implementierungen — die "Stecker"
│       │   ├── __init__.py
│       │   ├── nvml_backend.py
│       │   ├── nvidia_smi_backend.py     # Fallback (NoPermission → über CLI)
│       │   ├── presentmon_source.py
│       │   ├── compute_load_source.py    # torch, optional
│       │   ├── clock_proxy_source.py
│       │   ├── hwinfo_source.py          # optional, Shared Memory
│       │   └── process_benchmark_runner.py
│       │
│       ├── infra/
│       │   ├── presentmon_bundle.py      # PresentMon-Pfad via sys._MEIPASS auflösen
│       │   └── persistence.py            # JSON-Run speichern/laden, CSV-Export
│       │
│       └── ui/                           # UI in kleine Bausteine zerlegt (keine Riesen-app.py)
│           ├── __init__.py
│           ├── config_panel.py
│           ├── chart.py
│           └── results_table.py
│
└── tests/
    ├── domain/
    │   ├── test_analysis.py
    │   └── test_sweep.py                 # mit Fake-Ports (kein GPU nötig)
    └── adapters/
        └── test_presentmon_parse.py      # CSV-Parsing mit Sample-Zeilen
```

**Richtwert Dateigröße:** ~150–200 Zeilen pro Datei. Lieber eine Datei mehr als eine zu große.
`app.py` koordiniert nur; konkrete UI-Bausteine wandern nach `ui/`.

---

## Architektur & Patterns

### Ports & Adapters (Hexagonal)

```
        ┌─────────────── UI (NiceGUI, app.py / ui/) ───────────────┐
        │                         ▼ ruft                            │
        │             domain/  (analysis.py, sweep.py)              │  ← PURE, Single Source of Truth
        │                  ▲ hängt nur an Ports                     │
        │        ports/ (Protocol: GpuBackend, PerfSource, ...)     │
        └──────────────────────────┬───────────────────────────────┘
                                    │ implementiert von
                          adapters/ (NVML, PresentMon, ...)  +  infra/ (Persistenz, Bundle)
```

- **Domain** hängt **nur** an Ports (`Protocol`-Interfaces), nie an konkreten Adaptern. Dadurch in
  Tests mit Fakes austauschbar und ohne GPU lauffähig.
- **Adapter** sind dünn: sie übersetzen zwischen Außenwelt (NVML, PresentMon-CSV, sysfs) und den
  Domain-Modellen. **Keine** Geschäftslogik in Adaptern.
- **Composition Root** (`__main__.py`) ist der EINZIGE Ort, der konkrete Adapter erzeugt und in die
  Sweep-Engine injiziert (Dependency Injection von Hand — kein Framework nötig).

#### Referenz-Pattern: Port (Interface) + Modell

```python
# models.py — geteilte Value Objects, unveränderlich
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PowerLimits:
    default_w: float
    min_w: float
    max_w: float
    current_w: float

@dataclass(frozen=True, slots=True)
class Telemetry:
    power_w: float
    clock_mhz: float
    temp_c: float
    util_pct: float

@dataclass(frozen=True, slots=True)
class SweepRow:
    set_watt: float
    pct: int
    power_w: float
    clock_mhz: float
    temp_c: float
    avg_fps: float | None = None
    low_1: float | None = None
    low_01: float | None = None

# ports/gpu_backend.py — strukturelles Interface, keine Implementierung
from typing import Protocol
from gpu_efficiency_finder.models import PowerLimits, Telemetry, GpuInfo

class GpuBackend(Protocol):
    def list_gpus(self) -> list[GpuInfo]: ...
    def get_limits(self, idx: int) -> PowerLimits: ...
    def set_power_limit_w(self, idx: int, watt: float) -> None: ...
    def read_telemetry(self, idx: int) -> Telemetry: ...
    def reset_to_default(self, idx: int) -> None: ...
```

#### Referenz-Pattern: Pure Domain-Logik (testbar ohne GPU)

```python
# domain/analysis.py — KEINE I/O, nur Rechnen
from collections.abc import Sequence
from gpu_efficiency_finder.models import SweepRow, OperatingPoint

def low_fps(frametimes_ms: Sequence[float], pct: float) -> float | None:
    """Zeitgewichtetes x% Low (Afterburner/CapFrameX-Definition)."""
    fts = [ft for ft in frametimes_ms if ft > 0]
    if not fts:
        return None
    total = sum(fts)
    threshold = total * pct / 100.0
    acc = 0.0
    for ft in sorted(fts, reverse=True):
        acc += ft
        if acc >= threshold:
            return 1000.0 / ft
    return 1000.0 / max(fts)

def recommend(
    rows: Sequence[SweepRow],
    avg_tol_pct: float,
    low_tol_pct: float,
    min_fps_floor: float | None = None,
) -> Recommendation:
    """Niedrigstes Limit, das relative Toleranzen UND (falls gesetzt) die absolute
    FPS-Untergrenze hält. Gibt zusätzlich das unbeschränkte Optimum + Delta zurück."""
    ...
```

#### Referenz-Pattern: Sweep-Engine hängt nur an Ports (DI)

```python
# domain/sweep.py — orchestriert, kennt keine konkrete Hardware
from gpu_efficiency_finder.ports import GpuBackend, PerfSource

class SweepEngine:
    def __init__(self, gpu: GpuBackend, perf: PerfSource) -> None:
        self._gpu = gpu
        self._perf = perf

    async def run(self, config: SweepConfig, on_row: RowCallback) -> SweepResult:
        limits = self._gpu.get_limits(config.gpu_index)
        try:
            for pct in config.steps(limits.default_w):
                watt = clamp(limits.default_w * pct / 100, limits.min_w, limits.max_w)
                self._gpu.set_power_limit_w(config.gpu_index, watt)
                await settle(config.settle_s)
                row = await self._measure(config, watt, pct)
                on_row(row)
            return build_result(...)
        finally:
            self._gpu.reset_to_default(config.gpu_index)  # IMMER zurücksetzen
```

#### Referenz-Pattern: Config-Validierung (pydantic v2)

```python
# config.py — User-Eingaben validieren, typsichere Daten an die Domain geben
from pydantic import BaseModel, Field, model_validator

class SweepConfig(BaseModel):
    gpu_index: int = Field(0, ge=0)
    start_pct: int = Field(100, ge=20, le=100)
    end_pct: int = Field(50, ge=20, le=100)
    step_pct: int = Field(5, ge=1, le=25)
    settle_s: float = Field(8, ge=2, le=60)
    measure_s: float = Field(25, ge=5, le=120)
    avg_tol_pct: float = Field(3, ge=0, le=30)
    low_tol_pct: float = Field(5, ge=0, le=40)
    min_fps_floor: float | None = Field(None, ge=1)   # optional, abschaltbar
    randomize_order: bool = True

    @model_validator(mode="after")
    def _start_above_end(self) -> "SweepConfig":
        if self.start_pct <= self.end_pct:
            raise ValueError("start_pct muss größer als end_pct sein")
        return self
```

#### Referenz-Pattern: Fehlerbehandlung

```python
# errors.py — sprechende Domain-Exceptions, keine nackten Strings
class GpuEfficiencyError(Exception): ...
class GpuPermissionError(GpuEfficiencyError): ...   # NVML NoPermission → Admin nötig
class PresentMonError(GpuEfficiencyError): ...
class NoLoadRunningError(GpuEfficiencyError): ...

# UI fängt diese ab und zeigt eine verständliche Meldung (kein Stacktrace),
# z. B. GpuPermissionError → "Bitte als Administrator starten".
```

#### Referenz-Pattern: Tests mit Fake-Ports (kein GPU)

```python
# tests/domain/test_sweep.py
class FakeGpu:
    def __init__(self) -> None:
        self.set_calls: list[float] = []
        self.reset_called = False
    def get_limits(self, idx): return PowerLimits(300, 100, 350, 300)
    def set_power_limit_w(self, idx, watt): self.set_calls.append(watt)
    def read_telemetry(self, idx): return Telemetry(200, 1800, 60, 99)
    def reset_to_default(self, idx): self.reset_called = True

async def test_sweep_resets_limit_even_on_error() -> None:
    gpu = FakeGpu()
    engine = SweepEngine(gpu, FakePerf())
    ...
    assert gpu.reset_called  # Default-Limit MUSS wiederhergestellt werden
```

### Mess-Modi (über denselben PerfSource-Port)

Gestaffelt, alle über einen Schalter wählbar:

- **ClockProxySource** — braucht nichts Zusätzliches, findet das Knie näherungsweise (Default für
  einen schnellen Lauf). Eine externe Last muss laufen.
- **PresentMonSource** — Präzisions-Modus: echte FPS + 1%/0.1% Low. PresentMon ist gebündelt.
- **ComputeLoadSource** — erzeugt eigene Last (torch), kein externer Benchmark; nicht in der EXE.
- **HwinfoSource** — optionale Telemetrie-/FPS-Quelle (siehe Fallstricke).

---

## Python-Regeln

- **Vollständige Type Hints**, kein `Any`. Parameter UND Rückgabewerte annotieren.
- **Value Objects** als `@dataclass(frozen=True, slots=True)`; **User-Config** als pydantic-Modell.
- `from __future__ import annotations` oben in jeder Datei.
- **Keine Magic Strings** — Konstanten/Enums in `constants.py` (z. B. Mess-Modi als `enum.StrEnum`).
- Öffentliche Modul-API über `__all__` deklarieren; intern `_private` benennen.
- Imports absolut (`from gpu_efficiency_finder.domain import analysis`), nicht relativ-tief.
- I/O in Adaptern; Domain bleibt synchron-rein bzw. nutzt nur übergebene Ports.

---

## Logging

```python
# Python logging, konfiguriert in logging_setup.py. Level-Konvention:
# - logging.error()  → unerwartete Fehler, NVML/PresentMon-Ausfälle
# - logging.warning()→ erwartete Auffälligkeiten (NoPermission-Fallback, einzelne Stufe ohne FPS)
# - logging.info()   → Lifecycle: App-Start, Sweep-Start/-Ende, Default-Limit wiederhergestellt
# - logging.debug()  → Detail beim Entwickeln; nicht laut in Produktion
#
# Loggen: Sweep-Runs (Modus, Bereich, GPU), gesetzte Limits, Fehler mit Kontext (welcher Adapter).
# NICHT loggen: jeden Telemetrie-Poll (zu laut), komplette PresentMon-CSV-Ströme.
```

---

## Befehle

```bash
# Setup
uv sync                      # Env + Dependencies aus uv.lock

# Entwicklung
uv run gpu-efficiency-finder # App starten (natives Fenster)
uv run pytest                # Tests
uv run pytest -q --watch     # (mit pytest-watcher, falls genehmigt)

# Qualität
uv run ruff check .          # Lint
uv run ruff format .         # Format
uv run pyright               # Typecheck (strict)

# EXE bauen (lokal, auf Windows)
uv run nicegui-pack --onefile --name GpuEfficiencyFinder src/gpu_efficiency_finder/__main__.py
```

---

## Konventionen

### Dateinamen

- Module: `snake_case.py` (z. B. `nvml_backend.py`, `presentmon_source.py`).
- Tests: `test_<modul>.py` im gespiegelten `tests/`-Baum.
- Ports = Interface pro Datei; Adapter = eine konkrete Implementierung pro Datei.

### Code-Stil

- Funktionen/Variablen: `snake_case`; Klassen: `PascalCase`; Konstanten: `UPPER_SNAKE_CASE`.
- Enums für feste Wertemengen (Mess-Modus, Betriebspunkt-Typ).
- ruff + pyright sind verbindlich; CI bricht bei Verstößen.

### Deutsche Texte & Umlaute (UI)

- **Umlaute IMMER als echte UTF-8-Zeichen** — `ü`, `ö`, `ä`, `Ü`, `Ö`, `Ä`, `ß`.
- **NIEMALS** ASCII-Ersatz (`ue`, `oe`, `ss`) und **NIEMALS** Unicode-Escapes (`\u00fc`).
- Gilt für UI-Labels, Hinweise, Fehlermeldungen, Kommentare.

### Git

- Commit Messages englisch, **lowercase**, `feat:`/`fix:`/`refactor:`/`test:`/`docs:`/`chore:`.
- Branches: `feature/...`, `fix/...`.

---

## Implementierungs-Hinweise & Bekannte Fallstricke

> Recherchierte Fakten — bitte beachten, NICHT aus dem Gedächtnis raten.

### ⚠️ Sicherheit & Reversibilität (Domain-Invariante)

- Ein abgesenktes Power-Limit kann die GPU **nicht** zerstören — sie taktet nur runter. Der Treiber
  akzeptiert ohnehin nur Werte in `[min, max]`; zusätzlich in Software clampen.
- Das Default-Limit MUSS in **jedem** Pfad wiederhergestellt werden: normales Ende, Stop, Exception,
  Programmabbruch (`try/finally` in der Sweep-Engine + Signal-Handler/atexit im Composition Root).

### ⚠️ NVML (`nvidia-ml-py`, import `pynvml`)

- `nvmlDeviceSetPowerManagementLimit(handle, limit_mw)` — Wert in **Milliwatt** (int!). Braucht
  Admin, sonst `NVMLError_NoPermission`.
- Grenzen: `nvmlDeviceGetPowerManagementLimitConstraints` (min/max mW), Default:
  `nvmlDeviceGetPowerManagementDefaultLimit` (mW).
- Telemetrie: `nvmlDeviceGetPowerUsage` (mW), `nvmlDeviceGetClockInfo(.., NVML_CLOCK_GRAPHICS)`,
  `nvmlDeviceGetTemperature(.., NVML_TEMPERATURE_GPU)`, `nvmlDeviceGetUtilizationRates().gpu`.
- **Fallback-Adapter:** bei `NoPermission` auf `nvidia-smi -i <idx> -pl <watt>` (Watt!) ausweichen
  und dem Nutzer „als Administrator starten" anzeigen.

### ⚠️ PresentMon (GameTechDev/PresentMon, MIT)

- **Standalone-Konsolen-Binary** verwenden (z. B. `PresentMon-2.x.x-x64.exe`) — braucht KEINEN
  installierten Service (Service ist nur für die GUI-/Overlay-Variante). Nutzt ETW, Admin nötig.
- Start: `--output_stdout`, `--process_name <spiel.exe>` (filtert direkt), `--v1_metrics`
  (stabile 1.x-Spalten), `--no_console_stats`, `--stop_existing_session`.
- Aus v1-Schema `MsBetweenPresents` lesen; FPS = 1000 / MsBetweenPresents. Beim Einlesen eigene
  Empfangszeit (`time.monotonic()`) je Zeile speichern (Zeitfenster-Mapping). Parser defensiv
  (Header dynamisch suchen, Alternativnamen wie `FrameTime` zulassen).
- **In die EXE bündeln** (`assets/presentmon/`, PyInstaller `datas`), Pfad über `sys._MEIPASS`
  auflösen (`infra/presentmon_bundle.py`). PyInstaller entpackt nach `%TEMP%` und löscht beim
  Beenden → nichts bleibt liegen. Kein Download-Cache, kein Service-Setup.

### ⚠️ NVIDIA-Overlay

- Das NVIDIA-App-/GeForce-Overlay hat **keine auslesbare API**. Es nutzt dieselbe ETW-Mess-Technik
  wie PresentMon/FrameView — daher ist PresentMon die korrekte, gleichwertige Quelle. Nicht
  versuchen, das Overlay per OCR o. Ä. abzugreifen.

### ⚠️ HWiNFO Shared Memory (optionaler Adapter)

- HWiNFO muss laufen, „Shared Memory Support" aktiv. **Free-Version: nach 12 h automatisch
  deaktiviert** (manuell neu aktivieren); Pro hebt das auf. In der UI als Hinweis zeigen.
- Auslesen über `Global\HWiNFO_SENS_SM2` (mmap, dokumentiertes Layout) — fertige Community-Reader
  prüfen, sonst schlanker mmap-Parser. FPS nur, wenn HWiNFO sie von **RTSS** bekommt; meist nur
  gemittelt → keine sauberen Lows. HWiNFO ist **nur lesend**; Limit-Setzen bleibt bei NVML.

### ⚠️ Externer Benchmark als Last

- Loop-fähige Optionen: Unigine Superposition / Heaven / Valley. **3DMark** nur in der
  **Professional Edition** per CLI (`3DMarkCmd.exe`) startbar; Steam/Basic nicht.
- Score-am-Ende-Benchmarks sind ungeeignet — der Sweep braucht ein durchgehendes Lastfenster.
- Prozess**baum** sauber beenden (`psutil.Process(...).children(recursive=True)`), sonst läuft der
  Benchmark nach dem Sweep weiter.
- Kopplung: der für PresentMon eingetragene Prozessname ist der tatsächlich rendernde Prozess
  (bei Launchern oft ein Kindprozess).

### ⚠️ Eigene Spiele testen

- PresentMon filtert per `--process_name` auf das Spiel → **Knie pro Spiel** ermittelbar (das Knie
  ist workload-abhängig). Wichtig: **FPS-Cap/V-Sync aus**, GPU-lastige, reproduzierbare Szene —
  sonst deckelt der Cap die Kurve und das Ergebnis ist keine echte Effizienzkurve.

### ⚠️ Gleichzeitig undervolten (Afterburner & Co.)

- Power-Limit (dieses Tool) und V/F-Kurve (Afterburner-Undervolt) sind **unabhängige Hebel** und
  dürfen koexistieren — das Tool misst das tatsächliche Verhalten und findet das beste Limit
  *obendrauf*. Caveats: in Afterburner **nur die V/F-Kurve** formen und den **Power-Limit-Regler
  dort auf Default lassen** (sonst Schreibkonflikt auf dieselbe Einstellung); Undervolt während des
  Sweeps **unverändert** lassen.

### ⚠️ Thermal-Drift (Messmethodik)

- Über einen langen Sweep verzerrt Aufheizen spätere Stufen. Gegenmaßnahmen: Stufen-Reihenfolge
  **randomisieren** (Default an), Aufwärmphase pro Stufe verwerfen, Temp protokollieren, Baseline am
  Ende gegenmessen und bei >X% Abweichung warnen.

### ⚠️ FPS-Untergrenze

- Optional und **abschaltbar**. Ist sie bindend (das unbeschränkte Optimum läge tiefer), zusätzlich
  anzeigen: „nicht der effizienteste Punkt" + wie viel % mehr Ersparnis ohne die Grenze möglich
  wäre. `recommend` gibt daher Empfehlung UND unbeschränktes Optimum + Delta zurück.

### ⚠️ Portabilität (nichts bleibt liegen)

- Kein NiceGUI-Persistent-Storage (`app.storage.*` legt `.nicegui/` an) — App-Zustand im Speicher.
- Nur explizit exportierte Dateien (CSV/JSON) werden geschrieben, an vom Nutzer gewählten Ort.
- Ehrlich im README: transiente ETW-Session (kein Datei-Artefakt, nach Reboot weg), reversible
  Power-Limit-Änderung, bei hartem Absturz evtl. PyInstaller-Temp-Ordner bis `%TEMP%`-Cleanup.

### ⚠️ Verpackung (native + onefile)

- Einstieg mit `if __name__ in {"__main__", "__mp_main__"}:` schützen (native Mode + Multiprocessing,
  sonst mehrere Fenster/Build-Hang).
- pywebview nutzt unter Windows die **WebView2-Runtime** (auf aktuellem Windows vorinstalliert; sonst
  „Edge WebView2 Runtime" nachinstallieren). Bei leerem Fenster/Build-Problemen PyInstaller um
  `--collect-all webview` (ggf. `--collect-all clr_loader` / `pythonnet`) erweitern.
- **torch NICHT bündeln** (GB-groß). PyInstaller cross-kompiliert nicht — EXE auf Windows bauen
  (lokal oder GH-Actions `windows-latest`). Python muss auf dem Zielrechner nicht installiert sein.

---

## Packaging & CI

`.github/workflows/build-windows.yml` baut die EXE auf einem Windows-Runner (kein lokaler Compiler
nötig):

```yaml
name: Build Windows EXE
on:
  workflow_dispatch:
  push:
    tags: ['v*']
jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install uv
        run: pip install uv
      - name: Sync deps
        run: uv sync
      - name: Build EXE
        run: uv run nicegui-pack --onefile --name GpuEfficiencyFinder src/gpu_efficiency_finder/__main__.py
      - uses: actions/upload-artifact@v4
        with:
          name: GpuEfficiencyFinder-windows
          path: dist/GpuEfficiencyFinder.exe
      - name: Attach to release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: dist/GpuEfficiencyFinder.exe
```

Empfohlen zusätzlich ein CI-Job, der auf `ubuntu-latest` `ruff check`, `pyright` und `pytest`
laufen lässt (die Domänen-Tests brauchen keine GPU) — so bleibt Qualität bei jedem Push grün.

---

## Dokumentation

- **NVML API:** <https://docs.nvidia.com/deploy/nvml-api/>
- **nvidia-ml-py (PyPI):** <https://pypi.org/project/nvidia-ml-py/>
- **PresentMon (Konsole):** <https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md>
- **kneed:** <https://kneed.readthedocs.io/>
- **NiceGUI:** <https://nicegui.io/documentation>
- **NiceGUI Packaging:** <https://nicegui.io/documentation/section_configuration_deployment#package_for_installation>
- **pydantic v2:** <https://docs.pydantic.dev/latest/>
- **uv:** <https://docs.astral.sh/uv/>
- **ruff:** <https://docs.astral.sh/ruff/>
- **pyright:** <https://microsoft.github.io/pyright/>
- **PyInstaller:** <https://pyinstaller.org/en/stable/>
