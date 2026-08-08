import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.tasks import Task
from epyhia.queue.handlers.site import UpstreamNotClean, handle_site
from tests.queue.conftest import make_run

# No model is reachable from here: the refusal happens before `build_site` is called, so a
# test that never overrides a model is itself the evidence that no model call was made.


async def _seed_brand_doc(session: AsyncSession, run_id: uuid.UUID) -> None:
    """The handler loads the brand doc before it reaches the guard, so a run without one
    would fail for the wrong reason."""
    brief_id = (
        await session.execute(
            text("SELECT brief_id FROM runs WHERE id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    brand_doc_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO brand_docs (id, brief_id, version, doc, authored_by) "
            "VALUES (:id, :brief_id, 1, '{}'::jsonb, 'strategist')"
        ),
        {"id": brand_doc_id, "brief_id": brief_id},
    )
    await session.execute(
        text("UPDATE runs SET brand_doc_id = :doc_id WHERE id = :run_id"),
        {"doc_id": brand_doc_id, "run_id": run_id},
    )
    await session.commit()


async def _seed_copy(session: AsyncSession, run_id: uuid.UUID, status: str) -> None:
    await session.execute(
        text(
            "INSERT INTO artifacts (id, run_id, kind, path, content_type, bytes, sha256, "
            "grounding_status, violations, revision) "
            "VALUES (:id, :run_id, 'copy', 'copy.json', 'application/json', :bytes, :sha, "
            ":status, :violations, 0)"
        ),
        {
            "id": uuid.uuid4(),
            "run_id": run_id,
            "bytes": b'{"sections": []}',
            "sha": "0" * 64,
            "status": status,
            "violations": '[{"kind": "ungrounded_numeral", "quote": "1", "why": "not given"}]'
            if status == "flagged"
            else None,
        },
    )
    await session.commit()


def _site_task(run_id: uuid.UUID) -> Task:
    """Transient, like `test_us2_grounding_hold.py` drives `produce` directly: the guard is
    reached without the worker's handler registry or its lease."""
    return Task(id=uuid.uuid4(), run_id=run_id, kind="site", state="running")


async def _counts(session: AsyncSession, run_id: uuid.UUID) -> tuple[int, int]:
    sites = (
        await session.execute(
            text("SELECT count(*) FROM artifacts WHERE run_id = :run_id AND kind = 'site'"),
            {"run_id": run_id},
        )
    ).scalar_one()
    actions = (
        await session.execute(
            text("SELECT count(*) FROM actions WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    return sites, actions


async def test_a_flagged_copy_artifact_never_becomes_a_page(
    queue_session: AsyncSession,
) -> None:
    """`copy → site` is an ordering edge. Without a refusal here, a claim the Reviewer held
    is rendered into a page and parked one operator click from deploy (FR-024)."""
    run_id = await make_run(queue_session)
    await _seed_brand_doc(queue_session, run_id)
    await _seed_copy(queue_session, run_id, "flagged")

    with pytest.raises(UpstreamNotClean) as raised:
        await handle_site(queue_session, _site_task(run_id))

    assert "flagged" in str(raised.value)

    # No page was built and no deploy was requested — the held copy stopped short of both.
    assert await _counts(queue_session, run_id) == (0, 0)


async def test_a_missing_copy_artifact_never_becomes_a_page(
    queue_session: AsyncSession,
) -> None:
    run_id = await make_run(queue_session)
    await _seed_brand_doc(queue_session, run_id)

    with pytest.raises(UpstreamNotClean):
        await handle_site(queue_session, _site_task(run_id))

    assert await _counts(queue_session, run_id) == (0, 0)
