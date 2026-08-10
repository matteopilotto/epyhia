from dataclasses import dataclass
from typing import Literal

import logfire
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from epyhia.prompts_service import prompt_service

AGENT = "guardrail"
GUARDRAIL_MODEL = "anthropic:claude-haiku-4-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)


class GuardrailVerdict(BaseModel):
    decision: Literal["pass", "reject"]
    reason: str


@dataclass(frozen=True)
class GuardrailResult:
    decision: Literal["pass", "reject"]
    reason: str
    model: str


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
    result = await _agent.run(
        prompt,
        usage_limits=UsageLimits(request_limit=1, output_tokens_limit=200),
    )
    verdict = result.output
    logfire.info(
        "guardrail decision",
        decision=verdict.decision,
        reason=verdict.reason,
        model=GUARDRAIL_MODEL,
    )
    return GuardrailResult(decision=verdict.decision, reason=verdict.reason, model=GUARDRAIL_MODEL)
