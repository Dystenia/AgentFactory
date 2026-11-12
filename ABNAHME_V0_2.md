# Dystenia Agent Factory v0.2 – Windows-Abnahme

## Automatische Prüfung

Im Projektordner `C:\MVP` (dort, wo `main.py` liegt):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\PRUEFUNG_WINDOWS.ps1
```

Das Skript prüft PySide6, Python-Syntax und den Scanner. Es führt **keinen Code aus importierten Projekten** aus.

## Manuelle GUI-Abnahme

- [ ] `main.py` startet mit dunkler Oberfläche und App-Icon.
- [ ] Bereits gespeicherte Aufträge sind noch vorhanden.
- [ ] Doppelklick auf Auftrag lädt den Prompt; Änderung und Speicherung funktionieren.
- [ ] Frühere Prompt-Version ist im Verlauf sichtbar.
- [ ] Reiter „Bestehende Projekte“ ist sichtbar.
- [ ] Eigenen, kleinen Python-Projektordner auswählen und analysieren.
- [ ] Bericht zeigt Einstiegspunkte, Dateizahl und erkannte Abhängigkeiten.
- [ ] Projekt erneut scannen: kein doppelter Eintrag.
- [ ] „Entwicklungsauftrag vorbereiten“ übernimmt Projektpfad und öffnet den Auftrag.
- [ ] Originalprojekt ist nach dem Scan unverändert.
- [ ] Desktopverknüpfung startet die GUI.

## Grenzen

- Nur **lokale Ordner**, kein ZIP-Import oder GitHub-Import in v0.2.
- Statische Bestandsaufnahme, keine vollständige Code- oder Sicherheitsanalyse.
- Noch keine KI-API, keine autonome Codeausführung, keine Testausführung fremder Projekte.
- GUI und SQLite-Migration auf Windows müssen lokal abgenommen werden.

## Fehler melden

Bei Fehlern die vollständige PowerShell-Ausgabe und einen Screenshot der GUI senden; keine API-Schlüssel oder privaten Projektdateien veröffentlichen.
