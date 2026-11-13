"""Read-only Git preflight for an explicitly selected project root."""
import subprocess
from project_access import validate_project_root


def git_preflight(path, timeout=12):
    root = validate_project_root(path)

    def run(*args):
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, check=False,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ValueError("Git ist nicht installiert oder nicht im PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Git-Prüfung hat das Zeitlimit überschritten.") from exc
        if result.returncode:
            raise ValueError("Git-Prüfung fehlgeschlagen: " + (result.stderr.strip() or "Unbekannter Fehler")[:350])
        return result.stdout.strip()

    top = run("rev-parse", "--show-toplevel")
    if validate_project_root(top) != root:
        raise ValueError("Der gewählte Projektordner ist nicht die Wurzel des Git-Repositories.")
    branch = run("symbolic-ref", "--quiet", "--short", "HEAD") if run("symbolic-ref", "--quiet", "HEAD") else ""
    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "root": str(root), "branch": branch or "(detached HEAD)",
        "commit": commit, "clean": not bool(status),
        "changes": status.splitlines()[:100],
        "truncated": len(status.splitlines()) > 100,
    }


def format_preflight(info):
    changes = "\n".join(info["changes"]) if info["changes"] else "Keine"
    return (
        f"Projekt: {info['root']}\nBranch: {info['branch']}\n"
        f"Commit: {info['commit']}\n"
        f"Arbeitsverzeichnis: {'Sauber' if info['clean'] else 'Änderungen vorhanden'}\n"
        f"Änderungen (max. 100):\n{changes}\n"
        + ("Weitere Änderungen nicht angezeigt.\n" if info["truncated"] else "")
        + "\nNur lesende Git-Befehle; keine Dateien geändert."
    )
