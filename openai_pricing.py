"""Conservative OpenAI standard short-context price reader.

Only exact model IDs in the official Standard markdown table are accepted.
No pricing is inferred from the Models API, model prefixes or other modes.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

PRICING_URL = "https://developers.openai.com/api/docs/pricing.md"


class PricingLookupError(ValueError):
    pass


def parse_standard_prices(markdown):
    marker = "### Standard pricing data"
    start = markdown.find(marker)
    if start < 0:
        raise PricingLookupError("Offizielle Standard-Preistabelle nicht gefunden.")
    end = markdown.find("\nBatch", start)
    section = markdown[start:end if end >= 0 else None]
    prices = {}
    for line in section.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith(("gpt-", "o")):
            continue
        model = cells[0]
        # Ignore annotated names and aliases; exact IDs only.
        if any(ch in model for ch in " ()<>"):
            continue
        try:
            incoming = Decimal(cells[1].removeprefix("$"))
            outgoing = Decimal(cells[2].removeprefix("$"))
        except InvalidOperation:
            continue
        if not incoming.is_finite() or not outgoing.is_finite() or incoming < 0 or outgoing < 0:
            continue
        if model in prices:
            raise PricingLookupError("Mehrdeutiger Modellpreis: " + model)
        prices[model] = {"input": str(incoming), "output": str(outgoing)}
    if not prices:
        raise PricingLookupError("Keine eindeutigen Standardpreise erkannt.")
    return prices


def fetch_standard_prices(timeout=12):
    request = Request(PRICING_URL, headers={"User-Agent": "AgentFactory/0.4 (pricing lookup)", "Accept": "text/markdown"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(512_001)
    except Exception as exc:
        raise PricingLookupError("Offizielle Preisseite nicht erreichbar: " + str(exc)) from exc
    if len(data) > 512_000:
        raise PricingLookupError("Preisdokument überschreitet die Sicherheitsgrenze.")
    try:
        prices = parse_standard_prices(data.decode("utf-8"))
    except UnicodeError as exc:
        raise PricingLookupError("Ungültige Kodierung der Preisseite.") from exc
    return {"prices": prices, "retrieved_at": datetime.now(timezone.utc).date().isoformat(),
            "source": PRICING_URL, "mode": "Standard / short context"}
