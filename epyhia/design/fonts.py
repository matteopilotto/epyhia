from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# The font tree is a top-level asset directory, resolved the way `PromptService` resolves
# `PROMPTS_DIR` — binaries and registries the agency owns live beside `prompts/` and
# `video/`, not inside the package.
FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"

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
    weights: list[FontWeight] = Field(min_length=1)
    license: FontLicense


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
