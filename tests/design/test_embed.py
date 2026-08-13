import pytest

from epyhia.design.fonts import (
    PAGE_BUDGET_BYTES,
    STYLE_ID,
    PageMalformed,
    PageOverBudget,
    embed_fonts,
    library,
)

# A page shaped like the output contract — one document, a `<head>`, one style block — and
# carrying nothing a client ever said.
PAGE = (
    "<!doctype html><html lang='en'><head><title>Specimen</title>"
    "<style>body{margin:0}</style></head>"
    "<body><h1>Specimen</h1></body></html>"
)


def _pairing():
    """Two faces taken from the library by role rather than by name: the curation may grow
    or be renamed, and none of these assertions is about which faces were curated."""
    display = next(face for face in library.faces if face.role in ("display", "both"))
    body = next(
        face for face in library.faces if face.role in ("body", "both") and face.id != display.id
    )
    return library.resolve_pairing(display.id, body.id)


def _block(embedded: str) -> str:
    start = embedded.index(f'<style id="{STYLE_ID}"')
    return embedded[start : embedded.index("</style>", start) + len("</style>")]


def test_the_block_lands_immediately_after_head() -> None:
    embedded = embed_fonts(PAGE, _pairing())

    head_end = embedded.index("<head>") + len("<head>")
    assert embedded[head_end:].startswith(f'<style id="{STYLE_ID}">')
    # Insertion, not rewriting: remove the block and the page the model wrote is back.
    assert embedded.replace(_block(embedded), "") == PAGE


def test_every_weight_file_becomes_one_font_face_rule_for_its_family() -> None:
    pairing = _pairing()

    block = _block(embed_fonts(PAGE, pairing))

    expected = [
        (face.family, weight.weight, weight.style)
        for face in (pairing.display, pairing.body)
        for weight in face.weights
    ]
    assert block.count("@font-face") == len(expected)
    for family, weight, style in expected:
        assert f'font-family:"{family}";font-style:{style};font-weight:{weight}' in block


def test_the_page_stays_one_document_with_no_external_request() -> None:
    """SC-004: the faces travel inside the page. A `url()` pointing anywhere but at the
    embedded data is a request a visitor's browser would make."""
    embedded = embed_fonts(PAGE, _pairing())

    assert embedded.count("<html") == 1
    for url in ("http://", "https://", "//fonts", "url(/"):
        assert url not in embedded
    assert embedded.count("url(") == embedded.count("url(data:font/woff2;base64,")


def test_a_page_pushed_past_the_budget_fails_visibly() -> None:
    """FR-006: the check is on the finished bytes, so a runaway generation fails the stage
    rather than being deployed unsized."""
    runaway = PAGE.replace("<h1>Specimen</h1>", "<p>x</p>" * (PAGE_BUDGET_BYTES // 8))

    with pytest.raises(PageOverBudget) as raised:
        embed_fonts(runaway, _pairing())

    assert str(PAGE_BUDGET_BYTES) in str(raised.value)


def test_a_page_without_a_head_fails_rather_than_embedding_before_the_doctype() -> None:
    with pytest.raises(PageMalformed):
        embed_fonts("<!doctype html><html><body>x</body></html>", _pairing())
