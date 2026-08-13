"""The deterministic half of the design check.

Six tells of the page a model produces when asked for "a landing page", each detected by
reading the finished document — no model call, no browser, no cost. The lint reports; it
never refuses a deploy (FR-010). Grounding remains the only mechanical refusal.

The output contract is what makes regex tractable here: one self-contained document, one
hand-authored `<style>` block, no framework and no build step (research R6). A CSS parser
would buy precision this shape does not need.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from typing import Literal

from pydantic import BaseModel, Field

from epyhia.design.fonts import STYLE_ID, ResolvedPairing

# Every threshold below is fixed here once. They are properties of the six tells, not of any
# client: nothing in this module reads a brief, and the only per-run inputs are the run's own
# brand doc and the pairing it resolved to (FR-009).
UNIFORM_SECTIONS = 4
RADIUS_REUSE = 3
ACCENT_SHARE = 0.4
ACCENT_MIN_COLOURS = 5
TYPE_SCALE_RATIO = 2.5

Rule = Literal[
    "uniform_sections",
    "gradient_hero",
    "single_radius",
    "accent_overuse",
    "weak_type_scale",
    "ignored_pairing",
]


class DesignFinding(BaseModel):
    """One detected tell. `where` names the selector or the sections it was found in, so an
    operator reading the design report can go and look at it."""

    rule: Rule
    detail: str = Field(min_length=1)
    where: str = Field(min_length=1)


# --- reading the page -------------------------------------------------------------------

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}


@dataclass
class _Section:
    """A top-level section and every selector fragment that can reach into it. Matching a
    CSS rule to a section by the classes, ids and element names it contains is coarse, but
    it is how hand-authored CSS is written and it needs no cascade of its own."""

    index: int
    depth: int
    tokens: set[str] = field(default_factory=set)


class _Page(HTMLParser):
    """Structure and CSS, in one pass.

    The embedded `@font-face` block is skipped by id: it is pipeline output, not the page's
    own styling, and the families it registers would answer `ignored_pairing` with the
    injector's own work.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.styles: list[str] = []
        self.sections: list[_Section] = []
        self._open: list[str] = []
        self._inside: list[_Section] = []
        self._authored_style = False

    @classmethod
    def parse(cls, html: str) -> "_Page":
        page = cls()
        page.feed(html)
        page.close()
        return page

    @property
    def css(self) -> str:
        return "\n".join(self.styles)

    @property
    def top_level_sections(self) -> list[_Section]:
        """The shallowest `<section>` elements, whether the page wraps them in a `<main>` or
        hangs them off `<body>`."""
        if not self.sections:
            return []
        shallowest = min(section.depth for section in self.sections)
        return [section for section in self.sections if section.depth == shallowest]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "style":
            self._authored_style = values.get("id") != STYLE_ID
        if tag not in _VOID:
            self._open.append(tag)

        tokens = {f".{name}" for name in (values.get("class") or "").split()} | {tag}
        if values.get("id"):
            tokens.add(f"#{values['id']}")
        for section in self._inside:
            section.tokens |= tokens

        if tag == "section":
            section = _Section(
                index=len(self.sections), depth=len(self._open), tokens=set(tokens)
            )
            self.sections.append(section)
            self._inside.append(section)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._authored_style = False
        if tag not in self._open:
            return
        while self._open and self._open.pop() != tag:
            pass
        self._inside = [
            section for section in self._inside if section.depth <= len(self._open)
        ]

    def handle_data(self, data: str) -> None:
        if self._authored_style:
            self.styles.append(data)


# --- reading the CSS --------------------------------------------------------------------


@dataclass(frozen=True)
class _CssRule:
    selector: str
    declarations: tuple[tuple[str, str], ...]


_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _declarations(body: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    for chunk in body.split(";"):
        prop, separator, value = chunk.partition(":")
        if separator:
            pairs.append((prop.strip().lower(), value.strip()))
    return tuple(pairs)


def _css_rules(css: str) -> list[_CssRule]:
    """Flat `(selector, declarations)` pairs. `@media` and `@supports` blocks contribute the
    rules inside them — a tell hidden behind a breakpoint is still on the page — while
    `@font-face` and `@keyframes` contribute nothing, being plumbing rather than styling."""
    css = _COMMENT.sub("", css)
    rules: list[_CssRule] = []
    cursor = 0
    while (opening := css.find("{", cursor)) != -1:
        selector = css[cursor:opening].strip()
        depth, index = 1, opening + 1
        while index < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            index += 1
        body = css[opening + 1 : index - 1]
        if selector.startswith(("@media", "@supports")):
            rules.extend(_css_rules(body))
        elif not selector.startswith("@"):
            rules.append(_CssRule(selector, _declarations(body)))
        cursor = index
    return rules


@cache
def _token_pattern(token: str) -> re.Pattern[str]:
    """`.card` must not match inside `.cardboard`, and the element name `section` must not
    match inside `.section-title`."""
    return re.compile(rf"(?<![\w.#-]){re.escape(token)}(?![\w-])")


def _mentions(selector: str, tokens: set[str]) -> bool:
    return any(_token_pattern(token).search(selector) for token in tokens)


_VAR_CALL = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,[^()]*)?\)")


def _custom_properties(rules: list[_CssRule]) -> dict[str, str]:
    return {
        prop: value
        for rule in rules
        for prop, value in rule.declarations
        if prop.startswith("--")
    }


def _resolve(value: str, custom: dict[str, str]) -> str:
    """A declaration's value with its custom properties substituted in. A page that keeps its
    palette and its faces in `:root` variables — the way a studio would — must read the same
    to these rules as one that repeats the literals."""
    for _ in range(3):
        if "var(" not in value:
            break
        value = _VAR_CALL.sub(lambda match: custom.get(match.group(1), ""), value)
    return value


_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _hex(colour: str) -> str:
    colour = colour.lower()
    if len(colour) == 4:
        return "#" + "".join(channel * 2 for channel in colour[1:])
    return colour


_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(rem|em|px)")


def _px(value: str) -> float | None:
    """The largest length a font-size value can resolve to. `clamp(2rem, 6vw, 5rem)` commits
    to 5rem at the top of its range, and that is the size the scale is judged on."""
    sizes = [
        float(number) * (16 if unit in ("rem", "em") else 1)
        for number, unit in _SIZE.findall(value)
    ]
    return max(sizes) if sizes else None


# --- the six rules ----------------------------------------------------------------------


def _centred_widths(rules: list[_CssRule], tokens: set[str]) -> set[str]:
    widths = set()
    for rule in rules:
        if not _mentions(rule.selector, tokens):
            continue
        declarations = dict(rule.declarations)
        centred = any(
            prop.startswith("margin") and "auto" in value
            for prop, value in rule.declarations
        )
        if centred and "max-width" in declarations:
            widths.add(declarations["max-width"].lower())
    return widths


def _uniform_sections(page: _Page, rules: list[_CssRule]) -> list[DesignFinding]:
    signatures: dict[str, list[int]] = {}
    for section in page.top_level_sections:
        widths = _centred_widths(rules, section.tokens)
        if len(widths) == 1:
            signatures.setdefault(widths.pop(), []).append(section.index + 1)
    return [
        DesignFinding(
            rule="uniform_sections",
            detail=(
                f"{len(where)} top-level sections resolve to the same centred {width} "
                "container: the page keeps one rhythm from top to bottom"
            ),
            where="sections " + ", ".join(str(index) for index in where),
        )
        for width, where in signatures.items()
        if len(where) >= UNIFORM_SECTIONS
    ]


_GRADIENT = re.compile(r"(linear|radial|conic)-gradient", re.IGNORECASE)


def _gradient_hero(page: _Page, rules: list[_CssRule]) -> list[DesignFinding]:
    sections = page.top_level_sections
    if not sections:
        return []
    hero = sections[0]
    for rule in rules:
        if not _mentions(rule.selector, hero.tokens):
            continue
        for prop, value in rule.declarations:
            if prop.startswith("background") and _GRADIENT.search(value):
                return [
                    DesignFinding(
                        rule="gradient_hero",
                        detail=f"the first section is backed by a gradient: {value}",
                        where=rule.selector,
                    )
                ]
    return []


def _single_radius(rules: list[_CssRule]) -> list[DesignFinding]:
    used = [
        (rule.selector, " ".join(value.split()))
        for rule in rules
        for prop, value in rule.declarations
        if prop == "border-radius" and re.search(r"[1-9]", value)
    ]
    values = {value for _, value in used}
    if len(values) != 1 or len(used) < RADIUS_REUSE:
        return []
    return [
        DesignFinding(
            rule="single_radius",
            detail=(
                f"one radius, {values.pop()}, on {len(used)} declarations and no other "
                "radius on the page: the shape language is a single default"
            ),
            where=", ".join(selector for selector, _ in used),
        )
    ]


def _accent_overuse(rules: list[_CssRule], accent: str) -> list[DesignFinding]:
    custom = _custom_properties(rules)
    accent = _hex(accent)
    total, uses = 0, []
    for rule in rules:
        for prop, value in rule.declarations:
            if prop.startswith("--"):
                continue
            colours = {_hex(found) for found in _HEX.findall(_resolve(value, custom))}
            if not colours:
                continue
            total += 1
            if accent in colours:
                uses.append(f"{rule.selector} {{{prop}}}")
    if total < ACCENT_MIN_COLOURS or len(uses) <= total * ACCENT_SHARE:
        return []
    return [
        DesignFinding(
            rule="accent_overuse",
            detail=(
                f"the brand doc's accent {accent} carries {len(uses)} of {total} colour "
                "declarations: an accent on everything reads as a theme, not a decision"
            ),
            where=", ".join(uses[:5]),
        )
    ]


def _weak_type_scale(rules: list[_CssRule]) -> list[DesignFinding]:
    sizes = [
        (rule.selector, size)
        for rule in rules
        for prop, value in rule.declarations
        if prop == "font-size" and (size := _px(value))
    ]
    if not sizes:
        return []
    body = next(
        (size for selector, size in sizes if _mentions(selector, {"body", "html", ":root"})),
        16.0,
    )
    selector, largest = max(sizes, key=lambda pair: pair[1])
    ratio = largest / body
    if ratio >= TYPE_SCALE_RATIO:
        return []
    return [
        DesignFinding(
            rule="weak_type_scale",
            detail=(
                f"the largest declared size is {ratio:.2f}x body ({largest:g}px against "
                f"{body:g}px), under the {TYPE_SCALE_RATIO} the scale has to clear to read "
                "as a decision"
            ),
            where=selector,
        )
    ]


def _ignored_pairing(
    rules: list[_CssRule], pairing: ResolvedPairing
) -> list[DesignFinding]:
    custom = _custom_properties(rules)
    families = {pairing.display.family.lower(), pairing.body.family.lower()}
    declared = [
        (rule.selector, _resolve(value, custom).split(",")[0].strip().strip("\"'").lower())
        for rule in rules
        for prop, value in rule.declarations
        if prop == "font-family"
    ]
    if not declared:
        return [
            DesignFinding(
                rule="ignored_pairing",
                detail=(
                    "no font-family declaration on the page: the pairing's faces are "
                    "embedded and never set"
                ),
                where="<style>",
            )
        ]
    return [
        DesignFinding(
            rule="ignored_pairing",
            detail=(
                f"font-family leads with {lead!r}, not the brand doc's "
                f"{pairing.display.family} or {pairing.body.family}"
            ),
            where=selector,
        )
        for selector, lead in declared
        if lead not in families
    ]


def lint(
    html: str, *, brand_doc: dict, pairing: ResolvedPairing
) -> list[DesignFinding]:
    """Every tell the finished page carries, in rule order.

    Pure: same page, same brand doc, same answer, at zero cost. The two brand-parameterised
    rules read this run's own brand doc — the accent it committed to and the faces its
    pairing resolved to — and nothing here is a judgement about a business.
    """
    page = _Page.parse(html)
    rules = _css_rules(page.css)
    return [
        *_uniform_sections(page, rules),
        *_gradient_hero(page, rules),
        *_single_radius(rules),
        *_accent_overuse(rules, brand_doc["palette"]["accent"]),
        *_weak_type_scale(rules),
        *_ignored_pairing(rules, pairing),
    ]
