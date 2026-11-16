"""Bounded local pytest execution for an explicitly selected project."""
import os
import subprocess
import sys
from pathlib import Path


def run_project_tests(root, timeout=90, max_output=16000):
    """Run pytest without a shell; return a structured, bounded report.

    Tests execute project code and therefore require an explicitly trusted project.
    """
    base = Path(root).resolve(strict=True)
    if not base.is_dir() or not (base / ".git").exists():
        raise ValueError("Testziel muss ein vorhandener Git-Projektordner sein.")
    if not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("Ungültiges Test-Zeitlimit.")
    if not isinstance(max_output, int) or not 1000 <= max_output <= 100000:
        raise ValueError("Ungültige Ausgabelänge.")
    command = [sys.executable, "-m", "pytest", "tests", "-q"]
    if not (base / "tests").is_dir():
        return {"status": "NO_TESTS", "exit_code": None, "output": "Kein tests/-Ordner vorhanden.",
                "command": "python -m pytest tests -q"}
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(command, cwd=str(base), env=env, shell=False,
                                   capture_output=True, text=True, errors="replace",
                                   timeout=timeout)
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return {"status": "PASSED" if completed.returncode == 0 else "FAILED",
                "exit_code": completed.returncode, "output": output[:max_output],
                "command": "python -m pytest tests -q"}
    except subprocess.TimeoutExpired as exc:
        return {"status": "TIMEOUT", "exit_code": None,
                "output": ("Testlauf nach " + str(timeout) + " Sekunden abgebrochen.\n" +
                           str(exc.stdout or "")[:max_output]),
                "command": "python -m pytest tests -q"}
    except OSError as exc:
        return {"status": "ERROR", "exit_code": None, "output": str(exc)[:max_output],
                "command": "python -m pytest tests -q"}
