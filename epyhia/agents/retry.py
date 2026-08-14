import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

logger = logging.getLogger(__name__)

# The statuses a provider returns for "ask again", plus 529 (overloaded). A 400 is what a
# stray `temperature` produces and is permanent — four more of them is four times the
# latency and the same answer.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

# The bound on this schedule is the task lease. `LEASE_MINUTES_BY_KIND` gives `site` 15
# minutes and a streamed 64K-token generation already consumes a real fraction of it. Three
# attempts spend at most 35s sleeping, which is noise against that budget; a schedule
# generous enough to outlast a real outage would let the lease expire mid-generation and hand
# the same task to a second worker. Retrying a provider blip is this helper's job. Outlasting
# an outage is the operator's re-queue (T142).
MODEL_RETRY_ATTEMPTS = 3
MODEL_BACKOFF_BASE_SECONDS = 5.0
MODEL_BACKOFF_CAP_SECONDS = 30.0


class ModelCallStalled(Exception):
    """A model call that spent its whole wall-clock budget without returning.

    Distinct from every other failure here because it is not the provider saying anything:
    the socket is open, the request is accepted, and nothing arrives. The worker's
    `except Exception` records this as a failed task naming the agent and the budget, which
    an operator re-queues through `POST /tasks/{id}/retry`.
    """

    def __init__(self, agent: str, budget_seconds: float) -> None:
        self.agent = agent
        self.budget_seconds = budget_seconds
        super().__init__(
            f"{agent}: no response within its {budget_seconds:g}s call budget"
        )


def _backoff_seconds(attempt: int) -> float:
    return min(MODEL_BACKOFF_BASE_SECONDS * 2**attempt, MODEL_BACKOFF_CAP_SECONDS)


def _is_transient(exc: ModelAPIError | httpx.TransportError) -> bool:
    """Whether asking the same question again is worth the call.

    A `ModelAPIError` that is *not* a `ModelHTTPError` carries no status code: it is the
    streamed-error case (the provider returned 200 and then an `error` event in the body).
    An `httpx.TransportError` is the connection itself failing — and during stream iteration,
    where a 64K-token generation spends nearly all its life, that is the *only* shape a
    dropped connection has: the response body is read by httpx directly and neither the
    Anthropic SDK nor PydanticAI wraps what it raises. Erring toward retrying the
    unclassifiable is right for both — the cost of a wrong retry is one wasted call, the cost
    of a wrong refusal is the run.

    `httpx.StreamError` is deliberately not in that family. It subclasses `RuntimeError` and
    means the stream was misused by the caller — read twice, or after close — which is a
    programming error retrying would only repeat.
    """
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in RETRYABLE_STATUS
    return True


def _retry_after_seconds(exc: ModelAPIError | httpx.TransportError) -> float | None:
    """The provider's own answer, when it gave one. `ModelHTTPError.headers` is lowercased by
    PydanticAI, so there is one spelling to read."""
    headers = getattr(exc, "headers", None) or {}
    try:
        return float(headers["retry-after"])
    except (KeyError, TypeError, ValueError):
        return None


async def call_with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    agent: str,
    budget_seconds: float | None = None,
) -> T:
    """Run one model call, retrying the failures the provider means as "ask again".

    Takes a factory rather than a coroutine because the Web Builder's call is an async
    context manager and cannot be re-awaited — each attempt has to build its own.

    Anything that is neither a `ModelAPIError` nor an `httpx.TransportError` propagates
    untouched, including `UsageLimitExceeded` and `UnexpectedModelBehavior`: a token ceiling
    is a decision, not a transient. So does a `ModelAPIError` whose status says the request
    itself is wrong.

    `budget_seconds` bounds the *whole* call in wall clock, retries included. Without it a
    stream that goes quiet without closing — an ESTABLISHED socket delivering keepalives and
    nothing else — parks the worker forever: the lease sweeper runs between polls, so a
    lapsed lease has no authority over a call already in flight, and every other run queued
    behind this worker waits with it. One deadline for the whole call rather than one per
    attempt, because three per-attempt timeouts large enough to be useful add up past the
    lease they are supposed to fit inside. Expiry raises `ModelCallStalled` and is
    deliberately not retried: the budget was chosen to fit the lease, and a second
    multi-minute attempt after a hang does not.

    Note for the ledger: `record_call` runs only on success, and a failed attempt's tokens
    cannot be read off a raised stream — so `runs.spend_usd` under-reports by whatever the
    failed attempts consumed. That holds for a stalled call too, whose cancellation closes
    the connection mid-generation with no usage to read. That is the existing behaviour of
    any failed call; retrying makes it reachable up to `MODEL_RETRY_ATTEMPTS` times per stage
    rather than once. The bound is small and known, and inventing an estimate would put a
    fabricated number into a ledger FR-055 says is derived from `RunUsage`.
    """
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    for attempt in range(MODEL_RETRY_ATTEMPTS):
        try:
            if deadline is None:
                return await operation()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelCallStalled(agent, budget_seconds)
            # Cancels the coroutine on expiry, which unwinds the `async with run_stream(...)`
            # the operation opened — and it is that close, not the raise, that stops the
            # provider generating tokens we would otherwise be billed for.
            return await asyncio.wait_for(operation(), remaining)
        except TimeoutError as exc:
            raise ModelCallStalled(agent, budget_seconds) from exc
        except (ModelAPIError, httpx.TransportError) as exc:
            last_attempt = attempt == MODEL_RETRY_ATTEMPTS - 1
            if last_attempt or not _is_transient(exc):
                raise
            delay = _retry_after_seconds(exc) or _backoff_seconds(attempt)
            if deadline is not None:
                delay = min(delay, max(deadline - time.monotonic(), 0.0))
            logger.warning(
                "%s: model call failed transiently (attempt %d/%d), retrying in %.1fs: %s",
                agent,
                attempt + 1,
                MODEL_RETRY_ATTEMPTS,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
