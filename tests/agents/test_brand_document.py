import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from epyhia.agents.strategist import BrandDocument, Offering

CONTRACTS = (
    Path(__file__).resolve().parents[2] / "specs" / "001-epyhia-agency" / "contracts"
)

# Nothing below is a client value: the offerings here are shaped like offerings and say
# nothing about any business (FR-059).
_GENERIC_OFFERING = {
    "name": "Offering A",
    "description": "What this one is.",
    "price_minor": 1234,
    "currency_display": "XTS",
    "billing": "one_time",
    "features": ["included thing"],
    "not_covered": ["excluded thing"],
}

_GENERIC_DOC = {
    "name": "Business",
    "descriptor": "what it is",
    "positioning": "why this one",
    "palette": {"bg": "#101014", "fg": "#f4f4f5", "accent": "#c2410c", "muted": "#71717a"},
    "type": {"display": "Display Face", "body": "Body Face"},
    "motion_language": "mechanical, deliberate",
    "composition_archetype": "editorial_stack",
    "video_archetype": "technical_spec_sheet",
    "voice": {"adjectives": ["plain"], "do": ["say it once"], "dont": ["no exclamation marks"]},
    "composition_plan": [
        {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"}
    ],
    "offerings": [_GENERIC_OFFERING],
}


def test_a_brand_document_without_offerings_is_rejected() -> None:
    """Required rather than optional, because an optional fact channel is one the Strategist
    omits — and every downstream "state the offerings" rule then points at nothing."""
    without = {k: v for k, v in _GENERIC_DOC.items() if k != "offerings"}
    with pytest.raises(ValidationError):
        BrandDocument.model_validate(without)

    with pytest.raises(ValidationError):
        BrandDocument.model_validate({**_GENERIC_DOC, "offerings": []})


def test_an_offering_mirrors_the_brief_product_field_for_field() -> None:
    """The Strategist is told to copy each product across verbatim. That instruction is only
    mechanical while the two shapes match, so the shapes are compared rather than trusted —
    a field added to the brief's products and not here is a fact with nowhere to arrive."""
    schema = json.loads((CONTRACTS / "brief.schema.json").read_text())
    product_fields = set(schema["properties"]["products"]["items"]["required"])

    # `currency_charge` is Ops' charging detail and belongs on no page, so it is the one
    # field deliberately not carried across.
    assert set(Offering.model_fields) == product_fields - {"currency_charge"}


def test_a_complete_brand_document_round_trips() -> None:
    assert BrandDocument.model_validate(_GENERIC_DOC).model_dump() == _GENERIC_DOC
