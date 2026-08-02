import asyncio
import uuid
from datetime import UTC, datetime

from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.gate.errors import PreconditionFailed, VerificationFailed
from epyhia.gate.registry import Adapter, GateContext, get_adapter
from epyhia.models.actions import Action

MAX_VERIFY_ATTEMPTS = 5
TERMINAL_STATES = ("succeeded", "failed", "denied")

# Static so a missing credential is reported even when no adapter is registered for the
# action type at all (FR-064, SC-010) — the check must not depend on adapter lookup.
_CREDENTIAL_BY_ACTION_TYPE = {
    "deploy": "vercel",
    "stripe_product": "stripe",
    "stripe_price": "stripe",
    "arm_charge_path": "stripe",
    "checkout_session": "stripe",
    "send_email": "smtp",
    "publish": "sink",
}


def _verify_backoff_seconds(attempt: int) -> float:
    return min(2**attempt * 0.01, 1.0)


async def _check_preconditions(session: AsyncSession, action_type: str, run_id: uuid.UUID) -> None:
    """Step 1: fail fast, before any row is written (contracts/action-gate.md §2, §5)."""
    provider = _CREDENTIAL_BY_ACTION_TYPE.get(action_type)
    if provider is not None:
        settings.require(provider)

    if action_type == "deploy":
        # The gate refuses, not the agent (FR-016, §3.4) — queried against `artifacts`,
        # which lands in Phase 2b; this branch is inert until then.
        row = (
            await session.execute(
                text(
                    "SELECT grounding_status FROM artifacts "
                    "WHERE run_id = :run_id AND kind = 'site'"
                ),
                {"run_id": run_id},
            )
        ).first()
        if row is None or row[0] != "clean":
            raise PreconditionFailed("site artifact is not clean")

    if action_type == "checkout_session":
        stmt = select(Action.state).where(
            Action.run_id == run_id, Action.action_type == "arm_charge_path"
        )
        row = (await session.execute(stmt)).first()
        if row is None or row[0] != "succeeded":
            raise PreconditionFailed("not_armed")


async def request(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    requested_by: str,
    action_type: str,
    action_request: dict,
    idempotency_key: str,
    task_id: uuid.UUID | None = None,
    projected_cost_usd: float | None = None,
    brand_doc: dict | None = None,
) -> dict:
    await _check_preconditions(session, action_type, run_id)

    insert_stmt = (
        pg_insert(Action)
        .values(
            id=uuid.uuid4(),
            run_id=run_id,
            task_id=task_id,
            requested_by=requested_by,
            action_type=action_type,
            idempotency_key=idempotency_key,
            request=action_request,
            state="pending",
            projected_cost_usd=projected_cost_usd,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Action.id)
    )
    action_id = (await session.execute(insert_stmt)).scalar_one_or_none()
    await session.commit()

    if action_id is None:
        # Lost the race, or a genuine re-run against the same key (§7.2).
        existing = (
            await session.execute(select(Action).where(Action.idempotency_key == idempotency_key))
        ).scalar_one()
        if existing.state in TERMINAL_STATES:
            return _result(existing)
        # In-flight under someone else's ownership. Nothing executes here — a stuck row is
        # unstuck through `resume()`, not by a second request() racing the first.
        return {"action_id": existing.id, "state": existing.state, "in_progress": True}

    action = await session.get(Action, action_id)
    adapter = get_adapter(action_type)

    if adapter.requires_approval:
        action.state = "awaiting_approval"
        await session.commit()
        raise ApprovalRequired(
            metadata={"action_id": str(action.id), "idempotency_key": idempotency_key}
        )

    return await _run(session, action, adapter, brand_doc)


async def approve(
    session: AsyncSession, action_id: uuid.UUID, approved_by: str, brand_doc: dict | None = None
) -> dict:
    action = await session.get(Action, action_id)
    if action.state != "awaiting_approval":
        raise PreconditionFailed("not_awaiting_approval")
    action.approval_decision = "approved"
    action.approved_by = approved_by
    action.approved_at = datetime.now(UTC)
    await session.commit()

    adapter = get_adapter(action.action_type)
    return await _run(session, action, adapter, brand_doc)


async def deny(session: AsyncSession, action_id: uuid.UUID, approved_by: str) -> dict:
    action = await session.get(Action, action_id)
    if action.state != "awaiting_approval":
        raise PreconditionFailed("not_awaiting_approval")
    action.state = "denied"
    action.approval_decision = "denied"
    action.approved_by = approved_by
    action.approved_at = datetime.now(UTC)
    await session.commit()
    return _result(action)


async def resume(
    session: AsyncSession, action_id: uuid.UUID, brand_doc: dict | None = None
) -> dict:
    """Continue a row left behind by a crash. The truth comes from the probe, never from
    whatever state the process happened to leave on the row (§7.4)."""
    action = await session.get(Action, action_id)
    if action.state in TERMINAL_STATES:
        return _result(action)
    adapter = get_adapter(action.action_type)
    return await _run(session, action, adapter, brand_doc)


async def _run(
    session: AsyncSession, action: Action, adapter: Adapter, brand_doc: dict | None
) -> dict:
    ctx = GateContext(run_id=action.run_id, brand_doc=brand_doc)
    result: dict = {}

    if action.state in ("pending", "awaiting_approval"):
        action.state = "executing"
        await session.commit()

    if action.state == "executing":
        try:
            result = await adapter.execute(action.request, ctx)
        except Exception as exc:
            action.state = "failed"
            action.error = str(exc)
            await session.commit()
            raise
        action.state = "verifying"
        await session.commit()

    if action.state == "verifying":
        while action.verify_attempts < MAX_VERIFY_ATTEMPTS:
            try:
                evidence = await adapter.verify(action.request, result, ctx)
            except VerificationFailed as exc:
                action.verify_attempts += 1
                action.error = str(exc)
                await session.commit()
                if action.verify_attempts < MAX_VERIFY_ATTEMPTS:
                    await asyncio.sleep(_verify_backoff_seconds(action.verify_attempts))
                continue
            action.evidence = evidence
            action.error = None
            action.state = "succeeded"
            await session.commit()
            return _result(action)

        action.state = "failed"
        await session.commit()
        return _result(action)

    return _result(action)


def _result(action: Action) -> dict:
    return {
        "action_id": action.id,
        "state": action.state,
        "evidence": action.evidence,
        "error": action.error,
    }
