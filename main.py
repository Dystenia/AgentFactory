"""Dystenia Agent Factory: local, simulation-only MVP."""
import sqlite3
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import json
from project_inspector import inspect_project, report_text
from prompt_context import collect_context, build_request, SYSTEM_PROMPT
from model_router import generate, list_openai_models, ModelError
from cost_budget import price_record, check_budget, estimated_cost, money, BudgetError
from project_analysis import MODES, system_prompt_for
from project_access import validate_project_root
import job_workflow
from git_preflight import git_preflight, format_preflight
from controlled_edit import preview as preview_edit, apply as apply_edit, EditRejected
import hashlib
import difflib
from ai_proposal import parse_proposal, ProposalError
from project_proposal import parse_project_proposal, ProjectProposalError
from project_apply import apply_project_proposal
from emergency_control import emergency
from PySide6.QtCore import QThread, Signal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget, QFileDialog, QTabWidget, QScrollArea, QSizePolicy, QInputDialog, QStackedWidget, QHeaderView)

APP_DIR = Path(__file__).resolve().parent
ICON_PATH = APP_DIR / "assets" / "dystenia_agent_factory.ico"

# Curated model IDs: availability depends on the user's API account.
OPENAI_MODELS = ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra", "gpt-5.6-sol", "gpt-5", "gpt-4.1-mini"]

DB = Path.home() / ".dystenia-agent-factory" / "jobs.sqlite3"


DARK_QSS = """
QWidget { background-color: #12151c; color: #e6edf3; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background-color: #12151c; }
QLabel { background: transparent; }
QLineEdit, QTextEdit, QComboBox, QTableWidget {
    background-color: #1d2430; color: #e6edf3;
    border: 1px solid #344154; border-radius: 6px; padding: 7px;
    selection-background-color: #155e75; selection-color: white;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #00d4ff; }
QLineEdit::placeholder, QTextEdit::placeholder { color: #8998ab; }
QComboBox { padding-right: 22px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background-color: #1d2430; color: #e6edf3; selection-background-color: #155e75; }
QPushButton { background-color: #253246; color: #e6edf3; border: 1px solid #3c4b60;
    border-radius: 6px; padding: 10px 14px; font-weight: 600; }
QPushButton:hover { background-color: #31445d; border-color: #00d4ff; }
QPushButton:pressed { background-color: #155e75; }
QPushButton#primaryButton { background-color: #164e63; border-color: #0891b2; color: #ffffff; }
QPushButton#primaryButton:hover { background-color: #0e7490; }
QTableWidget { gridline-color: #303b4d; alternate-background-color: #18202b; padding: 0px; }
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background-color: #155e75; color: white; }
QHeaderView::section { background-color: #253246; color: #e6edf3; border: none;
    border-right: 1px solid #344154; border-bottom: 1px solid #344154; padding: 8px; }
QTableCornerButton::section { background-color: #253246; border: none; }
QScrollBar:vertical { background: #12151c; width: 12px; }
QScrollBar::handle:vertical { background: #435269; border-radius: 5px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #12151c; }
"""


def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#12151c"))
    palette.setColor(QPalette.WindowText, QColor("#e6edf3"))
    palette.setColor(QPalette.Base, QColor("#1d2430"))
    palette.setColor(QPalette.AlternateBase, QColor("#18202b"))
    palette.setColor(QPalette.Text, QColor("#e6edf3"))
    palette.setColor(QPalette.Button, QColor("#253246"))
    palette.setColor(QPalette.ButtonText, QColor("#e6edf3"))
    palette.setColor(QPalette.Highlight, QColor("#155e75"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor("#8998ab"))
    app.setPalette(palette)
    app.setStyleSheet(DARK_QSS)


def connect_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL,
        description TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS job_revisions (
        revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        saved_at TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS imported_projects (
        id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, root TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL, report_json TEXT NOT NULL
    )""")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "project_root" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN project_root TEXT")
    job_workflow.migrate(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS project_proposals (
        job_id TEXT PRIMARY KEY, project_root TEXT NOT NULL,
        commit_sha TEXT NOT NULL, proposal_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS api_spend (
        id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
        cost_usd TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


class PromptWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, provider, model, payload, mode, api_key, max_output_tokens):
        super().__init__()
        self.provider, self.model, self.payload, self.mode, self.api_key = provider, model, payload, mode, api_key
        self.max_output_tokens = max_output_tokens

    def run(self):
        try:
            self.succeeded.emit(generate(self.provider, self.model, system_prompt_for(self.mode), self.payload, api_key=self.api_key, max_output_tokens=self.max_output_tokens, return_usage=True))
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, ModelError) else "Unerwarteter Anbieterfehler.")


class ProposalWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, provider, model, payload, api_key, budget):
        super().__init__()
        self.provider, self.model, self.payload = provider, model, payload
        self.api_key, self.budget = api_key, budget

    def run(self):
        try:
            result = generate(self.provider, self.model,
                "Du bist ein Python-Entwickler. Antworte ausschließlich mit einem JSON-Objekt "
                "mit exakt den Feldern path, content und summary. content ist der vollständige "
                "neue Dateiinhalt, keine Diffs oder Markdown. Bearbeite nur die angegebene Datei. "
                "Wenn du die Änderung nicht sicher vornehmen kannst, melde den Grund in summary "
                "und lasse content unverändert.",
                self.payload, api_key=self.api_key, max_output_tokens=self.budget, return_usage=True)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, ModelError) else "KI-Anfrage fehlgeschlagen.")


class ProjectGenerationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, provider, model, payload, api_key, budget):
        super().__init__()
        self.provider, self.model, self.payload = provider, model, payload
        self.api_key, self.budget = api_key, budget

    def run(self):
        try:
            result = generate(
                self.provider, self.model,
                "Du entwickelst ein Python-Webprojekt. Gib AUSSCHLIESSLICH ein JSON-Objekt "
                "mit exakt summary (String) und files (Liste) zurück. "
                "Jede Datei hat exakt path (relativer POSIX-Pfad) und content (vollständiger UTF-8-Text). "
                "Maximal 12 Dateien. Keine Markdown-Codeblöcke. Keine geheimen Schlüssel. "
                "Keine erfundenen Steuersätze oder Versicherungsbeiträge. "
                "Phase A: lauffähige FastAPI-Weboberfläche, Eingabevalidierung, Datenmodelle, "
                "README und Tests; Steuerberechnung nur als explizit nicht implementiert kennzeichnen. "
                "Die Rentenversicherungspflicht bei Selbstständigen wird vom Benutzer gesetzt, "
                "nicht rechtlich automatisch festgestellt.",
                self.payload, api_key=self.api_key, max_output_tokens=self.budget, return_usage=True
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, ModelError) else "Projektgenerierung fehlgeschlagen.")


class ModelListWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key

    def run(self):
        try:
            self.succeeded.emit(list_openai_models(api_key=self.api_key))
        except ModelError as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = connect_db()
        self.setWindowTitle("Dystenia Agent Factory · MVP 0.4.0-dev")
        self.editing_job_id = None
        self.workflow_request = None
        self.emergency_stop = False
        self.stop_generation = 0
        self.pending_cost = None
        self.cost_unverified = False
        # Native decorated Windows window; keep it inside the usable desktop area.
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(560, 400)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1020, max(560, available.width() - 80)),
                    min(760, max(400, available.height() - 80)))
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)
        heading = QLabel("DYSTENIA AGENT FACTORY")
        heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #00d4ff;")
        header = QHBoxLayout()
        header.addWidget(heading, 1)
        self.hard_stop_button = QPushButton("⛔  NOT-AUS")
        self.hard_stop_button.setToolTip(
            "SOFORTSTOPP: Beendet den AgentFactory-Prozess ohne Rückfrage oder Speichern. "
            "Alle lokalen Netzwerkverbindungen werden getrennt; ungespeicherte Daten gehen verloren."
        )
        self.hard_stop_button.setMinimumHeight(48)
        self.hard_stop_button.setMinimumWidth(160)
        self.hard_stop_button.setStyleSheet(
            "QPushButton { background-color: #b91c1c; color: white; "
            "border: 2px solid #f87171; border-radius: 7px; "
            "font-size: 16px; font-weight: 800; padding: 8px 16px; } "
            "QPushButton:hover { background-color: #dc2626; } "
            "QPushButton:pressed { background-color: #7f1d1d; }"
        )
        self.hard_stop_button.clicked.connect(self.hard_emergency_stop)
        header.addWidget(self.hard_stop_button)
        layout.addLayout(header)
        self.hard_stop_shortcut = QShortcut(QKeySequence("Ctrl+Shift+X"), self)
        self.hard_stop_shortcut.activated.connect(self.hard_emergency_stop)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. Log Analyzer")
        form.addRow("Projektname", self.name)
        self.kind = QComboBox()
        self.kind.addItems(["Neues Projekt", "Bestehendes Projekt (Planung)"])
        form.addRow("Auftragstyp", self.kind)
        self.job_project = QComboBox()
        self.job_project.addItem("Kein importiertes Codeprojekt", "")
        form.addRow("Zugeordnetes Codeprojekt", self.job_project)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Was soll entwickelt werden?")
        form.addRow("Anforderungen", self.description)
        tabs = QTabWidget()
        new_tab = QWidget()
        new_layout = QVBoxLayout(new_tab)
        new_layout.addLayout(form)
        tabs.addTab(self.scroll_tab(new_tab), "Entwicklungsaufträge")
        self.tabs = tabs
        self.edit_label = QLabel("NEUER AUFTRAG")
        self.edit_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        new_layout.addWidget(self.edit_label)
        controls = QHBoxLayout()
        self.save_button = QPushButton("Neuen Auftrag speichern")
        create = self.save_button
        create.setObjectName("primaryButton")
        create.clicked.connect(self.save_job)
        controls.addWidget(create)
        reset = QPushButton("Neuer Auftrag / Abbrechen")
        reset.clicked.connect(self.clear_editor)
        controls.addWidget(reset)
        simulate = QPushButton("Ausgewählten Auftrag simulieren")
        simulate.clicked.connect(self.simulate_job)
        controls.addWidget(simulate)
        new_layout.addLayout(controls)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Projekt", "Typ", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.load_job)
        new_layout.addWidget(self.table)
        history = QPushButton("Prompt-Verlauf anzeigen")
        history.clicked.connect(self.show_history)
        new_layout.addWidget(history)
        footer = QLabel("SIMULATIONSMODUS  ·  Keine KI-Aufrufe, Codeausführung oder GitHub-Schreibzugriffe")
        footer.setStyleSheet("color: #94a3b8; font-size: 11px;")
        new_layout.addWidget(footer)
        self.import_tab = QWidget()
        import_layout = QVBoxLayout(self.import_tab)
        import_layout.addWidget(QLabel("Bestehendes Projekt lokal auswählen und ohne Codeausführung analysieren"))
        import_controls = QHBoxLayout()
        self.project_path = QLineEdit()
        self.project_path.setReadOnly(True)
        import_controls.addWidget(self.project_path)
        browse = QPushButton("Ordner auswählen")
        browse.clicked.connect(self.choose_project)
        import_controls.addWidget(browse)
        import_layout.addLayout(import_controls)
        scan = QPushButton("Projekt prüfen und speichern")
        scan.setObjectName("primaryButton")
        scan.clicked.connect(self.scan_project)
        import_layout.addWidget(scan)
        import_layout.addWidget(QLabel("Gespeicherte Codeprojekte (nicht Entwicklungsaufträge)"))
        import_layout.addWidget(QLabel("Hier erscheinen importierte lokale Projektordner. Entwicklungsaufträge findest du im ersten Reiter."))
        self.import_project = QComboBox()
        self.import_project.setMinimumWidth(240)
        self.import_project.currentIndexChanged.connect(self.select_imported_project)
        import_layout.addWidget(self.import_project)
        self.imported_table = QTableWidget(0, 2)
        self.imported_table.setHorizontalHeaderLabels(["Projektname", "Projekt-ID"])
        self.imported_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.imported_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.imported_table.setWordWrap(True)
        self.imported_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.imported_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.imported_table.cellClicked.connect(self.show_imported_report)
        self.imported_table.itemSelectionChanged.connect(self.sync_imported_selection)
        import_layout.addWidget(self.imported_table)
        self.project_report = QTextEdit()
        self.project_report.setReadOnly(True)
        import_layout.addWidget(self.project_report)
        prepare = QPushButton("Entwicklungsauftrag für ausgewähltes Projekt vorbereiten")
        prepare.clicked.connect(self.prepare_existing_job)
        import_layout.addWidget(prepare)
        use_in_prompt = QPushButton("Ausgewähltes Projekt im Prompt Studio verwenden")
        use_in_prompt.clicked.connect(self.use_selected_project_in_prompt)
        import_layout.addWidget(use_in_prompt)
        existing_tab = QWidget()
        existing_layout = QVBoxLayout(existing_tab)
        existing_layout.addWidget(QLabel("Gespeicherte Entwicklungsaufträge (aus der Auftragsdatenbank)"))
        self.existing_job = QComboBox()
        self.existing_job.currentIndexChanged.connect(self.show_existing_job)
        existing_layout.addWidget(self.existing_job)
        self.existing_job_details = QTextEdit()
        self.existing_job_details.setReadOnly(True)
        existing_layout.addWidget(self.existing_job_details)
        open_existing = QPushButton("Ausgewählten Auftrag im Prompt Studio öffnen")
        open_existing.setObjectName("primaryButton")
        open_existing.clicked.connect(self.open_existing_job)
        existing_layout.addWidget(open_existing)
        reload_existing = QPushButton("Auftragsliste aktualisieren")
        reload_existing.clicked.connect(self.refresh_existing_jobs)
        existing_layout.addWidget(reload_existing)
        tabs.addTab(self.scroll_tab(existing_tab), "Bestehende Aufträge")
        tabs.addTab(self.scroll_tab(self.import_tab), "Bestehende Projekte")
        prompt_tab = QWidget()
        self.prompt_tab = prompt_tab
        prompt_root = QVBoxLayout(prompt_tab)
        prompt_root.addWidget(QLabel("Entwicklungsassistent · Idee → Prüfung → Rückfragen → Antworten → Arbeiten"))
        self.workflow_pages = QStackedWidget()
        self.workflow_step_buttons = []
        step_bar = QHBoxLayout()
        for step, label in enumerate(("Idee", "Prüfung", "Rückfragen", "Antworten", "Arbeiten")):
            button = QPushButton(f"{step + 1} · {label}")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, index=step: self.show_workflow_step(index))
            self.workflow_step_buttons.append(button)
            step_bar.addWidget(button)
        prompt_root.addLayout(step_bar)
        prompt_root.addWidget(self.workflow_pages, 1)

        def new_step():
            page = QWidget()
            page_layout = QVBoxLayout(page)
            self.workflow_pages.addWidget(self.scroll_tab(page))
            return page_layout

        prompt_layout = new_step()
        prompt_layout.addWidget(QLabel("1 · Idee und Projekt auswählen"))
        self.prompt_project = QComboBox()
        self.prompt_project.setMinimumWidth(240)
        self.prompt_project.setMaxVisibleItems(15)
        self.prompt_project.currentIndexChanged.connect(self.invalidate_prompt_preview)
        prompt_layout.addWidget(QLabel("Gespeicherten Entwicklungsauftrag auswählen"))
        self.prompt_job = QComboBox()
        self.prompt_job.addItem("Kein Auftrag ausgewählt", "")
        self.prompt_job.currentIndexChanged.connect(self.select_prompt_job)
        prompt_layout.addWidget(self.prompt_job)
        prompt_layout.addWidget(QLabel("Importiertes Codeprojekt (optional)"))
        prompt_layout.addWidget(self.prompt_project)
        reload_projects = QPushButton("Projektliste aktualisieren")
        reload_projects.clicked.connect(self.refresh_prompt_projects)
        prompt_layout.addWidget(reload_projects)
        bind_project = QPushButton("Projekt dem ausgewählten Auftrag verbindlich zuordnen")
        bind_project.clicked.connect(self.bind_selected_project)
        prompt_layout.addWidget(bind_project)
        open_projects = QPushButton("Codeprojekt importieren / auswählen")
        open_projects.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        prompt_layout.addWidget(open_projects)
        prompt_layout.addWidget(QLabel("Projektzuordnung ist erst nach dem Speichern verbindlich. Änderungen widerrufen READY."))
        prompt_layout.addWidget(QLabel("KI-Arbeitsmodus"))
        self.prompt_mode = QComboBox()
        self.prompt_mode.addItems(list(MODES))
        self.prompt_mode.currentTextChanged.connect(self.invalidate_prompt_preview)
        prompt_layout.addWidget(self.prompt_mode)
        self.prompt_task = QTextEdit()
        self.prompt_task.textChanged.connect(self.invalidate_prompt_preview)
        self.prompt_task.setPlaceholderText("Welche Änderung oder Untersuchung wünschst du?")
        prompt_layout.addWidget(QLabel("Dein Originalauftrag"))
        prompt_layout.addWidget(self.prompt_task)
        self.prompt_provider = QComboBox()
        self.prompt_provider.addItems(["OpenAI", "LM Studio (lokal)"])
        self.prompt_provider.currentTextChanged.connect(self.provider_changed)
        self.prompt_model = QComboBox()
        self.prompt_model.setEditable(False)
        self.prompt_model.addItems(OPENAI_MODELS)
        self.prompt_model.setCurrentText("gpt-6-luna")
        self.prompt_model.currentTextChanged.connect(self.invalidate_prompt_preview)
        refresh_models = QPushButton("Verfügbare OpenAI-Modelle abrufen")
        refresh_models.clicked.connect(self.refresh_openai_models)
        self.output_budget = QComboBox()
        self.output_budget.addItems(["4096", "8192", "12000", "16000", "24000", "32000", "65536"])
        self.output_budget.setCurrentText("12000")
        self.output_budget.currentTextChanged.connect(self.invalidate_prompt_preview)
        self.usd_limit = QLineEdit("5.00")
        self.usd_limit.setPlaceholderText("USD-Budget, z. B. 5.00")
        self.usd_input_price = QLineEdit()
        self.usd_input_price.setPlaceholderText("USD pro 1 Mio. Input-Tokens (verifiziert)")
        self.usd_output_price = QLineEdit()
        self.usd_output_price.setPlaceholderText("USD pro 1 Mio. Output-Tokens (verifiziert)")
        self.usd_price_date = QLineEdit()
        self.usd_price_date.setPlaceholderText("Preisstand YYYY-MM-DD")
        self.usd_status = QLabel("USD-Kostenkontrolle: Preise eintragen, bevor OpenAI verwendet wird.")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("OpenAI API-Key (nur für diese Sitzung; nicht gespeichert)")
        self.api_key.textChanged.connect(self.invalidate_prompt_preview)
        prompt_layout.addStretch()
        prompt_layout = new_step()
        prompt_layout.addWidget(QLabel("2 · Idee und KI-Kontext prüfen"))
        self.context_preview = QTextEdit()
        self.context_preview.setReadOnly(True)
        prompt_layout.addWidget(QLabel("Vorschau der Daten, die an den Anbieter gesendet werden"))
        prompt_layout.addWidget(self.context_preview)
        preview_button = QPushButton("Kontext und Anfrage vorbereiten")
        preview_button.clicked.connect(self.prepare_prompt)
        prompt_layout.addWidget(preview_button)
        self.send_button = QPushButton("Anfrage ausdrücklich freigeben und senden")
        self.send_button.setObjectName("primaryButton")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_prompt)
        prompt_layout.addWidget(self.send_button)
        self.prompt_result = QTextEdit()
        self.prompt_result.setReadOnly(True)
        prompt_layout.addWidget(QLabel("KI-Ergebnis (nur Vorschlag, keine Ausführung)"))
        prompt_layout.addWidget(self.prompt_result)
        prompt_layout.addStretch()
        prompt_layout = new_step()
        prompt_layout.addWidget(QLabel("3 · Rückfragen der KI prüfen"))
        prompt_layout.addWidget(QLabel("Anforderungsklärung · Fragen getrennt vom finalen Prompt"))
        self.clarification_questions = QTextEdit()
        self.clarification_questions.setReadOnly(True)
        self.clarification_questions.setPlaceholderText("Hier erscheinen die von der KI erkannten Rückfragen.")
        prompt_layout.addWidget(self.clarification_questions)
        self.clarification_answers = QTextEdit()
        self.clarification_answers.setPlaceholderText("Antworten zu den Fragen; bei keinen Rückfragen ausdrücklich 'Keine Rückfragen' eintragen.")
        prompt_layout.addWidget(self.clarification_answers)
        clarify_actions = QHBoxLayout()
        check_questions = QPushButton("1 · Rückfragen mit KI prüfen")
        check_questions.clicked.connect(self.request_clarification)
        clarify_actions.addWidget(check_questions)
        save_answers = QPushButton("2 · Antworten speichern")
        save_answers.clicked.connect(self.store_clarification_answers)
        clarify_actions.addWidget(save_answers)
        prompt_layout.addLayout(clarify_actions)
        prompt_layout.addStretch()
        prompt_layout = new_step()
        prompt_layout.addWidget(QLabel("4 · Antworten auswerten und finalen Auftrag freigeben"))
        self.final_prompt = QTextEdit()
        self.final_prompt.setPlaceholderText("Finaler Auftrag: KI-Vorschlag prüfen und bei Bedarf bearbeiten.")
        prompt_layout.addWidget(QLabel("Finaler Entwicklungsauftrag · vor Freigabe editierbar"))
        prompt_layout.addWidget(self.final_prompt)
        final_actions = QHBoxLayout()
        make_final = QPushButton("3 · Finalen Prompt mit KI erstellen")
        make_final.clicked.connect(self.request_final_prompt)
        final_actions.addWidget(make_final)
        save_final = QPushButton("4 · Finalen Prompt speichern")
        save_final.clicked.connect(self.store_final_prompt)
        final_actions.addWidget(save_final)
        approve_final = QPushButton("5 · Auftrag freigeben (READY)")
        approve_final.clicked.connect(self.approve_final_prompt)
        final_actions.addWidget(approve_final)
        prompt_layout.addLayout(final_actions)
        self.workflow_status = QLabel("Workflow: Bitte gespeicherten Auftrag auswählen")
        prompt_layout.addWidget(self.workflow_status)
        prompt_layout.addStretch()
        prompt_layout = new_step()
        prompt_layout.addWidget(QLabel("5 · Arbeiten · Änderungen prüfen und freigeben"))
        prompt_layout.addWidget(QLabel("Git-Projektprüfung (nur lesend)"))
        self.git_preflight_button = QPushButton("6 · Freigegebenes Projekt und Git-Status prüfen")
        self.git_preflight_button.clicked.connect(self.check_approved_project)
        prompt_layout.addWidget(self.git_preflight_button)
        self.git_preflight_result = QTextEdit()
        self.git_preflight_result.setReadOnly(True)
        self.git_preflight_result.setMinimumHeight(160)
        self.git_preflight_result.setPlaceholderText("Ein READY-Auftrag mit gespeichertem Git-Projekt ist erforderlich.")
        prompt_layout.addWidget(self.git_preflight_result)
        prompt_layout.addWidget(QLabel("Phase A · Neues Programm als vollständigen Projektvorschlag erzeugen"))
        phase_a_info = QLabel(
            "Kein Dateipfad erforderlich. Der Agent plant die Dateien selbst. "
            "Voraussetzung: freigegebener Auftrag (READY) und zugeordnetes sauberes Git-Projekt."
        )
        phase_a_info.setWordWrap(True)
        prompt_layout.addWidget(phase_a_info)
        self.project_generate_button = QPushButton("Projektdateien mit KI vorbereiten")
        self.project_generate_button.clicked.connect(self.request_project_generation)
        prompt_layout.addWidget(self.project_generate_button)
        self.project_generation_preview = QTextEdit()
        self.project_generation_preview.setReadOnly(True)
        self.project_generation_preview.setPlaceholderText("Der geprüfte Projektvorschlag wird gespeichert. Hier siehst du eine kurze Übersicht.")
        self.project_generation_preview.setMinimumHeight(200)
        prompt_layout.addWidget(self.project_generation_preview)
        self.project_apply_button = QPushButton("Geprüften Projektvorschlag in Git-Arbeitsordner schreiben")
        self.project_apply_button.setEnabled(False)
        self.project_apply_button.clicked.connect(self.apply_generated_project)
        prompt_layout.addWidget(self.project_apply_button)
        self.validated_project_proposal = None
        self.single_file_section = QWidget()
        single_file_layout = QVBoxLayout(self.single_file_section)
        single_file_layout.setContentsMargins(0, 8, 0, 0)
        single_file_layout.addWidget(QLabel("Optional · Einzelne vorhandene Datei bearbeiten"))
        self.edit_relative_path = QLineEdit()
        self.edit_relative_path.setPlaceholderText("Relativer Pfad einer vorhandenen Textdatei, z. B. README.md")
        single_file_layout.addWidget(self.edit_relative_path)
        self.edit_replacement = QTextEdit()
        self.edit_replacement.setPlaceholderText("Vollständiger neuer UTF-8-Dateiinhalt")
        single_file_layout.addWidget(self.edit_replacement)
        edit_buttons = QHBoxLayout()
        preview_button = QPushButton("7 · Änderung als Diff prüfen")
        preview_button.clicked.connect(self.preview_approved_edit)
        edit_buttons.addWidget(preview_button)
        apply_button = QPushButton("8 · Geprüfte Änderung ausführen")
        apply_button.clicked.connect(self.apply_approved_edit)
        edit_buttons.addWidget(apply_button)
        single_file_layout.addLayout(edit_buttons)
        self.edit_diff = QTextEdit()
        self.edit_diff.setReadOnly(True)
        self.edit_diff.setMinimumHeight(180)
        single_file_layout.addWidget(self.edit_diff)
        self.edit_approval_snapshot = None
        self.proposal_context = None
        self.proposal_button = QPushButton("KI-Änderung für diese Datei vorschlagen")
        self.proposal_button.clicked.connect(self.request_ai_edit)
        single_file_layout.addWidget(self.proposal_button)
        self.single_file_section.setVisible(False)
        toggle_single_file = QPushButton("Erweitert: Einzeldatei-Bearbeitung einblenden")
        toggle_single_file.setCheckable(True)
        toggle_single_file.toggled.connect(self.single_file_section.setVisible)
        prompt_layout.addWidget(toggle_single_file)
        prompt_layout.addWidget(self.single_file_section)
        prompt_layout.addStretch()
        self.show_workflow_step(0)
        self.prompt_tab_index = tabs.addTab(prompt_tab, "Entwicklungsassistent")
        system_page = QWidget()
        system_layout = QVBoxLayout(system_page)
        system_layout.setContentsMargins(12, 12, 12, 12)
        system_layout.setSpacing(8)

        def system_label(text):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            system_layout.addWidget(label)
            return label

        system_label("System · KI-Konfiguration (nur während dieser Sitzung)")
        system_label("API-Schlüssel bleibt ausschließlich im Arbeitsspeicher; kein Speichern in SQLite.")
        system_label("KI-Anbieter")
        system_layout.addWidget(self.prompt_provider)
        system_label("Modell")
        system_layout.addWidget(self.prompt_model)
        system_layout.addWidget(refresh_models)
        system_label("Maximale Ausgabe-Tokens")
        system_layout.addWidget(self.output_budget)
        system_label("USD-Budget (global, bereits verbrauchte Kosten werden aus SQLite geladen)")
        system_layout.addWidget(self.usd_limit)
        system_label("Verifizierte Modellpreise – Input und Output jeweils USD / 1 Mio. Tokens")
        system_layout.addWidget(self.usd_input_price)
        system_layout.addWidget(self.usd_output_price)
        system_layout.addWidget(self.usd_price_date)
        system_layout.addWidget(self.usd_status)
        system_label("OpenAI API-Schlüssel")
        system_layout.addWidget(self.api_key)
        system_label("KI-Sperre · blockiert neue KI-Anfragen und Dateischreibvorgänge")
        self.kill_switch = QPushButton("KI-SPERRE AKTIVIEREN")
        self.kill_switch.setCheckable(True)
        self.kill_switch.clicked.connect(self.toggle_emergency_stop)
        system_layout.addWidget(self.kill_switch)
        self.kill_status = QLabel("Status: bereit")
        system_layout.addWidget(self.kill_status)
        system_label("Harter NOT-AUS: roter Button oben rechts, jederzeit erreichbar (Strg+Umschalt+X). "
                     "Beendet die Anwendung ohne Rückfrage; ungespeicherte Änderungen gehen verloren.")
        system_label(
            "Laufende Netzwerkaufrufe können nicht garantiert abgebrochen werden; "
            "deren Ergebnisse werden nach Not-Aus verworfen. Keine automatische Dateiausführung."
        )
        system_layout.addStretch()
        for control in (self.prompt_provider, self.prompt_model, self.output_budget,
                        self.api_key, refresh_models, self.kill_switch):
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tabs.addTab(self.scroll_tab(system_page, horizontal=False), "System")
        # Navigation uses the existing tab pages, preserving their widgets and signals.
        self.nav_expanded = True
        self.nav_panel = QWidget()
        self.nav_panel.setObjectName("navigationPanel")
        self.nav_panel.setFixedWidth(215)
        self.nav_layout = QVBoxLayout(self.nav_panel)
        self.nav_layout.setContentsMargins(6, 8, 6, 8)
        self.nav_layout.setSpacing(6)
        self.nav_toggle = QPushButton("☰  Menü einklappen")
        self.nav_toggle.setToolTip("Seitennavigation ein- oder ausklappen")
        self.nav_toggle.clicked.connect(self.toggle_navigation)
        self.nav_layout.addWidget(self.nav_toggle)
        self.nav_buttons = []
        navigation = [
            ("▤", "1 · Auftrag erstellen"),
            ("≡", "2 · Auftrag auswählen"),
            ("▣", "3 · Projekt zuordnen"),
            ("⌘", "4 · KI-Entwicklung"),
            ("⚙", "Einstellungen"),
        ]
        for index, (symbol, label) in enumerate(navigation):
            button = QPushButton(symbol + "  " + label)
            button.setToolTip(label)
            button.setCheckable(True)
            button.setProperty("navSymbol", symbol)
            button.setProperty("navLabel", label)
            button.clicked.connect(lambda checked=False, page=index: self.tabs.setCurrentIndex(page))
            self.nav_layout.addWidget(button)
            self.nav_buttons.append(button)
        # Direct access to the five workflow phases without changing their state.
        self.workflow_nav_buttons = []
        for step, title in enumerate(("Idee", "Prüfung", "Rückfragen", "Antworten", "Arbeiten")):
            button = QPushButton(f"    {step + 1} · {title}")
            button.setToolTip(f"KI-Entwicklung: {title}")
            button.setObjectName("workflowNavigation")
            button.clicked.connect(lambda checked=False, phase=step: self.open_workflow_phase(phase))
            self.nav_layout.addWidget(button)
            self.workflow_nav_buttons.append(button)
        self.nav_layout.addStretch()
        tabs.tabBar().hide()
        tabs.currentChanged.connect(self.update_navigation_selection)
        workspace = QHBoxLayout()
        workspace.setSpacing(10)
        workspace.addWidget(self.nav_panel)
        workspace.addWidget(tabs, 1)
        layout.addLayout(workspace, 1)
        self.setCentralWidget(root)
        self.update_navigation_selection(tabs.currentIndex())
        self.refresh_imports()
        self.refresh_prompt_projects()
        self.refresh()
        self.refresh_prompt_jobs()
        self.refresh_existing_jobs()

    def hard_emergency_stop(self):
        """Latch all local actions, terminate registered child trees, then exit."""
        emergency.stop()
        os._exit(137)

    def toggle_emergency_stop(self, checked):
        self.emergency_stop = bool(checked)
        self.kill_switch.setText("KI-SPERRE AUFHEBEN" if checked else "KI-SPERRE AKTIVIEREN")
        self.kill_switch.setStyleSheet(
            "background-color: #991b1b; color: white;" if checked else ""
        )
        self.kill_status.setText(
            "Status: GESPERRT – keine KI-Anfragen oder Dateischreibvorgänge"
            if checked else "Status: bereit"
        )
        if checked:
            self.stop_generation += 1
            self.workflow_request = None
            self.proposal_context = None
            self.edit_approval_snapshot = None
            self.edit_diff.clear()
            self.send_button.setEnabled(False)
            self.proposal_button.setEnabled(False)
        else:
            self.proposal_button.setEnabled(True)
            self.invalidate_prompt_preview()

    def ensure_running(self):
        emergency.check()
        if self.emergency_stop:
            raise ValueError("NOT-AUS ist aktiv. Aktion gesperrt; unter System aufheben.")

    def show_workflow_step(self, index):
        self.workflow_pages.setCurrentIndex(index)
        for step, button in enumerate(getattr(self, "workflow_nav_buttons", ())):
            button.setStyleSheet(
                "QPushButton { text-align: left; background-color: #164e63; border-color: #0891b2; }"
                if step == index else "QPushButton { text-align: left; }"
            )
        for step, button in enumerate(self.workflow_step_buttons):
            button.setChecked(step == index)
            button.setStyleSheet(
                "QPushButton { background-color: #164e63; border-color: #0891b2; }"
                if step == index else ""
            )

    def open_workflow_phase(self, phase):
        """Open a workflow phase while retaining the current job and project."""
        self.tabs.setCurrentIndex(self.prompt_tab_index)
        self.show_workflow_step(phase)

    def toggle_navigation(self):
        self.nav_expanded = not self.nav_expanded
        self.nav_panel.setFixedWidth(215 if self.nav_expanded else 54)
        self.nav_toggle.setText("☰  Menü einklappen" if self.nav_expanded else "☰")
        for button in self.nav_buttons:
            symbol = button.property("navSymbol")
            label = button.property("navLabel")
            button.setText(symbol + "  " + label if self.nav_expanded else symbol)
        for button in self.workflow_nav_buttons:
            button.setVisible(self.nav_expanded)

    def update_navigation_selection(self, index):
        for page, button in enumerate(self.nav_buttons):
            button.setChecked(page == index)
            button.setStyleSheet(
                "QPushButton { text-align: left; background-color: #164e63; border-color: #0891b2; }"
                if page == index else "QPushButton { text-align: left; }"
            )

    @staticmethod
    def scroll_tab(widget, horizontal=True):
        """Scroll vertically; responsive pages never scroll horizontally."""
        scroll = QScrollArea()
        if not horizontal:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def invalidate_prompt_preview(self, *_):
        self.send_button.setEnabled(False)

    def refresh_existing_jobs(self):
        previous = self.existing_job.currentData()
        self.existing_job.blockSignals(True)
        self.existing_job.clear()
        self.existing_job.addItem("Auftrag auswählen", "")
        for job_id, name, status in self.db.execute(
            "SELECT id, name, status FROM jobs ORDER BY created_at DESC"
        ):
            self.existing_job.addItem(f"{name} · {status} · {job_id[:8]}", job_id)
            self.existing_job.setItemData(self.existing_job.count() - 1, job_id, Qt.ToolTipRole)
        index = self.existing_job.findData(previous) if previous else 0
        self.existing_job.setCurrentIndex(max(0, index))
        self.existing_job.blockSignals(False)
        self.show_existing_job(self.existing_job.currentIndex())

    def show_existing_job(self, index):
        job_id = self.existing_job.itemData(index) if index >= 0 else None
        if not job_id:
            self.existing_job_details.clear()
            return
        record = self.db.execute(
            "SELECT name, kind, status, description, project_root FROM jobs WHERE id=?",
            (job_id,)
        ).fetchone()
        if record:
            self.existing_job_details.setPlainText(
                f"Auftrag: {record[0]}\\nUUID: {job_id}\\nTyp: {record[1]}\\n"
                f"Status: {record[2]}\\nCodeprojekt: {record[4] or 'Noch nicht zugeordnet'}\\n\\n"
                f"Anforderungen:\\n{record[3]}"
            )

    def open_existing_job(self):
        job_id = self.existing_job.currentData()
        if not job_id:
            QMessageBox.information(self, "Auftrag", "Bitte einen gespeicherten Auftrag auswählen.")
            return
        self.refresh_prompt_jobs()
        index = self.prompt_job.findData(job_id)
        if index < 0:
            QMessageBox.warning(self, "Auftrag", "Auftrag wurde nicht gefunden.")
            return
        self.prompt_job.setCurrentIndex(index)
        self.select_prompt_job(index)
        self.tabs.setCurrentIndex(self.prompt_tab_index)

    def refresh_prompt_jobs(self):
        previous = self.prompt_job.currentData()
        self.prompt_job.blockSignals(True)
        self.prompt_job.clear()
        self.prompt_job.addItem("Kein Auftrag ausgewählt", "")
        for job_id, name in self.db.execute(
            "SELECT id, name FROM jobs ORDER BY created_at DESC"
        ):
            self.prompt_job.addItem(name, job_id)
        index = self.prompt_job.findData(previous) if previous else 0
        self.prompt_job.setCurrentIndex(max(0, index))
        self.prompt_job.blockSignals(False)

    def select_prompt_job(self, index):
        job_id = self.prompt_job.itemData(index)
        if not job_id:
            self.invalidate_prompt_preview()
            return
        record = self.db.execute(
            "SELECT description, project_root FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if record:
            self.prompt_task.setPlainText(record[0])
            project_index = self.prompt_project.findData(record[1] or "")
            self.prompt_project.setCurrentIndex(max(0, project_index))
        self.invalidate_prompt_preview()
        self.load_workflow()

    def default_project_index(self, combo):
        """Choose the sole imported project for new jobs, not existing jobs."""
        roots = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)]
        return combo.findData(roots[0]) if len(roots) == 1 else 0

    def refresh_prompt_projects(self):
        previous = self.prompt_project.currentData()
        self.prompt_project.blockSignals(True)
        self.prompt_project.clear()
        self.prompt_project.addItem("Kein Projekt (nur Auftrag)", "")
        for name, root in self.db.execute("SELECT name, root FROM imported_projects ORDER BY imported_at DESC"):
            self.prompt_project.addItem(name, root)
            self.prompt_project.setItemData(self.prompt_project.count()-1, root, Qt.ToolTipRole)
        if previous:
            idx = self.prompt_project.findData(previous)
            if idx >= 0:
                self.prompt_project.setCurrentIndex(idx)
        else:
            self.prompt_project.setCurrentIndex(self.default_project_index(self.prompt_project))
        self.prompt_project.blockSignals(False)
        self.send_button.setEnabled(False)
        if hasattr(self, "job_project"):
            previous_job_project = self.job_project.currentData()
            self.job_project.blockSignals(True)
            self.job_project.clear()
            self.job_project.addItem("Kein importiertes Codeprojekt", "")
            for name, root in self.db.execute(
                "SELECT name, root FROM imported_projects ORDER BY imported_at DESC"
            ):
                self.job_project.addItem(name, root)
            index = (self.job_project.findData(previous_job_project)
                     if previous_job_project else self.default_project_index(self.job_project))
            self.job_project.setCurrentIndex(max(0, index))
            self.job_project.blockSignals(False)

    def refresh_openai_models(self):
        try:
            self.ensure_running()
        except ValueError as exc:
            QMessageBox.warning(self, "Not-Aus", str(exc))
            return
        if self.prompt_provider.currentText() != "OpenAI":
            QMessageBox.information(self, "Modelle", "Bitte zuerst OpenAI als Anbieter auswählen.")
            return
        self.model_worker = ModelListWorker(self.api_key.text().strip() or None)
        self.model_worker.succeeded.connect(self.models_received)
        self.model_worker.failed.connect(lambda msg: QMessageBox.warning(self, "Modellabfrage", msg))
        self.model_worker.finished.connect(self.model_worker.deleteLater)
        self.model_worker.start()

    def models_received(self, models):
        if self.emergency_stop:
            return
        previous = self.prompt_model.currentText()
        self.prompt_model.blockSignals(True)
        self.prompt_model.clear()
        self.prompt_model.addItems(models)
        if previous in models:
            self.prompt_model.setCurrentText(previous)
        self.prompt_model.blockSignals(False)
        self.invalidate_prompt_preview()

    def provider_changed(self, provider):
        self.prompt_model.blockSignals(True)
        self.prompt_model.clear()
        if provider == "OpenAI":
            self.prompt_model.setEditable(False)
            self.prompt_model.addItems(OPENAI_MODELS)
            self.prompt_model.setCurrentText("gpt-6-luna")
        else:
            # LM Studio IDs depend on the locally loaded model.
            self.prompt_model.setEditable(True)
            self.prompt_model.addItem("local-model")
        self.prompt_model.blockSignals(False)
        self.send_button.setEnabled(False)

    def active_workflow(self):
        job_id = self.prompt_job.currentData()
        if not job_id:
            raise ValueError("Bitte zuerst einen gespeicherten Entwicklungsauftrag auswählen.")
        row = self.db.execute("SELECT description, project_root FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Entwicklungsauftrag nicht gefunden.")
        if row[0] != self.prompt_task.toPlainText():
            raise ValueError("Der Originalauftrag weicht vom gespeicherten Auftrag ab. Bitte zuerst in der Auftragsverwaltung speichern.")
        if (row[1] or "") != (self.prompt_project.currentData() or ""):
            raise ValueError("Projektzuordnung weicht vom gespeicherten Auftrag ab. Bitte zuerst in der Auftragsverwaltung speichern.")
        return job_id, row[0]

    def load_workflow(self):
        job_id = self.prompt_job.currentData()
        state = job_workflow.get(self.db, job_id) if job_id else None
        self.clarification_questions.setPlainText(state["questions"] if state else "")
        self.clarification_answers.setPlainText(state["answers"] if state else "")
        self.final_prompt.setPlainText(state["final_prompt"] if state else "")
        self.workflow_status.setText("Workflow: " + (state["status"] if state else "DRAFT / kein Auftrag"))
        self.restore_project_proposal()

    def restore_project_proposal(self):
        self.validated_project_proposal = None
        self.project_apply_button.setEnabled(False)
        job_id = self.prompt_job.currentData()
        if not job_id:
            return
        row = self.db.execute("SELECT project_root, commit_sha, proposal_json FROM project_proposals WHERE job_id=?",
                              (job_id,)).fetchone()
        if not row:
            return
        try:
            root, commit, raw = row
            proposal = parse_project_proposal(raw)
            self.project_generation_preview.setPlainText(
                proposal["summary"] + "\n\nGespeicherter Projektvorschlag:\n" +
                "\n".join("• " + item["path"] for item in proposal["files"]) +
                "\n\nVor der Übernahme wird der aktuelle Git-Stand erneut geprüft.")
            if self.prompt_project.currentData() == root:
                self.validated_project_proposal = (job_id, root, commit, self.stop_generation, proposal)
                self.project_apply_button.setEnabled(True)
        except (ValueError, ProjectProposalError):
            self.project_generation_preview.setPlainText("Gespeicherter Vorschlag ist ungültig.")

    def bind_selected_project(self):
        try:
            job_id = self.prompt_job.currentData()
            root = self.prompt_project.currentData()
            if not job_id:
                raise ValueError("Bitte zuerst einen gespeicherten Entwicklungsauftrag auswählen.")
            if not root:
                raise ValueError("Bitte ein importiertes Codeprojekt auswählen. Über 'Codeprojekt importieren / auswählen' gelangst du zur Projektverwaltung.")
            row = self.db.execute("SELECT name FROM imported_projects WHERE root=?", (root,)).fetchone()
            if not row:
                raise ValueError("Das Codeprojekt wurde nicht gefunden.")
            confirm = QMessageBox.question(
                self, "Projekt verbindlich zuordnen",
                "Projekt '" + row[0] + "' diesem Auftrag zuordnen?\\n"
                "Eine bestehende READY-Freigabe wird widerrufen; der finale Prompt bleibt erhalten.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return
            changed = job_workflow.bind_project(self.db, job_id, root)
            self.load_workflow()
            self.git_preflight_result.clear()
            QMessageBox.information(self, "Projektzuordnung",
                "Projekt zugeordnet. Bitte finalen Auftrag erneut freigeben." if changed
                else "Dieses Projekt ist bereits zugeordnet.")
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Projektzuordnung", str(exc))

    def check_approved_project(self):
        try:
            job_id, source = self.active_workflow()
            state = job_workflow.get(self.db, job_id)
            if not state or state["status"] != "READY" or state["source_description"] != source:
                raise ValueError("Zuerst den Entwicklungsauftrag freigeben (READY).")
            row = self.db.execute("SELECT project_root FROM jobs WHERE id=?", (job_id,)).fetchone()
            project_root = row[0] if row else None
            if not project_root:
                raise ValueError("Der Auftrag hat noch kein Codeprojekt. Bitte in der Auftragsverwaltung ein importiertes Git-Projekt zuordnen.")
            info = git_preflight(project_root)
            self.git_preflight_result.setPlainText(format_preflight(info))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.git_preflight_result.setPlainText("")
            QMessageBox.warning(self, "Git-Projektprüfung", str(exc))

    def request_project_generation(self):
        self.validated_project_proposal = None
        self.project_apply_button.setEnabled(False)
        try:
            self.ensure_running()
            job_id, root = self._approved_edit_context()
            info = git_preflight(root)
            if not info["clean"]:
                raise ValueError("Das Git-Projekt muss vor der Generierung sauber sein.")
            state = job_workflow.get(self.db, job_id)
            if not state or not state["final_prompt"]:
                raise ValueError("Ein freigegebener finaler Auftrag ist erforderlich.")
            provider = self.prompt_provider.currentText()
            if QMessageBox.question(
                self, "Phase A – Projektvorschlag",
                "Der freigegebene Auftrag wird an " + provider +
                " gesendet. Die KI erstellt bis zu 12 Dateien als Vorschlag. "
                "Es werden keine Dateien geschrieben. Fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
            self.project_generation_context = (job_id, root, info["commit"], self.stop_generation)
            self.project_generate_button.setEnabled(False)
            self.project_generation_preview.setPlainText("Projektvorschlag wird generiert …")
            payload = ("PHASE A – TAXCALCULATOR. Freigegebener Entwicklungsauftrag:\n" +
                       state["final_prompt"] +
                       "\n\nErzeuge einen zusammenhängenden, startfähigen Webanwendungs-Vorschlag. "
                       "Noch keine Berechnung mit unbelegten Steuer- oder Beitragssätzen.")
            self.authorize_api_cost(provider, self.prompt_model.currentText(), payload, int(self.output_budget.currentText()))
            self.project_generation_worker = ProjectGenerationWorker(
                provider, self.prompt_model.currentText(), payload,
                self.api_key.text().strip() if provider == "OpenAI" else None,
                int(self.output_budget.currentText()))
            self.project_generation_worker.succeeded.connect(self.receive_project_generation)
            self.project_generation_worker.failed.connect(self.fail_project_generation)
            self.project_generation_worker.finished.connect(self.project_generation_worker.deleteLater)
            self.project_generation_worker.start()
        except (ValueError, OSError, sqlite3.Error, BudgetError) as exc:
            QMessageBox.warning(self, "Projektgenerierung", str(exc))

    def fail_project_generation(self, message):
        if getattr(self, "pending_cost", None):
            self.cost_unverified = True
            self.pending_cost = None
        self.project_generate_button.setEnabled(True)
        self.project_generation_context = None
        if not emergency.stopped and not self.emergency_stop:
            QMessageBox.warning(self, "Projektgenerierung", message)

    def receive_project_generation(self, raw):
        raw = self.record_api_cost(raw)
        self.project_generate_button.setEnabled(True)
        context = getattr(self, "project_generation_context", None)
        self.project_generation_context = None
        if emergency.stopped or self.emergency_stop or not context:
            return
        try:
            job_id, root, commit, generation = context
            if generation != self.stop_generation:
                return
            current_job, current_root = self._approved_edit_context()
            if (current_job, current_root) != (job_id, root):
                raise ValueError("Auftrag oder Projekt wurde während der Anfrage gewechselt.")
            info = git_preflight(root)
            if not info["clean"] or info["commit"] != commit:
                raise ValueError("Git-Zustand hat sich während der Generierung verändert.")
            proposal = parse_project_proposal(raw)
            self.db.execute("INSERT OR REPLACE INTO project_proposals (job_id, project_root, commit_sha, proposal_json) VALUES (?, ?, ?, ?)",
                            (job_id, root, commit, json.dumps(proposal, ensure_ascii=False)))
            self.db.commit()
            self.validated_project_proposal = (job_id, root, commit, generation, proposal)
            self.project_apply_button.setEnabled(True)
            lines = [proposal["summary"], "", "VORSCHAU – KEINE DATEIEN GESCHRIEBEN", ""]
            for item in proposal["files"]:
                lines.append("• " + item["path"] + " (" + str(len(item["content"].encode("utf-8"))) + " Bytes)")
            lines.append("\nVollständige Inhalte sind in SQLite gespeichert und bleiben nach Neustart verfügbar.")
            self.project_generation_preview.setPlainText("\n".join(lines))
        except (ValueError, OSError, ProjectProposalError, sqlite3.Error) as exc:
            self.validated_project_proposal = None
            self.project_apply_button.setEnabled(False)
            self.project_generation_preview.setPlainText("Projektvorschlag verworfen: " + str(exc))

    def apply_generated_project(self):
        try:
            self.ensure_running()
            snapshot = self.validated_project_proposal
            if snapshot is None:
                raise ValueError("Kein gültiger Projektvorschlag zur Übernahme vorhanden.")
            job_id, root, commit, generation, proposal = snapshot
            if generation != self.stop_generation or self._approved_edit_context() != (job_id, root):
                raise ValueError("Auftrag oder Freigabe hat sich geändert.")
            info = git_preflight(root)
            if not info["clean"] or info["commit"] != commit:
                raise ValueError("Git-Zustand hat sich geändert.")
            paths = [entry["path"] for entry in proposal["files"]]
            question = ("Folgende NEUE Dateien werden im ausgewählten Git-Arbeitsordner erstellt:\n\n"
                        + "\n".join(paths) + "\n\n"
                        "Vorhandene Dateien werden nicht überschrieben. Kein Test, Commit oder Push. "
                        "Dateien jetzt ausdrücklich freigeben?")
            if QMessageBox.question(self, "Projektdateien schreiben", question,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self.ensure_running()
            written = apply_project_proposal(root, proposal, commit, approved=True)
            self.db.execute("DELETE FROM project_proposals WHERE job_id=?", (job_id,))
            self.db.commit()
            self.validated_project_proposal = None
            self.project_apply_button.setEnabled(False)
            self.project_generation_preview.append("\nDATEIEN ERSTELLT (nicht committed):\n" + "\n".join(written))
            QMessageBox.information(self, "Projektdateien erstellt",
                                    "Erstellt: " + str(len(written)) + " Dateien. Bitte Git-Diff und Tests prüfen.")
        except (ValueError, OSError, sqlite3.Error, ProjectProposalError) as exc:
            QMessageBox.warning(self, "Projektübernahme", str(exc))

    def request_ai_edit(self):
        try:
            self.ensure_running()
            job_id, root = self._approved_edit_context()
            relative = self.edit_relative_path.text().strip()
            info = git_preflight(root)
            if not info["clean"]:
                raise ValueError("Git-Arbeitsverzeichnis muss sauber sein.")
            # The existing controlled_edit.preview validates Git tracking and path safety.
            rel = Path(relative)
            if not relative or rel.is_absolute() or ".." in rel.parts or "\\\\" in relative:
                raise ValueError("Ungültiger relativer Dateipfad.")
            current = Path(root)
            for part in rel.parts:
                current = current / part
                if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                    raise ValueError("Symlink/Junction nicht erlaubt.")
            target = current
            if not target.is_file() or not target.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError("Datei liegt außerhalb des Projekts oder existiert nicht.")
            original = target.read_bytes()
            if len(original) > 120_000:
                raise ValueError("Datei ist für einen Einzeldatei-KI-Vorschlag zu groß.")
            source = original.decode("utf-8")
            sha = hashlib.sha256(original).hexdigest()
            preview_edit(root, relative, sha, source)
            state = job_workflow.get(self.db, job_id)
            payload = ("FREIGEGEBENER ENTWICKLUNGSAUFTRAG:\n" + state["final_prompt"]
                + "\n\nBEARBEITE AUSSCHLIESSLICH DIE DATEI: " + relative
                + "\n\nAKTUELLER DATEIINHALT:\n" + source
                + "\n\nGib exakt ein JSON-Objekt mit path, content, summary zurück.")
            provider = self.prompt_provider.currentText()
            answer = QMessageBox.question(self, "KI-Codevorschlag",
                "Der vollständige Inhalt von " + relative
                + " und der freigegebene Auftrag werden an " + provider
                + " übertragen. Fortfahren?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self.authorize_api_cost(provider, self.prompt_model.currentText(), payload, int(self.output_budget.currentText()))
            self.proposal_context = (job_id, root, relative, sha, info["commit"])
            self.proposal_request_generation = self.stop_generation
            self.proposal_button.setEnabled(False)
            self.proposal_worker = ProposalWorker(provider, self.prompt_model.currentText(),
                payload, self.api_key.text().strip() if provider == "OpenAI" else None,
                int(self.output_budget.currentText()))
            self.proposal_worker.succeeded.connect(self.receive_ai_edit)
            self.proposal_worker.failed.connect(self.fail_ai_edit)
            self.proposal_worker.finished.connect(self.proposal_worker.deleteLater)
            self.proposal_worker.start()
        except (ValueError, OSError, UnicodeError, EditRejected, sqlite3.Error, BudgetError) as exc:
            QMessageBox.warning(self, "KI-Codevorschlag", str(exc))

    def fail_ai_edit(self, message):
        if getattr(self, "pending_cost", None):
            self.cost_unverified = True
            self.pending_cost = None
        self.proposal_button.setEnabled(True)
        self.proposal_context = None
        QMessageBox.warning(self, "KI-Codevorschlag", message)

    def receive_ai_edit(self, raw):
        raw = self.record_api_cost(raw)
        if emergency.stopped:
            return
        if self.emergency_stop or self.proposal_request_generation != self.stop_generation:
            self.proposal_context = None
            return
        self.proposal_button.setEnabled(True)
        context = self.proposal_context
        self.proposal_context = None
        try:
            if not context:
                raise ValueError("KI-Vorschlag ist nicht mehr zugeordnet.")
            job_id, root, relative, sha, commit = context
            current_job, current_root = self._approved_edit_context()
            if (current_job, current_root) != (job_id, root):
                raise ValueError("Auftrag oder Projekt wurde während der KI-Anfrage gewechselt.")
            info = git_preflight(root)
            if not info["clean"] or info["commit"] != commit:
                raise ValueError("Git-Zustand hat sich während der KI-Anfrage geändert.")
            proposal = parse_proposal(raw, relative)
            preview_edit(root, relative, sha, proposal["content"])
            self.edit_relative_path.setText(relative)
            self.edit_replacement.setPlainText(proposal["content"])
            self.edit_approval_snapshot = None
            self.edit_diff.clear()
            self.preview_approved_edit()
            QMessageBox.information(self, "KI-Vorschlag",
                proposal["summary"] + "\n\nBitte den Diff prüfen. Schreiben erfordert eine weitere Freigabe.")
        except (ValueError, OSError, UnicodeError, EditRejected, ProposalError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "KI-Vorschlag verworfen", str(exc))

    def _approved_edit_context(self):
        job_id, source = self.active_workflow()
        state = job_workflow.get(self.db, job_id)
        if not state or state["status"] != "READY" or state["source_description"] != source:
            raise ValueError("Der gespeicherte Entwicklungsauftrag muss READY sein.")
        if self.final_prompt.toPlainText() != state["final_prompt"]:
            raise ValueError("Der finale Auftrag wurde verändert; bitte erneut speichern und freigeben.")
        row = self.db.execute("SELECT project_root FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or not row[0]:
            raise ValueError(
                "Dieser Auftrag hat noch keine gespeicherte Projektzuordnung. "
                "Wähle oben das importierte Projekt und klicke auf "
                "'Projekt dem ausgewählten Auftrag verbindlich zuordnen'. "
                "Eine bestehende Freigabe muss danach erneut bestätigt werden."
            )
        return job_id, row[0]

    def preview_approved_edit(self):
        if self.emergency_stop:
            QMessageBox.warning(self, "Not-Aus", "Änderungsvorschau gesperrt.")
            return
        self.edit_approval_snapshot = None
        self.edit_diff.clear()
        try:
            job_id, root = self._approved_edit_context()
            relative = self.edit_relative_path.text().strip()
            # First validate the path and Git state before reading its bytes.
            from pathlib import Path
            info = git_preflight(root)
            if not info["clean"]:
                raise ValueError("Git-Arbeitsverzeichnis ist nicht sauber.")
            rel = Path(relative)
            if not relative or rel.is_absolute() or ".." in rel.parts or "." in rel.parts:
                raise ValueError("Nur relative Dateipfade innerhalb des Projekts erlaubt.")
            base = Path(info["root"])
            target = base / rel
            current = base
            for component in rel.parts:
                current = current / component
                if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                    raise ValueError("Symlink/Junction im Dateipfad ist nicht erlaubt.")
            if not target.is_file() or not target.resolve().is_relative_to(base.resolve()):
                raise ValueError("Die Datei muss innerhalb des Projektordners existieren.")
            original = target.read_bytes()
            sha = hashlib.sha256(original).hexdigest()
            replacement = self.edit_replacement.toPlainText()
            result = preview_edit(root, relative, sha, replacement)
            try:
                old_text = original.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Nur UTF-8-Textdateien werden unterstützt.") from exc
            diff = "".join(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                replacement.splitlines(keepends=True),
                fromfile="a/" + relative, tofile="b/" + relative,
            ))
            if not diff:
                raise ValueError("Keine Änderung vorhanden.")
            self.edit_diff.setPlainText(diff)
            self.edit_approval_snapshot = (job_id, root, relative, sha, replacement, info["commit"])
        except (ValueError, OSError, EditRejected, sqlite3.Error) as exc:
            self.edit_diff.clear()
            QMessageBox.warning(self, "Änderungsvorschau", str(exc))

    def apply_approved_edit(self):
        try:
            self.ensure_running()
            if self.edit_approval_snapshot is None:
                raise ValueError("Zuerst die Änderungsvorschau erstellen.")
            job_id, root, relative, sha, replacement, commit = self.edit_approval_snapshot
            active_job, active_root = self._approved_edit_context()
            if (active_job, active_root) != (job_id, root):
                raise ValueError("Auftrag oder Projektzuordnung hat sich geändert.")
            if self.edit_relative_path.text().strip() != relative or self.edit_replacement.toPlainText() != replacement:
                raise ValueError("Dateipfad oder Inhalt wurde seit der Vorschau verändert.")
            info = git_preflight(root)
            if not info["clean"] or info["commit"] != commit:
                raise ValueError("Git-Stand hat sich seit der Vorschau geändert.")
            answer = QMessageBox.question(
                self, "Dateiänderung ausdrücklich freigeben",
                "Diese Aktion überschreibt genau eine vorhandene Datei:\n"
                + str(Path(root) / relative)
                + "\n\nDer Diff wurde angezeigt. Änderung jetzt schreiben?\n"
                "Es erfolgt kein Commit und kein Push.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.ensure_running()
            apply_edit(root, relative, sha, replacement, approved=True)
            self.edit_approval_snapshot = None
            self.git_preflight_result.setPlainText(format_preflight(git_preflight(root)))
            QMessageBox.information(self, "Datei geändert",
                "Änderung geschrieben. Bitte Git-Diff prüfen und Tests ausführen; kein Commit erstellt.")
        except (ValueError, OSError, EditRejected, sqlite3.Error) as exc:
            self.edit_approval_snapshot = None
            QMessageBox.warning(self, "Dateiänderung", str(exc))

    def request_clarification(self):
        try:
            job_id, source = self.active_workflow()
            job_workflow.ensure(self.db, job_id, source)
            self.prompt_mode.setCurrentText("Anforderungen klären")
            self.workflow_request = ("questions", job_id, source)
            self.prepare_prompt()
            if not self.send_button.isEnabled():
                return
            self.workflow_request = ("questions", job_id, source)
            self.send_prompt()
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Anforderungsklärung", str(exc))

    def store_clarification_answers(self):
        try:
            job_id, source = self.active_workflow()
            job_workflow.ensure(self.db, job_id, source)
            job_workflow.save_answers(self.db, job_id, self.clarification_answers.toPlainText())
            self.load_workflow()
            self.show_workflow_step(3)
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Antworten", str(exc))

    def request_final_prompt(self):
        try:
            job_id, source = self.active_workflow()
            state = job_workflow.ensure(self.db, job_id, source)
            if state["status"] not in ("ANSWERED", "FINAL_REVIEW", "READY"):
                raise ValueError("Bitte zuerst die Rückfragen prüfen und beantworten.")
            self.prompt_mode.setCurrentText("Finalen Auftrag erstellen")
            self.workflow_request = ("final", job_id, source)
            self.prepare_prompt()
            if not self.send_button.isEnabled():
                return
            self.workflow_request = ("final", job_id, source)
            self.send_prompt()
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Finaler Auftrag", str(exc))

    def store_final_prompt(self):
        try:
            job_id, source = self.active_workflow()
            job_workflow.ensure(self.db, job_id, source)
            job_workflow.save_final(self.db, job_id, self.final_prompt.toPlainText())
            self.load_workflow()
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Finaler Auftrag", str(exc))

    def approve_final_prompt(self):
        try:
            job_id, source = self.active_workflow()
            job_workflow.ensure(self.db, job_id, source)
            answer = QMessageBox.question(self, "Freigabe",
                "Diesen finalen Entwicklungsauftrag als READY freigeben? Es werden keine Dateien geändert.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            job_workflow.approve(self.db, job_id, self.final_prompt.toPlainText())
            self.load_workflow()
            self.show_workflow_step(4)
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Freigabe", str(exc))

    def prepare_prompt(self):
        try:
            self.ensure_running()
            root = self.prompt_project.currentData()
            context = "Kein Projektkontext ausgewählt."
            if root:
                row = self.db.execute("SELECT report_json FROM imported_projects WHERE root=?", (root,)).fetchone()
                if not row:
                    raise ValueError("Projekt nicht gefunden.")
                validate_project_root(root)
                context = collect_context(root, json.loads(row[0]))
            task = self.prompt_task.toPlainText()
            if self.prompt_mode.currentText() == "Finalen Auftrag erstellen" and self.workflow_request and self.workflow_request[0] == "final":
                state = job_workflow.get(self.db, self.workflow_request[1])
                if state and state["status"] in ("ANSWERED", "FINAL_REVIEW", "READY"):
                    task += "\n\nBESTÄTIGTE ANTWORTEN DES BENUTZERS:\n" + state["answers"]
                    task += "\n\nBISHERIGE RÜCKFRAGEN:\n" + state["questions"]
            self.prepared_payload = build_request(task, context)
            self.prepared_identity = (self.prompt_task.toPlainText(), root, self.prompt_provider.currentText(), self.prompt_model.currentText(), self.prompt_mode.currentText(), self.output_budget.currentText())
            self.context_preview.setPlainText(self.prepared_payload)
            self.send_button.setEnabled(True)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.send_button.setEnabled(False)
            QMessageBox.warning(self, "Kontextprüfung", str(exc))

    def authorize_api_cost(self, provider, model, payload, output_tokens):
        if getattr(self, "pending_cost", None):
            raise BudgetError("Es läuft bereits eine kostenpflichtige Anfrage. Bitte deren Abschluss abwarten.")
        if getattr(self, "cost_unverified", False) and provider == "OpenAI":
            raise BudgetError("Kosten einer früheren Anfrage sind unklar. Bitte zuerst den API-Verbrauch beim Anbieter abgleichen und AgentFactory neu starten.")
        if provider != "OpenAI":
            self.pending_cost = None
            return
        price = price_record(model, self.usd_input_price.text(), self.usd_output_price.text(),
                             self.usd_price_date.text())
        # Conservative approximation for UTF-8 text; not a provider-guaranteed upper bound.
        estimated_input = max(1000, len(payload.encode("utf-8")))
        spent = sum((money(row[0]) for row in self.db.execute("SELECT cost_usd FROM api_spend")), money("0"))
        estimate = check_budget(self.usd_limit.text(), spent, price, estimated_input, output_tokens)
        self.pending_cost = (model, price)
        self.usd_status.setText(f"Verbraucht: {spent} USD · nächster Aufruf geschätzt: {estimate} USD")

    def record_api_cost(self, response):
        if not isinstance(response, tuple) or len(response) != 2:
            return response
        raw, usage = response
        pending = getattr(self, "pending_cost", None)
        self.pending_cost = None
        if pending and usage:
            model, price = pending
            amount = estimated_cost(usage["input_tokens"], usage["output_tokens"], price)
            self.db.execute("INSERT INTO api_spend (model, input_tokens, output_tokens, cost_usd) VALUES (?, ?, ?, ?)",
                            (model, usage["input_tokens"], usage["output_tokens"], str(amount)))
            self.db.commit()
            spent = sum((money(row[0]) for row in self.db.execute("SELECT cost_usd FROM api_spend")), money("0"))
            self.usd_status.setText(f"Verbraucht: {spent} USD (gemeldete Tokens)")
        elif pending:
            self.cost_unverified = True
            self.usd_status.setText("Keine Nutzungsdaten vom Anbieter: Kosten unklar – weitere Aufrufe prüfen.")
        return raw

    def send_prompt(self):
        if emergency.stopped:
            return
        if self.emergency_stop:
            QMessageBox.warning(self, "Not-Aus", "KI-Anfrage gesperrt.")
            return
        identity = (self.prompt_task.toPlainText(), self.prompt_project.currentData(), self.prompt_provider.currentText(), self.prompt_model.currentText(), self.prompt_mode.currentText(), self.output_budget.currentText())
        if identity != getattr(self, "prepared_identity", None):
            self.workflow_request = None
            self.send_button.setEnabled(False)
            QMessageBox.warning(self, "Vorschau veraltet", "Eingaben wurden geändert. Bitte Kontext erneut vorbereiten.")
            return
        if identity[1]:
            try:
                record = self.db.execute("SELECT report_json FROM imported_projects WHERE root=?", (identity[1],)).fetchone()
                validate_project_root(identity[1])
                current_task = identity[0]
                if self.workflow_request and self.workflow_request[0] == "final":
                    state = job_workflow.get(self.db, self.workflow_request[1])
                    if state and state["status"] in ("ANSWERED", "FINAL_REVIEW", "READY"):
                        current_task += "\n\nBESTÄTIGTE ANTWORTEN DES BENUTZERS:\n" + state["answers"]
                        current_task += "\n\nBISHERIGE RÜCKFRAGEN:\n" + state["questions"]
                current = build_request(current_task, collect_context(identity[1], json.loads(record[0])))
                if current != self.prepared_payload:
                    self.send_button.setEnabled(False)
                    QMessageBox.warning(self, "Projekt geändert", "Projektkontext wurde seit der Vorschau geändert. Bitte erneut vorbereiten.")
                    return
            except (OSError, ValueError, TypeError, KeyError) as exc:
                QMessageBox.warning(self, "Kontextprüfung", str(exc))
                return
        reply = QMessageBox.question(self, "Externe Datenübertragung bestätigen",
            "Anbieter: " + identity[2] + "\nModell: " + identity[3] + "\nModus: " + identity[4] +
            "\n\nDer angezeigte Auftrag und Projektkontext werden an diesen Anbieter gesendet. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.workflow_request = None
            return
        try:
            self.authorize_api_cost(identity[2], identity[3], self.prepared_payload, int(identity[5]))
        except BudgetError as exc:
            QMessageBox.warning(self, "USD-Budget", str(exc))
            return
        self.send_button.setEnabled(False)
        self.prompt_result.setPlainText("Anfrage läuft …")
        self.prompt_request_generation = self.stop_generation
        self.worker = PromptWorker(identity[2], identity[3], self.prepared_payload, identity[4], self.api_key.text().strip() if identity[2] == "OpenAI" else None, int(identity[5]))
        self.worker.succeeded.connect(self.prompt_success)
        self.worker.failed.connect(self.prompt_failure)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def prompt_success(self, text):
        text = self.record_api_cost(text)
        if emergency.stopped:
            return
        if self.emergency_stop or self.prompt_request_generation != self.stop_generation:
            self.workflow_request = None
            return
        self.prompt_result.setPlainText(text)
        request = self.workflow_request
        self.workflow_request = None
        if not request:
            return
        action, job_id, source = request
        try:
            if action == "questions":
                job_workflow.save_questions(self.db, job_id, source, text)
            elif action == "final":
                state = job_workflow.get(self.db, job_id)
                if state and state["source_description"] == source and self.prompt_job.currentData() == job_id:
                    # Keep the generated draft visible until the user reviews and saves it.
                    # Reloading from SQLite here would erase the unsaved draft.
                    self.final_prompt.setPlainText(text)
                    self.workflow_status.setText("Workflow: Finalen Entwurf prüfen und speichern")
                    self.show_workflow_step(3)
                    return
            self.load_workflow()
            if action == "questions":
                self.show_workflow_step(2)
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Workflow", str(exc))

    def prompt_failure(self, error):
        if getattr(self, "pending_cost", None):
            self.cost_unverified = True
            self.pending_cost = None
        if self.emergency_stop or self.prompt_request_generation != self.stop_generation:
            return
        self.workflow_request = None
        self.prompt_result.setPlainText("Fehler: " + error)

    def choose_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Projektordner auswählen")
        if folder:
            self.project_path.setText(folder)

    def scan_project(self):
        folder = self.project_path.text().strip()
        if not folder:
            QMessageBox.information(self, "Projekt", "Bitte zuerst einen Ordner auswählen.")
            return
        try:
            validate_project_root(folder)
            data = inspect_project(folder)
            display_name, accepted = QInputDialog.getText(self, "Projektname", "Anzeigename für das Projekt:", text=Path(data["root"]).name)
            if not accepted:
                return
            display_name = display_name.strip()
            if not display_name or len(display_name) > 100:
                raise ValueError("Bitte einen Projektnamen mit 1–100 Zeichen eingeben.")
            now = datetime.now(timezone.utc).isoformat()
            with self.db:
                self.db.execute("""INSERT INTO imported_projects
                    (id, imported_at, root, name, report_json) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(root) DO UPDATE SET imported_at=excluded.imported_at,
                    name=excluded.name, report_json=excluded.report_json""",
                    (str(uuid.uuid4()), now, data['root'], display_name,
                     json.dumps(data, ensure_ascii=False)))
            self.project_report.setPlainText(report_text(data))
            self.refresh_imports()
            self.refresh_prompt_projects()
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.critical(self, "Analysefehler", str(exc))

    def refresh_imports(self):
        rows = self.db.execute("SELECT name, root FROM imported_projects ORDER BY imported_at DESC").fetchall()
        previous = self.import_project.currentData()
        self.import_project.blockSignals(True)
        self.import_project.clear()
        self.imported_table.blockSignals(True)
        self.imported_table.setRowCount(len(rows))
        for i, (name, root) in enumerate(rows):
            self.import_project.addItem(name, root)
            self.imported_table.setItem(i, 0, QTableWidgetItem(name))
            path_item = QTableWidgetItem("Projekt " + str(i + 1))
            path_item.setData(Qt.UserRole, root)
            self.imported_table.setItem(i, 1, path_item)
        self.imported_table.blockSignals(False)
        if previous:
            idx = self.import_project.findData(previous)
            if idx >= 0:
                self.import_project.setCurrentIndex(idx)
        elif rows:
            self.import_project.setCurrentIndex(0)
        self.import_project.blockSignals(False)
        self.imported_table.resizeColumnsToContents()
        self.select_imported_project(self.import_project.currentIndex())

    def select_imported_project(self, index):
        if index < 0:
            self.project_report.clear()
            return
        root = self.import_project.itemData(index)
        for row in range(self.imported_table.rowCount()):
            item = self.imported_table.item(row, 1)
            if item and item.data(Qt.UserRole) == root:
                self.imported_table.blockSignals(True)
                self.imported_table.selectRow(row)
                self.imported_table.blockSignals(False)
                self.show_imported_report(row)
                break

    def sync_imported_selection(self):
        row = self.imported_table.currentRow()
        item = self.imported_table.item(row, 1) if row >= 0 else None
        if item:
            idx = self.import_project.findData(item.data(Qt.UserRole))
            if idx >= 0 and idx != self.import_project.currentIndex():
                self.import_project.setCurrentIndex(idx)
            self.show_imported_report(row)

    def selected_imported_root(self):
        return self.import_project.currentData() or None

    def show_imported_report(self, row, column=0):
        item = self.imported_table.item(row, 1)
        if not item:
            return
        record = self.db.execute("SELECT report_json FROM imported_projects WHERE root=?", (item.data(Qt.UserRole),)).fetchone()
        if record:
            self.project_report.setPlainText(report_text(json.loads(record[0])))

    def use_selected_project_in_prompt(self):
        project_root = self.selected_imported_root()
        if not project_root:
            QMessageBox.information(self, "Auswahl", "Bitte zuerst ein Projekt auswählen.")
            return
        self.refresh_prompt_projects()
        index = self.prompt_project.findData(project_root)
        if index < 0:
            QMessageBox.warning(self, "Projekt", "Projekt wurde nicht in der Prompt-Auswahl gefunden.")
            return
        self.prompt_project.setCurrentIndex(index)
        self.tabs.setCurrentIndex(2)

    def prepare_existing_job(self):
        project_root = self.selected_imported_root()
        if not project_root:
            QMessageBox.information(self, "Auswahl", "Bitte ein importiertes Projekt auswählen.")
            return
        project_name = self.import_project.currentText()
        self.clear_editor()
        self.name.setText(project_name)
        self.kind.setCurrentText("Bestehendes Projekt (Planung)")
        self.description.setPlainText(f"Projekt: {project_name}\\n\\nGewünschte Änderungen:\\n")
        index = self.job_project.findData(project_root)
        self.job_project.setCurrentIndex(index if index >= 0 else 0)
        self.tabs.setCurrentIndex(0)
        self.description.setFocus()

    def selected_job_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item else None

    def clear_editor(self):
        self.editing_job_id = None
        self.name.clear()
        self.kind.setCurrentIndex(0)
        self.job_project.setCurrentIndex(self.default_project_index(self.job_project))
        self.description.clear()
        self.edit_label.setText("NEUER AUFTRAG")
        self.save_button.setText("Neuen Auftrag speichern")

    def load_job(self, row, column=0):
        item = self.table.item(row, 0)
        if item is None:
            return
        job = self.db.execute(
            "SELECT id, name, description, kind, project_root FROM jobs WHERE id = ?", (item.text(),)
        ).fetchone()
        if not job:
            QMessageBox.warning(self, "Nicht gefunden", "Der Auftrag existiert nicht mehr.")
            return
        self.editing_job_id = job[0]
        idx = self.job_project.findData(job[4] or "")
        self.job_project.setCurrentIndex(max(0, idx))
        self.name.setText(job[1])
        self.description.setPlainText(job[2])
        index = self.kind.findText(job[3])
        self.kind.setCurrentIndex(index if index >= 0 else 0)
        self.edit_label.setText(f"AUFTRAG BEARBEITEN  ·  {job[0]}")
        self.save_button.setText("Änderungen speichern")

    def save_job(self):
        name = self.name.text().strip()
        description = self.description.toPlainText().strip()
        kind = self.kind.currentText()
        project_root = self.job_project.currentData() or None
        if project_root and not self.db.execute(
            "SELECT 1 FROM imported_projects WHERE root=?", (project_root,)
        ).fetchone():
            QMessageBox.warning(self, "Projekt", "Zugeordnetes Codeprojekt nicht gefunden.")
            return
        if not name or not description:
            QMessageBox.warning(self, "Fehlende Angaben", "Projektname und Anforderungen eingeben.")
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.db:
                if self.editing_job_id:
                    old = self.db.execute(
                        "SELECT name, description, kind, status, project_root FROM jobs WHERE id = ?",
                        (self.editing_job_id,)
                    ).fetchone()
                    if old is None:
                        raise ValueError("Der bearbeitete Auftrag wurde nicht gefunden.")
                    if (name, description, kind, project_root) == (old[0], old[1], old[2], old[4]):
                        QMessageBox.information(self, "Unverändert", "Es wurden keine Änderungen vorgenommen.")
                        return
                    self.db.execute(
                        """INSERT INTO job_revisions
                           (job_id, saved_at, name, description, kind, status)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (self.editing_job_id, now, *old[:4])
                    )
                    self.db.execute(
                        "UPDATE jobs SET name=?, description=?, kind=?, status=?, project_root=? WHERE id=?",
                        (name, description, kind, "QUEUED", project_root, self.editing_job_id)
                    )
                    if (old[2], old[4]) != (kind, project_root):
                        state = job_workflow.get(self.db, self.editing_job_id)
                        if state:
                            status = "FINAL_REVIEW" if state["final_prompt"].strip() and old[2] == kind else "DRAFT"
                            self.db.execute(
                                "UPDATE job_workflows SET status=?, approved_at=NULL, updated_at=? WHERE job_id=?",
                                (status, now, self.editing_job_id)
                            )
                else:
                    self.db.execute(
                        "INSERT INTO jobs (id, created_at, name, description, kind, status, project_root) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), now, name, description, kind, "QUEUED", project_root)
                    )
        except (sqlite3.Error, ValueError) as exc:
            QMessageBox.critical(self, "Speicherfehler", str(exc))
            return
        self.clear_editor()
        self.refresh()
        self.refresh_prompt_jobs()
        self.refresh_existing_jobs()
        self.refresh_prompt_projects()

    def simulate_job(self):
        job_id = self.selected_job_id()
        if not job_id:
            QMessageBox.information(self, "Auswahl", "Bitte einen Auftrag auswählen.")
            return
        with self.db:
            self.db.execute("UPDATE jobs SET status = ? WHERE id = ?", ("SIMULATED", job_id))
        self.refresh(select_id=job_id)
        QMessageBox.information(self, "Simulation", "Status gespeichert. Es wurde kein Code ausgeführt.")

    def show_history(self):
        job_id = self.editing_job_id or self.selected_job_id()
        if not job_id:
            QMessageBox.information(self, "Auswahl", "Bitte einen Auftrag auswählen oder öffnen.")
            return
        revisions = self.db.execute(
            "SELECT revision_id, saved_at, name, description, kind, status "
            "FROM job_revisions WHERE job_id = ? ORDER BY revision_id DESC", (job_id,)
        ).fetchall()
        if not revisions:
            QMessageBox.information(self, "Prompt-Verlauf", "Für diesen Auftrag gibt es noch keine früheren Fassungen.")
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QSplitter
        dialog = QDialog(self)
        dialog.setWindowTitle("Gespeicherte Prompt-Versionen (nur lesen)")
        dialog.resize(850, 500)
        layout = QVBoxLayout(dialog)
        split = QSplitter()
        versions = QListWidget()
        detail = QTextEdit()
        detail.setReadOnly(True)
        for revision in revisions:
            versions.addItem(f"#{revision[0]} · {revision[1]}")
        def show_revision(index):
            if index < 0:
                return
            rev = revisions[index]
            detail.setPlainText(
                f"Projekt: {rev[2]}\nTyp: {rev[4]}\nStatus vorher: {rev[5]}\n\n{rev[3]}"
            )
        versions.currentRowChanged.connect(show_revision)
        split.addWidget(versions)
        split.addWidget(detail)
        split.setSizes([260, 590])
        layout.addWidget(split)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        versions.setCurrentRow(0)
        dialog.exec()

    def refresh(self, select_id=None):
        rows = self.db.execute(
            "SELECT id, name, kind, status FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
            if row[0] == select_id:
                self.table.selectRow(row_index)
        self.table.resizeColumnsToContents()

    def closeEvent(self, event):
        self.api_key.clear()
        self.db.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
