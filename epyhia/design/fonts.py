import base64
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# The font tree is a top-level asset directory, resolved the way `PromptService` resolves
# `PROMPTS_DIR` — binaries and registries the agency owns live beside `prompts/` and
# `video/`, not inside the package.
FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"

# The finished page, fonts included. Wide enough to hold a hand-authored page plus a
# worst-case pairing several times over, tight enough to catch a runaway generation before
# it is deployed (FR-006, research R2).
PAGE_BUDGET_BYTES = 1_048_576

Role = Literal["display", "body", "both"]

Slot = Literal["display", "body"]

_COMPATIBLE: dict[Slot, tuple[Role, ...]] = {
    "display": ("display", "both"),
    "body": ("body", "both"),
}


class FontLibraryInvalid(Exception):
    """The registry itself is broken — a duplicate id, a missing woff2, a missing license.
    A repository defect, raised when the library loads, never a per-run condition."""


class PairingError(Exception):
    """A brand doc's `type` ids do not resolve against the library: an id nobody curated
    (including a free-text face name from a brand doc written before ids existed), or an id
    whose role cannot fill the slot it was chosen for. The site stage raises this before any
    model call (FR-005)."""


class PageMalformed(Exception):
    """The generated page has no `<head>` to embed the faces into. Inserting the block
    anywhere else would put a `<style>` ahead of the doctype and drop the page into quirks
    mode, so the stage fails instead."""


class PageOverBudget(Exception):
    """The finished page, fonts embedded, exceeds `PAGE_BUDGET_BYTES`. The site stage fails
    visibly rather than deploying a page nobody sized (FR-006)."""


class FontWeight(BaseModel):
    weight: int = Field(ge=1, le=1000)
    style: Literal["normal", "italic"]
    file: str = Field(pattern=r"^files/[a-z0-9-]+\.woff2$")


class FontLicense(BaseModel):
    name: str = Field(min_length=1)
    file: str = Field(pattern=r"^licenses/[a-z0-9-]+\.txt$")


class FontFace(BaseModel):
    """One curated typeface. Agency infrastructure: any brief may select any entry, and no
    field here names a client (Principle I, FR-001)."""

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    family: str = Field(min_length=1)
    role: Role
    character: str = Field(min_length=1)
    fallback: Literal["serif", "sans-serif", "monospace"]
    weights: list[FontWeight] = Field(min_length=1)
    license: FontLicense

    @property
    def stack(self) -> str:
        """What the Web Builder is handed to write `font-family` with. The generic keyword
        is unreachable in practice — the face travels inside the document as a data URI —
        but a stack that terminates in one is the declaration a studio would write."""
        return f'"{self.family}", {self.fallback}'


class ResolvedPairing(BaseModel):
    """The two faces a brand doc committed to, resolved to registry entries. What the
    injector embeds, what the Web Builder is handed family names from, and what the lint
    judges the page's `font-family` declarations against."""

    display: FontFace
    body: FontFace


class FontLibrary(BaseModel):
    faces: list[FontFace] = Field(min_length=1)

    def get(self, font_id: str) -> FontFace:
        for face in self.faces:
            if face.id == font_id:
                return face
        raise PairingError(f"unknown font id: {font_id}")

    def resolve_pairing(self, display_id: str, body_id: str) -> ResolvedPairing:
        return ResolvedPairing(
            display=self._for_slot(display_id, "display"),
            body=self._for_slot(body_id, "body"),
        )

    def _for_slot(self, font_id: str, slot: Slot) -> FontFace:
        face = self.get(font_id)
        if face.role not in _COMPATIBLE[slot]:
            raise PairingError(
                f"font id {font_id} has role {face.role}; not usable as the {slot} face"
            )
        return face


def load_library(fonts_dir: Path = FONTS_DIR) -> FontLibrary:
    """Parse and fully validate `library.json`. Every rule the registry claims is checked
    here — shape and roles by the models, uniqueness and the presence of every referenced
    file below — so a broken library is a loud failure at import rather than a surprise
    halfway through a run."""
    registry = fonts_dir / "library.json"
    try:
        library = FontLibrary.model_validate_json(registry.read_bytes())
    except (OSError, ValidationError) as exc:
        raise FontLibraryInvalid(f"{registry}: {exc}") from exc

    seen: set[str] = set()
    for face in library.faces:
        if face.id in seen:
            raise FontLibraryInvalid(f"duplicate font id: {face.id}")
        seen.add(face.id)
        for relative in [weight.file for weight in face.weights] + [face.license.file]:
            if not (fonts_dir / relative).is_file():
                raise FontLibraryInvalid(f"{face.id}: missing file {relative}")
    return library


library = load_library()

resolve_pairing = library.resolve_pairing

_HEAD = re.compile(r"<head[^>]*>", re.IGNORECASE)

STYLE_ID = "epyhia-fonts"


def _font_face_rules(face: FontFace, fonts_dir: Path) -> list[str]:
    rules = []
    for weight in face.weights:
        data = base64.b64encode((fonts_dir / weight.file).read_bytes()).decode("ascii")
        rules.append(
            f'@font-face{{font-family:"{face.family}";'
            f"font-style:{weight.style};font-weight:{weight.weight};"
            f'src:url(data:font/woff2;base64,{data}) format("woff2")}}'
        )
    return rules


def embed_fonts(
    html: str, pairing: ResolvedPairing, fonts_dir: Path = FONTS_DIR
) -> str:
    """Put the pairing's faces inside the page, as one `<style id="epyhia-fonts">` block of
    `@font-face` rules immediately after the opening `<head>`.

    Mechanical and post-generation: the model writes `font-family` against the family names
    it was handed and never sees a byte of font data (FR-003). The faces travel as data URIs,
    so the finished page is still one self-contained document making zero external requests,
    and the budget is enforced here — on the bytes that will actually be stored, checked and
    deployed (FR-006).
    """
    faces = [pairing.display]
    if pairing.body.id != pairing.display.id:
        faces.append(pairing.body)
    rules = [rule for face in faces for rule in _font_face_rules(face, fonts_dir)]
    block = f'<style id="{STYLE_ID}">{"".join(rules)}</style>'

    head = _HEAD.search(html)
    if head is None:
        raise PageMalformed("no <head> element to embed the type pairing into")
    embedded = html[: head.end()] + block + html[head.end() :]

    size = len(embedded.encode("utf-8"))
    if size > PAGE_BUDGET_BYTES:
        raise PageOverBudget(
            f"page with fonts embedded is {size} bytes; budget is {PAGE_BUDGET_BYTES}"
        )
    return embedded
