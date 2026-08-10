import time
from dataclasses import dataclass
from typing import Literal

import logfire
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from epyhia.prompts_service import prompt_service

AGENT = "guardrail"
# Bare id for the ledger, prefixed id for the agent — `rate_for` keys on `pricing.yaml`'s
# bare id and raises on an unknown one, so the two are split exactly as the agents split them.
MODEL_ID = "claude-haiku-4-5"
GUARDRAIL_MODEL = f"anthropic:{MODEL_ID}"
PROMPT_VERSION = prompt_service.active_version(AGENT)


class GuardrailVerdict(BaseModel):
    decision: Literal["pass", "reject"]
    reason: str


@dataclass(frozen=True)
class GuardrailResult:
    """The verdict, and what reaching it cost. The caller records the call once the run it
    belongs to exists — screening is the one model call made before there is a `run_id` to
    stamp on it, and it is metered like every other (FR-054, SC-007)."""

    decision: Literal["pass", "reject"]
    reason: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    latency_ms: int


_agent = Agent(
    GUARDRAIL_MODEL,
    output_type=GuardrailVerdict,
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    # The app starts with no credentials configured (FR-064) and CI runs with none at all.
    defer_model_check=True,
)


def _as_named_fields(value: object, prefix: str = "") -> list[str]:
    """Renders the brief as labelled field: value lines rather than raw prose, so the
    guardrail sees structured, named fields (FR-008) even though its whole job is to
    read their content for injection attempts."""
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lines.extend(_as_named_fields(item, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            lines.extend(_as_named_fields(item, f"{prefix}[{index}]"))
    else:
        lines.append(f"{prefix}: {value}")
    return lines


async def screen_brief(brief: dict) -> GuardrailResult:
    """Screens the raw brief for instructions aimed at the system, logging the decision
    and reason on both outcomes, and stopping a rejected brief before any expensive
    work begins (FR-007)."""
    prompt = "\n".join(_as_named_fields(brief))
    started = time.perf_counter()
    result = await _agent.run(
        prompt,
        usage_limits=UsageLimits(request_limit=1, output_tokens_limit=200),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    verdict = result.output
    usage = result.usage
    logfire.info(
        "guardrail decision",
        decision=verdict.decision,
        reason=verdict.reason,
        model=MODEL_ID,
    )
    return GuardrailResult(
        decision=verdict.decision,
        reason=verdict.reason,
        model=MODEL_ID,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        latency_ms=latency_ms,
    )
