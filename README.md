# GPU Efficiency Finder

Findet automatisch den **Effizienz-Sweet-Spot** einer NVIDIA-GPU: Das Tool senkt das
Power-Limit schrittweise ab, misst pro Stufe Stromverbrauch und Performance (Ø-FPS, 1% Low,
0.1% Low) und empfiehlt am Ende ein Power-Limit, mit dem man viel Strom spart, ohne spürbar
Leistung oder Frametime-Stabilität zu verlieren – statt jede Stufe manuell durchzuklicken.

- **Plattform:** Windows / NVIDIA. Die Ports-&-Adapters-Architektur erlaubt später AMD/Linux
  als weiteren Adapter, ohne die Kern-Logik anzufassen.
- **Auslieferung:** eine einzelne, portable `.exe` (PyInstaller `--onefile`). Beim Start öffnet
  sich die Oberfläche im **Standard-Browser** (kein eingebettetes Fenster/WebView2). Kein
  Python-Install nötig, keine zurückbleibenden Dateien.
- **Lizenz:** MIT.

> **Sicherheit:** Ein abgesenktes Power-Limit kann die GPU nicht beschädigen – die Karte taktet
> nur runter. Der Treiber akzeptiert ohnehin nur Werte innerhalb `[min, max]`. Das Default-Limit
> wird in **jedem** Pfad (normales Ende, Stop, Exception, Programmabbruch) wiederhergestellt.

---

## Installation (Entwicklung)

Empfohlen mit [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev          # Env + Dependencies
uv run gpu-efficiency-finder # App starten (öffnet sich im Browser)
uv run pytest                # Tests (laufen ohne GPU)
uv run ruff check .          # Lint
uv run pyright               # Typecheck (strict)
```

Alternativ mit pip:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m gpu_efficiency_finder
```

> Optionaler **Compute-Modus** braucht `torch` (CUDA): `uv sync --extra compute`. torch ist
> GB-groß und wird **nicht** in die EXE gebündelt.

---

## EXE-Build

### Lokal (auf Windows)

```bash
uv run nicegui-pack --onefile --name GpuEfficiencyFinder src/gpu_efficiency_finder/__main__.py
# Ergebnis: dist/GpuEfficiencyFinder.exe
```

Für einen automatischen UAC-Admin-Prompt eine `.spec` erzeugen und in `EXE(...)`
`uac_admin=True` setzen, dann `pyinstaller GpuEfficiencyFinder.spec`.

### Per GitHub Actions

`.github/workflows/ci.yml` ist **eine** Pipeline auf einem `windows-latest`-Runner mit
sequentiellen Schritten: `ruff` (Lint + Format) → `pyright` → `pytest` → **erst dann** EXE bauen
(`nicegui-pack`) → Artifact hochladen. Schlägt ein früherer Schritt fehl, wird die EXE gar nicht
erst gebaut. Sie läuft bei jedem Push auf `main`, bei Pull Requests, manuell per
*workflow_dispatch* und bei `v*`-Tags (dann wird die EXE zusätzlich an ein Release gehängt).
Komplett auf Windows, weil PyInstaller **nicht** cross-kompiliert; die GPU-freien Tests laufen
dort genauso.

---

## Voraussetzungen auf dem Zielrechner

| Was | wofür | Hinweis |
| --- | --- | --- |
| NVIDIA-Treiber | NVML (Steuerung/Telemetrie) | immer nötig |
| **Admin-Rechte** | Power-Limit setzen, PresentMon-ETW | EXE „als Administrator ausführen" |
| Standard-Browser | UI-Anzeige | jeder moderne Browser (Chrome/Edge/Firefox); auf Windows vorhanden |
| PresentMon | nur FPS-Modus | in die EXE gebündelt (kein Download) |
| HWiNFO + RTSS | nur HWiNFO-Modus | siehe unten |

**Browser-Modus:** Die App startet einen lokalen Webserver und öffnet die Oberfläche im
Standard-Browser (kein eingebettetes Fenster, keine WebView2-Runtime nötig). Schließt du den
Browser-Tab, läuft der Hintergrundprozess weiter, bis du ihn beendest.

**Admin:** Das Setzen des Power-Limits (NVML) und die PresentMon-ETW-Session brauchen
Administrator-Rechte. Ohne Admin weicht das Tool automatisch auf `nvidia-smi -pl` aus und zeigt
einen Hinweis – auch das benötigt aber Admin.

---

## Mess-Modi (gestaffelt)

Alle Modi sind über denselben Schalter wählbar:

- **Nur Takt** (Default, schneller Lauf): braucht nichts Zusätzliches und findet das Knie schon
  näherungsweise über den effektiven GPU-Takt. Eine externe Last muss laufen, aber keine
  FPS-Quelle. Keine 1%-Lows.
- **PresentMon (FPS)** – Präzisions-Modus: echte Spiele-FPS inkl. zeitgewichteter 1%/0.1%-Lows.
  PresentMon ist gebündelt; nur der **Prozessname** des rendernden Prozesses ist nötig.
- **Compute** (optional, `torch`): erzeugt eine eigene GPU-Last (Matmul-Loop) und misst
  Iterationen/s – kein externer Benchmark nötig.
- **HWiNFO** (optional): zusätzliche/alternative Telemetrie-Quelle (siehe unten).

---

## Benchmark-Last

Während des Sweeps muss eine **konstante, wiederholbare** GPU-Last anliegen. Das Tool kann eine
externe Last selbst starten (Feld „Benchmark-Befehl + Argumente" + Warmup-Zeit) oder du startest
sie manuell (z. B. ein Spiel) und lässt das Feld leer.

- **Empfohlen:** ein loop-fähiger Benchmark wie **Unigine Superposition / Heaven / Valley**
  (laufen als Endlosschleife; Superposition per CLI/Config startbar).
- **3DMark** lässt sich nur in der **Professional Edition** per Kommandozeile (`3DMarkCmd.exe`)
  automatisiert starten – die Steam-/Basic-Version nicht.
- Klassische **Score-am-Ende-Benchmarks** sind ungeeignet (der Sweep braucht ein durchgehendes
  Lastfenster pro Stufe). **FurMark** wird nicht empfohlen (untypische Power-Virus-Last).
- Beim Beenden wird der **gesamte Prozessbaum** des Benchmarks gekillt (Launcher starten den
  eigentlichen Render-Prozess oft als Kind).

---

## Eigene Spiele testen (Knie pro Spiel)

PresentMon filtert per Prozessname auf genau dein Spiel – so ermittelst du das Knie **pro
Spiel** (es ist workload-abhängig). Wichtig:

- Der einzutragende Prozessname ist der **tatsächlich rendernde** Prozess (bei
  Benchmark-Launchern oft ein Kindprozess, nicht der Launcher).
- **FPS-Cap und V-Sync ausschalten** und eine GPU-lastige, reproduzierbare Szene wählen – sonst
  deckelt der Cap die Kurve und das Ergebnis ist keine echte Effizienzkurve.
- Das NVIDIA-App-/GeForce-Overlay hat keine auslesbare API; es nutzt dieselbe ETW-Messtechnik wie
  PresentMon/FrameView. PresentMon ist also die korrekte, gleichwertige Quelle.

---

## Gleichzeitig undervolten (Afterburner & Co.)

Power-Limit (dieses Tool) und Spannungs-/Frequenz-Kurve (Afterburner-Undervolt) sind
**unabhängige Hebel** und dürfen gleichzeitig aktiv sein. Das Tool misst das *tatsächliche*
Verhalten und findet damit das beste Power-Limit **obendrauf** auf einen aktiven Undervolt (mit
Undervolt verschiebt sich das Knie – das Tool findet das neue).

- In Afterburner **nur die V/F-Kurve** formen und den dortigen **Power-Limit-Regler auf
  100 %/Default lassen** – sonst schreiben Afterburner und dieses Tool auf dieselbe Einstellung
  (letzter Schreibzugriff gewinnt). Das Tool soll das Power-Limit allein besitzen.
- Den Undervolt während des gesamten Sweeps **unverändert** lassen (eine Variable pro Messung).
- Crash-sicher bleibt es: ein abgesenktes Power-Limit taktet nur runter; etwaige Instabilität
  käme vom Undervolt selbst, nicht vom Sweep.

---

## HWiNFO-Modus (optional)

- HWiNFO muss laufen und **„Shared Memory Support"** muss in den Einstellungen aktiv sein.
- **Free-Version:** Shared Memory wird nach **12 Stunden** automatisch deaktiviert und muss manuell
  wieder eingeschaltet werden; die Pro-Version hebt das Limit auf.
- **FPS** erscheinen im Shared Memory nur, wenn HWiNFO sie von **RTSS** (RivaTuner Statistics
  Server) bekommt – und meist nur gemittelt, nicht pro Einzelframe. Für saubere, zeitgewichtete
  1%-Lows bleibt **PresentMon** die bessere Quelle; HWiNFO dient primär als zusätzliche
  Telemetrie-Quelle.
- HWiNFO ist **nur lesend** – das Setzen des Power-Limits bleibt immer bei NVML/nvidia-smi.

---

## Bedienung

1. GPU und Mess-Modus wählen, Sweep-Bereich (Start/Ende/Schritt %), Aufwärm- und Messdauer setzen.
2. Toleranzen festlegen (Default: 3 % Ø-FPS, 5 % 1%-Low). Optional eine **absolute FPS-Untergrenze**
   einschalten (z. B. Monitor-Hz) – sie muss nicht genutzt werden.
3. Optional einen Benchmark-Befehl + Warmup eintragen, oder die Last manuell starten.
4. **Sweep starten.** Live-Status, Live-Telemetrie und Chart aktualisieren sich pro Stufe.
   Mit **Stop** jederzeit abbrechen – das Default-Limit wird sofort wiederhergestellt.
5. Ergebnis: Chart (Ø-FPS durchgezogen, 1% Low gestrichelt über gemessenem Verbrauch) mit Markern
   für **FPS/W-Peak**, **Knie** und **Empfehlung**, plus Ergebnis-Tabelle.
6. **Empfehlung anwenden** setzt das empfohlene Limit, **Reset Default** stellt den Default her.
7. **CSV-Export** / **Run speichern/laden** (JSON) – so kannst du pro Spiel einen Run ablegen und
   vergleichen.

### Die drei Betriebspunkte

- **FPS/W-Peak** – der absolut effizienteste Punkt (höchstes Perf/Watt).
- **Knie** – der Punkt des abnehmenden Grenznutzens (Kneedle).
- **Empfehlung** (Default) – das niedrigste Limit, bei dem Ø-FPS- **und** 1%-Low-Verlust innerhalb
  der Toleranzen bleiben und, falls gesetzt, die FPS-Untergrenze gehalten wird.

Ist die FPS-Untergrenze **bindend** (das unbeschränkte Optimum läge tiefer), weist die Empfehlung
ausdrücklich aus, dass dies **nicht der effizienteste Punkt** ist, und **wie viel mehr Ersparnis**
(in W und %) ohne die Untergrenze möglich wäre.

---

## Portabilität – was bleibt liegen?

Ziel: 100 % portabel, Doppelklick, nach dem Schließen keine zurückbleibenden Dateien.

- PresentMon ist **in die EXE gebündelt** (kein Download-Cache, kein Service). PyInstaller entpackt
  es beim Start nach `%TEMP%` und **löscht es beim Beenden** wieder.
- **Kein** NiceGUI-Persistent-Storage (`app.storage.*` würde einen `.nicegui`-Ordner anlegen) – der
  App-Zustand bleibt im Speicher.
- Geschrieben werden **nur** Dateien, die du aktiv exportierst (CSV/JSON), an einen von dir
  gewählten Ort.

Ehrliche Caveats (systembedingt, **keine** Datei-Artefakte):

1. Admin + eine **transiente ETW-Session** für PresentMon (läuft im Speicher, spätestens nach
   Reboot weg; `--stop_existing_session` räumt verwaiste Sessions auf).
2. Die **Power-Limit-Änderung** ist eine System-Einstellung, die beim Beenden/Reboot zurückgesetzt
   wird.
3. Bei einem **harten Absturz** kann der PyInstaller-Temp-Ordner liegen bleiben, bis Windows
   `%TEMP%` aufräumt.

---

## Architektur

Ports & Adapters (Hexagonal). Details und Konventionen siehe [`CLAUDE.md`](CLAUDE.md).

```
src/gpu_efficiency_finder/
├── domain/      # PURE Logik (analysis, sweep) — testbar ohne GPU
├── ports/       # Protocol-Interfaces (GpuBackend, PerfSource, BenchmarkRunner)
├── adapters/    # NVML, nvidia-smi, PresentMon, Compute, ClockProxy, HWiNFO, Benchmark
├── infra/       # PresentMon-Bundle-Pfad, Persistenz (JSON/CSV)
├── ui/          # NiceGUI-Bausteine (config_panel, chart, results_table)
├── app.py       # Koordinator
└── __main__.py  # Einstieg + Composition Root (Browser-Modus)
```

Die Domäne hängt nur an Ports und ist mit Fake-Adaptern vollständig **ohne GPU** testbar
(`pytest`). Adapter sind dünn und kapseln die Außenwelt.
