import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer, strategist, web_builder
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.vercel import build_marker
from epyhia.gate.errors import VerificationFailed
from epyhia.gate.keys import alias_for
from epyhia.ingest.catalogue import resolve_catalogue
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.ingest.normalise import MINOR_EXPONENT
from epyhia.models.actions import Action
from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service
from epyhia.queue.worker import run_once

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"


def load_brief(name: str = "one.json") -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeDeployAdapter:
    """Stands in for the world. The honest HTTP probe is exercised in
    `tests/gate/test_vercel_adapter.py`; what this one is here to prove is that the run's own
    brand doc row reaches `verify()` — so the probe string is never a literal (FR-018, FR-059).
    """

    action_type = "deploy"
    requires_approval = True

    def __init__(self) -> None:
        self.execute_calls: list[dict] = []
        self.published: dict[str, str] = {}

    async def execute(self, request: dict, ctx) -> dict:
        self.execute_calls.append(request)
        self.published = {item["file"]: item["data"] for item in request["files"]}
        return {"deployment_id": "fake"}

    async def verify(self, request: dict, result: dict, ctx) -> dict:
        name = ctx.brand_doc["name"]
        if name not in self.published.get("index.html", ""):
            raise VerificationFailed("published page does not present the brand doc name")
        return {
            "status": 200,
            "matched_name": name,
            "matched_build_marker": build_marker(request),
            "url": f"https://{alias_for(request['brief_hash'])}",
        }


def _prompt_json(messages: list[ModelMessage]) -> dict:
    """The last user prompt, as the structured object the agent was handed (FR-008)."""
    for part in reversed(messages[-1].parts):
        content = getattr(part, "content", None)
        if isinstance(content, str):
            return json.loads(content)
    raise AssertionError("no user prompt found")


def _strategist_model(brief: dict) -> FunctionModel:
    """Writes a brand doc derived from the brief it is handed. Nothing here is a literal
    copied out of the fixture — every client value is read from the brief at call time."""
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        if len(calls) > 1:
            return ModelResponse(parts=[TextPart("planned")])

        payload = _prompt_json(messages)
        doc = {
            "name": payload["business_name"],
            "descriptor": payload["one_liner"],
            "positioning": payload["positioning"]["why_them"],
            "palette": {
                "bg": "#101014",
                "fg": "#f4f4f5",
                "accent": "#c2410c",
                "muted": "#71717a",
            },
            "type": {"display": "Display Face", "body": "Body Face"},
            "motion_language": "mechanical, deliberate",
            "composition_archetype": "editorial_stack",
            "video_archetype": "technical_spec_sheet",
            "voice": payload["voice"],
            "composition_plan": [
                {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"},
                {"section": "reach", "layout": "contact_block", "intent": "how to get in touch"},
            ],
            # Carried across from the brief's own products, field-for-field minus the
            # charging currency — the copy the Strategist is asked for, expressed as code
            # rather than as a literal.
            "offerings": [
                {k: v for k, v in product.items() if k != "currency_charge"}
                for product in payload["products"]
            ],
        }
        return ModelResponse(
            parts=[
                ToolCallPart("write_brand_doc", {"doc": doc}),
                ToolCallPart("enqueue_tasks", {"stages": ["site"]}),
            ]
        )

    return FunctionModel(respond)


def _major_form(offering: dict) -> str:
    """`price_minor` as a customer would see it written. The exponent comes from the same
    table the normaliser reduces by, so the two sides cannot drift apart into a test that
    passes for the wrong reason."""
    exponent = MINOR_EXPONENT.get(offering["currency_display"], 2)
    amount = Decimal(offering["price_minor"]).scaleb(-exponent)
    return f"{offering['currency_display']} {amount}"


def _marketer_model() -> FunctionModel:
    """Writes one copy block per planned section from the brand doc it is handed, and states
    the first offering by name and price. Every string it emits is one the brand doc already
    carried, so it states no fact of its own and the deterministic check has nothing to flag
    — which is the point: the offerings are given facts, so using them stays clean."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        doc = _prompt_json(messages)["brand_doc"]
        offering = doc["offerings"][0]
        copy = {
            "sections": [
                {
                    "section": entry["section"],
                    "headline": doc["descriptor"],
                    "body": doc["positioning"],
                }
                for entry in doc["composition_plan"]
            ]
        }
        copy["sections"][0]["body"] = f"{offering['name']}, {_major_form(offering)}."
        return ModelResponse(parts=[TextPart(json.dumps(copy))])

    return FunctionModel(respond)


def _reviewer_model() -> FunctionModel:
    """Finds nothing wrong. What the loop does when it *does* find something is US2's to
    prove (T086); here the point is only that the copy stage now runs through it."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps({"violations": []}))])

    return FunctionModel(respond)


def _web_builder_model(marker: str = "") -> FunctionModel:
    """Composes a page from the brand doc and copy it is handed, carrying no fact of its
    own — so the grounding check has nothing to flag and the deploy precondition holds.

    Every offering reaches the page, by exact name and price, because that is what the
    brand doc's `offerings` list is: the checklist the finished page is read against.

    `marker` is how a caller gets a second generation whose bytes genuinely differ, which is
    what a re-run has to survive (T107). It carries no numeral, so it changes the page
    without changing what the grounding check reads.
    """

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        payload = _prompt_json(messages)
        name = payload["brand_doc"]["name"]
        sections = "".join(
            f"<section><h2>{item['headline']}</h2><p>{item['body']}</p></section>"
            for item in payload["copy"]["sections"]
        )
        offerings = "".join(
            f"<li><h3>{item['name']}</h3><p>{_major_form(item)}</p></li>"
            for item in payload["brand_doc"]["offerings"]
        )
        html = (
            "<!doctype html><html lang='en'><head><title>"
            f"{name}</title><style>:root{{--bg:#101014}}.h{{padding:1.5rem}}</style>"
            f"</head><body><h1>{name}</h1>{sections}<ul>{offerings}</ul>"
            "<script>document.title = document.title;</script></body></html>"
            f"{f'<!-- {marker} -->' if marker else ''}"
        )
        for index in range(0, len(html), 64):
            yield html[index : index + 64]

    return FunctionModel(stream_function=stream)


async def _open_run(session: AsyncSession, brief_payload: dict) -> tuple[uuid.UUID, str]:
    """The ingest path `POST /briefs` performs, minus the HTTP and the guardrail's model
    call: hash, ground, open the run with its derived alias, enqueue `plan` (FR-004)."""
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
        resolved_catalogue=resolve_catalogue(brief_payload["products"]),
        budget_usd=25,
        status="running",
        alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.flush()
    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="plan", state="pending"))
    await session.commit()
    return run.id, brief_hash


async def _drive_to_approval(
    session: AsyncSession, brief_payload: dict, adapter: FakeDeployAdapter
) -> tuple[uuid.UUID, Action]:
    registry.register(adapter)
    run_id, _ = await _open_run(session, brief_payload)

    with strategist.agent.override(model=_strategist_model(brief_payload)):
        assert await run_once(session, kind="plan")
    with (
        marketer.agent.override(model=_marketer_model()),
        reviewer.agent.override(model=_reviewer_model()),
    ):
        assert await run_once(session, kind="copy")
    with web_builder.agent.override(model=_web_builder_model()):
        assert await run_once(session, kind="site")

    action = (
        await session.execute(select(Action).where(Action.run_id == run_id))
    ).scalar_one()
    return run_id, action


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vercel_token", "test-token")


async def test_brief_becomes_a_proved_live_site_once_approved(
    integration_session: AsyncSession,
) -> None:
    brief_payload = load_brief()
    adapter = FakeDeployAdapter()
    run_id, action = await _drive_to_approval(integration_session, brief_payload, adapter)

    # The Strategist wrote v1 and the run points at it.
    brand_doc = (
        await integration_session.execute(select(BrandDoc).where(BrandDoc.brief_id.is_not(None)))
    ).scalar_one()
    assert brand_doc.version == 1
    assert brand_doc.authored_by == "strategist"

    # copy blocks site, and both artifacts came out grounded.
    artifacts = {
        artifact.kind: artifact
        for artifact in (
            await integration_session.execute(
                select(Artifact).where(Artifact.run_id == run_id)
            )
        ).scalars()
    }
    assert artifacts["copy"].grounding_status == "clean"
    assert artifacts["site"].grounding_status == "clean"

    # The facts reached the page. Both sides of this are read from the run's own rows — the
    # brand doc the Strategist wrote and the site artifact that came out of it — so it holds
    # for any brief, and it is the check that was missing when a page could go out stating
    # nothing the business sells (FR-010).
    published = artifacts["site"].bytes.decode("utf-8")
    for offering in brand_doc.doc["offerings"]:
        assert offering["name"] in published
        assert _major_form(offering) in published

    # The deploy halted for a human, durably, before anything reached the world.
    assert action.state == "awaiting_approval"
    assert adapter.execute_calls == []
    parked = (
        await integration_session.execute(
            text("SELECT state FROM tasks WHERE kind = 'site'")
        )
    ).scalar_one()
    assert parked == "awaiting_approval"

    await gate.record_approval(integration_session, action.id, "auth0|operator")
    integration_session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await integration_session.commit()
    assert await run_once(integration_session, kind="resume")

    await integration_session.refresh(action)
    assert action.state == "succeeded"
    assert action.approved_by == "auth0|operator"

    # US1's independent test: the probe's matched_name is the brand doc row's own name.
    # Both sides are read from the database — no literal appears anywhere in this assertion.
    assert action.evidence["matched_name"] == brand_doc.doc["name"]
    assert action.evidence["status"] == 200
    assert action.evidence["matched_build_marker"] == build_marker(action.request)
    assert action.evidence["url"].endswith(
        (await integration_session.get(Run, run_id)).alias
    )


async def test_deny_leaves_nothing_published(integration_session: AsyncSession) -> None:
    brief_payload = load_brief()
    adapter = FakeDeployAdapter()
    run_id, action = await _drive_to_approval(integration_session, brief_payload, adapter)

    await gate.deny(integration_session, action.id, "auth0|operator")
    integration_session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await integration_session.commit()
    assert await run_once(integration_session, kind="resume")

    await integration_session.refresh(action)
    assert action.state == "denied"
    assert action.approval_decision == "denied"
    assert action.approved_by == "auth0|operator"
    assert action.evidence is None

    # Nothing executed, and nothing ever will for this key (§6).
    assert adapter.execute_calls == []
    assert adapter.published == {}
