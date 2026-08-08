import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer
from epyhia.gate.keys import alias_for
from epyhia.ingest.catalogue import resolve_catalogue
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service
from epyhia.queue.handlers.demand import DELIVERABLES
from epyhia.queue.worker import run_once

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"


def load_brief(name: str = "one.json") -> dict:
    return json.loads((FIXTURES / name).read_text())


def _prompt_json(messages: list[ModelMessage]) -> dict:
    """The last user prompt, as the structured object the agent was handed (FR-008)."""
    for part in reversed(messages[-1].parts):
        content = getattr(part, "content", None)
        if isinstance(content, str):
            return json.loads(content)
    raise AssertionError("no user prompt found")


def _brand_doc(brief: dict) -> dict:
    """Every client value is read from the brief at call time; the archetype and layout ids
    are EPYHIA's own library names. Nothing here is a literal copied out of the fixture."""
    return {
        "name": brief["business_name"],
        "descriptor": brief["one_liner"],
        "positioning": brief["positioning"]["why_them"],
        "palette": {"bg": "#101014", "fg": "#f4f4f5", "accent": "#c2410c", "muted": "#71717a"},
        "type": {"display": "Display Face", "body": "Body Face"},
        "motion_language": "mechanical, deliberate",
        "composition_archetype": "editorial_stack",
        "video_archetype": "technical_spec_sheet",
        "voice": brief["voice"],
        "composition_plan": [
            {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"},
        ],
        "offerings": [
            {k: v for k, v in product.items() if k != "currency_charge"}
            for product in brief["products"]
        ],
    }


def _ungrounded_amount(grounding_set: dict) -> int:
    """A number this run's brief demonstrably did not give us — found by searching the run's
    own grounding set rather than by picking one that happens to look wrong today."""
    taken = {
        Decimal(entry["value"])
        for entry in grounding_set["literal"] + grounding_set["derived"]
    }
    value = 999_983
    while Decimal(value) in taken:
        value += 1
    return value


async def _open_run(session: AsyncSession, brief_payload: dict) -> Run:
    """A run already planned: brief, grounding set, brand doc, and the `demand` task the
    Strategist's selection would have enqueued."""
    brief_hash = content_sha256(brief_payload)
    brief = Brief(
        id=uuid.uuid4(),
        payload=brief_payload,
        content_sha256=brief_hash,
        guardrail_decision="pass",
        guardrail_reason="fixture brief, screened offline",
        guardrail_model="test-model",
    )
    session.add(brief)
    await session.flush()
    brand_doc = BrandDoc(
        id=uuid.uuid4(),
        brief_id=brief.id,
        version=1,
        doc=_brand_doc(brief_payload),
        authored_by="strategist",
    )
    session.add(brand_doc)
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brand_doc_id=brand_doc.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(brief_payload, datetime.now(UTC).year),
        resolved_catalogue=resolve_catalogue(brief_payload["products"]),
        budget_usd=25,
        status="running",
        alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.flush()
    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="demand", state="pending"))
    await session.commit()
    return run


def _marketer_model(fabricated: int | None = None) -> FunctionModel:
    """One pack piece per request, each built from the brand doc it was handed. Every string
    is one the brand doc already carried, so the deterministic check has nothing to flag —
    unless `fabricated` is given, which puts one ungrounded numeral on screen."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = _prompt_json(messages)
        doc = payload["brand_doc"]
        offering = doc["offerings"][0]

        if payload["deliverable"] == "posts":
            draft = {
                "posts": [
                    {"angle": entry["name"], "body": entry["description"]}
                    for entry in doc["offerings"]
                ][:3]
                or [{"angle": doc["descriptor"], "body": doc["positioning"]}]
            }
            while len(draft["posts"]) < 3:
                draft["posts"].append(
                    {"angle": doc["descriptor"], "body": doc["positioning"]}
                )
        elif payload["deliverable"] == "email":
            draft = {
                "subject": offering["name"],
                "preheader": doc["descriptor"],
                "body": offering["description"],
            }
        else:
            lines = [doc["positioning"]]
            if fabricated is not None:
                lines.append(f"Only {fabricated} left.")
            draft = {
                "content": {
                    "headline": doc["name"],
                    "scenes": [
                        {
                            "kind": "offer",
                            "lines": lines,
                            # Every on-screen number goes in `values`, labelled with the
                            # offering it belongs to — the shape the check can read.
                            "values": [
                                {
                                    "label": offering["name"],
                                    "amount_minor": offering["price_minor"],
                                    "currency": offering["currency_display"],
                                }
                            ],
                        }
                    ],
                },
                "motion_intensity": "medium",
            }

        return ModelResponse(parts=[TextPart(json.dumps(draft))])

    return FunctionModel(respond)


def _reviewer_model() -> FunctionModel:
    """Finds nothing wrong. What the loop does when it does is US2's to prove (T086)."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps({"violations": []}))])

    return FunctionModel(respond)


async def _artifacts(session: AsyncSession, run_id: uuid.UUID) -> dict[str, Artifact]:
    return {
        artifact.kind: artifact
        for artifact in (
            await session.execute(select(Artifact).where(Artifact.run_id == run_id))
        ).scalars()
    }


async def _tasks(session: AsyncSession, run_id: uuid.UUID, kind: str) -> list[Task]:
    return list(
        (
            await session.execute(
                select(Task).where(Task.run_id == run_id, Task.kind == kind)
            )
        ).scalars()
    )


async def _run_demand(session: AsyncSession, model: FunctionModel) -> None:
    with (
        marketer.agent.override(model=model),
        reviewer.agent.override(model=_reviewer_model()),
    ):
        assert await run_once(session, kind="demand")


async def test_demand_writes_the_pack_and_queues_the_render(
    integration_session: AsyncSession,
) -> None:
    brief_payload = load_brief()
    run = await _open_run(integration_session, brief_payload)

    await _run_demand(integration_session, _marketer_model())

    artifacts = await _artifacts(integration_session, run.id)
    assert set(artifacts) == set(DELIVERABLES)
    for deliverable in DELIVERABLES:
        assert artifacts[deliverable].grounding_status == "clean"

    demand = (await _tasks(integration_session, run.id, "demand"))[0]
    assert demand.state == "done"

    # The render is queued by the handler rather than by the pipeline: the row lands in the
    # same commit as the `video_props` artifact, so `video` stays enqueued here and never
    # becomes something the Strategist can select.
    video = await _tasks(integration_session, run.id, "video")
    assert len(video) == 1
    assert video[0].state == "pending"
    assert video[0].depends_on is None


async def test_flagged_props_still_queue_the_render(
    integration_session: AsyncSession,
) -> None:
    """The refusal to render flagged props lives in `handle_video` and nowhere else.

    Gating the enqueue here would put a second copy of that rule in a second place — and a
    task that was never created is invisible, where a failed one carrying "video_props
    artifact is flagged, not clean" is a named, readable refusal (FR-024).
    """
    brief_payload = load_brief()
    run = await _open_run(integration_session, brief_payload)
    fabricated = _ungrounded_amount(run.grounding_set)

    await _run_demand(integration_session, _marketer_model(fabricated))

    artifacts = await _artifacts(integration_session, run.id)
    assert artifacts["video_props"].grounding_status == "flagged"
    assert artifacts["video_props"].violations
    assert artifacts["video_props"].violations[0]["quote"] == str(fabricated)

    # `handle_video` is deliberately not driven here: it shells out to `npx`.
    video = await _tasks(integration_session, run.id, "video")
    assert len(video) == 1
    assert video[0].state == "pending"
