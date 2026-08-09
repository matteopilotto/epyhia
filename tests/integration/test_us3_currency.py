import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.models.actions import Action
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.orders import Order
from tests.integration.test_us3_checkout import (
    WEBHOOK_SECRET,
    arm,
    client_for,
    completed_event,
    load_brief,
    open_run,
    register_stripe,
    signed,
)
from tests.stripe_stub import FakeStripe


@pytest.fixture(autouse=True)
def _stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_stub")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


async def test_display_and_charge_currencies_are_both_the_briefs_own(
    integration_session: AsyncSession,
) -> None:
    """A business may quote in one currency and charge in another. EPYHIA does neither the
    quoting nor the charging: both values are the brief's, and no rate is applied to either
    (FR-003, research.md R6).

    The proof is that one integer — `price_minor` — reaches the page's currency, the
    processor's currency and the order unchanged. A conversion anywhere would show up as a
    different number on one of the three.
    """
    api = FakeStripe()
    register_stripe(api)
    brief = load_brief()
    run = await open_run(integration_session, brief)

    differing = [
        row
        for row in run.resolved_catalogue
        if row["currency_display"] != row["currency_charge"]
    ]
    assert differing, "this fixture must carry a product whose two currencies differ"

    armed = await arm(integration_session, run)
    assert armed.state == "succeeded"

    # The display side: the brand doc carries the display currency and no charge currency at
    # all, so nothing downstream of it can quote what is actually charged.
    brand_doc = (
        await integration_session.execute(
            select(BrandDoc).where(BrandDoc.brief_id == run.brief_id)
        )
    ).scalar_one()
    for offering, row in zip(brand_doc.doc["offerings"], run.resolved_catalogue, strict=True):
        assert offering["currency_display"] == row["currency_display"]
        assert "currency_charge" not in offering
        assert offering["price_minor"] == row["price_minor"]

    # The charge side: same integer, in the charge currency, and never in the display one.
    for row, proved in zip(run.resolved_catalogue, armed.evidence["prices"], strict=True):
        assert proved["unit_amount"] == row["price_minor"]
        assert proved["currency"] == row["currency_charge"].lower()
        assert proved["currency"] != row["currency_display"].lower()

    # And what the operator approved shows both, unreconciled — the difference is the
    # business's own (FR-028).
    for approved, row in zip(armed.request["catalogue"], run.resolved_catalogue, strict=True):
        assert approved["currency_display"] == row["currency_display"]
        assert approved["currency_charge"] == row["currency_charge"]
        assert approved["price_minor"] == row["price_minor"]


async def test_the_order_records_what_was_charged_not_what_was_displayed(
    integration_session: AsyncSession,
) -> None:
    api = FakeStripe()
    register_stripe(api)
    run = await open_run(integration_session, load_brief())
    await arm(integration_session, run)

    row = next(
        r for r in run.resolved_catalogue if r["currency_display"] != r["currency_charge"]
    )
    async with client_for(integration_session) as client:
        response = await client.post(
            "/checkout", json={"run_id": str(run.id), "slug": row["slug"]}
        )
    assert response.status_code == 200

    action = (
        await integration_session.execute(
            select(Action).where(Action.action_type == "checkout_session")
        )
    ).scalar_one()
    session_id = next(iter(api.checkout.sessions.rows))
    payload, headers = signed(
        completed_event(
            event_id=f"evt_{uuid.uuid4()}",
            session_id=session_id,
            run_id=run.id,
            row=row,
            key=action.idempotency_key,
        )
    )
    async with client_for(integration_session) as client:
        assert (
            await client.post("/webhooks/stripe", content=payload, headers=headers)
        ).status_code == 200

    order = (
        await integration_session.execute(select(Order).where(Order.run_id == run.id))
    ).scalar_one()
    assert order.currency == row["currency_charge"].lower()
    assert order.currency != row["currency_display"].lower()
    # Unconverted: the amount the buyer paid is the number the business wrote down.
    assert order.amount_minor == row["price_minor"]
