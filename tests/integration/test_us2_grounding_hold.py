import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import marketer, reviewer
from epyhia.agents.reviewer import Violation
from epyhia.gate.keys import alias_for
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.prompts_service import prompt_service
from epyhia.queue.handlers.pack import MAX_REVISIONS, produce

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
    """Every client value is read from the brief at call time. The layout ids are EPYHIA's
    own library names, so nothing here is a literal copied out of the fixture (FR-059)."""
    return {
        "name": brief["business_name"],
        "descriptor": brief["one_liner"],
        "voice": brief["voice"],
        "composition_plan": [
            {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"},
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
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(brief_payload, datetime.now(UTC).year),
        budget_usd=25,
        status="running",
        alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.commit()
    return run


def _reviewer_that_must_not_be_asked() -> FunctionModel:
    """The deterministic check runs first and cannot be wrong, so a draft that already fails
    it must never reach a model: asking would be spending money to be told what is known."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError("the Reviewer was asked about a draft that already fails the check")

    return FunctionModel(respond)


async def test_a_fabricated_numeral_is_held_through_two_revisions_then_flagged(
    integration_session: AsyncSession,
) -> None:
    brief_payload = load_brief()
    run = await _open_run(integration_session, brief_payload)
    fabricated = _ungrounded_amount(run.grounding_set)

    drafts: list[dict] = []
    handed_back: list[list[dict] | None] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = _prompt_json(messages)
        handed_back.append(payload.get("violations"))
        doc = payload["brand_doc"]
        draft = {
            "sections": [
                {
                    "section": entry["section"],
                    "headline": doc["descriptor"],
                    "body": f"Only {fabricated} left.",
                }
                for entry in doc["composition_plan"]
            ]
        }
        drafts.append(draft)
        return ModelResponse(parts=[TextPart(json.dumps(draft))])

    with (
        marketer.agent.override(model=FunctionModel(respond)),
        reviewer.agent.override(model=_reviewer_that_must_not_be_asked()),
    ):
        artifact = await produce(
            integration_session,
            run_id=run.id,
            deliverable="copy",
            brand_doc=_brand_doc(brief_payload),
            brief=brief_payload,
            grounding_set=run.grounding_set,
        )
    await integration_session.commit()

    # One draft and at most two revisions — the loop is bounded, because an unbounded loop
    # against a draft that will not improve is an unbounded bill (FR-024).
    assert len(drafts) == MAX_REVISIONS + 1
    assert handed_back[0] is None
    assert all(violations for violations in handed_back[1:])
    assert all(v[0]["kind"] == "ungrounded_numeral" for v in handed_back[1:])

    assert artifact.grounding_status == "flagged"
    assert artifact.revision == MAX_REVISIONS
    assert artifact.violations
    for violation in artifact.violations:
        assert violation["kind"] == "ungrounded_numeral"
        assert violation["quote"] == str(fabricated)
        assert violation["why"]

    # Held rather than delivered — and stored rather than dropped, so it can be read and
    # corrected instead of disappearing quietly (FR-024).
    assert json.loads(artifact.bytes) == drafts[-1]


async def test_the_reviewer_itemises_and_never_rewrites(
    integration_session: AsyncSession,
) -> None:
    brief_payload = load_brief()
    run = await _open_run(integration_session, brief_payload)

    drafts: list[dict] = []
    reviewed: list[dict] = []

    def marketer_respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        doc = _prompt_json(messages)["brand_doc"]
        draft = {
            "sections": [
                {
                    "section": entry["section"],
                    "headline": doc["name"],
                    "body": doc["descriptor"],
                }
                for entry in doc["composition_plan"]
            ]
        }
        drafts.append(draft)
        return ModelResponse(parts=[TextPart(json.dumps(draft))])

    def reviewer_respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        draft = _prompt_json(messages)["draft"]
        reviewed.append(draft)
        review = {
            "violations": [
                {
                    "kind": "voice",
                    "quote": draft["sections"][0]["headline"],
                    "why": "stated more flatly than the brand doc's voice allows",
                }
            ]
        }
        return ModelResponse(parts=[TextPart(json.dumps(review))])

    with (
        marketer.agent.override(model=FunctionModel(marketer_respond)),
        reviewer.agent.override(model=FunctionModel(reviewer_respond)),
    ):
        artifact = await produce(
            integration_session,
            run_id=run.id,
            deliverable="copy",
            brand_doc=_brand_doc(brief_payload),
            brief=brief_payload,
            grounding_set=run.grounding_set,
        )
    await integration_session.commit()

    # The draft carries no numeral, so the deterministic check passes and the Reviewer is
    # asked about every one of them — voice is the only thing left to disagree about.
    assert len(reviewed) == MAX_REVISIONS + 1

    assert artifact.grounding_status == "flagged"
    assert artifact.violations
    for violation in artifact.violations:
        assert set(violation) == {"kind", "quote", "why"}
        assert violation["quote"] in json.dumps(drafts[-1])

    # Never a rewrite: the stored bytes are the Marketer's own last draft, and the Reviewer's
    # output shape has no field through which replacement wording could have arrived (FR-023).
    assert json.loads(artifact.bytes) == drafts[-1]
    assert set(Violation.model_fields) == {"kind", "quote", "why"}
