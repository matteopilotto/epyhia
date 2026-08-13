import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import web_builder
from epyhia.design.fonts import PAGE_BUDGET_BYTES, PageOverBudget, PairingError, library
from epyhia.design.lint import lint
from epyhia.gate import registry
from epyhia.models.tasks import Task
from epyhia.queue.handlers import site as site_handler
from epyhia.queue.handlers.site import UpstreamNotClean, handle_site
from tests.queue.conftest import make_run

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_REPORT_SCHEMA = json.loads(
    (
        REPO_ROOT / "specs" / "003-distinctive-sites" / "contracts" / "design-report.schema.json"
    ).read_text()
)

# No model is reachable from here: the refusal happens before `build_site` is called, so a
# test that never overrides a model is itself the evidence that no model call was made.

# A pairing taken from the library by role — the tests are about the mechanism, never about
# which faces were curated.
DISPLAY_ID = next(face for face in library.faces if face.role in ("display", "both")).id
BODY_ID = next(face for face in library.faces if face.role in ("body", "both")).id

# The brand doc the site stage reads for itself: the two ids it resolves, and the accent the
# design lint counts against. Invented values, structural to the last field.
PALETTE = {"bg": "#101010", "fg": "#f4f1ec", "accent": "#b4552d", "muted": "#8b857c"}


def _doc(display: str = DISPLAY_ID, body: str = BODY_ID) -> dict:
    return {"palette": PALETTE, "type": {"display": display, "body": body}}


async def _seed_brand_doc(
    session: AsyncSession, run_id: uuid.UUID, doc: dict | None = None
) -> None:
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
            "VALUES (:id, :brief_id, 1, CAST(:doc AS jsonb), 'strategist')"
        ),
        {"id": brand_doc_id, "brief_id": brief_id, "doc": json.dumps(doc or {})},
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


async def _make_buildable_run(session: AsyncSession, doc: dict) -> uuid.UUID:
    """A run the site stage can get all the way through: a brief with a locale, an empty
    catalogue and grounding set, a brand doc, and clean copy. Every value is structural —
    none of it says anything about a business."""
    run_id = await make_run(session)
    await session.execute(
        text(
            "UPDATE briefs SET payload = '{\"locale\": \"en-GB\"}'::jsonb "
            "WHERE id = (SELECT brief_id FROM runs WHERE id = :run_id)"
        ),
        {"run_id": run_id},
    )
    await session.execute(
        text(
            "UPDATE runs SET resolved_catalogue = '[]'::jsonb, "
            "grounding_set = '{\"literal\": [], \"derived\": []}'::jsonb WHERE id = :run_id"
        ),
        {"run_id": run_id},
    )
    await _seed_brand_doc(session, run_id, doc)
    await _seed_copy(session, run_id, "clean")
    return run_id


def _builder(page: str) -> FunctionModel:
    """A streamed Web Builder standing in for the real one. The page carries no numeral, so
    the grounding check has nothing to flag and these tests stay about the font path."""

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        yield page

    return FunctionModel(stream_function=stream)


def _never_called() -> FunctionModel:
    async def stream(messages: list[ModelMessage], info: AgentInfo):
        raise AssertionError("the model was called")
        yield ""  # pragma: no cover — unreachable, keeps this an async generator

    return FunctionModel(stream_function=stream)


PAGE = (
    "<!doctype html><html lang='en'><head><title>Specimen</title></head>"
    "<body><h1>Specimen</h1></body></html>"
)


class _FakeDeployAdapter:
    """Stands in for the world so this file needs no credential and reaches no provider.
    Approval-gated like the real one, so the request parks and `execute` is never called."""

    action_type = "deploy"
    requires_approval = True
    defer_verification = False
    cost_usd = Decimal("0")

    async def execute(self, request: dict, ctx) -> dict:  # pragma: no cover — never reached
        raise AssertionError("an approval-gated deploy must not execute on request")

    async def verify(self, request: dict, result: dict, ctx) -> dict:  # pragma: no cover
        raise AssertionError("nothing executed, so nothing is verified")


@pytest.fixture
def deploy_adapter() -> Iterator[None]:
    """The gate tests clear the registry at teardown, so the adapter a site build needs is
    registered here rather than inherited from whatever ran first."""
    registry.register(_FakeDeployAdapter())
    try:
        yield
    finally:
        registry.unregister("deploy")


def _site_task(run_id: uuid.UUID) -> Task:
    """Transient, like `test_us2_grounding_hold.py` drives `produce` directly: the guard is
    reached without the worker's handler registry or its lease."""
    return Task(id=uuid.uuid4(), run_id=run_id, kind="site", state="running")


async def _persisted_site_task(session: AsyncSession, run_id: uuid.UUID) -> Task:
    """The same task, durable — a stage that reaches the model records the call against its
    task id, and `agent_calls` has a foreign key to `tasks`."""
    task = _site_task(run_id)
    await session.execute(
        text(
            "INSERT INTO tasks (id, run_id, kind, state, attempts) "
            "VALUES (:id, :run_id, 'site', 'running', 0)"
        ),
        {"id": task.id, "run_id": run_id},
    )
    await session.commit()
    return task


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


async def test_an_unknown_pairing_id_fails_before_any_model_call(
    queue_session: AsyncSession,
) -> None:
    """FR-005. The brand doc names a face nobody curated — the shape a doc written before
    ids existed has, carrying free text — and the stage stops there: no generation is paid
    for, no page is stored, and nothing is set in whatever the visitor's device had."""
    run_id = await _make_buildable_run(queue_session, _doc(display="Helvetica Neue"))

    with (
        web_builder.agent.override(model=_never_called()),
        pytest.raises(PairingError) as raised,
    ):
        await handle_site(queue_session, _site_task(run_id))

    assert "unknown font id: Helvetica Neue" in str(raised.value)
    assert await _counts(queue_session, run_id) == (0, 0)


async def test_the_fonts_are_embedded_before_the_grounding_check_runs(
    queue_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deploy_adapter: None
) -> None:
    """The artifact of record has to be the exact bytes that were checked and deployed, so
    the injection happens upstream of the check rather than on the way out (research R3)."""
    run_id = await _make_buildable_run(queue_session, _doc())

    checked: list[str] = []
    original = site_handler.check_grounding
    monkeypatch.setattr(
        site_handler,
        "check_grounding",
        lambda html, *args: checked.append(html) or original(html, *args),
    )

    task = await _persisted_site_task(queue_session, run_id)
    with web_builder.agent.override(model=_builder(PAGE)):
        # The deploy parks for an operator, exactly as it did before this feature.
        with pytest.raises(ApprovalRequired):
            await handle_site(queue_session, task)

    assert '<style id="epyhia-fonts">' in checked[0]

    stored, deployed = (
        await queue_session.execute(
            text(
                "SELECT a.bytes, act.request FROM artifacts a, actions act "
                "WHERE a.run_id = :run_id AND a.kind = 'site' AND act.run_id = a.run_id"
            ),
            {"run_id": run_id},
        )
    ).one()
    page = stored.decode("utf-8")
    assert checked[0] == page == deployed["files"][0]["data"]
    assert "@font-face" in page


async def test_an_over_budget_page_fails_the_task_visibly(
    queue_session: AsyncSession,
) -> None:
    """FR-006. A runaway generation is caught on the finished bytes: the task fails, so an
    operator sees it, and no page nobody sized reaches the deploy request."""
    run_id = await _make_buildable_run(queue_session, _doc())
    runaway = PAGE.replace("<h1>Specimen</h1>", "<p>x</p>" * (PAGE_BUDGET_BYTES // 8))

    task = await _persisted_site_task(queue_session, run_id)
    with (
        web_builder.agent.override(model=_builder(runaway)),
        pytest.raises(PageOverBudget),
    ):
        await handle_site(queue_session, task)

    assert await _counts(queue_session, run_id) == (0, 0)


async def _report(session: AsyncSession, run_id: uuid.UUID):
    return (
        await session.execute(
            text(
                "SELECT bytes, grounding_status, revision FROM artifacts "
                "WHERE run_id = :run_id AND kind = 'design_report'"
            ),
            {"run_id": run_id},
        )
    ).one()


async def test_every_build_writes_a_design_report_an_operator_can_read(
    queue_session: AsyncSession, deploy_adapter: None
) -> None:
    """FR-008. Written on the way past rather than on a failure: a report that only appears
    when something is wrong is one an operator has to read by its absence."""
    run_id = await _make_buildable_run(queue_session, _doc())

    task = await _persisted_site_task(queue_session, run_id)
    with web_builder.agent.override(model=_builder(PAGE)), pytest.raises(ApprovalRequired):
        await handle_site(queue_session, task)

    row = await _report(queue_session, run_id)
    report = json.loads(row.bytes)
    jsonschema.Draft202012Validator(DESIGN_REPORT_SCHEMA).validate(report)

    stored = (
        await queue_session.execute(
            text(
                "SELECT bytes FROM artifacts WHERE run_id = :run_id AND kind = 'site'"
            ),
            {"run_id": run_id},
        )
    ).scalar_one()
    # The report describes the artifact of record — the same bytes that were grounded and
    # handed to the deploy request — so the two cannot drift apart.
    assert report["lint"] == [
        finding.model_dump()
        for finding in lint(
            stored.decode("utf-8"),
            brand_doc=_doc(),
            pairing=library.resolve_pairing(DISPLAY_ID, BODY_ID),
        )
    ]
    assert report["revision"] == {
        "outcome": "not_needed",
        "findings_before": len(report["lint"]),
    }
    assert row.revision == 0
    # Internal telemetry: never deployed, sent or published, so its status is asserted by
    # construction rather than scanned (research R7).
    assert row.grounding_status == "clean"


# A page with two of the six tells in it: a gradient behind the first section, and a
# `font-family` that is not the pairing's.
TELL_LADEN_PAGE = (
    "<!doctype html><html lang='en'><head><title>Specimen</title>"
    "<style>body{font-family:-apple-system,sans-serif;font-size:16px}"
    ".hero{background:linear-gradient(160deg,#101010,#b4552d)}</style></head>"
    "<body><main><section class='hero'><h1>Specimen</h1></section></main></body></html>"
)


async def test_a_page_the_lint_flagged_still_has_its_deploy_requested(
    queue_session: AsyncSession, deploy_adapter: None
) -> None:
    """FR-010. The tells are counted and recorded, and then the page goes on to the operator
    exactly as a clean one would: grounding remains the only mechanical refusal."""
    run_id = await _make_buildable_run(queue_session, _doc())

    task = await _persisted_site_task(queue_session, run_id)
    with (
        web_builder.agent.override(model=_builder(TELL_LADEN_PAGE)),
        pytest.raises(ApprovalRequired),
    ):
        await handle_site(queue_session, task)

    report = json.loads((await _report(queue_session, run_id)).bytes)
    assert {"gradient_hero", "ignored_pairing"} <= {
        finding["rule"] for finding in report["lint"]
    }

    action = (
        await queue_session.execute(
            text("SELECT action_type, state FROM actions WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    ).one()
    assert (action.action_type, action.state) == ("deploy", "awaiting_approval")
    assert await _counts(queue_session, run_id) == (1, 1)
