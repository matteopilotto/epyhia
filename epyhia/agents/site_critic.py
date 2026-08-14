import json
import time
import uuid
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.retry import call_with_retry
from epyhia.cost.ledger import record_call
from epyhia.cost.limits import limits_for_run
from epyhia.design.lint import DesignFinding
from epyhia.prompts_service import prompt_service

AGENT = "site_critic"
MODEL_ID = "claude-haiku-4-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

# The Reviewer's precedent, for the same reason: Haiku 4.5 predates adaptive thinking, so the
# budget is explicit and at least 1024, and `max_tokens` caps thinking and response together —
# without headroom an overrun reaches the ceiling mid-thought and the call returns only
# thinking, which PydanticAI raises as `UnexpectedModelBehavior`.
THINKING_BUDGET = 4_096
MAX_TOKENS = 16_384

# Eight is the whole punch list. A revision pass is one pass, and a list long enough to
# describe everything mildly wrong with a page spends it on nothing (contracts/site-critic.md).
MAX_FINDINGS = 8


class CritiqueFinding(BaseModel):
    """One thing wrong with how the page looks. There is no field here for replacement
    markup, CSS or copy, which is what makes "never edits the page" a property of the output
    shape rather than an instruction the critic could talk itself out of."""

    kind: Literal[
        "palette_ignored",
        "rhythm_uniform",
        "type_timid",
        "accent_overused",
        "hierarchy_flat",
        "broken_render",
        "other",
    ]
    where: str = Field(min_length=1)
    what: str = Field(min_length=1)


class Critique(BaseModel):
    findings: list[CritiqueFinding] = Field(max_length=MAX_FINDINGS)

    @property
    def clean(self) -> bool:
        """Approval is derived, never asserted — exactly as `Review.approved` is. A model
        that returns findings and calls the page fine anyway cannot produce a silent pass,
        because nothing reads an approval flag it wrote."""
        return not self.findings


agent = Agent(
    f"anthropic:{MODEL_ID}",
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    model_settings=AnthropicModelSettings(
        max_tokens=MAX_TOKENS,
        anthropic_thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
    ),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    defer_model_check=True,
)
# No toolset: the Site Critic holds no gate handle and reaches nothing. Structured output is
# prompted rather than tool-shaped, matching the Reviewer.
# Never set temperature/top_p/top_k.


async def critique(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    findings: Sequence[DesignFinding],
    screenshots: Sequence[bytes],
    task_id: uuid.UUID | None = None,
) -> Critique:
    """Judge one rendered page against the brand doc it was built to.

    There is no `brief` parameter and no `html` parameter, and that is the contract rather
    than an omission: the critic judges what a visitor sees, against this run's own art
    direction, and reaching the page source would invite it to prescribe code edits its
    output shape has no room for (contracts/site-critic.md).

    Raising is this function's only failure mode; the caller catches it and records a skip,
    because a run must not fail because a review of it did (FR-015).
    """
    request = {
        "brand_doc": brand_doc,
        "lint_findings": [finding.model_dump() for finding in findings],
    }
    prompt = [
        json.dumps(request, ensure_ascii=False, sort_keys=True),
        *(BinaryContent(data=image, media_type="image/png") for image in screenshots),
    ]

    started = time.perf_counter()
    limits = await limits_for_run(session, run_id)
    result = await call_with_retry(
        lambda: agent.run(
            prompt,
            output_type=PromptedOutput(Critique),
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
    return result.output
