from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
