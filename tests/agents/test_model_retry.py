import asyncio
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import retry, web_builder
from epyhia.agents.memo import memo_key
from epyhia.agents.memo import write as memo_write
from epyhia.models.agent_calls import AgentCall

pytestmark = pytest.mark.asyncio

# Nothing here is a client fact: the page the fake model returns is a marker string, and the
# inputs below are the shape `build_site` takes rather than any brief's contents.
BRAND_DOC = {"name": "N"}
BRAND_DOC_VERSION = 1
COPY = {"sections": []}
CHECKOUT = {"run_id": "r", "endpoint": "/checkout", "products": []}

PAGE = "<!doctype html><html><body><h1>generated</h1></body></html>"


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every backoff the helper asks for, taken at zero wall clock.

    The assertions here are about attempt *counts*, so the seconds a real overload is worth
    waiting would be pure suite latency — the same trade the gate's verify schedule makes in
    the root conftest.
    """
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return recorded


def _streaming_model(
    behaviour: Callable[[int], None], *, page: str = PAGE
) -> tuple[FunctionModel, list[int]]:
    """A streamed Web Builder call whose n-th attempt does whatever `behaviour` says.

    Raising *inside* the generator, before the first chunk is yielded, is the observed shape:
    the provider returned 200 and put the error in the body, so the failure arrives on
    `peek()` of the first chunk rather than as a transport-level status.
    """
    calls: list[int] = []

    async def stream(messages: list, info: AgentInfo) -> AsyncIterator[str]:
        calls.append(1)
        behaviour(len(calls))
        yield page

    return FunctionModel(stream_function=stream), calls


async def _open_run(session: AsyncSession) -> uuid.UUID:
    """The brief + run rows the `agent_calls` foreign key requires, and nothing else."""
    brief_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO briefs (id, payload, content_sha256, guardrail_decision, "
            "guardrail_model) VALUES (:id, '{}'::jsonb, :hash, 'pass', 'test-model')"
        ),
        {"id": brief_id, "hash": uuid.uuid4().hex},
    )
    run_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO runs (id, brief_id, prompt_version, grounding_set, budget_usd, "
            "spend_usd, status, alias) "
            "VALUES (:id, :brief_id, 'v1', '{}'::jsonb, 25, 0, 'running', :alias)"
        ),
        {"id": run_id, "brief_id": brief_id, "alias": f"epyhia-{run_id.hex[:12]}.vercel.app"},
    )
    await session.flush()
    return run_id


async def _build(session: AsyncSession, run_id: uuid.UUID, model: FunctionModel) -> str:
    with web_builder.agent.override(model=model):
        return await web_builder.build_site(
            session,
            run_id=run_id,
            brand_doc=BRAND_DOC,
            brand_doc_version=BRAND_DOC_VERSION,
            copy=COPY,
            checkout=CHECKOUT,
        )


async def test_a_streamed_overload_is_retried_and_the_second_attempt_is_returned(
    db_session: AsyncSession, sleeps: list[float]
) -> None:
    """The failure that ended run `c7751c83`: `overloaded_error` delivered as an SSE event in
    an already-successful response, so it carries no status code at all. Retrying the
    unclassifiable is deliberate — a wrong retry costs one call, a wrong refusal costs the
    run."""
    run_id = await _open_run(db_session)

    def behaviour(attempt: int) -> None:
        if attempt == 1:
            raise ModelAPIError(web_builder.MODEL_ID, "{'type': 'overloaded_error'}")

    model, calls = _streaming_model(behaviour)
    html = await _build(db_session, run_id, model)

    assert html == PAGE
    assert len(calls) == 2
    assert len(sleeps) == 1


async def test_a_429_is_retried(db_session: AsyncSession, sleeps: list[float]) -> None:
    """The one status the provider spells out as "ask again later"."""
    run_id = await _open_run(db_session)

    def rate_limited(attempt: int) -> None:
        if attempt == 1:
            raise ModelHTTPError(429, web_builder.MODEL_ID, "rate limited")

    model, calls = _streaming_model(rate_limited)
    assert await _build(db_session, run_id, model) == PAGE
    assert len(calls) == 2


async def test_a_400_costs_exactly_one_call(
    db_session: AsyncSession, sleeps: list[float]
) -> None:
    """A 400 is the shape a stray `temperature` produces and is permanent; three more of them
    is three times the latency and the same answer."""
    run_id = await _open_run(db_session)

    def bad_request(attempt: int) -> None:
        raise ModelHTTPError(400, web_builder.MODEL_ID, "invalid request")

    model, calls = _streaming_model(bad_request)
    with pytest.raises(ModelHTTPError) as raised:
        await _build(db_session, run_id, model)

    assert raised.value.status_code == 400
    assert len(calls) == 1
    assert sleeps == []


async def test_exhaustion_re_raises_the_last_error(
    db_session: AsyncSession, sleeps: list[float]
) -> None:
    """Once retrying has genuinely stopped helping the task still lands `failed`, with the
    provider's own last word as its reason rather than a wrapper's."""
    run_id = await _open_run(db_session)

    def always_overloaded(attempt: int) -> None:
        raise ModelAPIError(web_builder.MODEL_ID, f"overloaded on attempt {attempt}")

    model, calls = _streaming_model(always_overloaded)
    with pytest.raises(ModelAPIError) as raised:
        await _build(db_session, run_id, model)

    assert f"attempt {retry.MODEL_RETRY_ATTEMPTS}" in str(raised.value)
    assert len(calls) == retry.MODEL_RETRY_ATTEMPTS
    assert len(sleeps) == retry.MODEL_RETRY_ATTEMPTS - 1


async def test_a_memo_hit_makes_no_call_and_no_sleep(
    db_session: AsyncSession, sleeps: list[float]
) -> None:
    """The retry sits inside the memo check, never in front of it (FR-048)."""
    run_id = await _open_run(db_session)
    key = memo_key(
        agent=web_builder.AGENT,
        model_id=web_builder.MODEL_ID,
        prompt_version=web_builder.PROMPT_VERSION,
        brand_doc_version=BRAND_DOC_VERSION,
        scoped_inputs={"brand_doc": BRAND_DOC, "copy": COPY, "checkout": CHECKOUT},
    )
    await memo_write(db_session, key, {"html": PAGE})

    def never(attempt: int) -> None:
        raise AssertionError("a memo hit must not reach the model")

    model, calls = _streaming_model(never)
    assert await _build(db_session, run_id, model) == PAGE
    assert calls == []
    assert sleeps == []


async def test_the_ledger_records_one_call_not_one_per_attempt(
    db_session: AsyncSession, sleeps: list[float]
) -> None:
    """`record_call` is reached only by the attempt that succeeded, so a retried stage is one
    row in `agent_calls` — the retry must not inflate the run's spend by its own attempts."""
    run_id = await _open_run(db_session)

    def overloaded_once(attempt: int) -> None:
        if attempt == 1:
            raise ModelAPIError(web_builder.MODEL_ID, "overloaded")

    model, _ = _streaming_model(overloaded_once)
    await _build(db_session, run_id, model)

    rows = await db_session.scalar(
        select(func.count()).select_from(AgentCall).where(AgentCall.run_id == run_id)
    )
    assert rows == 1
