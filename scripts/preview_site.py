"""Drive one brief through the pipeline and write what came out to disk so you can read it.

    uv run python scripts/preview_site.py                       # stub models, no key needed
    uv run python scripts/preview_site.py --brief path/to.json  # any brief
    uv run python scripts/preview_site.py --stages site,demand  # the page and the pack
    ANTHROPIC_API_KEY=sk-... uv run python scripts/preview_site.py --real

`--real` calls Opus 5, Sonnet 5 and Haiku 4.5 and costs money. Everything else runs offline:
the deploy is a fake adapter, so no Vercel token is used and nothing reaches the world.

`--stages` takes any of `copy`, `site`, `demand`, `money`, closed over the fixed dependency
edges — `site` therefore also runs `copy`. `demand` writes the pack and queues the render;
the render itself is left pending, since it shells out to Remotion.

This TRUNCATEs the application database on every invocation, so a previous run's artifacts
are gone once the next one starts.
"""

import argparse
import asyncio
import json
import sys
import uuid
import webbrowser
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer, strategist, web_builder
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.keys import alias_for
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.ingest.normalise import _MINOR_EXPONENT
from epyhia.models.actions import Action
from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service
from epyhia.queue.pipeline import resolve_stages
from epyhia.queue.worker import run_once

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "preview"
TABLES = "actions, artifacts, agent_calls, tasks, runs, brand_docs, briefs"


class FakeDeploy:
    """Nothing leaves the machine. The real adapter is exercised in tests/gate/."""

    action_type = "deploy"
    requires_approval = True

    def __init__(self) -> None:
        self.published: dict[str, str] = {}

    async def execute(self, request: dict, ctx) -> dict:
        self.published = {item["file"]: item["data"] for item in request["files"]}
        return {"deployment_id": "local-preview"}

    async def verify(self, request: dict, result: dict, ctx) -> dict:
        name = ctx.brand_doc["name"]
        assert name in self.published["index.html"], "page does not present the brand doc name"
        return {"status": 200, "matched_name": name, "url": f"https://{alias_for(request['brief_hash'])}"}


def stub_strategist(brief: dict, stages: list[str]) -> FunctionModel:
    calls: list[int] = []

    def respond(messages, info) -> ModelResponse:
        calls.append(1)
        if len(calls) > 1:
            return ModelResponse(parts=[TextPart("planned")])
        doc = {
            "name": brief["business_name"],
            "descriptor": brief["one_liner"],
            "positioning": brief["positioning"]["why_them"],
            "palette": {"bg": "#101014", "fg": "#f4f4f5", "accent": "#c2410c", "muted": "#71717a"},
            "type": {"display": "Display Face", "body": "Body Face"},
            "motion_language": "mechanical, deliberate",
            "composition_archetype": "editorial_stack",
            "video_archetype": "technical_spec_sheet",
            "voice": brief["voice"],
            # Copied field-for-field from the brief minus the charge currency, which is what
            # the real Strategist is asked to do. Deriving it here rather than writing one
            # out keeps every client fact in the brief where it belongs.
            "offerings": [
                {k: v for k, v in product.items() if k != "currency_charge"}
                for product in brief["products"]
            ],
            "composition_plan": [
                {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"},
                {"section": "reach", "layout": "contact_block", "intent": "how to get in touch"},
            ],
        }
        return ModelResponse(parts=[
            ToolCallPart("write_brand_doc", {"doc": doc}),
            ToolCallPart("enqueue_tasks", {"stages": stages}),
        ])

    return FunctionModel(respond)


def _major_form(offering: dict) -> str:
    """`price_minor` as a customer would see it written. The exponent comes from the table
    the normaliser reduces by, so a stub price cannot read as an ungrounded numeral for the
    want of a decimal point."""
    exponent = _MINOR_EXPONENT.get(offering["currency_display"], 2)
    return f"{offering['currency_display']} {Decimal(offering['price_minor']).scaleb(-exponent)}"


def stub_marketer() -> FunctionModel:
    """One shape per deliverable, each stating the offerings it was handed by name and
    price. A stub that wrote around the offerings would leave the fact channel unexercised
    on the free path — which is the omission this whole checkpoint is about."""

    def respond(messages, info) -> ModelResponse:
        payload = json.loads(messages[-1].parts[-1].content)
        doc = payload["brand_doc"]
        offerings = doc["offerings"]

        if payload["deliverable"] == "posts":
            # SocialPosts wants three at minimum; a brief may carry fewer offerings.
            out = {"posts": [
                {
                    "angle": offerings[i % len(offerings)]["name"],
                    "body": f"{offerings[i % len(offerings)]['name']} — "
                            f"{_major_form(offerings[i % len(offerings)])}.",
                }
                for i in range(max(3, len(offerings)))
            ]}
        elif payload["deliverable"] == "email":
            out = {
                "subject": doc["descriptor"],
                "preheader": doc["positioning"],
                "body": " ".join(f"{o['name']}, {_major_form(o)}." for o in offerings),
            }
        elif payload["deliverable"] == "video_props":
            out = {
                "content": {
                    "headline": doc["name"],
                    "subhead": doc["descriptor"],
                    "scenes": [
                        {
                            "kind": "offer",
                            "lines": [o["name"]],
                            # Structured, because the check that reads values does not read
                            # prose — and an empty `values` is exactly what 5.3 found.
                            "values": [{
                                "label": o["name"],
                                "amount_minor": o["price_minor"],
                                "currency": o["currency_display"],
                            }],
                        }
                        for o in offerings
                    ],
                },
                "motion_intensity": "medium",
            }
        else:
            out = {"sections": [
                {"section": e["section"], "headline": doc["descriptor"], "body": doc["positioning"]}
                for e in doc["composition_plan"]
            ]}
            out["sections"][0]["body"] = " ".join(
                f"{o['name']}, {_major_form(o)}." for o in offerings
            )

        return ModelResponse(parts=[TextPart(json.dumps(out))])

    return FunctionModel(respond)


def stub_reviewer() -> FunctionModel:
    def respond(messages, info) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps({"violations": []}))])

    return FunctionModel(respond)


def stub_web_builder() -> FunctionModel:
    async def stream(messages, info):
        payload = json.loads(messages[-1].parts[-1].content)
        doc, copy = payload["brand_doc"], payload["copy"]
        sections = "".join(
            f"<section><h2>{s['headline']}</h2><p>{s['body']}</p></section>"
            for s in copy["sections"]
        )
        html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{doc['name']}</title><style>
:root{{--bg:{doc['palette']['bg']};--fg:{doc['palette']['fg']};--accent:{doc['palette']['accent']};--muted:{doc['palette']['muted']}}}
body{{background:var(--bg);color:var(--fg);font-family:system-ui}}
body{{margin:0;padding:4rem 2rem;max-width:52rem}}
h1{{font-size:3rem;margin:0 0 .5rem}}
h2{{color:var(--accent)}}
p{{color:var(--muted);line-height:1.6}}
</style></head><body><h1>{doc['name']}</h1><p>{doc['descriptor']}</p>{sections}
<script>console.log("stub build");</script></body></html>"""
        for i in range(0, len(html), 64):
            yield html[i:i + 64]

    return FunctionModel(stream_function=stream)


async def _ensure_enqueued(session, run_id: uuid.UUID, stages: list[str]) -> list[str]:
    """In `--real` mode the Strategist chooses what to enqueue, so a run can legitimately
    not select `demand` — and checking that path needs it to run regardless. Anything asked
    for but unselected is enqueued here and named in the output, never silently.

    No `depends_on`: this driver runs the stages itself, in pipeline order.
    """
    present = set(
        (await session.execute(select(Task.kind).where(Task.run_id == run_id))).scalars()
    )
    forced = [stage for stage in stages if stage not in present]
    for stage in forced:
        session.add(Task(id=uuid.uuid4(), run_id=run_id, kind=stage, state="pending"))
    if forced:
        await session.commit()
    return forced


async def main(brief_path: Path, real: bool, open_browser: bool, stages: list[str]) -> int:
    brief_payload = json.loads(brief_path.read_text())
    brief_hash = content_sha256(brief_payload)

    if real and not settings.anthropic_api_key:
        print("--real needs ANTHROPIC_API_KEY set", file=sys.stderr)
        return 1
    if not settings.vercel_token:
        # The gate checks the credential before any adapter runs (FR-064); the deploy here
        # is a fake, so this only gets it past the precondition.
        settings.vercel_token = "local-preview-not-a-real-token"

    engine = create_async_engine(
        settings.database_url or "postgresql+asyncpg://epyhia:epyhia@localhost:5432/epyhia"
    )
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    session = async_sessionmaker(bind=engine, expire_on_commit=False)()

    adapter = FakeDeploy()
    registry.register(adapter)

    brief = Brief(
        id=uuid.uuid4(), payload=brief_payload, content_sha256=brief_hash,
        guardrail_decision="pass", guardrail_reason="local preview", guardrail_model="none",
    )
    session.add(brief)
    run = Run(
        id=uuid.uuid4(), brief_id=brief.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(brief_payload, datetime.now(UTC).year),
        budget_usd=25, status="running", alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.flush()
    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="plan", state="pending"))
    await session.commit()

    print(f"brief    {brief_path}  ({brief_hash[:12]}…)")
    print(f"alias    {run.alias}")
    print(f"models   {'REAL — this costs money' if real else 'stubbed (offline, free)'}")
    print(f"stages   {' → '.join(stages)}\n")

    if real:
        assert await run_once(session, kind="plan"), "plan did not run"
        forced = await _ensure_enqueued(session, run.id, stages)
        for stage in stages:
            assert await run_once(session, kind=stage), f"{stage} did not run"
    else:
        with strategist.agent.override(model=stub_strategist(brief_payload, stages)):
            assert await run_once(session, kind="plan"), "plan did not run"
        forced = await _ensure_enqueued(session, run.id, stages)
        with (
            marketer.agent.override(model=stub_marketer()),
            reviewer.agent.override(model=stub_reviewer()),
            web_builder.agent.override(model=stub_web_builder()),
        ):
            for stage in stages:
                assert await run_once(session, kind=stage), f"{stage} did not run"

    if forced:
        print(f"forced   {', '.join(forced)} — the Strategist did not select it\n")

    brand_doc = (await session.execute(select(BrandDoc))).scalar_one()
    artifacts = {
        a.kind: a for a in (await session.execute(select(Artifact))).scalars()
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "brand_doc.json").write_text(json.dumps(brand_doc.doc, indent=2, ensure_ascii=False))
    for kind, artifact in artifacts.items():
        name = "index.html" if kind == "site" else f"{kind}.json"
        (OUT / name).write_text(artifact.bytes.decode("utf-8"))

    print(f"brand doc v{brand_doc.version}  name={brand_doc.doc['name']!r}")
    for kind, artifact in sorted(artifacts.items()):
        flag = "clean" if artifact.grounding_status == "clean" else "FLAGGED"
        print(f"artifact {kind:<11} {flag:<8} {len(artifact.bytes):>6} bytes")
        if artifact.violations:
            print(f"         ungrounded numerals: {artifact.violations}")

    render = (await session.execute(
        select(Task).where(Task.run_id == run.id, Task.kind == "video")
    )).scalars().first()
    if render is not None:
        print(f"video    render task {render.state} — left for the worker, which shells out"
              " to Remotion")

    action = (await session.execute(select(Action))).scalar_one_or_none()
    if action is None and "site" not in stages:
        print("\nno deploy action — this selection never built a page")
    elif action is None:
        print("\nno deploy action — the site artifact was flagged, so the gate refused it")
    else:
        print(f"\ndeploy   {action.state}   key={action.idempotency_key[:16]}…")
        await gate.record_approval(session, action.id, "local|preview")
        session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="resume", state="pending",
                         payload={"action_id": str(action.id)}))
        await session.commit()
        await run_once(session, kind="resume")
        await session.refresh(action)
        print(f"approved {action.state}   evidence={action.evidence}")

    page = OUT / "index.html"
    print(f"\npage     {page}")
    if open_browser and page.exists():
        webbrowser.open(page.as_uri())

    await session.close()
    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", type=Path, default=REPO / "tests/fixtures/briefs/one.json")
    parser.add_argument("--real", action="store_true", help="call the real models (costs money)")
    parser.add_argument("--open", action="store_true", help="open the page in a browser")
    parser.add_argument(
        "--stages",
        default="site",
        help="comma-separated: copy, site, demand, money (default: site)",
    )
    args = parser.parse_args()
    # Closed over the fixed dependency edges and returned in pipeline order, so `site`
    # brings `copy` with it and the driver never has to know that edge itself.
    selected = resolve_stages([s.strip() for s in args.stages.split(",") if s.strip()])
    raise SystemExit(asyncio.run(main(args.brief, args.real, args.open, selected)))
