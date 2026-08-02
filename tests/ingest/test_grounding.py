from decimal import Decimal

from epyhia.ingest.grounding import build_grounding_set, set_difference
from epyhia.ingest.normalise import GroundingEntry, find_amounts

_BRIEF = {
    "products": [
        {
            "name": "Basic",
            "price_minor": 12000,
            "currency_display": "EUR",
            "currency_charge": "USD",
            "features": ["one", "two"],
            "not_covered": ["three"],
        },
        {
            "name": "Pro",
            "price_minor": 20000,
            "currency_display": "EUR",
            "currency_charge": "USD",
            "features": ["one", "two", "three"],
            "not_covered": [],
        },
    ],
    "voice": {"adjectives": ["bold", "warm"], "do": ["show up"], "dont": ["shout", "lie"]},
    "established": 2015,
}


def _all_entries(grounding_set: dict) -> set[tuple[str, str | None]]:
    return {
        (e["value"], e["currency"]) for e in grounding_set["literal"] + grounding_set["derived"]
    }


def test_five_derivation_families_produced_exactly() -> None:
    grounding_set = build_grounding_set(_BRIEF, current_year=2026)
    entries = _all_entries(grounding_set)

    # 1. x12 / x52 annualisation.
    assert ("144000", "USD") in entries  # 12000 * 12
    assert ("624000", "USD") in entries  # 12000 * 52
    assert ("240000", "USD") in entries  # 20000 * 12
    assert ("1040000", "USD") in entries  # 20000 * 52

    # 2. pairwise sum / absolute difference.
    assert ("32000", "USD") in entries  # 12000 + 20000
    assert ("8000", "USD") in entries  # |12000 - 20000|

    # 3. list cardinalities.
    assert ("2", None) in entries  # len(products)
    assert ("3", None) in entries  # len(voice.dont) and len(Pro.features)
    assert ("1", None) in entries  # len(Basic.not_covered) and len(voice.do)

    # 4. current_year - established.
    assert ("11", None) in entries  # 2026 - 2015

    # 5. currency-label restatement, unconverted.
    assert ("12000", "EUR") in entries
    assert ("20000", "EUR") in entries


def test_same_number_written_four_ways_all_match() -> None:
    grounding_set = build_grounding_set(_BRIEF, current_year=2026)

    written_forms = [
        "Our Basic plan is $120.00 a month.",
        "Basic is priced at 120.00 USD.",
        "Basic is priced at USD 120.00.",
        "Basic is priced at one hundred twenty dollars.",
    ]
    for text in written_forms:
        extracted = find_amounts(text, "en-US")
        assert extracted, f"expected an amount extracted from: {text!r}"
        assert set_difference(extracted, grounding_set) == []


def test_currency_label_restatement_matches_without_conversion() -> None:
    grounding_set = build_grounding_set(_BRIEF, current_year=2026)

    extracted = find_amounts("In Europe, Basic costs €120.00.", "en-US")
    assert extracted == [GroundingEntry(value=Decimal("12000"), currency="EUR")]
    assert set_difference(extracted, grounding_set) == []


def test_fabricated_numeral_reported_as_violation() -> None:
    grounding_set = build_grounding_set(_BRIEF, current_year=2026)

    extracted = find_amounts("A hidden fee of $999.00 applies.", "en-US")
    violations = set_difference(extracted, grounding_set)

    assert violations == [GroundingEntry(value=Decimal("99900"), currency="USD")]
