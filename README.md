# Dystenia Agent Factory

Lokale Python/PySide6-Auftragsverwaltung (MVP 0.1.3). Dark Mode, SQLite, Prompt-Bearbeitung und Simulationsmodus; noch keine autonome Codeausführung.

## Lokaler Start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Desktop-Verknüpfung

Mit vorhandener `.venv`, `main.py` und `assets/dystenia_agent_factory.ico` im Projektordner:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop_verknuepfung.ps1
```

Alternativ `DESKTOP_STARTEN.cmd` doppelklicken. Die Verknüpfung startet `pythonw.exe` ohne Konsolenfenster.

**Hinweis:** Der vollständige Anwendungscode und die Icon-Dateien müssen noch aus dem lokalen Projektstand synchronisiert werden. Die SQLite-Datenbank gehört nicht ins Repository.
