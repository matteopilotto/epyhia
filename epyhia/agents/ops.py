import json
import time
import uuid

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.settings import ModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the Stripe pairs
from epyhia.cost.ledger import record_call
from epyhia.gate import gate
from epyhia.gate.keys import arm_charge_path_key, stripe_price_key, stripe_product_key
from epyhia.ingest.catalogue import catalogue_hash
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.prompts_service import prompt_service

AGENT = "ops"
MODEL_ID = "claude-haiku-4-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

# One short line per catalogue entry. Nothing here approaches the non-streaming ceiling.
MAX_TOKENS = 4_096

# Ops' whole authority, enumerated. It has no `deploy` and no `publish`, and it never sees
# markup: the three action types below are the only ones this module names
# (contracts/action-gate.md §1, DESIGN.md §3.1).
HANDLES = ("stripe_product", "stripe_price", "arm_charge_path")


class MismatchedCatalogue(Exception):
    """Ops returned a set of identifiers that is not the run's own. Nothing is created: an
    item silently dropped from a catalogue is an item nobody can buy, and an item silently
    added is one the business never agreed to sell."""


class CatalogueLine(BaseModel):
    slug: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CatalogueLines(BaseModel):
    lines: list[CatalogueLine] = Field(min_length=1)


agent = Agent(
    f"anthropic:{MODEL_ID}",
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    model_settings=ModelSettings(max_tokens=MAX_TOKENS),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    defer_model_check=True,
)
# No toolset: the three handles above are requested by `wire_catalogue` below, which is the
# only path out of this module. There is no function on this agent through which a model
# could reach the world (FR-033).
# Never set temperature/top_p/top_k — removed on the frontier models, and a non-default 400s.


async def describe_catalogue(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    catalogue: list[dict],
    task_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """One processor-facing line per catalogue entry, keyed by slug.

    **No amount, currency or billing type is passed in and none comes back.** Those fields
    are carried from the run's resolved catalogue to the gate request by `wire_catalogue`,
    untouched, so there is no step at which a model could restate a price and no field on
    `CatalogueLine` for it to put one in (FR-027, Principle I).
    """
    described = [
        {key: row[key] for key in ("slug", "name", "description", "features", "not_covered")}
        for row in catalogue
    ]
    request = {"brand_doc": brand_doc, "catalogue": described}

    started = time.perf_counter()
    result = await agent.run(
        json.dumps(request, ensure_ascii=False, sort_keys=True),
        output_type=PromptedOutput(CatalogueLines),
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

    lines = {line.slug: line.description for line in result.output.lines}
    if lines.keys() != {row["slug"] for row in catalogue}:
        raise MismatchedCatalogue(
            f"described {sorted(lines)}, resolved {sorted(row['slug'] for row in catalogue)}"
        )
    return lines


async def wire_catalogue(
    session: AsyncSession,
    *,
    run: Run,
    brief: Brief,
    brand_doc: dict,
    task_id: uuid.UUID | None = None,
) -> None:
    """Create the catalogue in the payment processor, then ask for the one approval.

    Every monetary field on every request below is read from `run.resolved_catalogue` at the
    moment it is used — which is `brief.products[]` with the ingest-derived slug on it. The
    raw brief is never read here and the brand doc carries no charge currency, so there is no
    route by which a price could arrive from anywhere but the business's own record (FR-011,
    FR-027).

    `arm_charge_path` raises `ApprovalRequired`, which parks the money task at the pause with
    the action id on its payload (R7 step 4). The products and prices already exist by then
    and are keyed, so the resumed task re-requests them and short-circuits rather than
    creating a second set.
    """
    catalogue = run.resolved_catalogue
    lines = await describe_catalogue(
        session,
        run_id=run.id,
        brand_doc=brand_doc,
        catalogue=catalogue,
        task_id=task_id,
    )

    priced = []
    for row in catalogue:
        product = await gate.request(
            session,
            run_id=run.id,
            requested_by=AGENT,
            action_type="stripe_product",
            action_request={
                "slug": row["slug"],
                "name": row["name"],
                "description": lines[row["slug"]],
            },
            idempotency_key=stripe_product_key(
                brief.content_sha256, row["name"], row["price_minor"], row["billing"]
            ),
            task_id=task_id,
            brand_doc=brand_doc,
        )
        price = await gate.request(
            session,
            run_id=run.id,
            requested_by=AGENT,
            action_type="stripe_price",
            action_request={
                "slug": row["slug"],
                "product_id": product["evidence"]["product_id"],
                "price_minor": row["price_minor"],
                "currency_charge": row["currency_charge"],
                "billing": row["billing"],
                "billing_interval": row.get("billing_interval"),
                "billing_interval_count": row.get("billing_interval_count"),
            },
            idempotency_key=stripe_price_key(
                brief.content_sha256, row["name"], row["price_minor"], row["billing"]
            ),
            task_id=task_id,
            brand_doc=brand_doc,
        )
        priced.append({**row, "price_id": price["evidence"]["price_id"]})

    await gate.request(
        session,
        run_id=run.id,
        requested_by=AGENT,
        action_type="arm_charge_path",
        # The whole resolved catalogue, priced: this request is what the approval screen
        # renders, so every amount, currency and billing type the operator is agreeing to is
        # on the row they click (FR-028, contracts/action-gate.md §6).
        action_request={"catalogue": priced},
        idempotency_key=arm_charge_path_key(
            brief.content_sha256, catalogue_hash(catalogue)
        ),
        task_id=task_id,
        brand_doc=brand_doc,
    )
