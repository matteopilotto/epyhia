"""Resolving what an `evidence` row names.

A judged row names *what* to show rather than carrying a pasted link (FR-063). Anything the
system produced resolves out of the stored records — a deploy action's evidence URL, an
artifact id, a field of a brand doc. Anything a person produced resolves to a tracked
repository path or a URL held in a tracked file.

Nothing here re-fetches anything to confirm it: that would reintroduce the probe DESIGN.md
§10 argued away, and the thing being confirmed was already observed and stored by a
`verify()`. A reference that resolves to nothing renders as `missing` — never a pass, never
a score, and never a broken link.

References are `<kind>:<rest>`. Run-scoped kinds resolve once per run, labelled by the brief
file the run was resolved from; repository-scoped kinds resolve once.
"""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — a runtime import would be circular
    from eval.eval import RunRecord

REPO_ROOT = Path(__file__).resolve().parent.parent

MISSING = "missing"

_URL = re.compile(r"https?://\S+")


def latest(record: "RunRecord", kind: str) -> dict | None:
    """The current revision of an artifact kind. A flagged draft superseded by a clean
    revision is the remedy loop working, so it is the latest one that speaks for the run."""
    of_kind = [artifact for artifact in record.artifacts if artifact["kind"] == kind]
    return max(of_kind, key=lambda artifact: artifact["revision"]) if of_kind else None


def resolve(
    reference: str,
    records: "list[RunRecord]",
    base_url: str,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[str, str]]:
    """What to show for one `evidence` row, as `(run label, value)` pairs.

    An unknown kind is `missing` rather than an error: a rubric is edited by hand, and a
    reference nobody can resolve is a gap in the evidence, not a broken evaluation.
    """
    kind, _, rest = reference.partition(":")

    if kind in _REPO_SCOPED:
        return [("", _REPO_SCOPED[kind](rest, base_url, repo_root))]
    if kind in _RUN_SCOPED:
        return [(record.label, _RUN_SCOPED[kind](rest, record)) for record in records]
    return [("", MISSING)]


def _action(rest: str, record: "RunRecord") -> str:
    """`action:<type>#<dotted field>` — read off the run's own succeeded action row."""
    action_type, _, dotted = rest.partition("#")
    for action in record.actions:
        if action["action_type"] == action_type and action["state"] == "succeeded":
            return _render(_dig(action, dotted))
    return MISSING


def _artifact(rest: str, record: "RunRecord") -> str:
    """`artifact:<kind>` — the artifact's id, which the console resolves to its content."""
    artifact = latest(record, rest)
    return _render(artifact and artifact["id"])


def _brand_doc(rest: str, record: "RunRecord") -> str:
    """`brand-doc:<dotted field>` — the parameterisation a reader is being asked to judge."""
    return _render(_dig((record.brand_doc or {}).get("doc", {}), rest))


def _path(rest: str, base_url: str, repo_root: Path) -> str:
    """`path:<repo-relative path>` — human-produced material that lives in the repository.

    Existence is all that is checked. Whether the path is tracked is a property of the
    reference, not something to re-derive here, and shelling out to git would make a reader
    without a working tree see `missing` for a file that is plainly there.
    """
    return rest if rest and (repo_root / rest).exists() else MISSING


def _url_in(rest: str, base_url: str, repo_root: Path) -> str:
    """`url-in:<repo-relative path>` — a URL held in a tracked file, for material that lives
    outside the repository. Before the recording exists the file does not, and the row reads
    `missing`, which is both the honest rendering and the useful one (FR-068)."""
    holder = repo_root / rest
    if not rest or not holder.exists():
        return MISSING
    found = _URL.search(holder.read_text())
    return found.group(0) if found else MISSING


def _system(rest: str, base_url: str, repo_root: Path) -> str:
    """`system:base-url` — the deployed agency this evaluation authenticated against and
    read every record from."""
    return base_url if rest == "base-url" and base_url else MISSING


_RUN_SCOPED = {"action": _action, "artifact": _artifact, "brand-doc": _brand_doc}
_REPO_SCOPED = {"path": _path, "url-in": _url_in, "system": _system}


def _dig(value: object, dotted: str) -> object:
    if not dotted:
        return value
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _render(value: object) -> str:
    if value is None:
        return MISSING
    if isinstance(value, str):
        return value or MISSING
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return str(value)
