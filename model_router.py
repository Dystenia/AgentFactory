"""Minimal, opt-in model routing. No file writes or automatic provider fallback."""
import json
import os
import urllib.request
import urllib.error

class ModelError(RuntimeError):
    pass

def generate(provider, model, system_prompt, user_prompt, timeout=45, api_key=None):
    if not model or not model.strip():
        raise ModelError("Bitte Modellnamen angeben.")
    if provider == "OpenAI":
        key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not key:
            raise ModelError("OPENAI_API_KEY fehlt. Bitte als Umgebungsvariable setzen.")
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": "Bearer " + key}
        payload = {"model": model.strip(), "instructions": system_prompt,
                   "input": user_prompt, "max_output_tokens": 1400, "store": False}
    elif provider == "LM Studio (lokal)":
        url = "http://127.0.0.1:1234/v1/chat/completions"
        headers = {}
        payload = {"model": model.strip(), "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}], "max_tokens": 1400}
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
        raise ModelError("Der Anbieter hat keinen Text zurückgegeben.")
    return result
