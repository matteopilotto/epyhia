from decimal import Decimal
from itertools import combinations

from epyhia.ingest.extractors import extract_structured_strings
from epyhia.ingest.normalise import GroundingEntry, find_amounts

# The closed derivation set (research.md R6). Exactly these five families, enumerated
# once, here — nothing at runtime, least of all a model, may extend it (FR-005,
# Principle VI).


def _entry_dict(entry: GroundingEntry) -> dict:
    return {"value": str(entry.value), "currency": entry.currency}


def _entry_from_dict(raw: dict) -> GroundingEntry:
    return GroundingEntry(value=Decimal(raw["value"]), currency=raw.get("currency"))


def _literal_entries(brief: dict) -> list[GroundingEntry]:
    entries = [
        GroundingEntry(value=Decimal(product["price_minor"]), currency=product["currency_charge"])
        for product in brief["products"]
    ]
    entries.append(GroundingEntry(value=Decimal(brief["established"]), currency=None))

    # FR-004 is "every numeral in the brief", not every numeric field. The brief states
    # durations, weights and counts in its prose as well — a numeral the client gave us
    # that is missing here makes the client's own words read as a fabrication.
    for text in extract_structured_strings(brief):
        entries.extend(find_amounts(text, brief["locale"]))

    return entries


def _derived_entries(brief: dict, current_year: int) -> list[GroundingEntry]:
    entries: list[GroundingEntry] = []
    products = brief["products"]

    # 1. x12 and x52 annualisation of each product price.
    for product in products:
        price = Decimal(product["price_minor"])
        currency = product["currency_charge"]
        entries.append(GroundingEntry(value=price * 12, currency=currency))
        entries.append(GroundingEntry(value=price * 52, currency=currency))

    # 2. Pairwise sums and pairwise absolute differences of stated prices.
    for a, b in combinations(products, 2):
        price_a, price_b = Decimal(a["price_minor"]), Decimal(b["price_minor"])
        currency = a["currency_charge"] if a["currency_charge"] == b["currency_charge"] else None
        entries.append(GroundingEntry(value=price_a + price_b, currency=currency))
        entries.append(GroundingEntry(value=abs(price_a - price_b), currency=currency))

    # 3. Cardinality of every list in the brief.
    entries.append(GroundingEntry(value=Decimal(len(products)), currency=None))
    for product in products:
        entries.append(GroundingEntry(value=Decimal(len(product["features"])), currency=None))
        entries.append(GroundingEntry(value=Decimal(len(product["not_covered"])), currency=None))
    voice = brief["voice"]
    entries.append(GroundingEntry(value=Decimal(len(voice["adjectives"])), currency=None))
    entries.append(GroundingEntry(value=Decimal(len(voice["do"])), currency=None))
    entries.append(GroundingEntry(value=Decimal(len(voice["dont"])), currency=None))

    # 4. current_year - established.
    elapsed = Decimal(current_year - brief["established"])
    entries.append(GroundingEntry(value=elapsed, currency=None))

    # 5. Each literal restated under the product's other currency label, unconverted.
    for product in products:
        entries.append(
            GroundingEntry(
                value=Decimal(product["price_minor"]), currency=product["currency_display"]
            )
        )

    return entries


def build_grounding_set(brief: dict, current_year: int) -> dict:
    """Extracts every numeral in the brief and expands it with the closed derivation
    set, before any expensive work begins (FR-004, FR-005)."""
    return {
        "literal": [_entry_dict(e) for e in _literal_entries(brief)],
        "derived": [_entry_dict(e) for e in _derived_entries(brief, current_year)],
    }


def _matches(entry: GroundingEntry, pool: list[GroundingEntry]) -> bool:
    for candidate in pool:
        if entry.value != candidate.value:
            continue
        no_currency = entry.currency is None or candidate.currency is None
        if no_currency or entry.currency == candidate.currency:
            return True
    return False


def set_difference(extracted: list[GroundingEntry], grounding_set: dict) -> list[GroundingEntry]:
    """Every extracted numeral not covered by `literal ∪ derived`. Matching is value
    equality plus currency compatibility (research.md R6)."""
    pool = [_entry_from_dict(e) for e in grounding_set["literal"] + grounding_set["derived"]]
    return [entry for entry in extracted if not _matches(entry, pool)]
