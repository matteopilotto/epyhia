import json
import uuid

import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import site_critic
from epyhia.agents.site_critic import MAX_FINDINGS, Critique, CritiqueFinding, critique
from epyhia.design.lint import DesignFinding
from epyhia.models.agent_calls import AgentCall

# Structural to the last field: a palette and a pairing that belong to no business, and two
# byte strings standing in for the renders.
BRAND_DOC = {
    "palette": {"bg": "#101010", "fg": "#f4f1ec", "accent": "#b4552d", "muted": "#8b857c"},
    "type": {"display": "display-id", "body": "body-id"},
}
SCREENSHOTS = [b"\x89PNG phone", b"\x89PNG desktop"]
LINT_FINDINGS = [
    DesignFinding(rule="gradient_hero", detail="a gradient backs the hero", where=".hero")
]


def _critic(payload: object) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(respond)


async def _open_run(session: AsyncSession) -> uuid.UUID:
    """The brief + run rows the `agent_calls` foreign key requires, and nothing else."""
    brief_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO briefs (id, payload, content_sha256, guardrail_decision, "
            "guardrail_model) VALUES (:id, '{}'::jsonb, :hash, 'pass', 'test-model')"
        ),
        {"id": brief_id, "hash": uuid.uuid4().hex},
    )
    run_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO runs (id, brief_id, prompt_version, grounding_set, budget_usd, "
            "spend_usd, status, alias) "
            "VALUES (:id, :brief_id, 'v1', '{}'::jsonb, 25, 0, 'running', :alias)"
        ),
        {"id": run_id, "brief_id": brief_id, "alias": f"epyhia-{run_id.hex[:12]}.vercel.app"},
    )
    await session.flush()
    return run_id


async def _critique(session: AsyncSession, run_id: uuid.UUID, model: FunctionModel) -> Critique:
    with site_critic.agent.override(model=model):
        return await critique(
            session,
            run_id=run_id,
            brand_doc=BRAND_DOC,
            findings=LINT_FINDINGS,
            screenshots=SCREENSHOTS,
        )


async def test_a_punch_list_parses_into_the_bounded_typed_shape(
    db_session: AsyncSession,
) -> None:
    run_id = await _open_run(db_session)

    review = await _critique(
        db_session,
        run_id,
        _critic(
            {
                "findings": [
                    {
                        "kind": "rhythm_uniform",
                        "where": "the middle of the page",
                        "what": "four sections in a row at the same width and spacing",
                    }
                ]
            }
        ),
    )

    assert not review.clean
    assert review.findings[0].kind == "rhythm_uniform"


async def test_an_empty_punch_list_is_a_clean_review(db_session: AsyncSession) -> None:
    """Approval is derived from emptiness, exactly as `Review.approved` is — the critic is
    never asked to assert that a page is fine, so it cannot pass one silently."""
    run_id = await _open_run(db_session)

    review = await _critique(db_session, run_id, _critic({"findings": []}))

    assert review.clean
    assert review.findings == []


async def test_unusable_output_surfaces_as_a_failure_the_handler_can_skip_on(
    db_session: AsyncSession,
) -> None:
    """The critic has no way to record its own skip: it raises, and the site handler catches
    that and records `critique.status="skipped"` (FR-015, research R5)."""
    run_id = await _open_run(db_session)

    with pytest.raises(UnexpectedModelBehavior):
        await _critique(db_session, run_id, _critic({"notes": "the page looks fine to me"}))


async def test_the_call_is_metered_against_the_run(db_session: AsyncSession) -> None:
    """Inference is metered, not gated — and it rolls into the run's one budget under its own
    agent name, so a cost view can say what looking at the page cost (FR-016)."""
    run_id = await _open_run(db_session)

    await _critique(db_session, run_id, _critic({"findings": []}))

    call = (
        await db_session.execute(select(AgentCall).where(AgentCall.run_id == run_id))
    ).scalar_one()
    assert (call.agent, call.model_id) == ("site_critic", site_critic.MODEL_ID)


def test_the_output_shape_cannot_carry_a_rewrite() -> None:
    """"Never edits the page" is a property of this shape, not an instruction: there is no
    field for markup, CSS or copy for the critic to put a rewrite in."""
    assert set(CritiqueFinding.model_fields) == {"kind", "where", "what"}
    assert set(Critique.model_fields) == {"findings"}


def test_the_punch_list_is_bounded() -> None:
    """A list long enough to describe everything mildly wrong with a page spends the single
    revision pass on nothing."""
    finding = {"kind": "other", "where": "somewhere", "what": "something"}
    with pytest.raises(ValidationError):
        Critique.model_validate({"findings": [finding] * (MAX_FINDINGS + 1)})
