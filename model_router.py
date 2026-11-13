"""Minimal, opt-in model routing. No file writes or automatic provider fallback."""
import json
import os
import urllib.request
import urllib.error

class ModelError(RuntimeError):
    pass

def generate(provider, model, system_prompt, user_prompt, timeout=180, api_key=None, max_output_tokens=12000, return_usage=False):
    if not isinstance(max_output_tokens, int) or not 1024 <= max_output_tokens <= 65536:
        raise ModelError('Output-Tokenbudget muss zwischen 1024 und 65536 liegen.')
    if not model or not model.strip():
        raise ModelError("Bitte Modellnamen angeben.")
    if provider == "OpenAI":
        key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not key:
            raise ModelError("OPENAI_API_KEY fehlt. Bitte als Umgebungsvariable setzen.")
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": "Bearer " + key}
        payload = {"model": model.strip(), "instructions": system_prompt,
                   "input": user_prompt, "max_output_tokens": max_output_tokens, "store": False}
    elif provider == "LM Studio (lokal)":
        url = "http://127.0.0.1:1234/v1/chat/completions"
        headers = {}
        payload = {"model": model.strip(), "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}], "max_tokens": max_output_tokens}
    else:
        raise ModelError("Unbekannter Modellanbieter.")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Avoid leaking request contents or auth headers in error messages.
        raise ModelError(f"Anbieter meldet HTTP {exc.code}. Modell und API-Zugriff prüfen.") from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise ModelError(f"Verbindung oder Antwort fehlgeschlagen: {type(exc).__name__}") from None
    if provider == "OpenAI":
        parts = [part.get("text", "") for item in data.get("output", [])
                 if item.get("type") == "message" for part in item.get("content", [])
                 if part.get("type") == "output_text"]
        result = "\n".join(parts).strip()
    else:
        choices = data.get("choices", [])
        result = choices[0].get("message", {}).get("content", "").strip() if choices else ""
    if not result:
        if provider == "OpenAI":
            details = data.get("incomplete_details") or {}
            if data.get("status") == "incomplete" and details.get("reason") == "max_output_tokens":
                raise ModelError(
                    f"Output-Tokenlimit ({max_output_tokens}) erreicht, ohne sichtbare Antwort. "
                    "Bitte Tokenbudget erhöhen oder ein weniger aufwendiges Modell wählen."
                )
            if data.get("error"):
                raise ModelError("OpenAI meldet einen Fehler in der Antwort.")
            raise ModelError(
                f"OpenAI hat keinen sichtbaren Antworttext geliefert (Status: {data.get('status', 'unbekannt')}). "
                "Bitte Modell und Tokenbudget prüfen."
            )
        raise ModelError("Der lokale Anbieter hat keinen Text zurückgegeben.")
    if return_usage:
        from cost_budget import usage_from_response
        return result, usage_from_response(provider, data)
    return result

def list_openai_models(api_key=None, timeout=20):
    """Fetch accessible GPT model IDs; never log or persist credentials."""
    key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not key:
        raise ModelError("OpenAI API-Key fehlt.")
    req = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": "Bearer " + key}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ModelError(f"Modellabfrage fehlgeschlagen (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ModelError("Modellabfrage: Verbindungsfehler oder ungültige Antwort.") from None
    models = sorted({
        item["id"] for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
        and item["id"].startswith("gpt-")
        and "realtime" not in item["id"] and "audio" not in item["id"]
        and "image" not in item["id"] and "transcribe" not in item["id"]
    })
    if not models:
        raise ModelError("Keine passenden GPT-Modelle für diesen API-Key gefunden.")
    return models
