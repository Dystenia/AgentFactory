"""USD budget accounting for AI jobs. Prices must be explicitly verified.

No provider price is assumed; unknown pricing blocks chargeable calls.
All monetary values use Decimal to avoid floating point rounding.
"""
from decimal import Decimal, InvalidOperation

class BudgetError(ValueError):
    pass

def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BudgetError("Ungültiger USD-Betrag.") from exc
    if not result.is_finite() or result < 0:
        raise BudgetError("USD-Betrag muss endlich und nicht negativ sein.")
    return result

def price_record(model, input_per_million, output_per_million, verified_at):
    if not isinstance(model, str) or not model.strip():
        raise BudgetError("Modell fehlt.")
    if not isinstance(verified_at, str) or not verified_at.strip():
        raise BudgetError("Preisstand fehlt. Bitte Anbieterpreise verifizieren.")
    return {"model": model.strip(), "input": str(money(input_per_million)),
            "output": str(money(output_per_million)), "verified_at": verified_at.strip()}

def estimated_cost(input_tokens, output_tokens, price):
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int) or min(input_tokens, output_tokens) < 0:
        raise BudgetError("Tokenzahlen müssen nichtnegative ganze Zahlen sein.")
    return ((Decimal(input_tokens) * money(price["input"]) +
             Decimal(output_tokens) * money(price["output"])) / Decimal(1_000_000))

def check_budget(limit_usd, spent_usd, price, estimated_input_tokens, max_output_tokens):
    limit, spent = money(limit_usd), money(spent_usd)
    if spent >= limit:
        raise BudgetError("USD-Budget erschöpft. Neue Freigabe erforderlich.")
    estimate = estimated_cost(estimated_input_tokens, max_output_tokens, price)
    if spent + estimate > limit:
        raise BudgetError(
            "Geschätzter maximaler API-Aufruf überschreitet das USD-Restbudget. "
            "Budget erhöhen, Tokenlimit reduzieren oder anderes Modell wählen.")
    return estimate

def usage_from_response(provider, response):
    """Normalize usage; None means the provider did not report billable usage."""
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    if provider == "OpenAI":
        a, b = usage.get("input_tokens"), usage.get("output_tokens")
    elif provider == "LM Studio (lokal)":
        a, b = usage.get("prompt_tokens"), usage.get("completion_tokens")
    else:
        return None
    if not isinstance(a, int) or isinstance(a, bool) or not isinstance(b, int) or isinstance(b, bool) or min(a, b) < 0:
        return None
    return {"input_tokens": a, "output_tokens": b}
