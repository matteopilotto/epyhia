"""The companion renderer, as pure functions.

Zero credentials, zero agents, zero network — the export module is this feature's
gate-analogue, so it has no excuse for being untested (research R10). Every record here is
invented in this file: the fidelity claim is about the rendering, not about any client.
"""

import json
import re

from epyhia.export import companions

COPY = {
    "sections": [
        {"section": "hero", "headline": "Headline one", "body": "Body one."},
        {"section": "proof", "headline": "Headline two", "body": "Body two."},
    ]
}

POSTS = {
    "posts": [
        {"angle": "angle alpha", "body": "post body alpha"},
        {"angle": "angle beta", "body": "post body beta"},
        {"angle": "angle gamma", "body": "post body gamma"},
    ]
}

EMAIL = {
    "subject": "Subject line",
    "preheader": "Preheader line",
    "body": "Email body paragraph.",
}


def video_props(currency: str, amount_minor: int) -> dict:
    return {
        "archetype_id": "archetype-one",
        "content": {
            "headline": "Video headline",
            "subhead": "Video subhead",
            "scenes": [
                {"kind": "opening", "lines": ["line one", "line two"]},
                {
                    "kind": "reveal",
                    "lines": ["line three"],
                    "values": [
                        {
                            "label": "label one",
                            "amount_minor": amount_minor,
                            "currency": currency,
                        }
                    ],
                },
            ],
            "cta": "Call to action",
        },
        "style": {"palette": {}, "type": {}, "motion_intensity": "low"},
    }


def encode(record: dict) -> bytes:
    return json.dumps(record).encode("utf-8")


def strings_in(value: object) -> list[str]:
    """Every string anywhere in the record — the vocabulary a faithful rendering may use."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings_in(item)]
    if isinstance(value, list):
        return [s for item in value for s in strings_in(item)]
    return []


def residue(markdown: str, record: dict) -> str:
    """What is left of the rendering once every string the record contains is removed.

    FR-011's "introducing no content of their own" is exactly this: a companion may add
    structure (headings, list markers, punctuation) and money digits derived from
    `amount_minor`, but never a word the record does not contain. Longest-first so a
    substring cannot mask a longer field.
    """
    for text in sorted(strings_in(record), key=len, reverse=True):
        markdown = markdown.replace(text, "")
    return markdown


def test_copy_renders_every_section_field() -> None:
    markdown = companions.render("copy", encode(COPY))

    assert markdown is not None
    for section in COPY["sections"]:
        assert section["section"] in markdown
        assert section["headline"] in markdown
        assert section["body"] in markdown
    # Order is the record's order — a reader pasting the page top to bottom gets the page.
    assert markdown.index("Headline one") < markdown.index("Headline two")


def test_posts_render_one_section_per_post() -> None:
    markdown = companions.render("posts", encode(POSTS))

    assert markdown is not None
    for post in POSTS["posts"]:
        assert post["angle"] in markdown
        assert post["body"] in markdown


def test_email_renders_subject_preheader_and_body() -> None:
    markdown = companions.render("email", encode(EMAIL))

    assert markdown is not None
    assert EMAIL["subject"] in markdown
    assert EMAIL["preheader"] in markdown
    assert EMAIL["body"] in markdown


def test_video_props_renders_scenes_in_order_with_lines() -> None:
    record = video_props("USD", 1200)
    markdown = companions.render("video_props", encode(record))

    assert markdown is not None
    assert record["content"]["headline"] in markdown
    for scene in record["content"]["scenes"]:
        assert scene["kind"] in markdown
        for line in scene["lines"]:
            assert line in markdown
    assert markdown.index("line one") < markdown.index("line three")


def test_storyboard_money_uses_the_currency_carried_by_the_value() -> None:
    """The exponent comes from the artifact's own currency, never from a two-decimal
    assumption (FR-003, research R7)."""
    markdown = companions.render("video_props", encode(video_props("USD", 1200)))

    assert markdown is not None
    assert "label one" in markdown
    assert "12.00" in markdown
    assert "USD" in markdown


def test_storyboard_money_in_a_zero_decimal_currency_has_no_decimals() -> None:
    markdown = companions.render("video_props", encode(video_props("JPY", 1200)))

    assert markdown is not None
    assert "1200" in markdown
    assert "12.00" not in markdown


def test_no_rendering_introduces_a_word_the_record_does_not_contain() -> None:
    """The mechanical half of FR-011. Strip the record's own strings out of the companion
    and nothing with a letter in it may remain — no label, no heading, no prose."""
    for kind, record in (
        ("copy", COPY),
        ("posts", POSTS),
        ("email", EMAIL),
        ("video_props", video_props("USD", 1200)),
    ):
        markdown = companions.render(kind, encode(record))
        assert markdown is not None
        assert not re.search(r"[A-Za-z]", residue(markdown, record)), kind


def test_content_that_does_not_parse_as_its_kind_yields_no_companion() -> None:
    """Skip, never fabricate: the record is the artifact of record and still ships."""
    assert companions.render("copy", b"not json at all") is None
    assert companions.render("copy", encode({"sections": []})) is None
    assert companions.render("posts", encode(COPY)) is None
    assert companions.render("email", encode({"subject": "only a subject"})) is None
    assert companions.render("video_props", encode({"content": {}})) is None


def test_kinds_that_are_already_human_usable_have_no_companion() -> None:
    assert companions.render("site", b"<!doctype html><title>x</title>") is None
    assert companions.render("video", b"\x00\x01\x02") is None
    assert companions.render("video_vertical", b"\x00\x01\x02") is None
    # An unknown kind is legal input and simply has no rendering (FR-014's server side).
    assert companions.render("something_new", encode(COPY)) is None
