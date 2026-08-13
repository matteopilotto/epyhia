"""Pack assembly, as pure functions over `Artifact` rows — no session, no credentials.

The archive is what leaves the system: it is read on a machine with no access to it
(SC-003), so its self-description has to be right without anything else to check against.
"""

import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from epyhia.export import archive
from epyhia.models.artifacts import Artifact
from tests.export.test_companions import COPY, EMAIL, POSTS, encode

MANIFEST_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "002-artifact-inspection"
        / "contracts"
        / "pack-manifest.schema.json"
    ).read_text()
)

RUN_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

VIOLATION = [{"kind": "ungrounded_numeral", "quote": "post body alpha", "why": "not in the brief"}]

SITE = b"<!doctype html><title>x</title>"
REVISED_COPY = b'{"sections": [{"section": "s", "headline": "h", "body": "b"}]}'


def artifact(
    kind: str,
    path: str,
    body: bytes,
    *,
    content_type: str = "application/json",
    grounding_status: str = "clean",
    violations: list[dict] | None = None,
    revision: int = 0,
) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        run_id=RUN_ID,
        kind=kind,
        path=path,
        content_type=content_type,
        bytes=body,
        sha256=hashlib.sha256(body).hexdigest(),
        grounding_status=grounding_status,
        violations=violations,
        revision=revision,
    )


def read(pack: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(pack))


def manifest_of(pack: bytes) -> dict:
    return json.loads(read(pack).read("manifest.json"))


def entry_for(manifest: dict, archive_path: str) -> dict:
    matches = [f for f in manifest["files"] if f["archive_path"] == archive_path]
    assert len(matches) == 1, f"{archive_path} appears {len(matches)} times in the manifest"
    return matches[0]


@pytest.fixture
def pack() -> bytes:
    return archive.build_pack(
        RUN_ID,
        [
            artifact("copy", "copy.json", encode(COPY)),
            artifact("email", "email.json", encode(EMAIL)),
            artifact(
                "posts",
                "posts.json",
                encode(POSTS),
                grounding_status="flagged",
                violations=VIOLATION,
            ),
            artifact("site", "index.html", SITE, content_type="text/html"),
            artifact("video", "launch.mp4", bytes(range(256)), content_type="video/mp4"),
        ],
    )


def test_layout_matches_the_data_model(pack: bytes) -> None:
    names = set(read(pack).namelist())

    assert names == {
        "manifest.json",
        "deliverables/copy.json",
        "deliverables/copy.md",
        "deliverables/email.json",
        "deliverables/email.md",
        "deliverables/index.html",
        "deliverables/launch.mp4",
        "flagged/posts.json",
        "flagged/posts.violations.json",
        "flagged/posts.md",
    }


def test_record_bytes_are_the_stored_bytes_verbatim(pack: bytes) -> None:
    """Binary included — a decode round trip anywhere in this path yields a file that plays
    as garbage."""
    assert read(pack).read("deliverables/copy.json") == encode(COPY)
    assert read(pack).read("deliverables/launch.mp4") == bytes(range(256))


def test_every_manifest_hash_matches_the_bytes_it_describes(pack: bytes) -> None:
    """SC-004: unzip, hash, compare — with nothing but the archive in hand."""
    zf = read(pack)
    for entry in manifest_of(pack)["files"]:
        member = zf.read(entry["archive_path"])
        assert hashlib.sha256(member).hexdigest() == entry["sha256"], entry["archive_path"]


def test_record_hashes_are_copied_from_the_rows(pack: bytes) -> None:
    """What ties the archive back to the audit trail: the manifest's record hash is the
    artifact row's own, not something recomputed at assembly."""
    entry = entry_for(manifest_of(pack), "deliverables/copy.json")

    assert entry["role"] == "record"
    assert entry["sha256"] == hashlib.sha256(encode(COPY)).hexdigest()
    assert entry["content_type"] == "application/json"


def test_derived_files_declare_their_own_type_and_hash(pack: bytes) -> None:
    manifest = manifest_of(pack)

    companion = entry_for(manifest, "deliverables/copy.md")
    assert companion["role"] == "companion"
    assert companion["content_type"] == "text/markdown"
    assert companion["kind"] == "copy"

    violations = entry_for(manifest, "flagged/posts.violations.json")
    assert violations["role"] == "violations"
    assert violations["content_type"] == "application/json"
    assert json.loads(read(pack).read("flagged/posts.violations.json")) == VIOLATION


def test_manifest_lists_every_file_but_itself(pack: bytes) -> None:
    manifest = manifest_of(pack)
    listed = {entry["archive_path"] for entry in manifest["files"]}

    assert listed == set(read(pack).namelist()) - {"manifest.json"}


def test_manifest_matches_the_published_schema(pack: bytes) -> None:
    manifest = manifest_of(pack)

    jsonschema.validate(manifest, MANIFEST_SCHEMA)
    assert manifest["run_id"] == str(RUN_ID)
    stamped = datetime.fromisoformat(manifest["generated_at"])
    assert stamped.utcoffset() is not None and stamped.utcoffset().total_seconds() == 0


def test_only_the_latest_revision_of_a_kind_ships() -> None:
    pack = archive.build_pack(
        RUN_ID,
        [
            artifact("copy", "copy.json", encode(COPY), revision=0),
            artifact("copy", "copy.json", REVISED_COPY, revision=2),
            artifact("copy", "copy.json", encode(COPY), revision=1),
        ],
    )

    assert entry_for(manifest_of(pack), "deliverables/copy.json")["revision"] == 2
    assert b'"headline": "h"' in read(pack).read("deliverables/copy.json")


def test_a_flagged_latest_revision_ships_flagged_even_after_a_clean_one() -> None:
    """The edge case FR-010 names: the latest is what ships, and it ships segregated —
    never quietly replaced by the earlier revision that happened to pass."""
    pack = archive.build_pack(
        RUN_ID,
        [
            artifact("posts", "posts.json", encode(POSTS), revision=0),
            artifact(
                "posts",
                "posts.json",
                encode(POSTS),
                grounding_status="flagged",
                violations=VIOLATION,
                revision=1,
            ),
        ],
    )
    names = read(pack).namelist()

    assert "flagged/posts.json" in names
    assert not [name for name in names if name.startswith("deliverables/")]
    assert entry_for(manifest_of(pack), "flagged/posts.json")["grounding_status"] == "flagged"


def test_a_run_with_no_artifacts_yields_a_valid_empty_archive() -> None:
    """An accurate empty manifest, never an error."""
    pack = archive.build_pack(RUN_ID, [])

    assert read(pack).namelist() == ["manifest.json"]
    manifest = manifest_of(pack)
    jsonschema.validate(manifest, MANIFEST_SCHEMA)
    assert manifest["files"] == []


def test_a_record_that_does_not_parse_ships_without_a_companion() -> None:
    pack = archive.build_pack(RUN_ID, [artifact("copy", "copy.json", b"not json at all")])

    assert read(pack).namelist() == ["manifest.json", "deliverables/copy.json"]
    assert read(pack).read("deliverables/copy.json") == b"not json at all"
