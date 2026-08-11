"""EPYHIA's evaluation.

Runs against the **deployed** agency and writes `PRODUCT_EVAL.md` (DESIGN.md §10).

It does not drive the runs it grades. An operator drives both briefs through the console —
approvals and the one test purchase included — and this asserts afterwards over what those
runs left behind. Every value it reads was already observed and stored by a `verify()` step,
so nothing here re-probes the world: an eval that re-drives it would be asserting against a
second, weaker observation while a stronger one sits in the row.

    uv run python eval/eval.py tests/fixtures/briefs/one.json tests/fixtures/briefs/two.json

Each run is located by hashing the brief it was handed, with ingest's own canonicalisation.
Run identity is brief identity (§7.1), so no run id is written into the repository and no
"most recent run" rule can quietly grade the wrong thing (FR-061).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

if __package__ in (None, ""):
    # The documented invocation runs this as a script, which puts `eval/` on `sys.path` and
    # not the repository root — its sibling modules would not import.
    sys.path.insert(0, str(REPO_ROOT))

import json  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Protocol  # noqa: E402

import httpx  # noqa: E402

from epyhia.config import CredentialNotConfigured, settings  # noqa: E402
from epyhia.ingest.hashing import content_sha256  # noqa: E402

RUBRIC_PATH = HERE / "rubric.json"
REPORT_PATH = REPO_ROOT / "PRODUCT_EVAL.md"

# Exit codes. `FAILED` is FR-068's signal and is reserved for a failed required *automated*
# check; refusing to run at all is a different condition and says so with its own code, so a
# missing credential can never be read as a graded failure.
PASSED = 0
FAILED = 1
REFUSED = 2

TIMEOUT_SECONDS = 30.0


class EvalRefused(Exception):
    """The evaluation cannot run, and says why rather than grading something else.

    An unconfigured credential and an undriven brief both land here: neither is a result,
    and reporting either as a failed check would put a number on a run that never happened.
    """


class EvalClient:
    """The evaluation's Auth0 machine-to-machine client.

    Two properties are structural rather than conventional. It authenticates through the
    same validator as the console — a bypass key would be a second auth path around my own
    auth, which is the same smell as an agent that deploys around the gate. And it carries
    **no approve/deny call path at all**: not a disabled one, not one behind a flag. There is
    no method here that can post an approval decision (FR-058, §10).

    `submit_brief` is the single write it can perform, and it is safe by construction: an
    identical payload hashes to the existing brief, so every gate key short-circuits and the
    resubmission has no external effect (§7.2).
    """

    def __init__(self, base_url: str, token: str, identity: str, transport=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.identity = identity
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=TIMEOUT_SECONDS,
        )

    @classmethod
    def from_settings(cls) -> "EvalClient":
        base_url = settings.require("eval_api_base_url")
        client_id = settings.require("eval_auth0_client_id")
        client_secret = settings.require("eval_auth0_client_secret")
        domain = settings.require("auth0")
        if settings.auth0_audience is None:
            raise CredentialNotConfigured("auth0_audience")

        response = httpx.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": settings.auth0_audience,
            },
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise EvalRefused(
                f"Auth0 refused the machine-to-machine grant: {response.status_code}"
            )
        # The `sub` Auth0 mints for a client-credentials grant. Held so the record can be
        # asserted to carry no approval decision attributed to it (FR-058).
        return cls(base_url, response.json()["access_token"], f"{client_id}@clients")

    def get(self, path: str) -> object:
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()

    def submit_brief(self, payload: dict) -> httpx.Response:
        """The one action the evaluation initiates. Byte-identical by construction: the
        payload handed back is the payload read off disk."""
        return self._client.post("/briefs", json=payload)


@dataclass(frozen=True)
class RunRecord:
    """One driven run, as stored. Named by the brief file it was resolved from, so a report
    covering two runs can say which is which without naming either business."""

    label: str
    brief: dict
    brief_sha256: str
    run: dict
    actions: list[dict]
    artifacts: list[dict]
    brand_doc: dict | None
    orders: list[dict]
    cost: dict


class RecordSource(Protocol):
    """What the checks read. A protocol so the report can be tested against a stub source
    with no credentials and no network — the checks themselves still need driven runs."""

    base_url: str
    records: list[RunRecord]

    def resubmit(self, record: RunRecord) -> httpx.Response: ...


@dataclass
class DeployedRecords:
    """The stored records of the deployed agency, read once, up front."""

    client: EvalClient
    brief_paths: list[Path]
    records: list[RunRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        runs = self.client.get("/runs")
        self.records = [self._record(path, runs) for path in self.brief_paths]

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def resubmit(self, record: RunRecord) -> httpx.Response:
        return self.client.submit_brief(record.brief)

    def _record(self, path: Path, runs: list[dict]) -> RunRecord:
        brief = json.loads(path.read_text())
        brief_sha256 = content_sha256(brief)
        run = _resolve_run(runs, brief_sha256, path.name)
        run_id = run["id"]
        return RunRecord(
            label=path.stem,
            brief=brief,
            brief_sha256=brief_sha256,
            run=run,
            actions=self.client.get(f"/runs/{run_id}/actions"),
            artifacts=self.client.get(f"/runs/{run_id}/artifacts"),
            brand_doc=_optional(self.client, f"/runs/{run_id}/brand-doc"),
            orders=self.client.get(f"/runs/{run_id}/orders"),
            cost=self.client.get(f"/runs/{run_id}/cost"),
        )


def _optional(client: EvalClient, path: str) -> dict | None:
    """A record the run may legitimately not have reached yet. A 404 is data, not an error;
    the check that needs it decides what its absence means."""
    try:
        return client.get(path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def _resolve_run(runs: list[dict], brief_sha256: str, name: str) -> dict:
    matching = [run for run in runs if run.get("brief_sha256") == brief_sha256]
    if not matching:
        raise EvalRefused(
            f"no run carries {name}'s brief hash — the evaluation grades runs an operator "
            f"has already driven end to end, and does not drive them itself"
        )
    if len(matching) > 1:
        raise EvalRefused(
            f"{len(matching)} runs carry {name}'s brief hash; refusing to choose between them"
        )
    return matching[0]


@dataclass(frozen=True)
class Result:
    """One rubric row, evaluated.

    `passed` is `None` for an `evidence` row and stays that way: those rows are human
    judgement, and the evaluation neither passes nor scores them (FR-063).
    """

    check: dict
    passed: bool | None
    observed: str
    resolved: list[tuple[str, str]] = field(default_factory=list)


# Every `automated` rubric id, mapped to what asserts it. A row with no implementation fails
# loudly rather than passing by omission.
CHECKS: dict[str, object] = {}


def load_rubric() -> list[dict]:
    return json.loads(RUBRIC_PATH.read_text())["checks"]


def evaluate(source: RecordSource, checks: list[dict] | None = None) -> list[Result]:
    return [_evaluate(check, source) for check in (checks or load_rubric())]


def _evaluate(check: dict, source: RecordSource) -> Result:
    if check["kind"] != "automated":
        return Result(check=check, passed=None, observed="")

    implementation = CHECKS.get(check["id"])
    if implementation is None:
        return Result(check, False, f"no implementation for check id {check['id']!r}")
    try:
        passed, observed = implementation(source)
    except Exception as exc:
        # A check that raises fails that check and nothing else: the report is written on
        # every run, and one broken assertion must not take the other twenty with it.
        return Result(check, False, f"raised {type(exc).__name__}: {exc}")
    return Result(check, passed, observed)


def render_report(results: list[Result], source: RecordSource) -> str:
    lines = [
        "# PRODUCT_EVAL.md",
        "",
        f"Read from the stored records of the deployed agency at `{source.base_url}`.",
        "",
    ]
    for result in results:
        check = result.check
        state = {True: "pass", False: "FAIL", None: "judged"}[result.passed]
        lines.append(f"- [{check['area']}] {check['title']} — {state} — {result.observed}")
    return "\n".join(lines) + "\n"


def exit_status(results: list[Result]) -> int:
    failed = [r for r in results if r.check["required"] and r.passed is False]
    return FAILED if failed else PASSED


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: eval.py <brief.json> [<brief.json> ...]", file=sys.stderr)
        return REFUSED

    try:
        source = DeployedRecords(EvalClient.from_settings(), [Path(a) for a in argv])
    except (CredentialNotConfigured, EvalRefused) as exc:
        print(f"evaluation refused: {exc}", file=sys.stderr)
        return REFUSED

    results = evaluate(source)
    REPORT_PATH.write_text(render_report(results, source))
    return exit_status(results)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
