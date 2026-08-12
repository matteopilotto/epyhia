"""Human-readable renderings of the structured text deliverables (FR-011).

The recipient of a pack should be able to paste the launch copy without parsing a data
file. What makes that safe is that these renderings are mechanical: the content is parsed
through the very models the Marketer emits, and every word written out is a field read back
off that model. Structure — headings, list markers, the decimal point in an amount — is all
this module adds. If content does not parse as its kind's shape the companion is skipped
and the record still ships; a fabricated rendering would be worse than none (research R5).
"""

import json
from collections.abc import Callable
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from epyhia.agents.marketer import LandingCopy, LaunchEmail, SocialPosts, VideoContent
from epyhia.ingest.normalise import MINOR_EXPONENT


class _AssembledVideoProps(BaseModel):
    """The stored `video_props` shape — `assemble_video_props`' output, of which only the
    Marketer-authored `content` half has anything to read."""

    content: VideoContent


def _document(blocks: list[str]) -> str:
    return "\n\n".join(blocks) + "\n"


def _copy(payload: object) -> str:
    copy = LandingCopy.model_validate(payload)
    return _document(
        [
            block
            for section in copy.sections
            for block in (f"## {section.section}", f"### {section.headline}", section.body)
        ]
    )


def _posts(payload: object) -> str:
    posts = SocialPosts.model_validate(payload)
    return _document(
        [block for post in posts.posts for block in (f"## {post.angle}", post.body)]
    )


def _email(payload: object) -> str:
    email = LaunchEmail.model_validate(payload)
    return _document([f"# {email.subject}", f"> {email.preheader}", email.body])


def _money(amount_minor: int, currency: str) -> str:
    """The currency's own exponent, never an assumed two — the same table ingest reduced the
    amount with, read backwards (FR-003, research R7)."""
    exponent = MINOR_EXPONENT.get(currency, 2)
    return f"{Decimal(amount_minor).scaleb(-exponent):.{exponent}f} {currency}"


def _video_props(payload: object) -> str:
    content = _AssembledVideoProps.model_validate(payload).content
    blocks = [f"# {content.headline}"]
    if content.subhead:
        blocks.append(content.subhead)
    for scene in content.scenes:
        blocks.append(f"## {scene.kind}")
        if scene.lines:
            blocks.append("\n".join(f"- {line}" for line in scene.lines))
        if scene.values:
            blocks.append(
                "\n".join(
                    f"- {value.label}: {_money(value.amount_minor, value.currency)}"
                    for value in scene.values
                )
            )
    if content.cta:
        blocks.append(content.cta)
    return _document(blocks)


# Only the structured text kinds. `site` and `video` are already the human-usable form of
# themselves; an unknown kind has no shape to render and falls through to no companion.
_RENDERERS: dict[str, Callable[[object], str]] = {
    "copy": _copy,
    "posts": _posts,
    "email": _email,
    "video_props": _video_props,
}


def render(kind: str, content: bytes) -> str | None:
    """The Markdown companion for a record, or `None` when there is none to write."""
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        return None
    try:
        return renderer(json.loads(content))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
        return None
