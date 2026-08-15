import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.cost.budget import HALTED
from epyhia.queue.claim import claim_task
from tests.queue.conftest import _insert_task, make_run

pytestmark = pytest.mark.asyncio


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": "auth0|operator"}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    )


async def _state_of(session: AsyncSession, task_id: uuid.UUID) -> tuple[str, str | None, int]:
    row = (
        await session.execute(
            text("SELECT state, error, attempts FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    return row.state, row.error, row.attempts


async def test_a_failed_task_returns_to_pending_and_is_claimable(
    queue_session: AsyncSession,
) -> None:
    """The one state nothing else can leave. `attempts` resets because the cap exists to stop
    an unattended lease-expiry loop, and a human clicking a button is the circuit breaker that
    cap stands in for."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(
        queue_session, run_id, kind="site", state="failed", attempts=3
    )
    await queue_session.execute(
        text("UPDATE tasks SET error = 'ModelAPIError: overloaded' WHERE id = :id"),
        {"id": task_id},
    )
    await queue_session.commit()

    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{task_id}/retry")

    assert response.status_code == 200
    assert response.json() == {"state": "pending"}
    assert await _state_of(queue_session, task_id) == ("pending", None, 0)

    claimed = await claim_task(queue_session, kind="site")
    await queue_session.commit()
    assert claimed is not None
    assert claimed.id == task_id


async def test_an_unknown_task_is_a_404(queue_session: AsyncSession) -> None:
    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{uuid.uuid4()}/retry")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_a_done_task_returns_to_pending_and_is_claimable(
    queue_session: AsyncSession,
) -> None:
    """The operator remedy for a flagged artifact — correct the brand doc, re-run the stage —
    needs a route back into a stage that *completed* around its held output (T145). Without
    this, the remedy the spec documents takes a raw UPDATE in psql, which is where run
    `9445c473` ended up."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="copy", state="done")

    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{task_id}/retry")

    assert response.status_code == 200
    assert response.json() == {"state": "pending"}
    assert await _state_of(queue_session, task_id) == ("pending", None, 0)

    claimed = await claim_task(queue_session, kind="copy")
    await queue_session.commit()
    assert claimed is not None
    assert claimed.id == task_id


@pytest.mark.parametrize("state", ["pending", "running", "awaiting_approval"])
async def test_only_a_terminal_task_is_re_queueable(
    queue_session: AsyncSession, state: str
) -> None:
    """Each of these is a different mechanism's territory: `pending` belongs to the claim
    loop, `running` to the lease sweep, and `awaiting_approval` to the approve button."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="money", state=state)

    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{task_id}/retry")

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "not_retryable"
    assert body["state"] == state
    assert (await _state_of(queue_session, task_id))[0] == state


async def test_re_queueing_a_stage_re_opens_a_settled_run(
    queue_session: AsyncSession,
) -> None:
    """T144's other half. A `failed` stage the operator is about to re-queue is not a failed
    run — the click is the statement that the run is not finished after all, so the run
    re-opens with the stage and settles again when it next has no stage that can move."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="site", state="failed")
    await queue_session.execute(
        text("UPDATE runs SET status = 'failed' WHERE id = :id"), {"id": run_id}
    )
    await queue_session.commit()

    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{task_id}/retry")

    assert response.status_code == 200
    status = (
        await queue_session.execute(
            text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one()
    assert status == "running"


async def test_a_halted_run_refuses_rather_than_re_failing_the_task(
    queue_session: AsyncSession,
) -> None:
    """`enforce_run_budget` fails a claimed task immediately while the run is halted, so
    without this guard the click would produce a task that re-fails in under a second with a
    different error than the one the operator was reading. Refusing up front says the true
    thing once."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="site", state="failed")
    await queue_session.execute(
        text("UPDATE runs SET status = :status WHERE id = :id"),
        {"id": run_id, "status": HALTED},
    )
    await queue_session.commit()

    async with client_for(queue_session) as client:
        response = await client.post(f"/tasks/{task_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"] == "run_halted"
    assert (await _state_of(queue_session, task_id))[0] == "failed"


async def test_a_re_queued_task_keeps_its_dependents_blocked(
    queue_session: AsyncSession,
) -> None:
    """`_CLAIM_SQL` already refuses a task whose `depends_on` are not all `done`, so
    re-queueing an upstream stage needs no extra ordering logic here."""
    run_id = await make_run(queue_session)
    upstream = await _insert_task(queue_session, run_id, kind="copy", state="failed")
    downstream = await _insert_task(
        queue_session, run_id, kind="site", state="pending", depends_on=[upstream]
    )

    async with client_for(queue_session) as client:
        assert (await client.post(f"/tasks/{upstream}/retry")).status_code == 200

    claimed = await claim_task(queue_session, kind="site")
    await queue_session.commit()
    assert claimed is None

    await queue_session.execute(
        text("UPDATE tasks SET state = 'done' WHERE id = :id"), {"id": upstream}
    )
    await queue_session.commit()

    claimed = await claim_task(queue_session, kind="site")
    await queue_session.commit()
    assert claimed is not None
    assert claimed.id == downstream
