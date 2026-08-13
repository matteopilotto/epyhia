import json
from pathlib import Path

from epyhia.design.fonts import ResolvedPairing, library
from epyhia.design.lint import DesignFinding, lint

FIXTURES = Path(__file__).parent / "fixtures"

# A synthetic brand doc and two synthetic pages: one deliberately built with every tell, one
# faithful to the same document. Invented outright — no client ever said any of it, so the
# fixtures can be read as what a page looks like rather than as what a business looks like.
BRAND_DOC = json.loads((FIXTURES / "brand_doc.json").read_text())
PAIRING = library.resolve_pairing(BRAND_DOC["type"]["display"], BRAND_DOC["type"]["body"])

TELLS = {
    "uniform_sections",
    "gradient_hero",
    "single_radius",
    "accent_overuse",
    "weak_type_scale",
    "ignored_pairing",
}


def _lint(
    page: str, *, brand_doc: dict | None = None, pairing: ResolvedPairing | None = None
) -> list[DesignFinding]:
    return lint(
        (FIXTURES / page).read_text(),
        brand_doc=brand_doc or BRAND_DOC,
        pairing=pairing or PAIRING,
    )


def _rules(findings: list[DesignFinding]) -> set[str]:
    return {finding.rule for finding in findings}


def _with_accent(hex_value: str) -> dict:
    return BRAND_DOC | {"palette": BRAND_DOC["palette"] | {"accent": hex_value}}


def _other_pairing() -> ResolvedPairing:
    """Two faces that are not the fixture's, chosen by role rather than by name — none of
    these assertions is about which faces were curated."""
    display = next(
        face
        for face in library.faces
        if face.role in ("display", "both") and face.id != PAIRING.display.id
    )
    body = next(
        face
        for face in library.faces
        if face.role in ("body", "both") and face.id not in (PAIRING.body.id, display.id)
    )
    return library.resolve_pairing(display.id, body.id)


def test_every_seeded_tell_is_reported() -> None:
    """FR-011. The fixture carries all six on purpose; a rule that stops firing is a
    regression the suite states out loud rather than one nobody notices."""
    findings = _lint("tell_laden.html")

    assert _rules(findings) == TELLS


def test_every_finding_names_where_it_is() -> None:
    """A count is not a report: an operator reading one has to be able to go and look."""
    located = {finding.rule: finding.where for finding in _lint("tell_laden.html")}

    assert located["gradient_hero"] == ".hero"
    assert located["uniform_sections"].startswith("sections ")
    assert ".card" in located["single_radius"]
    assert located["ignored_pairing"] == "body"
    assert located["weak_type_scale"] == ".hero h1"
    assert ".hero" in located["accent_overuse"]


def test_the_clean_page_reports_none() -> None:
    """The same six rules over a page that varies its rhythm, commits to a scale, keeps the
    accent scarce and sets the faces it was given."""
    assert _lint("clean.html") == []


def test_ignored_pairing_judges_against_the_passed_brand_doc() -> None:
    """FR-009. The clean page's `font-family` declarations are correct for its own pairing
    and wrong for any other — the rule reads the run's document, not a fixed family list."""
    other = _other_pairing()

    findings = _lint("clean.html", pairing=other)

    assert _rules(findings) == {"ignored_pairing"}
    assert all(other.display.family in finding.detail for finding in findings)


def test_accent_overuse_judges_against_the_passed_brand_doc() -> None:
    """The same page is an overused accent under one brand doc and a scarce one under
    another, because the hex being counted comes from the document."""
    assert "accent_overuse" in _rules(_lint("tell_laden.html"))

    muted = _with_accent(BRAND_DOC["palette"]["muted"])

    assert "accent_overuse" not in _rules(_lint("tell_laden.html", brand_doc=muted))


def test_the_embedded_font_block_is_not_the_page_s_own_styling() -> None:
    """The injector's `@font-face` block registers the pairing's families. Reading it as page
    CSS would let the pipeline answer `ignored_pairing` with its own work."""
    from epyhia.design.fonts import embed_fonts

    page = (FIXTURES / "tell_laden.html").read_text()

    assert _lint("tell_laden.html") == lint(
        embed_fonts(page, PAIRING), brand_doc=BRAND_DOC, pairing=PAIRING
    )
