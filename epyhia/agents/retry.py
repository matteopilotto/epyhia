import asyncio
import logging
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


async def call_with_retry[T](operation: Callable[[], Awaitable[T]], *, agent: str) -> T:
    """Run one model call, retrying the failures the provider means as "ask again".

    Takes a factory rather than a coroutine because the Web Builder's call is an async
    context manager and cannot be re-awaited — each attempt has to build its own.

    Anything that is neither a `ModelAPIError` nor an `httpx.TransportError` propagates
    untouched, including `UsageLimitExceeded` and `UnexpectedModelBehavior`: a token ceiling
    is a decision, not a transient. So does a `ModelAPIError` whose status says the request
    itself is wrong.

    Note for the ledger: `record_call` runs only on success, and a failed attempt's tokens
    cannot be read off a raised stream — so `runs.spend_usd` under-reports by whatever the
    failed attempts consumed. That is the existing behaviour of any failed call; retrying
    makes it reachable up to `MODEL_RETRY_ATTEMPTS` times per stage rather than once. The
    bound is small and known, and inventing an estimate would put a fabricated number into a
    ledger FR-055 says is derived from `RunUsage`.
    """
    for attempt in range(MODEL_RETRY_ATTEMPTS):
        try:
            return await operation()
        except (ModelAPIError, httpx.TransportError) as exc:
            last_attempt = attempt == MODEL_RETRY_ATTEMPTS - 1
            if last_attempt or not _is_transient(exc):
                raise
            delay = _retry_after_seconds(exc) or _backoff_seconds(attempt)
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
