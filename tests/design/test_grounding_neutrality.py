from epyhia.design.fonts import embed_fonts, library
from epyhia.ingest.extractors import extract_site_text
from epyhia.ingest.grounding import set_difference
from epyhia.ingest.normalise import find_amounts

# A page carrying numerals of every shape the extractor reads — body text, an `alt`, a meta
# description — plus CSS numerals that must stay invisible to it. Invented, so the fixture
# states nothing any client said.
PAGE = (
    "<!doctype html><html lang='en'><head><title>Specimen</title>"
    "<meta name='description' content='Plans from 1200 a month.'>"
    "<style>:root{--pad:1.5rem;--ink:#0a0a0a}h1{font-size:4.75rem}</style></head>"
    "<body><h1>Specimen</h1><p>Plans. 1200 a month, or 12000 a year.</p>"
    "<img src='data:image/gif;base64,R0lGODlhAQABAAAAACw=' alt='3 of 4 rooms'>"
    "<script>const rate = 999;</script></body></html>"
)

LOCALE = "en-GB"

# What the run would have been grounded on. Deliberately partial: leaving one numeral
# uncovered means the comparison below is over a non-empty difference, so a check that
# silently stopped extracting would not pass by finding nothing on either side.
GROUNDING_SET = {
    "literal": [{"value": "1200", "currency": None}, {"value": "12000", "currency": None}],
    "derived": [],
}


def _pairing():
    display = next(face for face in library.faces if face.role in ("display", "both"))
    body = next(
        face for face in library.faces if face.role in ("body", "both") and face.id != display.id
    )
    return library.resolve_pairing(display.id, body.id)


def _violations(html: str) -> list[tuple[str, str | None]]:
    extracted = [
        amount for text in extract_site_text(html) for amount in find_amounts(text, LOCALE)
    ]
    return [(str(v.value), v.currency) for v in set_difference(extracted, GROUNDING_SET)]


def test_embedded_fonts_change_nothing_the_grounding_scan_reads() -> None:
    """FR-004 / SC-005, proved rather than assumed: the extractor skips `<style>` today, so
    a future change that starts reading it — where a base64 blob is thousands of digit runs —
    fails here instead of flagging every page that carries its own faces."""
    embedded = embed_fonts(PAGE, _pairing())

    assert extract_site_text(embedded) == extract_site_text(PAGE)
    assert _violations(embedded) == _violations(PAGE)


def test_the_scan_this_compares_is_not_vacuous() -> None:
    """The equality above is only evidence if the scan has something to say: this fixture's
    uncovered numeral must be reported on both sides."""
    assert _violations(PAGE) == [("3", None), ("4", None)]
