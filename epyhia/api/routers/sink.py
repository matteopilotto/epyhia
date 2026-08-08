import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import Unauthorized
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.ingest.hashing import content_sha256
from epyhia.models.sink_posts import SinkPost

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_sink_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """A shared machine token, deliberately not the operator's Auth0 bearer: the caller here
    is the publish adapter, not a person, and the two principals must not share a key."""
    expected = settings.require("sink")
    if credentials is None or not hmac.compare_digest(credentials.credentials, expected):
        raise Unauthorized("invalid sink token")


# The publish adapter's destination (research.md R4). A stand-in for a social API, reached
# over HTTP so `execute()` and `verify()` are not two halves of the same transaction — but
# it is EPYHIA infrastructure, and nothing about it is client-shaped.
router = APIRouter(prefix="/sink", dependencies=[Depends(require_sink_token)])


def _permalink(request: Request, post_id: uuid.UUID) -> str:
    """Derived from the route itself rather than from configuration, so the URL handed back
    is by construction the one that serves the post."""
    return str(request.url_for("get_sink_post", post_id=post_id))


@router.post("/posts", status_code=201)
async def create_sink_post(
    payload: dict, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    post = SinkPost(
        id=uuid.uuid4(), payload=payload, payload_sha256=content_sha256(payload)
    )
    session.add(post)
    await session.commit()
    return {"id": post.id, "permalink": _permalink(request, post.id)}


@router.get("/posts/{post_id}")
async def get_sink_post(
    post_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    post = await session.get(SinkPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="no such post")
    return {
        "id": post.id,
        "payload": post.payload,
        "payload_sha256": post.payload_sha256,
        "permalink": _permalink(request, post.id),
        "created_at": post.created_at,
    }
