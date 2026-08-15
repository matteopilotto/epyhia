import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the publish/email pair
from epyhia.agents import marketer
from epyhia.gate import gate
from epyhia.gate.keys import publish_key, send_email_key
from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler

AGENT = "marketer"

# One outreach template, named the way the US2 test and the §7.2 key both name it.
LAUNCH_TEMPLATE = "launch"


class PublishRefused(Exception):
    """The Marketer's posts artifact isn't fit to publish this slot from. The task fails and
    the sweeper decides whether it is worth another attempt (R8)."""


class SendEmailRefused(Exception):
    """The Marketer's email artifact isn't fit to send, or the brief carries no recipient.
    The task fails and the sweeper decides whether it is worth another attempt (R8)."""


async def handle_publish(session: AsyncSession, task: Task) -> None:
    """Publish one slot of the run's marketing posts (§8.2 of the outreach plan).

    Deterministic, like the site handler's deploy request: no model call, just a read, a
    refusal, or a request. `task.payload["slot"]` is fixed at enqueue time, so a re-generated
    posts artifact with fewer posts than it once had is refused by name rather than silently
    publishing whatever slot 0 now means.
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)
    slot = task.payload["slot"]

    # Newest generation, not highest revision — the same lookup the site and video handlers
    # use, for the same reason: a re-run's fresh clean artifact must not lose to a stale
    # flagged generation still holding more review-round revisions (T142).
    posts_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.kind == "posts")
            .order_by(Artifact.created_at.desc(), Artifact.revision.desc())
        )
    ).scalars().first()

    if posts_artifact is None:
        raise PublishRefused("no posts artifact for this run")
    if posts_artifact.grounding_status != "clean":
        raise PublishRefused(
            f"posts artifact is {posts_artifact.grounding_status}, not clean"
        )

    posts = json.loads(posts_artifact.bytes)["posts"]
    if slot >= len(posts):
        raise PublishRefused(f"slot {slot} of a {len(posts)}-post artifact")

    await gate.request(
        session,
        run_id=run.id,
        requested_by=AGENT,
        action_type="publish",
        action_request={"payload": posts[slot], "brief_hash": brief.content_sha256},
        idempotency_key=publish_key(
            brief.content_sha256, brand_doc.version, marketer.PROMPT_VERSION, slot
        ),
        task_id=task.id,
        brand_doc=brand_doc.doc,
    )


async def handle_send_email(session: AsyncSession, task: Task) -> None:
    """Send the run's launch email to the brief's own contact address.

    The recipient is read from `brief.payload["contact"]["email"]` at request time — never
    from code or config — so the genericity invariant holds for the one client fact this
    handler touches (CLAUDE.md's invariant table).
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    email_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.kind == "email")
            .order_by(Artifact.created_at.desc(), Artifact.revision.desc())
        )
    ).scalars().first()

    if email_artifact is None:
        raise SendEmailRefused("no email artifact for this run")
    if email_artifact.grounding_status != "clean":
        raise SendEmailRefused(
            f"email artifact is {email_artifact.grounding_status}, not clean"
        )

    recipient = (brief.payload.get("contact") or {}).get("email")
    if not recipient:
        raise SendEmailRefused("brief carries no contact.email")

    email = json.loads(email_artifact.bytes)

    await gate.request(
        session,
        run_id=run.id,
        requested_by=AGENT,
        action_type="send_email",
        action_request={
            "brief_hash": brief.content_sha256,
            "template": LAUNCH_TEMPLATE,
            "recipient": recipient,
            "subject": email["subject"],
            "body": email["body"],
        },
        idempotency_key=send_email_key(brief.content_sha256, LAUNCH_TEMPLATE, recipient),
        task_id=task.id,
        brand_doc=brand_doc.doc,
    )


register_handler("publish", handle_publish)
register_handler("send_email", handle_send_email)
