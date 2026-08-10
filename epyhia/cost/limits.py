import uuid

from pydantic_ai.usage import UsageLimits
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.agent_calls import AgentCall

# Tokens a single run may spend across every agent call it makes. A code constant, not a
# knob: it is a ceiling on runaway generation, not a per-client setting, and the thing an
# operator actually tunes is the dollar budget in `budget.py`.
RUN_TOKEN_LIMIT = 1_000_000


async def tokens_spent(session: AsyncSession, run_id: uuid.UUID) -> int:
    """Tokens the run has already recorded, in the same denomination `UsageLimits` counts:
    `RunUsage.total_tokens` is `input + output`, with cache reads and writes reported
    separately and excluded from it."""
    total = await session.scalar(
        select(
            func.coalesce(func.sum(AgentCall.input_tokens + AgentCall.output_tokens), 0)
        ).where(AgentCall.run_id == run_id)
    )
    return int(total)


async def limits_for_run(session: AsyncSession, run_id: uuid.UUID) -> UsageLimits:
    """The token allowance left to this run, expressed as `UsageLimits` (§8, FR-053).

    Enforcement is in tokens and only in tokens. `UsageLimits` carries no dollar field and
    none is invented here — dollars are derived after the fact from `RunUsage` through
    `pricing.yaml`'s effective-dated rates, and enforced separately in `budget.py`.

    The allowance is the run's ceiling minus what the `agent_calls` ledger already records,
    rather than an in-memory accumulator: a run crosses tasks, transactions and worker
    processes, so the only place its spend so far exists is Postgres. It is passed as the
    limit for a *fresh* usage accumulator rather than by pre-seeding one, because a seeded
    `RunUsage` comes back out of `result.usage` and would be recorded a second time.
    """
    remaining = RUN_TOKEN_LIMIT - await tokens_spent(session, run_id)
    return UsageLimits(total_tokens_limit=max(remaining, 0))
