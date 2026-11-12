"""Restrict project roots to explicitly selected non-critical project folders."""
from pathlib import Path
import os

def validate_project_root(path):
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Bitte einen Projektordner auswählen.")
    home = Path.home().resolve()
    forbidden = {home, home.parent, Path(root.anchor)}
    for env in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        value = os.environ.get(env)
        if value:
            forbidden.add(Path(value).resolve())
    # Never scan entire drives, Windows/system folders, user profiles or their parents.
    if any(root == f or root in f.parents for f in forbidden):
        raise ValueError("Kritischer System- oder Profilordner: Bitte einen konkreten Projektunterordner auswählen.")
    if root == home or (root == home.parent):
        raise ValueError("Bitte einen konkreten Projektordner auswählen.")
    return root
