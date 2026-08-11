import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.orders import Order

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/runs/{run_id}/orders")
async def list_run_orders(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """The orders a run's checkouts actually persisted.

    Read-only and operator-authenticated, like every other record route. It exists because
    "a test purchase persisted a real order" is asserted from the stored row rather than
    from a success screen (FR-061), and the evaluation reads records through this same
    authenticated path — there is no second way in (FR-058).
    """
    result = await session.execute(
        select(Order).where(Order.run_id == run_id).order_by(Order.created_at)
    )
    return [
        {
            "id": order.id,
            "run_id": order.run_id,
            "stripe_event_id": order.stripe_event_id,
            "stripe_session_id": order.stripe_session_id,
            "product_slug": order.product_slug,
            # What was actually charged, copied from the processor's signed event — never
            # from the brief (data-model.md "orders").
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "paid": order.paid,
            "created_at": order.created_at,
        }
        for order in result.scalars().all()
    ]
