from html.parser import HTMLParser

# research.md R5: what counts as a numeral, per artifact kind. Deciding scope per kind,
# in code, once, is what keeps the grounding check from crying wolf on `#0a0a0a`,
# `1.5rem` or `viewBox` — and from being quietly widened to absorb the false positives.

_SITE_SKIP_TAGS = {"script", "style"}
_SITE_ATTRS = {"alt", "title", "aria-label"}


def extract_structured_strings(artifact: object) -> list[str]:
    """copy/posts/email: every string value in the structured artifact."""
    strings: list[str] = []
    _walk_strings(artifact, strings)
    return strings


def _walk_strings(node: object, out: list[str]) -> None:
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            _walk_strings(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_strings(item, out)


def extract_video_props_content(props: dict) -> list[str]:
    """video_props: every leaf under `content`, stringified, and nothing under `style` —
    a schema guarantee (the props contract splits the two) rather than a heuristic."""
    leaves: list[str] = []
    _walk_leaves(props.get("content", {}), leaves)
    return leaves


def _walk_leaves(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk_leaves(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_leaves(item, out)
    elif node is not None and not isinstance(node, bool):
        out.append(str(node))


class _SiteTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []
        self._skip_depth = 0
        self._in_meta_description = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in _SITE_SKIP_TAGS:
            self._skip_depth += 1
            return
        for name in _SITE_ATTRS:
            value = attrs_dict.get(name)
            if value:
                self.texts.append(value)
        if tag == "meta" and attrs_dict.get("name") == "description":
            content = attrs_dict.get("content")
            if content:
                self.texts.append(content)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SITE_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.texts.append(data.strip())


def extract_site_text(html: str) -> list[str]:
    """site: text nodes outside `<script>`/`<style>`, plus `alt`, `title`,
    `aria-label` and `<meta name="description">` content — nothing else."""
    parser = _SiteTextParser()
    parser.feed(html)
    return parser.texts
