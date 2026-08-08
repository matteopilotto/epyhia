import json
import uuid
from pathlib import Path

import pytest

from epyhia.gate.adapters.stripe import (
    StripePriceAdapter,
    StripeProductAdapter,
    price_lookup_key,
    product_id_for,
)
from epyhia.gate.errors import VerificationFailed
from epyhia.gate.registry import GateContext
from epyhia.ingest.catalogue import resolve_catalogue

BRIEF_HASH = "0123456789ab" + "f" * 52

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "briefs" / "one.json"


def catalogue() -> list[dict]:
    """Every product fact in this module comes from the fixture brief, never from a literal
    here: a price or a currency written into a test is the same violation as one written into
    source (Principle I, FR-059)."""
    return resolve_catalogue(json.loads(_FIXTURE.read_text())["products"])


class FakeStripe:
    """The two resources the pair touches, in memory. No key, no network, no account."""

    def __init__(self) -> None:
        self.products = FakeResource(assigns_ids=False)
        self.prices = FakeResource(assigns_ids=True)
        # `client.v1.products` reaches the same store as `client.products`, as on the real
        # client.
        self.v1 = self


class FakeResource:
    def __init__(self, *, assigns_ids: bool) -> None:
        self.rows: dict[str, dict] = {}
        self._assigns_ids = assigns_ids

    async def create_async(self, params: dict) -> dict:
        obj = {**params, "active": True}
        if self._assigns_ids:
            # Stripe names prices itself, which is why the price pair verifies through a
            # derived lookup key rather than an id.
            obj["id"] = f"price_{len(self.rows)}"
        self.rows[obj["id"]] = obj
        return obj

    async def retrieve_async(self, object_id: str) -> dict | None:
        return self.rows.get(object_id)

    async def list_async(self, params: dict) -> dict:
        wanted = params["lookup_keys"]
        return {"data": [p for p in self.rows.values() if p.get("lookup_key") in wanted]}


class _Credentials:
    def require(self, provider: str) -> str:
        return "sk_test_stub"


def _ctx() -> GateContext:
    return GateContext(run_id=uuid.uuid4(), credentials=_Credentials())


def product_request(row: dict) -> dict:
    return {
        "brief_hash": BRIEF_HASH,
        "slug": row["slug"],
        "name": row["name"],
        "description": row["description"],
    }


def price_request(row: dict, product_id: str) -> dict:
    return {
        "brief_hash": BRIEF_HASH,
        "slug": row["slug"],
        "product_id": product_id,
        "price_minor": row["price_minor"],
        "currency_charge": row["currency_charge"],
        "billing": row["billing"],
        "billing_interval": row.get("billing_interval"),
        "billing_interval_count": row.get("billing_interval_count"),
    }


async def test_every_row_of_the_brief_becomes_a_product_and_a_price() -> None:
    api = FakeStripe()
    products = StripeProductAdapter(client_factory=lambda _: api)
    prices = StripePriceAdapter(client_factory=lambda _: api)

    for row in catalogue():
        product = await products.execute(product_request(row), _ctx())
        await products.verify(product_request(row), product, _ctx())

        request = price_request(row, product["product_id"])
        price = await prices.execute(request, _ctx())
        evidence = await prices.verify(request, price, _ctx())

        created = api.prices.rows[price["price_id"]]
        assert created["unit_amount"] == row["price_minor"]
        # Charged in the brief's charge currency, not its display currency, and nothing
        # converts between them (FR-003, research.md R6).
        assert created["currency"] == row["currency_charge"].lower()
        assert created["currency"] != row["currency_display"].lower()
        assert evidence["unit_amount"] == row["price_minor"]


async def test_the_recurring_clause_is_the_briefs_own_cadence() -> None:
    api = FakeStripe()
    prices = StripePriceAdapter(client_factory=lambda _: api)

    for row in catalogue():
        request = price_request(row, "prod_stub")
        created = api.prices.rows[(await prices.execute(request, _ctx()))["price_id"]]

        if row["billing"] == "subscription":
            assert created["recurring"] == {
                "interval": row["billing_interval"],
                "interval_count": row["billing_interval_count"],
            }
        else:
            assert "recurring" not in created


async def test_verify_reads_back_by_a_derived_handle_not_by_what_execute_returned() -> None:
    """Both halves derive the same identifier from the request, which is what lets a resumed
    action prove itself with no `result` to trust (§7.4, contracts/action-gate.md §3)."""
    api = FakeStripe()
    row = catalogue()[0]
    products = StripeProductAdapter(client_factory=lambda _: api)
    prices = StripePriceAdapter(client_factory=lambda _: api)

    await products.execute(product_request(row), _ctx())
    request = price_request(row, product_id_for(product_request(row)))
    await prices.execute(request, _ctx())

    assert await products.verify(product_request(row), {}, _ctx())
    assert await prices.verify(request, {}, _ctx())
    assert price_lookup_key(request) in {p["lookup_key"] for p in api.prices.rows.values()}


async def test_a_price_that_drifted_from_the_brief_fails_verification() -> None:
    api = FakeStripe()
    row = catalogue()[0]
    prices = StripePriceAdapter(client_factory=lambda _: api)
    request = price_request(row, "prod_stub")
    price_id = (await prices.execute(request, _ctx()))["price_id"]

    api.prices.rows[price_id]["unit_amount"] = row["price_minor"] + 1

    with pytest.raises(VerificationFailed):
        await prices.verify(request, {"price_id": price_id}, _ctx())


async def test_a_missing_object_fails_verification_rather_than_succeeding() -> None:
    api = FakeStripe()
    row = catalogue()[0]

    with pytest.raises(VerificationFailed):
        await StripeProductAdapter(client_factory=lambda _: api).verify(
            product_request(row), {}, _ctx()
        )
    with pytest.raises(VerificationFailed):
        await StripePriceAdapter(client_factory=lambda _: api).verify(
            price_request(row, "prod_stub"), {}, _ctx()
        )
