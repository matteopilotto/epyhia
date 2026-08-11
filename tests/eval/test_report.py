from dataclasses import dataclass, field
from pathlib import Path

import pytest

import eval.eval as ev
from eval.resolve import MISSING

FAILING = "a-failing-required-check"
PASSING = "a-passing-required-check"
JUDGED = "a-judged-row"


@dataclass
class StubSource:
    """A record source with no records, no credentials and no network.

    The report writer is what is under test here, not the assertions: those need runs an
    operator drove, and no stub can stand in for one. What a stub can do is put the writer
    in each of the states FR-068 and FR-063 name.
    """

    base_url: str = "https://agency.invalid"
    identity: str = "an-eval-client@clients"
    records: list = field(default_factory=list)

    def resubmit(self, record):
        raise AssertionError("the report writer initiates nothing")

    def reread(self, record):
        raise AssertionError("the report writer initiates nothing")


def row(check_id: str, kind: str, required: bool, evidence: str) -> dict:
    """A rubric row of this evaluation's own shape, carrying no client data and belonging to
    no real check — the report writer is being graded here, not the agency."""
    return {
        "id": check_id,
        "area": "action-gate",
        "points": 5,
        "title": f"Row {check_id}",
        "kind": kind,
        "assertion": "What a reader is being asked to look at.",
        "evidence": evidence,
        "required": required,
    }


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ev.CHECKS, FAILING, lambda source: (False, "the evidence it read"))
    monkeypatch.setitem(ev.CHECKS, PASSING, lambda source: (True, "the evidence it read"))


@pytest.mark.usefixtures("registered")
def test_a_failed_required_check_still_writes_the_report_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = ev.evaluate(
        StubSource(),
        [
            row(FAILING, "automated", required=True, evidence="actions:state"),
            row(JUDGED, "evidence", required=False, evidence="path:DESIGN.md"),
        ],
    )
    monkeypatch.setattr(ev, "REPORT_PATH", tmp_path / "PRODUCT_EVAL.md")

    assert ev.write_report(results, StubSource()) == ev.FAILED

    report = (tmp_path / "PRODUCT_EVAL.md").read_text()
    # Named at the top, above everything a reader would have to scroll past to find it.
    summary = report.split("## How to read this")[0]
    assert FAILING in summary
    # And the document is still whole rather than truncated at the failure.
    assert "### Left to judgement — no score awarded" in report


@pytest.mark.usefixtures("registered")
def test_an_unresolvable_judged_row_reads_missing_and_leaves_the_status_at_zero() -> None:
    results = ev.evaluate(
        StubSource(),
        [
            row(PASSING, "automated", required=True, evidence="actions:state"),
            row(JUDGED, "evidence", required=False, evidence="url-in:no/such/tracked/file.md"),
        ],
    )

    judged = next(result for result in results if result.check["id"] == JUDGED)
    assert judged.passed is None
    assert judged.resolved == [("", MISSING)]

    # A gap in the evidence is not a mechanical failure (FR-068).
    assert ev.exit_status(results) == ev.PASSED
    report = ev.render_report(results, StubSource())
    assert MISSING in report
    assert "None — every required check passed." in report


@pytest.mark.usefixtures("registered")
@pytest.mark.parametrize("automated", [FAILING, PASSING])
def test_a_judged_row_never_renders_a_score(automated: str) -> None:
    results = ev.evaluate(
        StubSource(),
        [
            row(automated, "automated", required=True, evidence="actions:state"),
            row(JUDGED, "evidence", required=False, evidence="path:DESIGN.md"),
        ],
    )

    assert all(r.passed is None for r in results if r.check["kind"] == "evidence")

    report = ev.render_report(results, StubSource())
    rendered = next(line for line in report.splitlines() if line.startswith(f"| Row {JUDGED}"))
    assert "pass" not in rendered
    assert "FAIL" not in rendered
    # What it points at is still there — a judged row carries evidence, just never a score.
    assert "DESIGN.md" in rendered
