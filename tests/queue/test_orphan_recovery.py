import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action
from epyhia.queue.sweeper import resume_orphaned_actions
from tests.queue.conftest import _insert_task, make_run

PAST = timedelta(hours=1)
FUTURE = timedelta(minutes=5)


@pytest_asyncio.fixture
async def recovery_session(queue_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """`queue_session` plus a clean `actions` table — this pass reads across both, and the
    queue fixture truncates only the task side."""
    await queue_session.execute(text("TRUNCATE actions"))
    await queue_session.commit()
    try:
        yield queue_session
    finally:
        registry.clear()
        await queue_session.rollback()
        await queue_session.execute(text("TRUNCATE actions"))
        await queue_session.commit()


async def _stranded_action(
    session: AsyncSession,
    *,
    action_type: str,
    lease: timedelta,
    state: str = "verifying",
    task_state: str = "running",
) -> Action:
    """One action mid-flight under a task whose lease is `lease` away from now."""
    run_id = await make_run(session)
    task_id = await _insert_task(
        session,
        run_id,
        kind="money",
        state=task_state,
        lease_expires_at=datetime.now(UTC) + lease,
    )
    action = Action(
        id=uuid.uuid4(),
        run_id=run_id,
        task_id=task_id,
        requested_by="ops",
        action_type=action_type,
        idempotency_key=str(uuid.uuid4()),
        request={"marker": "stranded"},
        state=state,
    )
    session.add(action)
    await session.commit()
    return action


async def test_an_action_orphaned_by_a_dead_worker_is_resumed_to_terminal(
    recovery_session: AsyncSession,
) -> None:
    """The bug this pass exists for: run 8d89a987 sat at `verifying` with nothing that would
    ever come back for it, because `resume()` is reached only from an operator's approval and
    the Stripe webhook."""
    adapter = FakeAdapter("test_orphan")
    registry.register(adapter)
    action = await _stranded_action(
        recovery_session, action_type=adapter.action_type, lease=-PAST
    )

    await resume_orphaned_actions(recovery_session)
    await recovery_session.commit()

    await recovery_session.refresh(action)
    assert action.state == "succeeded"
    assert action.evidence == {"status": "ok"}
    # The effect is proved, not repeated — a resumed stripe_product must not create a second
    # product (§7.4).
    assert adapter.execute_calls == []
    assert len(adapter.verify_calls) == 1


async def test_a_deferred_action_is_left_waiting_for_its_observer(
    recovery_session: AsyncSession,
) -> None:
    """A checkout session has no order to prove until the buyer pays. Resuming it would spend
    its verify attempts against a world that has not caught up (contracts/action-gate.md §4)."""
    adapter = FakeAdapter("test_orphan_deferred")
    adapter.defer_verification = True
    registry.register(adapter)
    action = await _stranded_action(
        recovery_session, action_type=adapter.action_type, lease=-PAST
    )

    await resume_orphaned_actions(recovery_session)
    await recovery_session.commit()

    await recovery_session.refresh(action)
    assert action.state == "verifying"
    assert adapter.verify_calls == []


async def test_an_action_under_a_live_lease_is_left_alone(
    recovery_session: AsyncSession,
) -> None:
    """Its worker is alive and holding it. Re-driving here is the second `request()` racing
    the first, which is the thing the gate refuses on purpose."""
    adapter = FakeAdapter("test_orphan_live")
    registry.register(adapter)
    action = await _stranded_action(
        recovery_session, action_type=adapter.action_type, lease=FUTURE
    )

    await resume_orphaned_actions(recovery_session)
    await recovery_session.commit()

    await recovery_session.refresh(action)
    assert action.state == "verifying"
    assert adapter.verify_calls == []


async def test_an_action_awaiting_approval_is_never_resurrected(
    recovery_session: AsyncSession,
) -> None:
    """A parked approval carries no lease by construction (R7 step 4). Resuming it would
    execute behind the operator's back — the approval feature losing its point."""
    adapter = FakeAdapter("test_orphan_approval", requires_approval=True)
    registry.register(adapter)
    action = await _stranded_action(
        recovery_session,
        action_type=adapter.action_type,
        lease=-PAST,
        state="awaiting_approval",
        task_state="awaiting_approval",
    )

    await resume_orphaned_actions(recovery_session)
    await recovery_session.commit()

    await recovery_session.refresh(action)
    assert action.state == "awaiting_approval"
    assert adapter.execute_calls == []
