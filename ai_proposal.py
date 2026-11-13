"""Strict one-file AI proposal parser. Never executes generated text."""
import json
from pathlib import Path


class ProposalError(ValueError):
    pass


def parse_proposal(raw, requested_path):
    if not isinstance(raw, str) or len(raw) > 500_000:
        raise ProposalError("KI-Antwort fehlt oder ist zu groß.")
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or not lines[-1].strip() == "```":
            raise ProposalError("Ungültiger JSON-Codeblock.")
        text = "\n".join(lines[1:-1])
        if text.lstrip().startswith("json\n"):
            text = text.lstrip()[5:]
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ProposalError("KI-Antwort ist kein gültiges JSON.") from exc
    if not isinstance(data, dict) or set(data) != {"path", "content", "summary"}:
        raise ProposalError("Erwartet werden exakt path, content und summary.")
    if not all(isinstance(data[key], str) for key in data):
        raise ProposalError("Alle Felder müssen Text sein.")
    path = data["path"]
    rel = Path(path)
    if not path or rel.is_absolute() or ".." in rel.parts or path != requested_path or "\\" in path:
        raise ProposalError("KI-Vorschlag betrifft nicht die angeforderte Datei.")
    if len(data["content"].encode("utf-8")) > 250_000:
        raise ProposalError("Vorgeschlagener Dateiinhalt ist zu groß.")
    return data
