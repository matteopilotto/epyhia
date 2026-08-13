import json
from pathlib import Path

import pytest

from epyhia.design.fonts import (
    FONTS_DIR,
    FontLibraryInvalid,
    PairingError,
    library,
    load_library,
)

_ENTRY = {
    "id": "specimen-display",
    "family": "Specimen Display",
    "role": "display",
    "character": "a curation line about width and warmth",
    "weights": [{"weight": 400, "style": "normal", "file": "files/specimen-display-400.woff2"}],
    "license": {"name": "SIL OFL 1.1", "file": "licenses/specimen-display.txt"},
}


def _write(tmp_path: Path, faces: list[dict], *, files: bool = True, licenses: bool = True) -> Path:
    (tmp_path / "files").mkdir()
    (tmp_path / "licenses").mkdir()
    for face in faces:
        if files:
            for weight in face["weights"]:
                (tmp_path / weight["file"]).write_bytes(b"wOF2")
        if licenses:
            (tmp_path / face["license"]["file"]).write_text("license text")
    (tmp_path / "library.json").write_text(json.dumps({"faces": faces}))
    return tmp_path


def test_valid_registry_loads(tmp_path):
    loaded = load_library(_write(tmp_path, [_ENTRY]))

    assert [face.id for face in loaded.faces] == ["specimen-display"]
    assert loaded.get("specimen-display").family == "Specimen Display"


def test_duplicate_id_fails_at_load(tmp_path):
    with pytest.raises(FontLibraryInvalid, match="duplicate font id: specimen-display"):
        load_library(_write(tmp_path, [_ENTRY, dict(_ENTRY)]))


def test_missing_woff2_fails_at_load(tmp_path):
    with pytest.raises(FontLibraryInvalid, match="missing file files/specimen-display-400.woff2"):
        load_library(_write(tmp_path, [_ENTRY], files=False))


def test_missing_license_fails_at_load(tmp_path):
    with pytest.raises(FontLibraryInvalid, match="missing file licenses/specimen-display.txt"):
        load_library(_write(tmp_path, [_ENTRY], licenses=False))


def test_shipped_library_is_valid():
    # The library the runs actually use — loaded at import, asserted here so a curation
    # mistake fails this suite rather than a deployed worker.
    assert load_library(FONTS_DIR).faces == library.faces
    assert {face.role for face in library.faces} <= {"display", "body", "both"}


def test_resolve_pairing_accepts_a_valid_pair():
    display = next(f for f in library.faces if f.role in ("display", "both"))
    body = next(f for f in library.faces if f.role in ("body", "both"))

    pairing = library.resolve_pairing(display.id, body.id)

    assert (pairing.display.id, pairing.body.id) == (display.id, body.id)


def test_resolve_pairing_rejects_an_unknown_id_naming_it():
    body = next(f for f in library.faces if f.role in ("body", "both"))

    # A brand doc written before ids existed carries a free-text face name; it fails this
    # lookup by construction (FR-005).
    with pytest.raises(PairingError, match="unknown font id: Helvetica Neue"):
        library.resolve_pairing("Helvetica Neue", body.id)


def test_resolve_pairing_rejects_a_role_incompatible_pair_naming_id_and_role():
    display_only = next(f for f in library.faces if f.role == "display")

    with pytest.raises(
        PairingError,
        match=f"font id {display_only.id} has role display; not usable as the body face",
    ):
        library.resolve_pairing(display_only.id, display_only.id)
