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
from collections.abc import Callable  # noqa: E402
from dataclasses import dataclass, field, replace  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Protocol  # noqa: E402

import httpx  # noqa: E402

import epyhia.gate.adapters  # noqa: E402,F401  — registers every adapter pair
from epyhia.agents.strategist import AGENT as STRATEGIST  # noqa: E402
from epyhia.agents.strategist import MODEL_ID as STRATEGIST_MODEL  # noqa: E402
from epyhia.config import CredentialNotConfigured, settings  # noqa: E402
from epyhia.cost.pricing import rate_for  # noqa: E402
from epyhia.gate.registry import get_adapter  # noqa: E402
from epyhia.ingest.catalogue import resolve_catalogue  # noqa: E402
from epyhia.ingest.hashing import content_sha256  # noqa: E402
from eval.resolve import MISSING, latest, resolve  # noqa: E402

# Derived, not named: the top tier is whatever tier `pricing.yaml` gives the model the
# orchestrator runs on. Writing "planning" here would be a third place that fact lives.
TOP_TIER = rate_for(STRATEGIST_MODEL, datetime.now(UTC)).tier

# EPYHIA's own deliverable names — infrastructure vocabulary, not client data.
PACK_KINDS = ("copy", "posts", "email", "video_props")
VIDEO_KINDS = ("video", "video_vertical")
SITE_KIND = "site"

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
    identity: str
    records: list[RunRecord]

    def resubmit(self, record: RunRecord) -> httpx.Response: ...

    def reread(self, record: RunRecord) -> RunRecord: ...


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

    @property
    def identity(self) -> str:
        return self.client.identity

    def resubmit(self, record: RunRecord) -> httpx.Response:
        return self.client.submit_brief(record.brief)

    def reread(self, record: RunRecord) -> RunRecord:
        """The two collections a second run would have added to, read again.

        Still a read of stored records: what the resubmission is asserted by is what the
        run's rows say afterwards, not anything the resubmission itself reported.
        """
        run_id = record.run["id"]
        return replace(
            record,
            actions=self.client.get(f"/runs/{run_id}/actions"),
            orders=self.client.get(f"/runs/{run_id}/orders"),
        )

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
Assertion = Callable[[RunRecord], tuple[bool, str]]
CHECKS: dict[str, Callable[[RecordSource], tuple[bool, str]]] = {}


def check(check_id: str):
    """Bind an assertion to the rubric row it earns points for, by id."""

    def register(fn: Callable[[RecordSource], tuple[bool, str]]):
        CHECKS[check_id] = fn
        return fn

    return register


def for_each_run(source: RecordSource, assertion: Assertion) -> tuple[bool, str]:
    """Every assertion holds for every run handed in, or the check fails.

    Each run's detail is labelled by the brief file it was resolved from: the report has to
    say which run it read without naming either business (Principle I).

    No runs is a failure, not a pass. `all()` over nothing is true, and a check that passes
    because it asserted nothing is the report telling a reader what they want to hear.
    """
    if not source.records:
        return False, "no runs to assert against"

    outcomes = [(record.label, *assertion(record)) for record in source.records]
    detail = "; ".join(f"{label}: {detail}" for label, _, detail in outcomes)
    return all(passed for _, passed, _ in outcomes), detail


@check("deliverables-site-published")
def _site_published(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        deploys = [
            action
            for action in record.actions
            if action["action_type"] == "deploy" and action["state"] == "succeeded"
        ]
        if len(deploys) != 1:
            return False, f"{len(deploys)} succeeded deploy actions"
        evidence = deploys[0]["evidence"] or {}
        # Read from this run's own brand doc row, exactly as the probe did — the string a
        # deploy is proved by varies per client and exists in no source file (FR-018).
        expected_name = (record.brand_doc or {}).get("doc", {}).get("name")
        passed = (
            evidence.get("status") == 200
            and expected_name is not None
            and evidence.get("matched_name") == expected_name
            and bool(evidence.get("matched_build_marker"))
        )
        return passed, f"deploy evidence {json.dumps(evidence, sort_keys=True)}"

    return for_each_run(source, assertion)


@check("deliverables-pack-grounded")
def _pack_grounded(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        current = {kind: latest(record, kind) for kind in PACK_KINDS}
        missing = sorted(kind for kind, artifact in current.items() if artifact is None)
        flagged = sorted(
            kind
            for kind, artifact in current.items()
            if artifact is not None and artifact["grounding_status"] == "flagged"
        )
        return not missing and not flagged, f"missing {missing}, flagged {flagged}"

    return for_each_run(source, assertion)


@check("deliverables-order-persists")
def _order_persists(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        # The brief's own catalogue, slugged the way ingest slugs it — so "matching a
        # product in that brief" is decided against the brief, not against a list here.
        catalogue = {row["slug"]: row for row in resolve_catalogue(record.brief["products"])}
        paid = [order for order in record.orders if order["paid"]]
        matched = [
            order
            for order in paid
            if order["product_slug"] in catalogue
            and order["amount_minor"] == catalogue[order["product_slug"]]["price_minor"]
        ]
        passed = bool(paid) and len(matched) == len(paid)
        return passed, f"{len(record.orders)} orders, {len(paid)} paid, {len(matched)} matching"

    return for_each_run(source, assertion)


@check("deliverables-video-rendered")
def _video_rendered(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        stored = [kind for kind in VIDEO_KINDS if latest(record, kind) is not None]
        return len(stored) == len(VIDEO_KINDS), f"cuts stored: {stored}"

    return for_each_run(source, assertion)


@check("crew-strategist-delegates-only")
def _strategist_delegates_only(source: RecordSource) -> tuple[bool, str]:
    """The mechanical proof of §3.3: the orchestrator is constructed with no gate handles in
    its toolset, so no action row can carry its name."""

    def assertion(record: RunRecord) -> tuple[bool, str]:
        theirs = [
            action["id"] for action in record.actions if action["requested_by"] == STRATEGIST
        ]
        return not theirs, f"{len(record.actions)} actions, {len(theirs)} the orchestrator's"

    return for_each_run(source, assertion)


@check("crew-tiers-are-scoped")
def _tiers_are_scoped(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        calls = record.cost["calls"]
        untiered = [call["id"] for call in calls if not call["model_id"] or not call["tier"]]
        top = [call for call in calls if call["tier"] == TOP_TIER]
        misattributed = [call["id"] for call in top if call["agent"] != STRATEGIST]
        passed = bool(calls) and not untiered and not misattributed
        return passed, (
            f"{len(calls)} calls, {len(untiered)} without a model id or tier, "
            f"{len(top)} at tier {TOP_TIER!r} of which {len(misattributed)} not the orchestrator's"
        )

    return for_each_run(source, assertion)


@check("crew-cost-logged")
def _cost_logged(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        calls = record.cost["calls"]
        uncosted_calls = [call["id"] for call in calls if call["cost_usd"] is None]
        uncosted_actions = [
            action["id"] for action in record.actions if action["cost_usd"] is None
        ]
        total = record.cost.get("total_usd")
        passed = not uncosted_calls and not uncosted_actions and total is not None
        return passed, (
            f"one total of {total} covering {len(calls)} calls and {len(record.actions)} "
            f"actions; {len(uncosted_calls)} calls and {len(uncosted_actions)} actions uncosted"
        )

    return for_each_run(source, assertion)


@check("crew-second-brief-shares-nothing")
def _second_brief_shares_nothing(source: RecordSource) -> tuple[bool, str]:
    """FR-062, and the cheapest strong evidence that this is an agency rather than a
    one-client script: a hardcoded probe string, a seeded product or an aesthetic baked into
    a prompt all fail here and nowhere else.

    Cross-run by nature, so it is the one check that does not hold per run.
    """
    records = source.records
    if len(records) < 2:
        return False, "fewer than two runs were handed in, and genericity is a comparison"

    def brand_field(record: RunRecord, name: str) -> object:
        return (record.brand_doc or {}).get("doc", {}).get(name)

    def probed_name(record: RunRecord) -> object:
        for action in record.actions:
            if action["action_type"] == "deploy" and action["state"] == "succeeded":
                return (action["evidence"] or {}).get("matched_name")
        return None

    palettes = [json.dumps(brand_field(r, "palette"), sort_keys=True) for r in records]
    aliases = [r.run.get("alias") for r in records]
    shared_artifacts = set.intersection(
        *({artifact["sha256"] for artifact in r.artifacts} for r in records)
    )
    own_name = all(
        brand_field(r, "name") is not None and probed_name(r) == brand_field(r, "name")
        for r in records
    )

    passed = (
        len(set(palettes)) == len(records)
        and len(set(aliases)) == len(records)
        and not shared_artifacts
        and own_name
    )
    return passed, (
        f"{len(set(palettes))} distinct palettes and {len(set(aliases))} distinct aliases "
        f"across {len(records)} runs, {len(shared_artifacts)} shared artifact hashes, "
        f"each deploy probe read its own brand doc name: {own_name}"
    )


@check("gate-approval-before-irreversible")
def _approval_before_irreversible(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        gated = [
            action
            for action in record.actions
            if get_adapter(action["action_type"]).requires_approval
        ]
        undecided = [
            action["id"]
            for action in gated
            if action["state"] == "succeeded"
            and not (
                action["approval_decision"] == "approved"
                and action["approved_by"]
                and action["approved_at"]
            )
        ]
        return not undecided, (
            f"{len(gated)} approval-gated actions, {len(undecided)} executed with no "
            f"recorded decision, approver and time"
        )

    return for_each_run(source, assertion)


@check("gate-rerun-is-idempotent")
def _rerun_is_idempotent(source: RecordSource) -> tuple[bool, str]:
    """The one action the evaluation initiates, and the only one it may.

    A byte-identical payload hashes to the existing brief, so the submission resolves to the
    run that already exists and every gate key short-circuits — the re-run assertion is
    *produced* by that rather than arranged (§7.2). One publication is asserted as one
    succeeded deploy at one alias, not merely as one order.
    """

    def assertion(record: RunRecord) -> tuple[bool, str]:
        response = source.resubmit(record)
        body = response.json() if response.content else {}
        deduplicated = (
            response.status_code == 200
            and body.get("deduplicated") is True
            and str(body.get("run_id")) == str(record.run["id"])
        )

        after = source.reread(record)
        deploys = [
            action
            for action in after.actions
            if action["action_type"] == "deploy" and action["state"] == "succeeded"
        ]
        aliases = {(action["evidence"] or {}).get("url") for action in deploys}
        passed = deduplicated and len(deploys) == 1 and len(aliases) == 1 and len(after.orders) == 1
        return passed, (
            f"resubmission {response.status_code} deduplicated={body.get('deduplicated')!r}; "
            f"afterwards {len(deploys)} publication(s) at {len(aliases)} alias(es) and "
            f"{len(after.orders)} order(s)"
        )

    return for_each_run(source, assertion)


@check("gate-no-approval-by-the-eval")
def _no_approval_by_the_eval(source: RecordSource) -> tuple[bool, str]:
    """FR-058 as an absence. The client above has no approve/deny call path in it at all;
    this asserts the record agrees, which is the half a reader can check."""

    def assertion(record: RunRecord) -> tuple[bool, str]:
        theirs = [
            action["id"]
            for action in record.actions
            if action["approved_by"] == source.identity
        ]
        decided = [action for action in record.actions if action["approved_by"]]
        return not theirs, (
            f"{len(decided)} approval decisions, {len(theirs)} attributed to {source.identity}"
        )

    return for_each_run(source, assertion)


@check("gate-audit-and-cost")
def _audit_and_cost(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        incomplete = [
            action["id"]
            for action in record.actions
            if not action["idempotency_key"]
            or not action["state"]
            or action["cost_usd"] is None
            or (action["state"] == "succeeded" and not action["evidence"])
        ]
        return not incomplete, (
            f"{len(record.actions)} action rows, {len(incomplete)} missing a key, a cost or "
            f"the evidence a verification stored"
        )

    return for_each_run(source, assertion)


@check("gate-refuses-flagged-and-unarmed")
def _refuses_flagged_and_unarmed(source: RecordSource) -> tuple[bool, str]:
    def assertion(record: RunRecord) -> tuple[bool, str]:
        site = latest(record, SITE_KIND)
        published = any(
            action["action_type"] == "deploy" and action["state"] == "succeeded"
            for action in record.actions
        )
        flagged_published = published and (
            site is None or site["grounding_status"] == "flagged"
        )

        armed = any(
            action["action_type"] == "arm_charge_path" and action["state"] == "succeeded"
            for action in record.actions
        )
        purchases = len(record.orders) + sum(
            1 for action in record.actions if action["action_type"] == "checkout_session"
        )
        return not flagged_published and not (purchases and not armed), (
            f"site artifact {site and site['grounding_status']}, charge path "
            f"{'armed' if armed else 'unarmed'}, {purchases} purchases"
        )

    return for_each_run(source, assertion)


def load_rubric() -> list[dict]:
    return json.loads(RUBRIC_PATH.read_text())["checks"]


def evaluate(source: RecordSource, checks: list[dict] | None = None) -> list[Result]:
    return [_evaluate(check, source) for check in (checks or load_rubric())]


def _evaluate(check: dict, source: RecordSource) -> Result:
    if check["kind"] != "automated":
        # Resolved, never asserted: `passed` stays `None` for a judged row however its
        # reference resolves, and a reference resolving to nothing is a gap in the evidence
        # rather than a failure (FR-063).
        return Result(
            check=check,
            passed=None,
            observed="",
            resolved=resolve(check["evidence"], source.records, source.base_url),
        )

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


PREAMBLE = """Two kinds of row, and the difference between them is the point.

- **Mechanically checked** rows were asserted by `eval/eval.py` against the records those
  runs left behind. They carry pass/fail and the evidence they read.
- **Left to judgement** rows are human judgements. They carry what to look at and **no
  score**: a script that awards itself points for aesthetics is worth nothing to a reader.
  Their points are this area's budget for a judgement, not points this evaluation earned.
  A reference that resolves to nothing reads `missing` — a gap in the evidence rather than
  a failure, and it does not move this run's exit status.

Per-area budgets come from `eval/rubric.json`, whose areas and totals reconcile to the
tracked grading table in `specs/001-epyhia-agency/contracts/grading-rubric.md` — asserted by
`tests/eval/test_rubric_contract.py` rather than by reading."""


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _resolved(result: Result) -> str:
    """What a judged row points at. Run-scoped references carry the label of the brief the
    run was resolved from, so two runs read as two lines rather than one ambiguous one."""
    return "<br>".join(
        f"`{label}`: {value}" if label else f"{value}" for label, value in result.resolved
    ) or MISSING


def _areas(results: list[Result]) -> dict[str, list[Result]]:
    grouped: dict[str, list[Result]] = {}
    for result in results:
        grouped.setdefault(result.check["area"], []).append(result)
    return grouped


def _area_table(grouped: dict[str, list[Result]]) -> list[str]:
    lines = [
        "| Area | Budget | Mechanically checked | Of those, passing | Left to judgement |",
        "|---|---|---|---|---|",
    ]
    for area, results in grouped.items():
        automated = [r for r in results if r.check["kind"] == "automated"]
        judged = [r for r in results if r.check["kind"] != "automated"]
        checked = sum(r.check["points"] for r in automated)
        passing = sum(r.check["points"] for r in automated if r.passed)
        lines.append(
            f"| `{area}` | {sum(r.check['points'] for r in results)} | {checked} | "
            f"{passing} | {sum(r.check['points'] for r in judged)} |"
        )
    return lines


def render_report(results: list[Result], source: RecordSource) -> str:
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    grouped = _areas(results)
    lines = [
        "# PRODUCT_EVAL.md",
        "",
        f"Read at {generated} from the stored records of the deployed agency at "
        f"`{source.base_url}`. The runs were driven by an operator; this evaluation graded "
        "what they left behind.",
        "",
        "## How to read this",
        "",
        PREAMBLE,
        "",
        "## Areas",
        "",
        *_area_table(grouped),
        "",
    ]

    for area, area_results in grouped.items():
        lines += [f"## `{area}`", ""]

        automated = [r for r in area_results if r.check["kind"] == "automated"]
        if automated:
            lines += [
                "### Mechanically checked",
                "",
                "| Check | Points | Result | Evidence read |",
                "|---|---|---|---|",
            ]
            for result in automated:
                verdict = "pass" if result.passed else "**FAIL**"
                required = "" if result.check["required"] else " (not required)"
                lines.append(
                    f"| {_cell(result.check['title'])}{required} | {result.check['points']} "
                    f"| {verdict} | {_cell(result.observed)} |"
                )
            lines.append("")

        judged = [r for r in area_results if r.check["kind"] != "automated"]
        if judged:
            lines += [
                "### Left to judgement — no score awarded",
                "",
                "| Check | Budget | What to look at | Resolves to |",
                "|---|---|---|---|",
            ]
            for result in judged:
                lines.append(
                    f"| {_cell(result.check['title'])} | {result.check['points']} | "
                    f"{_cell(result.check['assertion'])} | {_cell(_resolved(result))} |"
                )
            lines.append("")

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
