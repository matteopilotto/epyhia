import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter

# What a CDN alias plausibly needs to stop serving the previous build. Not a tuning knob —
# a floor, below which the schedule stops being patience and becomes a formality.
MINIMUM_TOTAL_PATIENCE_SECONDS = 30.0


@pytest.mark.realistic_backoff
def test_the_verify_schedule_waits_long_enough_to_be_worth_calling_a_retry() -> None:
    """The regression that cost run 8d89a987 its second publication.

    The schedule was `2**attempt * 0.01` capped at 1.0 — 0.30 seconds across all five
    attempts. The deploy had succeeded; the alias simply had not caught up, and the gate
    recorded a permanent failure against a world that agreed with it moments later. Attempt
    counts are asserted below; this asserts the waiting is real.
    """
    waits = [
        gate._verify_backoff_seconds(attempt)
        for attempt in range(1, gate.MAX_VERIFY_ATTEMPTS)
    ]
    assert sum(waits) >= MINIMUM_TOTAL_PATIENCE_SECONDS
    # Monotonic up to the cap: a schedule that front-loads its patience spends it before the
    # provider has begun, and one that never grows is a fixed poll wearing a backoff's name.
    assert waits == sorted(waits)


async def test_verify_that_always_fails_retries_to_cap_and_lands_failed(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_verify_retry", always_fail_verify=True)
    registry.register(adapter)

    result = await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="marketer",
        action_type="test_verify_retry",
        action_request={},
        idempotency_key=str(uuid.uuid4()),
    )

    assert result["state"] == "failed"
    assert result["state"] != "succeeded"
    assert len(adapter.verify_calls) == gate.MAX_VERIFY_ATTEMPTS
