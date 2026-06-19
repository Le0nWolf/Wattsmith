# PresentMon-Konsolen-Binary

Hier gehört die **Standalone-Konsolen-EXE** von PresentMon hinein, z. B.
`PresentMon-2.3.0-x64.exe`.

- Quelle: <https://github.com/GameTechDev/PresentMon/releases> (MIT-Lizenz).
- Es ist die **CLI-Variante** und braucht **keinen** installierten PresentMon-Service
  (der Service ist nur für die GUI-/Overlay-Variante). Sie nutzt ETW direkt und benötigt Admin.
- Beim EXE-Build wird die Datei über PyInstaller-`datas` mitgepackt und zur Laufzeit über
  `sys._MEIPASS` gefunden (`infra/presentmon_bundle.py`). PyInstaller entpackt sie beim Start
  in einen Temp-Ordner und **löscht ihn beim Beenden wieder** → es bleibt nichts liegen.

Die `.exe` ist absichtlich **nicht** eingecheckt (siehe `.gitignore`), da Binärdateien nicht ins
Repo gehören. Lade sie einmalig herunter und lege sie hier ab, bevor du die EXE baust oder den
PresentMon-Modus im Dev-Betrieb nutzt.
