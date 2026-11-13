"""Persistent, explicit approval workflow for a saved development job.

No project file writes or code execution occur in this module.
"""
import sqlite3
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc).isoformat()

def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS job_workflows (
        job_id TEXT PRIMARY KEY,
        source_description TEXT NOT NULL,
        questions TEXT NOT NULL DEFAULT '',
        answers TEXT NOT NULL DEFAULT '',
        final_prompt TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        approved_at TEXT,
        updated_at TEXT NOT NULL
    )""")
    conn.commit()

def get(conn, job_id):
    row = conn.execute(
        "SELECT source_description, questions, answers, final_prompt, status, approved_at "
        "FROM job_workflows WHERE job_id=?", (job_id,)
    ).fetchone()
    return dict(zip(("source_description", "questions", "answers", "final_prompt", "status", "approved_at"), row)) if row else None

def ensure(conn, job_id, source):
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        raise ValueError("Entwicklungsauftrag nicht gefunden.")
    current = get(conn, job_id)
    if current and current["source_description"] == source:
        return current
    with conn:
        conn.execute("""INSERT INTO job_workflows
            (job_id, source_description, questions, answers, final_prompt, status, approved_at, updated_at)
            VALUES (?, ?, '', '', '', 'DRAFT', NULL, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                source_description=excluded.source_description, questions='', answers='',
                final_prompt='', status='DRAFT', approved_at=NULL, updated_at=excluded.updated_at
        """, (job_id, source, _now()))
    return get(conn, job_id)

def save_questions(conn, job_id, source, questions):
    ensure(conn, job_id, source)
    if not questions.strip():
        raise ValueError("Die Fragenprüfung enthält keinen Text.")
    with conn:
        conn.execute("""UPDATE job_workflows SET questions=?, answers='', final_prompt='',
            status='CLARIFICATION', approved_at=NULL, updated_at=? WHERE job_id=?""",
            (questions, _now(), job_id))

def save_answers(conn, job_id, answers):
    state = get(conn, job_id)
    if not state or state["status"] != "CLARIFICATION":
        raise ValueError("Zuerst Fragen prüfen und speichern.")
    if not answers.strip():
        raise ValueError("Bitte Antworten eingeben oder ausdrücklich 'Keine Rückfragen' angeben.")
    with conn:
        conn.execute("""UPDATE job_workflows SET answers=?, final_prompt='', status='ANSWERED',
            approved_at=NULL, updated_at=? WHERE job_id=?""", (answers, _now(), job_id))

def save_final(conn, job_id, final_prompt):
    state = get(conn, job_id)
    if not state or state["status"] not in ("ANSWERED", "FINAL_REVIEW", "READY"):
        raise ValueError("Zuerst die Klärungsphase abschließen.")
    if not final_prompt.strip():
        raise ValueError("Der finale Auftrag darf nicht leer sein.")
    with conn:
        conn.execute("""UPDATE job_workflows SET final_prompt=?, status='FINAL_REVIEW',
            approved_at=NULL, updated_at=? WHERE job_id=?""",
            (final_prompt, _now(), job_id))

def approve(conn, job_id, displayed_prompt):
    state = get(conn, job_id)
    if not state or state["status"] != "FINAL_REVIEW":
        raise ValueError("Zuerst den finalen Auftrag speichern und prüfen.")
    if not displayed_prompt.strip() or displayed_prompt != state["final_prompt"]:
        raise ValueError("Finaler Auftrag wurde verändert. Bitte erneut speichern.")
    with conn:
        conn.execute("""UPDATE job_workflows SET status='READY', approved_at=?, updated_at=?
            WHERE job_id=?""", (_now(), _now(), job_id))

def bind_project(conn, job_id, root):
    """Bind an imported project to a job; revoke approval if the binding changes."""
    project = conn.execute("SELECT 1 FROM imported_projects WHERE root=?", (root,)).fetchone()
    if not project:
        raise ValueError("Bitte zuerst ein gespeichertes Codeprojekt auswählen.")
    job = conn.execute("SELECT project_root FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        raise ValueError("Entwicklungsauftrag nicht gefunden.")
    if (job[0] or "") == root:
        return False
    with conn:
        conn.execute("UPDATE jobs SET project_root=? WHERE id=?", (root, job_id))
        state = get(conn, job_id)
        if state:
            status = "FINAL_REVIEW" if state["final_prompt"].strip() else "DRAFT"
            conn.execute("UPDATE job_workflows SET status=?, approved_at=NULL, updated_at=? WHERE job_id=?",
                         (status, _now(), job_id))
    return True

