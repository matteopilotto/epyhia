import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.gate import registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.sweeper import resume_orphaned_actions
from epyhia.queue.worker import HANDLERS, register_handler, run_worker
from tests.queue.conftest import _insert_task, make_run

PAST = timedelta(hours=1)
FUTURE = timedelta(minutes=5)


async def _noop(session: AsyncSession, task: Task) -> None:
    """So the loop can claim the swept task without running a real stage."""


async def _until_succeeded(session: AsyncSession, action_id: uuid.UUID) -> None:
    while True:
        # A fresh snapshot each poll: the loop commits from its own sessions.
        await session.rollback()
        state = await session.scalar(
            text("SELECT state FROM actions WHERE id = :id").bindparams(id=action_id)
        )
        if state == "succeeded":
            return
        await asyncio.sleep(0.02)


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
    kind: str = "money",
) -> Action:
    """One action mid-flight under a task whose lease is `lease` away from now."""
    run_id = await make_run(session)
    task_id = await _insert_task(
        session,
        run_id,
        kind=kind,
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


async def test_one_failing_orphan_does_not_stop_the_others(
    recovery_session: AsyncSession,
) -> None:
    """Observed in production on the first deploy of this pass.

    `product.get("active")` raised `AttributeError` inside `verify()`, the exception left
    the loop, and the worker process exited — so a pass written to recover crashed runs
    became the thing that stopped every run instead. An adapter raising something other than
    `VerificationFailed` is a bug, and a bug in one adapter must not be an outage.
    """

    class Exploding(FakeAdapter):
        async def verify(self, request: dict, ctx=None, *args, **kwargs) -> dict:
            raise AttributeError("get")

    broken = Exploding("test_orphan_broken")
    healthy = FakeAdapter("test_orphan_healthy")
    registry.register(broken)
    registry.register(healthy)

    doomed = await _stranded_action(
        recovery_session, action_type=broken.action_type, lease=-PAST
    )
    other = await _stranded_action(
        recovery_session, action_type=healthy.action_type, lease=-PAST
    )

    # Must not raise, whichever order the two come back in.
    await resume_orphaned_actions(recovery_session)
    await recovery_session.commit()

    await recovery_session.refresh(doomed)
    await recovery_session.refresh(other)
    assert doomed.state == "verifying"
    # The healthy one was recovered regardless of the broken one's company.
    assert other.state == "succeeded"


async def test_the_worker_loop_actually_runs_the_recovery_pass(
    recovery_session: AsyncSession,
) -> None:
    """The wiring, not the function.

    `sweep_expired_leases` was correct and unit-tested for four phases while nothing in
    production called it. A recovery pass exercised only by tests that call it directly is
    that same bug wearing a different hat, so this drives the real loop.
    """
    kind = "test_orphan_loop"
    adapter = FakeAdapter("test_orphan_loop_action")
    registry.register(adapter)
    register_handler(kind, _noop)
    try:
        action = await _stranded_action(
            recovery_session, action_type=adapter.action_type, lease=-PAST, kind=kind
        )

        session_factory = async_sessionmaker(
            bind=recovery_session.bind, expire_on_commit=False
        )
        worker = asyncio.create_task(
            run_worker(
                poll_interval_seconds=0.01,
                sweep_interval_seconds=0.0,
                session_factory=session_factory,
            )
        )
        try:
            await asyncio.wait_for(_until_succeeded(recovery_session, action.id), timeout=10)
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
    finally:
        HANDLERS.pop(kind, None)
