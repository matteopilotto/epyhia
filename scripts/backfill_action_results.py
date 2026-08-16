"""Reconstruct `actions.result` for `publish` rows that predate the column — the outreach
incident's 19 (`.claude/plans/outreach-remediation-and-the-false-green.md`, Finding 2).

    uv run python -m scripts.backfill_action_results

Those actions executed — the sink holds their posts — but nothing durable held
`execute()`'s return, so `POST /actions/{id}/reverify` refuses them for want of a permalink
to probe. Each result is rebuilt by joining `content_sha256(action.request['payload'])`
against `sink_posts.payload_sha256` — the sink's own durable record, never the error text.
Rows without a sink match are left alone and reported: a publish that truly never executed
must stay `failed`.

Re-verification prep only; never re-execution, which idempotency keys govern (§7.2) and
which would write duplicate posts for content the sink already holds. Safe to run twice —
a healed row no longer has `result IS NULL` and is not selected again.

Not an Alembic migration: the join asserts something about production data ("this action's
payload is in the sink"), which is an operator's claim to check, not a schema deploy's.
"""

import asyncio
import json
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings
from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action
from epyhia.models.sink_posts import SinkPost


async def backfill(session: AsyncSession, base_url: str) -> list[dict]:
    actions = (
        await session.execute(
            select(Action)
            .where(
                Action.action_type == "publish",
                Action.state == "failed",
                Action.result.is_(None),
            )
            .order_by(Action.created_at)
        )
    ).scalars().all()

    results = []
    for action in actions:
        expected = content_sha256(action.request["payload"])
        # Oldest first: the row `execute()` created. Idempotency keys make a second sink row
        # for the same payload all but impossible, but the choice is still made explicit.
        post = (
            await session.execute(
                select(SinkPost)
                .where(SinkPost.payload_sha256 == expected)
                .order_by(SinkPost.created_at)
            )
        ).scalars().first()
        if post is None:
            results.append(
                {"action_id": action.id, "matched": False, "payload_sha256": expected}
            )
            continue
        action.result = {
            "post_id": str(post.id),
            "permalink": f"{base_url.rstrip('/')}/posts/{post.id}",
        }
        results.append({"action_id": action.id, "matched": True, "post_id": post.id})

    await session.commit()
    return results


async def main() -> int:
    base_url = settings.require("sink_base_url")
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            results = await backfill(session, base_url)
    finally:
        await engine.dispose()

    for result in results:
        print(json.dumps(result, default=str))
    matched = sum(1 for r in results if r["matched"])
    print(f"matched {matched}/{len(results)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
