import uuid

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the Stripe pairs
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.gate import gate

# One definition of "read a field off a provider object", beside the adapters that own the
# provider. Two copies is how one of them ends up reaching for `.get`.
from epyhia.gate.adapters.stripe import field
from epyhia.models.actions import Action
from epyhia.models.orders import Order

# Unauthenticated in the operator's sense: the signature is the authentication, and it is
# checked before the body is trusted for anything at all.
router = APIRouter()

COMPLETED = "checkout.session.completed"
PAID = "paid"


def construct_event(payload: bytes, signature: str) -> dict:
    """Verify and parse, in that order. An unsigned or mis-signed body never reaches the
    order table — this endpoint is public, and the event is what writes money-shaped rows."""
    secret = settings.require("stripe_webhook")
    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_signature"}) from exc


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    event = construct_event(await request.body(), stripe_signature)
    if event["type"] != COMPLETED:
        return {"received": True, "recorded": False}

    checkout = event["data"]["object"]
    metadata = field(checkout, "metadata") or {}
    if not field(metadata, "run_id") or not field(metadata, "slug"):
        # Signed, so it is genuinely Stripe's — but not a session this agency opened. It is
        # acknowledged rather than retried forever, and it writes nothing.
        return {"received": True, "recorded": False}

    # The order row and the event id are the same row, so recording that this event was
    # handled and recording the sale cannot come apart. Stripe delivers at least once, and a
    # repeat arriving while the first is still in flight is settled by the unique index
    # rather than by a read-then-write anyone could interleave (FR-032, §7.3).
    inserted = (
        await session.execute(
            pg_insert(Order)
            .values(
                id=uuid.uuid4(),
                run_id=uuid.UUID(metadata["run_id"]),
                stripe_event_id=event["id"],
                stripe_session_id=checkout["id"],
                product_slug=metadata["slug"],
                # Copied from the event, never from the brief: what was actually charged is
                # the only thing an order may claim (data-model.md "orders").
                amount_minor=checkout["amount_total"],
                currency=checkout["currency"],
                paid=checkout["payment_status"] == PAID,
            )
            .on_conflict_do_nothing(index_elements=["stripe_event_id"])
            .returning(Order.id)
        )
    ).scalar_one_or_none()
    await session.commit()

    # The click could not prove itself — the buyer had not paid yet — so its action has been
    # waiting at `verifying` since. This is the observation it was waiting for, and the
    # session id comes from the processor's own signed event (contracts/action-gate.md §4).
    action = (
        await session.execute(
            select(Action).where(
                Action.idempotency_key == field(checkout, "client_reference_id")
            )
        )
    ).scalars().first()
    if action is not None:
        await gate.resume(session, action.id, result={"session_id": checkout["id"]})

    return {"received": True, "recorded": inserted is not None}
