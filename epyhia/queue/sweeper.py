from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate
from epyhia.gate.registry import get_adapter

TASK_ATTEMPTS_CAP = 5

# `awaiting_approval` rows carry no lease (R7 step 4) and are excluded by construction —
# only `claimed`/`running` rows are ever leased, so only they are eligible to expire.
_SWEEP_TO_PENDING_SQL = text(
    """
    UPDATE tasks
    SET state = 'pending', attempts = attempts + 1, lease_expires_at = NULL
    WHERE state IN ('claimed', 'running')
      AND lease_expires_at < now()
      AND attempts + 1 <= :cap
    """
)

_SWEEP_TO_FAILED_SQL = text(
    """
    UPDATE tasks
    SET state = 'failed', lease_expires_at = NULL,
        error = 'lease expired past attempts cap'
    WHERE state IN ('claimed', 'running')
      AND lease_expires_at < now()
      AND attempts + 1 > :cap
    """
)


async def sweep_expired_leases(session: AsyncSession, *, cap: int = TASK_ATTEMPTS_CAP) -> None:
    """Return expired-lease rows to `pending`, incrementing `attempts`; past `cap` the row
    lands `failed` instead (R8, data-model.md "tasks" state transitions).
    """
    await session.execute(_SWEEP_TO_FAILED_SQL, {"cap": cap})
    await session.execute(_SWEEP_TO_PENDING_SQL, {"cap": cap})


# An action's owner is the lease on its task, so an action still `executing` or `verifying`
# under a lease that has lapsed is one whose worker is gone. `SKIP LOCKED` because every
# worker machine runs this pass and two of them re-driving one row is two probes against the
# same provider.
_ORPHANED_ACTIONS_SQL = text(
    """
    SELECT a.id, a.action_type
    FROM actions a
    JOIN tasks t ON t.id = a.task_id
    WHERE a.state IN ('executing', 'verifying')
      AND (t.lease_expires_at IS NULL OR t.lease_expires_at < now())
    FOR UPDATE OF a SKIP LOCKED
    """
)


async def resume_orphaned_actions(session: AsyncSession) -> None:
    """Re-drive actions a dead worker left mid-flight (§7.4).

    `request()` refuses to re-drive an in-flight row, and says a stuck one is unstuck through
    `resume()` — but the only callers of `resume()` are an operator's approval and the Stripe
    webhook. A non-approval action killed mid-verify therefore had no observer that would
    ever come back for it, and sat outside all three terminal states forever.

    `resume()` is safe here by construction: it skips `execute()` for any row past `pending`,
    so a resumed `stripe_product` re-reads the product that already exists rather than
    creating a second one.
    """
    rows = (await session.execute(_ORPHANED_ACTIONS_SQL)).all()
    for action_id, action_type in rows:
        try:
            adapter = get_adapter(action_type)
        except KeyError:
            # No adapter for it in this process. Nothing here can prove the action, and
            # guessing is worse than leaving it to a process that can.
            continue
        if getattr(adapter, "defer_verification", False):
            # Waiting on an observer by design: a checkout session has no order to prove
            # until the buyer pays. Resuming it would spend its attempts against a world
            # that has not caught up yet (contracts/action-gate.md §4).
            continue
        await gate.resume(session, action_id)
