import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.cost.pricing import rate_for
from epyhia.models.agent_calls import AgentCall


async def record_call(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    task_id: uuid.UUID | None,
    agent: str,
    model_id: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_read_tokens: int,
    latency_ms: int,
    cache_hit: bool,
    at: datetime | None = None,
) -> AgentCall:
    """Write one `agent_calls` row per model call (data-model.md "agent_calls").
    `tier` and `cost_usd` are derived from `pricing.yaml`, never inferred or
    defaulted, so both are always NOT NULL (SC-007, R9).
    """
    at = at or datetime.now(UTC)
    rate = rate_for(model_id, at)
    cost_usd = (
        input_tokens * rate.input
        + output_tokens * rate.output
        + cache_write_tokens * rate.cache_write
        + cache_read_tokens * rate.cache_read
    ) / 1_000_000

    call = AgentCall(
        run_id=run_id,
        task_id=task_id,
        agent=agent,
        model_id=model_id,
        tier=rate.tier,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
    )
    session.add(call)
    await session.flush()
    return call
