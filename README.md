# Dystenia Agent Factory v0.3 – Prompt Studio

Bestehende PySide6-App mit Aufträgen, SQLite, Projektinspektor und neuem **Prompt Studio**.

## Installation (Windows)
1. App schließen. Bestehenden Ordner `C:\MVP` und Datenbank `%USERPROFILE%\.dystenia-agent-factory\jobs.sqlite3` sichern.
2. ZIP nach `C:\MVP` entpacken, vorhandene Programmdateien überschreiben. `.venv` und Datenbank nicht löschen.
3. `cd C:\MVP` und `.\.venv\Scripts\python.exe main.py` starten.
4. Im Prompt Studio optional ein importiertes Projekt wählen, Auftrag eingeben, Anbieter/Modell wählen, **Kontext vorbereiten**, Daten prüfen und **ausdrücklich senden**.

## API-Konfiguration
**OpenAI (Standard):** `OPENAI_API_KEY` muss im Prozess-Environment gesetzt sein; der Schlüssel wird nicht in SQLite gespeichert. Beispiel für die **aktuelle PowerShell-Sitzung**:

```powershell
$env:OPENAI_API_KEY = Read-Host 'OpenAI API Key'
.\.venv\Scripts\python.exe main.py
```

Für einen dauerhaften sicheren Workflow Windows Credential Manager später ergänzen. Der hier gezeigte Befehl ist nur für die laufende Sitzung gedacht.

**LM Studio:** lokalen Server aktivieren unter `http://127.0.0.1:1234`, passende geladene Modell-ID eintragen. Nur Loopback-Verbindungen.

## Sicherheitsgrenzen
- Projektanalyse ohne Codeausführung und ohne Schreibzugriff auf importierte Projekte.
- Externe Übertragung nur nach Vorschau und zusätzlicher Bestätigung. **Achtung:** Redaction ist heuristisch und kann Geheimnisse übersehen. Vorschau prüfen, keine vertraulichen Projekte senden.
- Keine automatischen Modellwechsel oder Kosten-Fallbacks; OpenAI-API-Aufrufe können Kosten verursachen.
- Prompt-Ausgaben sind Vorschläge; keine ausführbaren Aktionen oder Sicherheitsfreigaben.
- Noch keine Sandbox, Git-Operationen oder autonome Entwicklung.

## Test
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## v0.3.1 – Modell-Dropdown und Windows-Fenster
- OpenAI-Modell per Dropdown wählen; die Einträge sind eine kuratierte Auswahl und keine Live-Abfrage des Accounts. Die API kann einzelne IDs ablehnen.
- LM Studio bleibt frei editierbar, weil lokale Modellnamen individuell sind.
- Standardmäßige Windows-Fensterdekoration und Maximieren/Minimieren/Wiederherstellen.
- Alle drei Reiter besitzen scrollbare Inhalte, damit kleine Bildschirme und die Taskleiste nicht überdeckt werden.
- Nach Modellwechsel muss die Anfrage erneut vorbereitet und freigegeben werden.

### Windows-Prüfung
1. Anwendung schließen, ZIP in `C:\MVP` entpacken, vorhandene Datenbank und `.venv` behalten.
2. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\PRUEFUNG_WINDOWS.ps1`
3. `\.venv\Scripts\python.exe main.py` (in PowerShell ` .\.venv\Scripts\python.exe main.py`)
4. Fenster maximieren, wiederherstellen, auf kleine Größe ziehen und die Taskleiste prüfen.
5. Prompt Studio: OpenAI-Modell auswählen; LM Studio wählen und eigene Modell-ID eintragen.

Die PySide6-Windows-Oberfläche konnte in der Erstellungsumgebung nicht ausgeführt werden. Die Tests prüfen Python-Logik und Syntax, nicht die Windows-Darstellung.


## v0.3.2 – KI-Projektanalyse und Änderungsplanung

Im Prompt Studio gibt es nun drei Arbeitsmodi: Prompt optimieren, Projekt analysieren, Änderungsplan erstellen. Projektimport und Kontextvorschau bleiben unverändert. Vor jedem API-Aufruf sind Kontextfreigabe und Anbieterbestätigung erforderlich. Die KI schreibt keine Dateien und führt keinen Code aus. Der tatsächliche Windows-GUI-Test und ein Live-API-Test stehen noch aus.


## v0.3.3 – Projektnamen und API-Key
- Beim Import wird ein **Anzeigename** abgefragt; bestehende Namen werden aus SQLite übernommen.
- Im Prompt Studio zeigt das Projekt-Dropdown **nur Namen**; der Pfad bleibt als interne Referenz und Tooltip.
- In „Bestehende Projekte“ markiertes Projekt über „Ausgewähltes Projekt im Prompt Studio verwenden“ direkt übernehmen.
- OpenAI-Key im Prompt Studio als Passwortfeld eingeben; **nur im Arbeitsspeicher dieser Sitzung**, nicht in SQLite oder Konfigurationsdateien. Alternativ weiterhin `OPENAI_API_KEY`.
- Vor jedem Scan und jeder Kontextgenerierung werden kritische Ordner (Laufwerkswurzel, Profilwurzel, Windows- und Systemverzeichnisse) abgelehnt. Das schützt nicht vor jeder möglichen sensiblen Datei in einem ausdrücklich ausgewählten Projekt; die Kontextvorschau ist weiterhin Pflicht.
- Bestehende Projekte bleiben am ursprünglichen Speicherort; es erfolgt kein Verschieben oder Kopieren.


## v0.3.4 – Projekt-Auswahl korrigiert
- „Bestehende Projekte“ hat ein explizites Dropdown für gespeicherte Projektnamen.
- Prompt Studio hat ein Projektnamen-Dropdown; bei vorhandenen Projekten ist standardmäßig das zuletzt importierte ausgewählt.
- Auswahl in Tabelle und Dropdown ist synchron; Übernahme ins Prompt Studio über eigenen Button.
- Projektpfade werden nicht mehr in der Projekttabelle angezeigt, bleiben intern als unveränderte Referenz in SQLite.
- Keine Projektdateien werden verschoben, verändert oder ausgeführt.
- Windows-GUI muss auf dem Zielrechner getestet werden.
