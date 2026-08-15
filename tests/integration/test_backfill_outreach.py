from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from scripts.backfill_outreach import backfill
from tests.integration.test_demand_pack import load_brief
from tests.integration.test_outreach_handlers import (
    EMAIL,
    POSTS,
    _open_run,
    _seed_email,
    _seed_posts,
)


async def _tasks(session: AsyncSession, run_id, kind: str) -> list[Task]:
    return list(
        (
            await session.execute(select(Task).where(Task.run_id == run_id, Task.kind == kind))
        ).scalars()
    )


async def test_backfill_enqueues_outreach_and_reopens_a_settled_run(
    integration_session: AsyncSession,
) -> None:
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS)
    await _seed_email(integration_session, run_id, EMAIL)
    run.status = "succeeded"
    await integration_session.commit()

    results = await backfill(integration_session, [run_id])

    assert results == [
        {
            "run_id": run_id,
            "publish_enqueued": len(POSTS),
            "send_email_enqueued": 1,
            "reopened": True,
        }
    ]

    publish = await _tasks(integration_session, run_id, "publish")
    assert {t.payload["slot"] for t in publish} == set(range(len(POSTS)))
    send_email = await _tasks(integration_session, run_id, "send_email")
    assert len(send_email) == 1

    reread = await integration_session.get(Run, run_id)
    assert reread.status == "running"


async def test_backfill_is_a_no_op_on_a_second_invocation(
    integration_session: AsyncSession,
) -> None:
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS)
    await _seed_email(integration_session, run_id, EMAIL)
    run.status = "succeeded"
    await integration_session.commit()

    await backfill(integration_session, [run_id])
    first_publish = {t.id for t in await _tasks(integration_session, run_id, "publish")}
    first_send_email = {t.id for t in await _tasks(integration_session, run_id, "send_email")}

    second = await backfill(integration_session, [run_id])

    assert second == [
        {"run_id": run_id, "publish_enqueued": 0, "send_email_enqueued": 0, "reopened": False}
    ]
    second_publish = {t.id for t in await _tasks(integration_session, run_id, "publish")}
    second_send_email = {t.id for t in await _tasks(integration_session, run_id, "send_email")}
    assert second_publish == first_publish
    assert second_send_email == first_send_email


async def test_backfill_skips_a_run_with_no_clean_posts_artifact(
    integration_session: AsyncSession,
) -> None:
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS, grounding_status="flagged")
    await _seed_email(integration_session, run_id, EMAIL)

    results = await backfill(integration_session, [run_id])

    assert results == [{"run_id": run_id, "skipped": "no clean posts artifact"}]
    assert await _tasks(integration_session, run_id, "publish") == []
    assert await _tasks(integration_session, run_id, "send_email") == []


async def test_backfill_skips_a_run_halted_on_budget(integration_session: AsyncSession) -> None:
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS)
    await _seed_email(integration_session, run_id, EMAIL)
    run.status = "halted_budget"
    await integration_session.commit()

    results = await backfill(integration_session, [run_id])

    assert results == [{"run_id": run_id, "skipped": "run is halted on budget"}]
    assert await _tasks(integration_session, run_id, "publish") == []
