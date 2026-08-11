"""The assertions, against stub records.

These are regression tests for four assertion functions, in the spirit `test_report.py`
established for the report writer. **They check off none of T122–T139**: those checks assert
over runs an operator drove end to end, and no stub stands in for one. What a stub can do is
hold an assertion to the shape of record the system actually stores — a denied action, a
second publication after a brand-doc edit — so a correctly-behaving agency is never reported
red.

Every record built here carries neutral placeholder strings and integers. Principle I applies
to this file exactly as it does to `eval/`: no client data, in a fixture or anywhere else.
"""

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

import eval.eval as ev


@dataclass
class StubSource:
    """A record source that supports the one write the evaluation may make.

    `test_report.py`'s stub refuses both `resubmit` and `reread` — that refusal is the point
    of what it tests. The re-run check needs them, so it gets its own stub rather than that
    one being weakened.
    """

    records: list = field(default_factory=list)
    base_url: str = "https://agency.invalid"
    identity: str = "an-eval-client@clients"
    response: httpx.Response | None = None
    after: "ev.RunRecord | None" = None

    def resubmit(self, record):
        return self.response

    def reread(self, record):
        return self.after if self.after is not None else record


def test_a_connect_error_refuses_rather_than_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connectivity problem is not a grade. Exiting 1 would make it indistinguishable from
    a required check that failed (FR-068)."""
    report = tmp_path / "PRODUCT_EVAL.md"
    monkeypatch.setattr(ev, "REPORT_PATH", report)
    monkeypatch.setattr(
        ev.EvalClient,
        "from_settings",
        classmethod(lambda cls: (_ for _ in ()).throw(httpx.ConnectError("no route"))),
    )

    assert ev.main(["tests/fixtures/briefs/does-not-matter.json"]) == ev.REFUSED
    assert not report.exists()


def test_an_unauthorised_read_refuses_rather_than_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same for a 401 raised by `raise_for_status()` deep inside the record reads."""
    report = tmp_path / "PRODUCT_EVAL.md"
    monkeypatch.setattr(ev, "REPORT_PATH", report)

    def unauthorised(cls):
        raise httpx.HTTPStatusError(
            "401 Unauthorized",
            request=httpx.Request("GET", "https://agency.invalid/runs"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(ev.EvalClient, "from_settings", classmethod(unauthorised))

    assert ev.main(["tests/fixtures/briefs/does-not-matter.json"]) == ev.REFUSED
    assert not report.exists()
