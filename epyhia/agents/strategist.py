import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.retry import call_with_retry
from epyhia.cost.ledger import record_call
from epyhia.cost.limits import limits_for_run
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.runs import Run
from epyhia.prompts_service import prompt_service

AGENT = "strategist"
MODEL_ID = "claude-opus-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

_HEX = r"^#[0-9a-fA-F]{6}$"

# The stages the Strategist may select from. A closed Literal rather than a free string is
# the mechanical half of "the pipeline is fixed in code": the model chooses which stages
# run, never what a stage is or what it depends on (FR-013, Principle III).
Stage = Literal["copy", "site", "demand", "money"]


# Mirrors contracts/brand-doc.schema.json. The schema is fixed and the contents vary
# entirely by client, so nothing here carries a default, an example or a client token.
class Palette(BaseModel):
    bg: str = Field(pattern=_HEX)
    fg: str = Field(pattern=_HEX)
    accent: str = Field(pattern=_HEX)
    muted: str = Field(pattern=_HEX)


class TypePairing(BaseModel):
    display: str = Field(min_length=1)
    body: str = Field(min_length=1)


class Voice(BaseModel):
    adjectives: list[str] = Field(min_length=1)
    do: list[str]
    dont: list[str]


class PlannedSection(BaseModel):
    section: str
    layout: str
    intent: str


class Offering(BaseModel):
    """One entry from the brief's `products[]`, carried across field-for-field minus
    `currency_charge` — Ops' charging detail, which belongs on no page. This is the only
    route by which what the business sells reaches the agents that sell it, since none of
    them but the Reviewer ever reads the brief (FR-011)."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    price_minor: int = Field(ge=0)
    currency_display: str = Field(min_length=1)
    billing: Literal["subscription", "one_time"]
    features: list[str]
    not_covered: list[str]


class BrandDocument(BaseModel):
    name: str = Field(min_length=1)
    descriptor: str = Field(min_length=1)
    positioning: str = Field(min_length=1)
    palette: Palette
    type: TypePairing
    motion_language: str = Field(min_length=1)
    composition_archetype: str
    video_archetype: str
    voice: Voice
    composition_plan: list[PlannedSection] = Field(min_length=1)
    # Required, not optional: an optional fact channel is one the Strategist omits, leaving
    # every downstream "state the offerings" rule pointing at nothing.
    offerings: list[Offering] = Field(min_length=1)


@dataclass
class StrategistDeps:
    """What the Strategist reaches through. Note what is absent: no gate handle, no
    credential store, no HTTP client. Its inability to make an external call is a property
    of what it was constructed with, not of an instruction in its prompt (FR-042)."""

    session: AsyncSession
    run_id: uuid.UUID
    brief_id: uuid.UUID
    selected_stages: list[Stage] = field(default_factory=list)


agent = Agent(
    f"anthropic:{MODEL_ID}",
    deps_type=StrategistDeps,
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    defer_model_check=True,
)
# No `output_type`: an output tool would be a third entry in a toolset the contract fixes
# at exactly two (contracts/action-gate.md §1, contracts/agent-io.md).
# Never set temperature/top_p/top_k — removed on Opus 5, and a non-default value 400s.


@agent.tool
async def write_brand_doc(ctx: RunContext[StrategistDeps], doc: BrandDocument) -> str:
    """Record the brand document for this run."""
    session = ctx.deps.session
    next_version = (
        await session.execute(
            select(func.coalesce(func.max(BrandDoc.version), 0) + 1).where(
                BrandDoc.brief_id == ctx.deps.brief_id
            )
        )
    ).scalar_one()

    # Append-only: an edit inserts version + 1, never updates in place (FR-012).
    brand_doc = BrandDoc(
        brief_id=ctx.deps.brief_id,
        version=next_version,
        doc=doc.model_dump(),
        authored_by=AGENT,
    )
    session.add(brand_doc)
    await session.flush()

    run = await session.get(Run, ctx.deps.run_id)
    run.brand_doc_id = brand_doc.id
    await session.flush()
    return f"brand doc v{next_version} recorded"


@agent.tool
def enqueue_tasks(ctx: RunContext[StrategistDeps], stages: list[Stage]) -> str:
    """Queue the stages this run needs."""
    ctx.deps.selected_stages = list(stages)
    return f"queued: {', '.join(stages)}"


async def run_strategist(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brief_id: uuid.UUID,
    brief_payload: dict,
    task_id: uuid.UUID | None = None,
) -> StrategistDeps:
    """Plan one run. The brief goes in the user message as a structured object with named
    fields — never as prose spliced into the instructions, where an injected sentence would
    read as something addressed to the model (FR-008, §9.6).
    """
    deps = StrategistDeps(session=session, run_id=run_id, brief_id=brief_id)
    started = time.perf_counter()
    limits = await limits_for_run(session, run_id)
    result = await call_with_retry(
        lambda: agent.run(
            json.dumps(brief_payload, ensure_ascii=False, sort_keys=True),
            deps=deps,
            usage_limits=limits,
        ),
        agent=AGENT,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    usage = result.usage
    await record_call(
        session,
        run_id=run_id,
        task_id=task_id,
        agent=AGENT,
        model_id=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        latency_ms=latency_ms,
        cache_hit=usage.cache_read_tokens > 0,
    )
    return deps
