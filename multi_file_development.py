"""Bounded read-only source context and atomic approved multi-file edits."""
import difflib
import hashlib
import os
import tempfile
from pathlib import Path

from git_preflight import git_preflight
from project_proposal import parse_project_proposal

SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
EXTENSIONS = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".html", ".css", ".js"}
MAX_FILES = 35
MAX_BYTES = 85_000


def project_source_context(root):
    base = Path(root).resolve(strict=True)
    output = []
    used = 0
    paths = sorted(base.rglob("*"), key=lambda p: (len(p.parts), str(p).lower()))
    for path in paths:
        if any(part in SKIP or part.startswith(".env") for part in path.relative_to(base).parts):
            continue
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXTENSIONS:
            continue
        if len(output) >= MAX_FILES or used >= MAX_BYTES:
            break
        if path.stat().st_size > 24_000:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        size = len(body.encode("utf-8"))
        if used + size > MAX_BYTES:
            continue
        output.append((path.relative_to(base).as_posix(), body))
        used += size
    return output


def _target(base, relative):
    target = base
    for component in relative.split("/"):
        target = target / component
        if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
            raise ValueError("Symlink/Junction verboten: " + relative)
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("Dateipfad außerhalb des Projekts.")
    return target


def review_changes(root, proposal):
    parsed = parse_project_proposal(__import__("json").dumps(proposal, ensure_ascii=False))
    base = Path(root).resolve(strict=True)
    changes = []
    for entry in parsed["files"]:
        path = entry["path"]
        target = _target(base, path)
        if target.exists() and not target.is_file():
            raise ValueError("Kein regulärer Dateipfad: " + path)
        old = target.read_bytes() if target.exists() else None
        if old is not None and len(old) > 120_000:
            raise ValueError("Bestehende Datei zu groß: " + path)
        try:
            old_text = old.decode("utf-8") if old is not None else ""
        except UnicodeError as exc:
            raise ValueError("Bestehende Datei ist kein UTF-8-Text: " + path) from exc
        new_text = entry["content"]
        if old_text == new_text:
            raise ValueError("Unveränderte Datei im Vorschlag: " + path)
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile="a/" + path if old is not None else "/dev/null",
            tofile="b/" + path))
        changes.append({"path": path, "old_sha": hashlib.sha256(old).hexdigest() if old is not None else None,
                        "content": new_text, "diff": diff})
    return changes


def apply_changes(root, proposal, expected_commit, expected_review, approved=False):
    if not approved:
        raise ValueError("Ausdrückliche Freigabe erforderlich.")
    info = git_preflight(root)
    if not info["clean"] or info["commit"] != expected_commit:
        raise ValueError("Git-Stand geändert; erneute Vorschau erforderlich.")
    base = Path(info["root"]).resolve(strict=True)
    current = review_changes(base, proposal)
    if [(x["path"], x["old_sha"], x["content"]) for x in current] != [
        (x["path"], x["old_sha"], x["content"]) for x in expected_review
    ]:
        raise ValueError("Dateien oder Vorschlag wurden seit der Freigabe verändert.")
    originals = {}
    temps = []
    created_dirs = []
    replaced = []
    try:
        for change in current:
            target = _target(base, change["path"])
            originals[target] = target.read_bytes() if target.exists() else None
            missing = []
            parent = target.parent
            while not parent.exists() and parent != base:
                missing.append(parent)
                parent = parent.parent
            for folder in reversed(missing):
                folder.mkdir()
                created_dirs.append(folder)
            fd, name = tempfile.mkstemp(prefix=".agentfactory-", dir=str(target.parent))
            temps.append((target, Path(name)))
            with os.fdopen(fd, "wb") as handle:
                handle.write(change["content"].encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        for target, temp in temps:
            before = originals[target]
            now = target.read_bytes() if target.exists() else None
            if now != before:
                raise ValueError("Datei während der Übernahme verändert: " + str(target))
            os.replace(temp, target)
            replaced.append(target)
        return [change["path"] for change in current]
    except Exception:
        for target in reversed(replaced):
            before = originals[target]
            if before is None:
                target.unlink(missing_ok=True)
            else:
                fd, name = tempfile.mkstemp(prefix=".agentfactory-rollback-", dir=str(target.parent))
                with os.fdopen(fd, "wb") as handle:
                    handle.write(before)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, target)
        raise
    finally:
        for _, temp in temps:
            temp.unlink(missing_ok=True)
        for folder in reversed(created_dirs):
            try:
                folder.rmdir()
            except OSError:
                pass
