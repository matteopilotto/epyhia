import json
from pathlib import Path

from epyhia.ingest.catalogue import catalogue_hash, resolve_catalogue, slugify

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "briefs" / "one.json"


def _products() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["products"]


def test_slug_is_url_safe_and_folds_accents():
    assert slugify("Crème Brûlée, 2 for 1!") == "creme-brulee-2-for-1"


def test_every_brief_product_yields_a_row_carrying_its_own_fields_unchanged():
    """No conversion, no rounding, no defaulting — the row is the brief's, plus the slug
    (FR-003, research.md R6)."""
    products = _products()
    catalogue = resolve_catalogue(products)

    assert [row["slug"] for row in catalogue] == [slugify(p["name"]) for p in products]
    for row, product in zip(catalogue, products, strict=True):
        assert {k: row[k] for k in product} == product


def test_hash_changes_when_a_price_changes():
    """The `arm_charge_path` key is derived from this, so an edited price must not
    short-circuit onto the approval given for the old one (§7.2)."""
    catalogue = resolve_catalogue(_products())
    repriced = [dict(catalogue[0], price_minor=catalogue[0]["price_minor"] + 1), *catalogue[1:]]

    assert catalogue_hash(catalogue) != catalogue_hash(repriced)
