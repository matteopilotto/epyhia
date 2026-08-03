import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from fastapi.responses import StreamingResponse

EventKind = Literal["task", "action", "artifact", "agent_call", "cost"]


@dataclass(frozen=True)
class SSEEvent:
    kind: EventKind
    data: dict


def format_sse(event: SSEEvent) -> str:
    """One `event: <kind>\\ndata: <json>\\n\\n` frame — the wire format a `fetch` +
    `ReadableStream` consumer parses on the other end, chosen over `EventSource` because
    `EventSource` cannot send an `Authorization` header (contracts/rest-api.md §10)."""
    return f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"


async def sse_stream(events: AsyncIterator[SSEEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield format_sse(event)


def sse_response(events: AsyncIterator[SSEEvent]) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
