import json
import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.retry import call_with_retry
from epyhia.cost.ledger import record_call
from epyhia.cost.limits import limits_for_run
from epyhia.prompts_service import prompt_service

AGENT = "reviewer"
MODEL_ID = "claude-haiku-4-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

# Thinking is where the Reviewer works a check through; `why` is where it states the result.
# Without a scratchpad it used `why` as one, and entries reading "this is correct" or
# retracting themselves in their own sentence shipped as violations and spent revisions.
#
# Haiku 4.5 predates adaptive thinking: the budget is explicit and at least 1024. It is a
# target, not a stop — the model may think past it, and `max_tokens` caps thinking and
# response together, so the two are not a budget and a remainder. At 8192 an overrun reached
# the ceiling mid-thought and the call came back with only thinking in it, which PydanticAI
# raises as `UnexpectedModelBehavior` and which fails the whole stage. The headroom is what
# makes the answer reachable; it costs nothing unless it is generated.
THINKING_BUDGET = 4_096
MAX_TOKENS = 16_384


class Violation(BaseModel):
    """One itemised finding (FR-023, contracts/agent-io.md). There is no field here for
    replacement wording, which is what makes "never rewrites the draft" a property of the
    output shape rather than an instruction the Reviewer could talk itself out of."""

    kind: Literal["unsupported_claim", "voice", "missing_fact"]
    quote: str = Field(min_length=1)
    why: str = Field(min_length=1)


class Review(BaseModel):
    violations: list[Violation]

    @property
    def approved(self) -> bool:
        """Approval is derived, never asserted. A model that returns violations and calls
        the draft approved anyway cannot produce a silent pass, because nothing reads an
        approval flag it wrote (FR-023)."""
        return not self.violations


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
# No toolset: the Reviewer holds no gate handle and reaches nothing (contracts/agent-io.md).
# Structured output is prompted rather than tool-shaped, matching the Marketer.
# Never set temperature/top_p/top_k. Haiku 4.5's prompt-cache minimum is 4096 tokens, so a
# brand doc that caches for the Strategist may well not cache here (§8.1).


async def review(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    draft: dict,
    brand_doc: dict,
    brief: dict,
    task_id: uuid.UUID | None = None,
) -> Review:
    """Check one draft against the brand doc's voice and the brief's facts.

    The Reviewer is the only agent that reads the raw brief, because it needs facts as well
    as voice (FR-011, §3.2). What it does not get is the run transcript: there is no
    parameter for message history here, so it cannot be handed the author's reasoning and
    talked round by it.

    The numeric check does not run here. It is an artifact-boundary function that has
    already run, deterministically, before this call (Principle VI, §3.4).
    """
    request = {"draft": draft, "brand_doc": brand_doc, "brief": brief}

    started = time.perf_counter()
    limits = await limits_for_run(session, run_id)
    result = await call_with_retry(
        lambda: agent.run(
            json.dumps(request, ensure_ascii=False, sort_keys=True),
            output_type=PromptedOutput(Review),
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
