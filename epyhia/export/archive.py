"""The deliverable pack: one zip, assembled per request, never stored (FR-008).

Latest revision per kind, clean deliverables and flagged ones in separate directories, a
manifest that describes every file in the archive. Record files carry the `sha256` from
their artifact row rather than a hash recomputed here — that equality is what ties an
archive opened on a machine with no access to the system back to the run's audit trail
(FR-009, SC-004). Nothing is dropped: a flagged artifact travels with its violations
(FR-010), and a run that has produced nothing yields an accurate empty manifest.
"""

import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath

from epyhia.export import companions
from epyhia.models.artifacts import Artifact

CLEAN_DIR = "deliverables"
FLAGGED_DIR = "flagged"
MANIFEST_NAME = "manifest.json"


def latest_revisions(artifacts: Sequence[Artifact]) -> list[Artifact]:
    """One artifact per kind: the highest revision the run reached for it."""
    latest: dict[str, Artifact] = {}
    for artifact in artifacts:
        current = latest.get(artifact.kind)
        if current is None or artifact.revision >= current.revision:
            latest[artifact.kind] = artifact
    return [latest[kind] for kind in sorted(latest)]


def build_pack(run_id: uuid.UUID, artifacts: Sequence[Artifact]) -> bytes:
    """The archive bytes for a run's artifacts."""
    members: list[tuple[str, bytes]] = []
    files: list[dict] = []

    def add(artifact: Artifact, path: str, body: bytes, role: str, content_type: str) -> None:
        members.append((path, body))
        files.append(
            {
                "archive_path": path,
                "kind": artifact.kind,
                "role": role,
                "revision": artifact.revision,
                "grounding_status": artifact.grounding_status,
                "content_type": content_type,
                # A record's hash is the row's own; a derived file has no row to be checked
                # against, so it is hashed over what is written here.
                "sha256": artifact.sha256 if role == "record" else hashlib.sha256(body).hexdigest(),
            }
        )

    for artifact in latest_revisions(artifacts):
        # Anything not clean is segregated — included, marked, and never intermixed.
        directory = CLEAN_DIR if artifact.grounding_status == "clean" else FLAGGED_DIR
        stem = PurePosixPath(artifact.path).stem
        add(
            artifact,
            f"{directory}/{artifact.path}",
            artifact.bytes,
            "record",
            artifact.content_type,
        )

        if directory == FLAGGED_DIR:
            violations = json.dumps(artifact.violations or [], ensure_ascii=False, indent=2)
            add(
                artifact,
                f"{directory}/{stem}.violations.json",
                violations.encode("utf-8"),
                "violations",
                "application/json",
            )

        companion = companions.render(artifact.kind, artifact.bytes)
        if companion is not None:
            add(
                artifact,
                f"{directory}/{stem}.md",
                companion.encode("utf-8"),
                "companion",
                "text/markdown",
            )

    manifest = {
        "run_id": str(run_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "files": files,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # First member, so the description of the archive is the first thing a reader meets.
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for path, body in members:
            zf.writestr(path, body)
    return buffer.getvalue()
