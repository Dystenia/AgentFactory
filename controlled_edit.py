"""Explicitly approved, bounded text replacement in a clean Git worktree.

This is not an OS sandbox. Do not pass untrusted paths to a privileged process.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
from pathlib import Path


class EditRejected(ValueError):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EditRejected("Git-Preflight konnte nicht ausgeführt werden.") from exc
    if result.returncode:
        raise EditRejected("Git-Preflight fehlgeschlagen: " + result.stderr.strip()[:200])
    return result.stdout.strip()


def _target(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise EditRejected("Ungültiger Dateipfad.")
    rel = Path(relative_path)
    if rel.is_absolute() or any(part in ("..", ".") for part in rel.parts):
        raise EditRejected("Nur relative Dateipfade ohne Traversal erlaubt.")
    target = root / rel
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise EditRejected("Symlink/Junction nicht zugelassen.")
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise EditRejected("Nur vorhandene reguläre Dateien erlaubt.")
    return target


def preview(root: str | Path, relative_path: str, expected_sha256: str, replacement: str) -> dict:
    base = Path(root).resolve(strict=True)
    if not base.is_dir() or Path(_git(base, "rev-parse", "--show-toplevel")).resolve() != base:
        raise EditRejected("Projektpfad muss exakt dem Git-Root entsprechen.")
    if _git(base, "status", "--porcelain=v1", "--untracked-files=normal"):
        raise EditRejected("Git-Arbeitsverzeichnis muss sauber sein.")
    if not isinstance(replacement, str):
        raise EditRejected("Ersatzinhalt muss UTF-8-Text sein.")
    target = _target(base, relative_path)
    if _git(base, "ls-files", "--error-unmatch", "--", relative_path) != relative_path.replace('\\', '/'):
        raise EditRejected("Datei muss von Git verfolgt sein.")
    data = target.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if not isinstance(expected_sha256, str) or actual != expected_sha256.lower():
        raise EditRejected("Originaldatei entspricht nicht der freigegebenen Version.")
    return {"root": str(base), "path": relative_path, "before_sha256": actual,
            "after_sha256": hashlib.sha256(replacement.encode('utf-8')).hexdigest(),
            "before_bytes": len(data), "after_bytes": len(replacement.encode('utf-8'))}


def apply(root: str | Path, relative_path: str, expected_sha256: str,
          replacement: str, *, approved: bool = False) -> dict:
    if approved is not True:
        raise EditRejected("Ausdrückliche Benutzerfreigabe fehlt.")
    info = preview(root, relative_path, expected_sha256, replacement)
    target = _target(Path(info['root']), relative_path)
    if hashlib.sha256(target.read_bytes()).hexdigest() != info['before_sha256']:
        raise EditRejected("Datei wurde während der Prüfung verändert.")
    # Atomic replacement on same filesystem; not a defense against hostile concurrent processes.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.agentfactory-',
                                         dir=target.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(replacement.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {**info, "written": True}
