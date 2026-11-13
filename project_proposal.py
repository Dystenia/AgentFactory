"""Validate a bounded, multi-file AI project proposal without executing it."""
import json
from pathlib import PurePosixPath


class ProjectProposalError(ValueError):
    pass


def parse_project_proposal(raw):
    if not isinstance(raw, str) or len(raw) > 900_000:
        raise ProjectProposalError("Projektvorschlag fehlt oder ist zu groß.")
    try:
        data = json.loads(raw.strip())
    except (TypeError, ValueError) as exc:
        raise ProjectProposalError("Projektvorschlag muss ein JSON-Objekt sein.") from exc
    if not isinstance(data, dict) or set(data) != {"summary", "files"}:
        raise ProjectProposalError("Erwartet werden summary und files.")
    if not isinstance(data["summary"], str) or not isinstance(data["files"], list):
        raise ProjectProposalError("Ungültiger Vorschlag.")
    files = data["files"]
    if not 1 <= len(files) <= 12:
        raise ProjectProposalError("Pro Auftrag sind 1 bis 12 Dateien erlaubt.")
    seen = set()
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "content"}:
            raise ProjectProposalError("Jede Datei benötigt path und content.")
        path, body = entry["path"], entry["content"]
        if not isinstance(path, str) or not isinstance(body, str):
            raise ProjectProposalError("Dateipfad und Inhalt müssen Text sein.")
        parts = path.split("/")
        posix = PurePosixPath(path)
        if (not path or len(path) > 180 or path.startswith("/") or "\\" in path
                or ":" in path or any(part in ("", ".", "..") for part in parts)
                or posix.is_absolute() or path.casefold() in seen):
            raise ProjectProposalError("Ungültiger oder doppelter Dateipfad.")
        if any(part.endswith((" ", ".")) for part in parts):
            raise ProjectProposalError("Windows-inkompatibler Dateipfad.")
        if any(part.lower().split(".")[0] in
               {"con", "prn", "aux", "nul", "com1", "com2", "lpt1", "lpt2"}
               for part in parts):
            raise ProjectProposalError("Reservierter Windows-Dateiname.")
        if not path.lower().endswith((".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".html", ".css", ".js", ".svg")):
            raise ProjectProposalError("Dateityp nicht freigegeben: " + path)
        size = len(body.encode("utf-8"))
        if size > 120_000:
            raise ProjectProposalError("Einzeldatei zu groß.")
        total += size
        seen.add(path.casefold())
    if total > 500_000:
        raise ProjectProposalError("Gesamtvorschlag zu groß.")
    return data
