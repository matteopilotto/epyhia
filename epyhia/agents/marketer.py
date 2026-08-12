import json
import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.settings import ModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.retry import call_with_retry
from epyhia.cost.ledger import record_call
from epyhia.cost.limits import limits_for_run
from epyhia.prompts_service import prompt_service

AGENT = "marketer"
MODEL_ID = "claude-sonnet-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

# A pack piece is a few thousand tokens, not a page, so this stays well inside the
# non-streaming ceiling the Web Builder has to stream around (§8.1).
MAX_TOKENS = 8_192


# What the Marketer emits, one model per deliverable (contracts/agent-io.md). None of these
# carries a default, an example or a placeholder: a shape with a sample value in it is a
# client fact waiting to be inherited by whichever run forgets to overwrite it.
class CopySection(BaseModel):
    section: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    body: str = Field(min_length=1)


class LandingCopy(BaseModel):
    """The `copy` artifact, and the seam the Web Builder reads. Its shape is the contract
    that survived the interim stub's removal (T077), so the Web Builder did not change."""

    sections: list[CopySection] = Field(min_length=1)


class SocialPost(BaseModel):
    angle: str = Field(min_length=1)
    body: str = Field(min_length=1)


class SocialPosts(BaseModel):
    # Three to five is FR-020's range, enforced here rather than asked for in prose.
    posts: list[SocialPost] = Field(min_length=3, max_length=5)


class LaunchEmail(BaseModel):
    subject: str = Field(min_length=1)
    preheader: str = Field(min_length=1)
    body: str = Field(min_length=1)


class OnScreenValue(BaseModel):
    label: str = Field(min_length=1)
    amount_minor: int
    currency: str = Field(min_length=1)


class Scene(BaseModel):
    kind: str = Field(min_length=1)
    lines: list[str]
    values: list[OnScreenValue] | None = None


class VideoContent(BaseModel):
    headline: str = Field(min_length=1)
    subhead: str | None = None
    scenes: list[Scene] = Field(min_length=1)
    cta: str | None = None


class VideoProps(BaseModel):
    """Props JSON, never TSX (FR-026). The Marketer authors `content` and two presentation
    choices; `archetype_id` and the palette/type half of `style` are copied from the brand
    doc by `assemble_video_props`. That split is why `style` cannot carry a fact: there is
    no field on this model for the Marketer to put one in."""

    content: VideoContent
    motion_intensity: Literal["low", "medium", "high"]
    density: Literal["sparse", "balanced", "dense"] | None = None


DELIVERABLES: dict[str, type[BaseModel]] = {
    "copy": LandingCopy,
    "posts": SocialPosts,
    "email": LaunchEmail,
    "video_props": VideoProps,
}


agent = Agent(
    f"anthropic:{MODEL_ID}",
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    model_settings=ModelSettings(max_tokens=MAX_TOKENS),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    defer_model_check=True,
)
# Structured output is asked for in the prompt rather than through an output tool, so the
# toolset stays exactly the gate handles the contract fixes it at and nothing else
# (contracts/agent-io.md). The Marketer holds `send_email` and `publish` and never `deploy`;
# both land with their adapters in 4b (T078, T080).
# Never set temperature/top_p/top_k — removed on Sonnet 5, and a non-default value 400s.


def assemble_video_props(brand_doc: dict, props: VideoProps) -> dict:
    """Widen the Marketer's output to the full props contract by copying presentation from
    the brand doc (contracts/video-props.schema.json). The archetype is the Strategist's
    selection, not the Marketer's (§6.4)."""
    style = {
        "palette": brand_doc["palette"],
        "type": brand_doc["type"],
        "motion_intensity": props.motion_intensity,
    }
    if props.density is not None:
        style["density"] = props.density
    return {
        "archetype_id": brand_doc["video_archetype"],
        "content": props.content.model_dump(exclude_none=True),
        "style": style,
    }


async def draft(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    deliverable: str,
    previous: dict | None = None,
    violations: list[dict] | None = None,
    task_id: uuid.UUID | None = None,
) -> BaseModel:
    """Write one pack deliverable, or revise it against a reviewer's violations.

    The brand doc is the whole of the input. The brief is not passed here and there is no
    parameter through which it could be: the Marketer's inability to read a client fact it
    was not given is a property of this signature, not of an instruction (FR-011, §3.2).

    A revision carries the previous draft and the violations against it and nothing else —
    no transcript, no earlier violations, no reviewer reasoning beyond what it itemised.
    """
    output_type = DELIVERABLES[deliverable]
    request: dict = {"deliverable": deliverable, "brand_doc": brand_doc}
    if violations is not None:
        request["previous_draft"] = previous
        request["violations"] = violations

    started = time.perf_counter()
    limits = await limits_for_run(session, run_id)
    result = await call_with_retry(
        lambda: agent.run(
            json.dumps(request, ensure_ascii=False, sort_keys=True),
            output_type=PromptedOutput(output_type),
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
