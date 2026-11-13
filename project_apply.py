"""Explicitly approved, bounded multi-file proposal application. No execution or Git push."""
import os
import tempfile
from pathlib import Path

from git_preflight import git_preflight
from project_proposal import parse_project_proposal


def apply_project_proposal(root, proposal, expected_commit, approved=False):
    if not approved:
        raise ValueError("Ausdrückliche Freigabe erforderlich.")
    info = git_preflight(root)
    if not info["clean"] or info["commit"] != expected_commit:
        raise ValueError("Git-Stand hat sich geändert. Vorschlag erneut prüfen.")
    base = Path(info["root"])
    parsed = parse_project_proposal(__import__("json").dumps(proposal, ensure_ascii=False))
    targets = []
    for entry in parsed["files"]:
        target = base
        for part in entry["path"].split("/"):
            target = target / part
            if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
                raise ValueError("Symlink/Junction im Dateipfad verboten: " + entry["path"])
        if target.exists():
            raise ValueError("Datei existiert bereits; bestehende Dateien werden nicht überschrieben: " + entry["path"])
        if not target.resolve().is_relative_to(base.resolve()):
            raise ValueError("Dateipfad außerhalb des Projekts.")
        targets.append((target, entry["content"].encode("utf-8")))
    created = []
    directories = []
    pending = []
    try:
        for target, body in targets:
            missing = []
            parent = target.parent
            while not parent.exists() and parent != base:
                missing.append(parent)
                parent = parent.parent
            for folder in reversed(missing):
                folder.mkdir()
                directories.append(folder)
            fd, name = tempfile.mkstemp(prefix=".agentfactory-", dir=str(target.parent))
            pending.append(Path(name))
            with os.fdopen(fd, "wb") as out:
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
        for (target, _), temp in zip(targets, pending):
            if target.exists() or target.is_symlink():
                raise ValueError("Zieldatei wurde zwischenzeitlich erstellt: " + str(target))
            os.rename(temp, target)
            created.append(target)
        return [str(path.relative_to(base)).replace("\\", "/") for path in created]
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        for path in pending:
            path.unlink(missing_ok=True)
        for folder in reversed(directories):
            try:
                folder.rmdir()
            except OSError:
                pass
