import json
import re
import time
import uuid

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.cost.ledger import record_call
from epyhia.prompts_service import prompt_service

AGENT = "web_builder"
MODEL_ID = "claude-sonnet-5"
PROMPT_VERSION = prompt_service.active_version(AGENT)

# A full page exceeds the non-streaming ceiling, and the failure mode is the dangerous one:
# an SDK timeout leaves truncated HTML that is still syntactically plausible and would then
# be deployed (§8.1, FR-014). Streaming is what makes the whole document arrive.
MAX_TOKENS = 64_000

_FENCE = re.compile(r"^\s*```(?:html)?\n(?P<body>.*?)\n```\s*$", re.DOTALL | re.IGNORECASE)

agent = Agent(
    f"anthropic:{MODEL_ID}",
    instructions=prompt_service.render(AGENT, PROMPT_VERSION),
    model_settings=ModelSettings(max_tokens=MAX_TOKENS),
    # Constructing the agent must not require ANTHROPIC_API_KEY — only calling it does.
    defer_model_check=True,
)
# No toolset at all. The Web Builder writes markup and nothing else: the deploy is requested
# by the site handler once the artifact is stored and its grounding check has run, so there
# is no ordering in which a page reaches the world before it has been checked
# (contracts/action-gate.md §5, FR-016).
# Never set temperature/top_p/top_k — removed on Sonnet 5, and a non-default value 400s.


def _strip_fence(text: str) -> str:
    match = _FENCE.match(text)
    return match.group("body") if match else text.strip()


async def build_site(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    copy: dict,
    task_id: uuid.UUID | None = None,
) -> str:
    """Compose one self-contained HTML document from the brand doc and the reviewed copy.

    Returns the markup. Storing it, checking it and deploying it are the handler's, so this
    function has no way to put anything into the world.
    """
    prompt = json.dumps(
        {"brand_doc": brand_doc, "copy": copy}, ensure_ascii=False, sort_keys=True
    )

    started = time.perf_counter()
    async with agent.run_stream(prompt) as result:
        html = await result.get_output()
        usage = result.usage
    latency_ms = int((time.perf_counter() - started) * 1000)

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
    return _strip_fence(html)
