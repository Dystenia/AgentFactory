# AgentFactory v0.4 – Phase 1 (Entwicklungsbranch)

Dieser Branch erweitert die vorhandene Anwendung. Die bisherige Auftragsverwaltung, der Projektimport und die Prompt-Studio-Funktionen bleiben erhalten.

## Workflow
1. Entwicklungsauftrag in **Entwicklungsaufträge** speichern und optional einem importierten Codeprojekt zuordnen.
2. Im **Prompt Studio** den gespeicherten Auftrag auswählen.
3. **1 · Rückfragen mit KI prüfen**: Vorschau und explizite Anbieterfreigabe bleiben erforderlich. Das KI-Ergebnis wird als Fragenstand gespeichert.
4. Fragen im separaten Textfeld beantworten und **2 · Antworten speichern**.
5. **3 · Finalen Prompt mit KI erstellen**: Gespeicherte Antworten werden in die Anfrage aufgenommen; erneut explizite API-Freigabe.
6. Finalen Text prüfen oder bearbeiten und **4 · Finalen Prompt speichern**.
7. **5 · Auftrag freigeben (READY)** nach zusätzlicher Bestätigung.

Nach einem Neustart werden gespeicherte Fragen, Antworten, der finale Prompt und der Freigabestatus beim Auswählen des Auftrags wiederhergestellt. Eine Änderung des Originalauftrags invalidiert die alte Freigabe beim nächsten Workflow-Zugriff.

## Grenzen dieser Phase
- Keine automatischen Codeänderungen, keine Shell- oder Git-Ausführung, kein Commit.
- Rückfragen sind derzeit Freitext; keine strukturierte Einzel-Fragen-Erkennung und keine automatische fachliche Vollständigkeitsprüfung.
- Der Benutzer ist verantwortlich, vor der Freigabe verbliebene Blocker zu klären. Eine KI-Antwort ist keine technische Freigabe.
- Die große GUI-Neuordnung in drei Spalten ist noch nicht Bestandteil dieser Phase.
- Der Workflow gilt nur für gespeicherte Entwicklungsaufträge; importierte Codeprojekte bleiben davon getrennt.

## Lokale Abnahme unter Windows
Vorher lokale Sicherung/Commit sicherstellen und auf einem sauberen Arbeitsbaum bleiben.
```powershell
cd C:\MVP
git fetch origin
git switch feature/clarification-workflow
.\.venv\Scripts\python.exe -m py_compile main.py job_workflow.py project_analysis.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```
GUI-Abnahme: vorhandene Jobs und importierte Projekte prüfen; einen Testauftrag durch alle fünf Workflow-Schritte führen; App neu starten und Zustand prüfen; Originalauftrag ändern und Freigaberücksetzung kontrollieren. Vor einem späteren Merge zurück nach `main` wechseln.

Tests und GUI-Ausführung wurden bei Veröffentlichung dieses Branches **nicht** auf dem Windows-Zielsystem ausgeführt.
