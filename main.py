"""Dystenia Agent Factory: local, simulation-only MVP."""
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import json
from project_inspector import inspect_project, report_text
from prompt_context import collect_context, build_request, SYSTEM_PROMPT
from model_router import generate, list_openai_models, ModelError
from project_analysis import MODES, system_prompt_for
from project_access import validate_project_root
import job_workflow
from PySide6.QtCore import QThread, Signal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget, QFileDialog, QTabWidget, QScrollArea, QSizePolicy, QInputDialog)

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
    conn.commit()
    return conn


class PromptWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, provider, model, payload, mode, api_key, max_output_tokens):
        super().__init__()
        self.provider, self.model, self.payload, self.mode, self.api_key = provider, model, payload, mode, api_key
        self.max_output_tokens = max_output_tokens

    def run(self):
        try:
            self.succeeded.emit(generate(self.provider, self.model, system_prompt_for(self.mode), self.payload, api_key=self.api_key, max_output_tokens=self.max_output_tokens))
        except Exception as exc:
            self.failed.emit(str(exc) if isinstance(exc, ModelError) else "Unerwarteter Anbieterfehler.")


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
        heading = QLabel("DYSTENIA AGENT FACTORY  ·  AUFTRAGSVERWALTUNG")
        heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #00d4ff;")
        layout.addWidget(heading)
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
        self.table.horizontalHeader().setStretchLastSection(True)
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
        import_layout.addWidget(QLabel("Gespeichertes Projekt auswählen"))
        self.import_project = QComboBox()
        self.import_project.setMinimumWidth(240)
        self.import_project.currentIndexChanged.connect(self.select_imported_project)
        import_layout.addWidget(self.import_project)
        self.imported_table = QTableWidget(0, 2)
        self.imported_table.setHorizontalHeaderLabels(["Projektname", "Projekt-ID"])
        self.imported_table.horizontalHeader().setStretchLastSection(True)
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
        tabs.addTab(self.scroll_tab(self.import_tab), "Bestehende Projekte")
        prompt_tab = QWidget()
        prompt_layout = QVBoxLayout(prompt_tab)
        prompt_layout.addWidget(QLabel("Prompt Studio · KI-Aufrufe nur nach ausdrücklicher Freigabe"))
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
        prompt_layout.addWidget(QLabel("Der Projektname wird angezeigt; der tatsächliche Pfad bleibt nur intern gespeichert."))
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
        provider_row = QHBoxLayout()
        self.prompt_provider = QComboBox()
        self.prompt_provider.addItems(["OpenAI", "LM Studio (lokal)"])
        self.prompt_provider.currentTextChanged.connect(self.provider_changed)
        self.prompt_model = QComboBox()
        self.prompt_model.setEditable(False)
        self.prompt_model.addItems(OPENAI_MODELS)
        self.prompt_model.setCurrentText("gpt-6-luna")
        self.prompt_model.currentTextChanged.connect(self.invalidate_prompt_preview)
        provider_row.addWidget(QLabel("Anbieter"))
        provider_row.addWidget(self.prompt_provider)
        provider_row.addWidget(QLabel("Modell-ID"))
        provider_row.addWidget(self.prompt_model)
        prompt_layout.addLayout(provider_row)
        refresh_models = QPushButton("Verfügbare OpenAI-Modelle abrufen")
        refresh_models.clicked.connect(self.refresh_openai_models)
        prompt_layout.addWidget(refresh_models)
        self.output_budget = QComboBox()
        self.output_budget.addItems(["4096", "8192", "12000", "16000", "24000", "32000", "65536"])
        self.output_budget.setCurrentText("12000")
        self.output_budget.currentTextChanged.connect(self.invalidate_prompt_preview)
        prompt_layout.addWidget(QLabel("Maximale Output-Tokens (einschließlich Reasoning; höhere Werte können mehr kosten)"))
        prompt_layout.addWidget(self.output_budget)
        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("OpenAI API-Key (nur für diese Sitzung; nicht gespeichert)")
        self.api_key.textChanged.connect(self.invalidate_prompt_preview)
        key_row.addWidget(QLabel("OpenAI API-Key"))
        key_row.addWidget(self.api_key)
        prompt_layout.addLayout(key_row)
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
        tabs.addTab(self.scroll_tab(prompt_tab), "Prompt Studio")
        layout.addWidget(tabs)
        self.setCentralWidget(root)
        self.refresh_imports()
        self.refresh_prompt_projects()
        self.refresh()
        self.refresh_prompt_jobs()

    @staticmethod
    def scroll_tab(widget):
        """Scroll contents instead of forcing the top-level window beyond taskbar."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def invalidate_prompt_preview(self, *_):
        self.send_button.setEnabled(False)

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
        elif self.prompt_project.count() > 1:
            self.prompt_project.setCurrentIndex(1)
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
            index = self.job_project.findData(previous_job_project) if previous_job_project else 0
            self.job_project.setCurrentIndex(max(0, index))
            self.job_project.blockSignals(False)

    def refresh_openai_models(self):
        if self.prompt_provider.currentText() != "OpenAI":
            QMessageBox.information(self, "Modelle", "Bitte zuerst OpenAI als Anbieter auswählen.")
            return
        self.model_worker = ModelListWorker(self.api_key.text().strip() or None)
        self.model_worker.succeeded.connect(self.models_received)
        self.model_worker.failed.connect(lambda msg: QMessageBox.warning(self, "Modellabfrage", msg))
        self.model_worker.finished.connect(self.model_worker.deleteLater)
        self.model_worker.start()

    def models_received(self, models):
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
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Antworten", str(exc))

    def request_final_prompt(self):
        try:
            job_id, source = self.active_workflow()
            state = job_workflow.ensure(self.db, job_id, source)
            if state["status"] not in ("ANSWERED", "FINAL_REVIEW", "READY"):
                raise ValueError("Bitte zuerst die Rückfragen prüfen und beantworten.")
            self.prompt_mode.setCurrentText("Prompt optimieren")
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
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Freigabe", str(exc))

    def prepare_prompt(self):
        try:
            root = self.prompt_project.currentData()
            context = "Kein Projektkontext ausgewählt."
            if root:
                row = self.db.execute("SELECT report_json FROM imported_projects WHERE root=?", (root,)).fetchone()
                if not row:
                    raise ValueError("Projekt nicht gefunden.")
                validate_project_root(root)
                context = collect_context(root, json.loads(row[0]))
            task = self.prompt_task.toPlainText()
            if self.prompt_mode.currentText() == "Prompt optimieren" and self.workflow_request and self.workflow_request[0] == "final":
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

    def send_prompt(self):
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
        self.send_button.setEnabled(False)
        self.prompt_result.setPlainText("Anfrage läuft …")
        self.worker = PromptWorker(identity[2], identity[3], self.prepared_payload, identity[4], self.api_key.text().strip() if identity[2] == "OpenAI" else None, int(identity[5]))
        self.worker.succeeded.connect(self.prompt_success)
        self.worker.failed.connect(self.prompt_failure)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def prompt_success(self, text):
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
                if state and state["source_description"] == source:
                    self.final_prompt.setPlainText(text)
            self.load_workflow()
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Workflow", str(exc))

    def prompt_failure(self, error):
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
        self.job_project.setCurrentIndex(0)
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
