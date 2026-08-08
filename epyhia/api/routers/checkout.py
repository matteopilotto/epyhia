import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the Stripe pairs
from epyhia.api.db import get_session
from epyhia.gate import gate
from epyhia.gate.keys import checkout_session_key
from epyhia.models.actions import Action
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run

# Unauthenticated by design: the caller is a buyer on the generated site, not an operator.
# There is nothing to protect here that the gate does not already hold — the site carries no
# key, and the only thing this route can do is create a session against a price the run's
# approval already covered (DESIGN.md §6.2).
router = APIRouter()

REQUESTED_BY = "checkout"


class CheckoutRequest(BaseModel):
    run_id: uuid.UUID
    slug: str


async def is_armed(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Read from the `actions` table, never from a flag on `runs`.

    The armed state and its evidence are then the same record: what made that row
    `succeeded` is FR-029's re-read of every price, so nothing can be armed without that
    check having passed (research.md R11).
    """
    state = (
        await session.execute(
            select(Action.state).where(
                Action.run_id == run_id, Action.action_type == "arm_charge_path"
            )
        )
    ).scalars().first()
    return state == "succeeded"


async def price_for(session: AsyncSession, run_id: uuid.UUID, slug: str) -> str | None:
    """The slug resolved against this run's own Ops output, at click time.

    This is why no Stripe identifier ever needs to reach the deployed bytes: the page carries
    the slug the brief produced at ingest, and the price it maps to is looked up here
    (FR-030, DESIGN.md §6.2).
    """
    return (
        await session.execute(
            select(Action.evidence["price_id"].astext).where(
                Action.run_id == run_id,
                Action.action_type == "stripe_price",
                Action.state == "succeeded",
                Action.request["slug"].astext == slug,
            )
        )
    ).scalars().first()


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    run = await session.get(Run, body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_run"})

    # Resolution order is research.md R11's, and it is the order that matters: a run that was
    # never armed answers `not_armed` whatever the slug, because the page's honest state is
    # "you cannot buy this yet" rather than "that product does not exist".
    if not await is_armed(session, run.id):
        raise HTTPException(status_code=409, detail={"error": "not_armed"})

    row = next((r for r in run.resolved_catalogue if r["slug"] == body.slug), None)
    price_id = await price_for(session, run.id, body.slug)
    if row is None or price_id is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_product"})

    brief = await session.get(Brief, run.brief_id)
    # One key per click. Two buyers must not share an action row, and a buyer who clicks
    # twice gets two sessions — which is correct: the thing that must never happen twice is
    # the charge, and Stripe settles that on the session the buyer actually completes.
    buyer_session = str(uuid.uuid4())
    idempotency_key = checkout_session_key(brief.content_sha256, body.slug, buyer_session)

    result = await gate.request(
        session,
        run_id=run.id,
        requested_by=REQUESTED_BY,
        action_type="checkout_session",
        action_request={
            "brief_hash": brief.content_sha256,
            "slug": body.slug,
            "price_id": price_id,
            "billing": row["billing"],
            "idempotency_key": idempotency_key,
            # Derived from the run's own alias, so the buyer returns to the page they left
            # and nothing about the destination is written here (R2).
            "success_url": f"https://{run.alias}/?checkout=success",
            "cancel_url": f"https://{run.alias}/?checkout=cancelled",
        },
        idempotency_key=idempotency_key,
    )
    return {"checkout_url": result["result"]["checkout_url"]}
