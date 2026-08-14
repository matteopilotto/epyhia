import json
import uuid
from pathlib import Path

import pytest
import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate.adapters.stripe import (
    ArmChargePathAdapter,
    CheckoutSessionAdapter,
    StripeCallFailed,
    StripePriceAdapter,
    StripeProductAdapter,
    plain,
    price_lookup_key,
    product_id_for,
)
from epyhia.gate.errors import VerificationFailed
from epyhia.gate.registry import GateContext
from epyhia.ingest.catalogue import resolve_catalogue
from tests.stripe_stub import FakeStripe

BRIEF_HASH = "0123456789ab" + "f" * 52

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "briefs" / "one.json"


def catalogue() -> list[dict]:
    """Every product fact in this module comes from the fixture brief, never from a literal
    here: a price or a currency written into a test is the same violation as one written into
    source (Principle I, FR-059)."""
    return resolve_catalogue(json.loads(_FIXTURE.read_text())["products"])


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
            # `plain()` because the provider hands back a nested object, not a mapping —
            # comparing one to a dict is always false (see `stripe_stub`).
            assert plain(created["recurring"]) == {
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


async def test_the_same_brief_twice_reuses_the_catalogue_it_already_made() -> None:
    """A re-run is a new `runs` row with new `actions` rows, so the gate's ledger correctly
    says "never done" while Stripe says "already there" — the derived product id and the
    derived lookup key both land on objects the first run created. Reaching them is the
    intended outcome of the same brief twice, not a failure (§7.2, FR-044)."""
    api = FakeStripe()
    row = catalogue()[0]
    products = StripeProductAdapter(client_factory=lambda _: api)
    prices = StripePriceAdapter(client_factory=lambda _: api)
    request = price_request(row, product_id_for(product_request(row)))

    first_product = await products.execute(product_request(row), _ctx())
    first = await prices.execute(request, _ctx())

    second_product = await products.execute(product_request(row), _ctx())
    second = await prices.execute(request, _ctx())

    assert second_product == first_product
    assert second == first
    assert len(api.products.rows) == 1
    assert len(api.prices.rows) == 1

    # And the truth still comes from the probe, over an object this pass did not create.
    evidence = await prices.verify(request, second, _ctx())
    assert evidence["price_id"] == first["price_id"]
    assert evidence["unit_amount"] == row["price_minor"]


async def test_a_repriced_row_is_a_new_price_rather_than_a_reused_one() -> None:
    """What the amount-in-the-key was for: the reuse above holds only because the key carries
    the amount, so a catalogue priced differently cannot silently sell at the old price."""
    api = FakeStripe()
    row = catalogue()[0]
    prices = StripePriceAdapter(client_factory=lambda _: api)
    request = price_request(row, "prod_stub")
    repriced = {**request, "price_minor": request["price_minor"] + 1}

    first = await prices.execute(request, _ctx())
    second = await prices.execute(repriced, _ctx())

    assert price_lookup_key(repriced) != price_lookup_key(request)
    assert second["price_id"] != first["price_id"]
    assert len(api.prices.rows) == 2
    assert (await prices.verify(repriced, {}, _ctx()))["unit_amount"] == repriced["price_minor"]


async def test_a_collision_with_no_findable_price_still_fails_loudly() -> None:
    """The fallback recovers a price it can read back. A refusal it cannot explain that way is
    a genuine failure and must stay one — falling open here would deploy a charge path nobody
    proved."""
    api = FakeStripe()
    row = catalogue()[0]
    prices = StripePriceAdapter(client_factory=lambda _: api)

    async def refuse(params: dict) -> None:
        raise stripe.InvalidRequestError("A price already uses that lookup key.", "lookup_key")

    api.prices.create_async = refuse

    with pytest.raises(StripeCallFailed):
        await prices.execute(price_request(row, "prod_stub"), _ctx())


async def test_an_archived_price_sharing_the_key_does_not_shadow_the_active_one() -> None:
    """Stripe's uniqueness constraint is over active prices only, so archiving one frees the
    key for a second — and a listing that asks for a single row lets the provider choose which
    of the two answers."""
    api = FakeStripe()
    row = catalogue()[0]
    prices = StripePriceAdapter(client_factory=lambda _: api)
    request = price_request(row, "prod_stub")

    archived = await prices.execute(request, _ctx())
    api.prices.rows[archived["price_id"]]["active"] = False
    live = await prices.execute(request, _ctx())

    assert live["price_id"] != archived["price_id"]
    assert (await prices.verify(request, {}, _ctx()))["price_id"] == live["price_id"]


async def _armed_request(api: FakeStripe) -> dict:
    """The catalogue as Ops leaves it: the brief's own rows, each carrying the price id its
    `stripe_price` action produced."""
    prices = StripePriceAdapter(client_factory=lambda _: api)
    priced = []
    for row in catalogue():
        request = price_request(row, "prod_stub")
        created = await prices.execute(request, _ctx())
        priced.append({**row, "price_id": created["price_id"]})
    return {"catalogue": priced}


async def test_arming_requires_approval_and_re_reads_every_price() -> None:
    api = FakeStripe()
    arm = ArmChargePathAdapter(client_factory=lambda _: api)
    request = await _armed_request(api)

    assert arm.requires_approval is True

    evidence = await arm.verify(request, await arm.execute(request, _ctx()), _ctx())

    assert [p["slug"] for p in evidence["prices"]] == [r["slug"] for r in request["catalogue"]]
    for proved, row in zip(evidence["prices"], request["catalogue"], strict=True):
        assert proved["unit_amount"] == row["price_minor"]
        assert proved["currency"] == row["currency_charge"].lower()


async def test_arming_fails_when_any_one_price_drifted() -> None:
    """Not a sample: a catalogue is armed as a whole, and the price that moved is the one a
    buyer is about to be charged (FR-029)."""
    api = FakeStripe()
    arm = ArmChargePathAdapter(client_factory=lambda _: api)
    request = await _armed_request(api)

    last = request["catalogue"][-1]
    api.prices.rows[last["price_id"]]["unit_amount"] = last["price_minor"] + 1

    with pytest.raises(VerificationFailed):
        await arm.verify(request, {}, _ctx())


async def test_arming_fails_when_a_price_was_deactivated() -> None:
    api = FakeStripe()
    arm = ArmChargePathAdapter(client_factory=lambda _: api)
    request = await _armed_request(api)

    api.prices.rows[request["catalogue"][0]["price_id"]]["active"] = False

    with pytest.raises(VerificationFailed):
        await arm.verify(request, {}, _ctx())


def checkout_request(row: dict, price_id: str) -> dict:
    return {
        "brief_hash": BRIEF_HASH,
        "slug": row["slug"],
        "price_id": price_id,
        "billing": row["billing"],
        "idempotency_key": "checkout-key",
        "success_url": "https://example.invalid/?checkout=success",
        "cancel_url": "https://example.invalid/",
    }


async def test_checkout_is_not_gated_and_defers_the_proof_it_cannot_have_yet() -> None:
    """An operator click must never sit between a buyer and the card form (§4.4, SC-009),
    and the order that proves the sale does not exist until the buyer has paid."""
    api = FakeStripe()
    checkout = CheckoutSessionAdapter(client_factory=lambda _: api)
    row = catalogue()[0]

    assert checkout.requires_approval is False
    assert checkout.defer_verification is True

    result = await checkout.execute(checkout_request(row, "price_0"), _ctx())
    created = api.checkout.sessions.rows[result["session_id"]]

    assert result["checkout_url"] == created["url"]
    assert created["mode"] == ("subscription" if row["billing"] == "subscription" else "payment")
    assert plain(created["line_items"]) == [{"price": "price_0", "quantity": 1}]
    assert created["metadata"]["slug"] == row["slug"]


async def test_an_unpaid_checkout_proves_nothing(gate_session: AsyncSession) -> None:
    api = FakeStripe()
    checkout = CheckoutSessionAdapter(client_factory=lambda _: api)
    request = checkout_request(catalogue()[0], "price_0")
    ctx = GateContext(run_id=uuid.uuid4(), credentials=_Credentials(), session=gate_session)
    result = await checkout.execute(request, ctx)

    # No webhook has written an order for this session, so there is nothing to prove.
    with pytest.raises(VerificationFailed):
        await checkout.verify(request, result, ctx)
    # And a re-drive that carries no session at all proves less, not more.
    with pytest.raises(VerificationFailed):
        await checkout.verify(request, {}, ctx)


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
