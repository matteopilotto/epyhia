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


def action(action_type: str, state: str, **overrides) -> dict:
    """One action row of the shape the gate stores and the API serialises.

    The defaults are a proved action: a key, both cost columns, evidence. Each test overrides
    only the columns whose emptiness it is about.
    """
    row = {
        "id": overrides.pop("id", f"{action_type}-{state}"),
        "action_type": action_type,
        "state": state,
        "idempotency_key": f"key-for-{action_type}-{state}",
        "projected_cost_usd": 0.0,
        "cost_usd": 0.0 if state == "succeeded" else None,
        "evidence": {"status": 200} if state == "succeeded" else None,
        "created_at": "2020-01-01T00:00:00+00:00",
        "requested_by": "an-agent",
        "approval_decision": None,
        "approved_by": None,
        "approved_at": None,
    }
    return row | overrides


def record(
    *,
    actions: list[dict] | None = None,
    artifacts: list[dict] | None = None,
    orders: list[dict] | None = None,
    cost: dict | None = None,
) -> ev.RunRecord:
    """A stored run carrying no client data — placeholder strings and integers only."""
    return ev.RunRecord(
        label="a-brief",
        brief={"products": []},
        brief_sha256="0" * 64,
        run={"id": "a-run", "alias": "an-alias"},
        actions=actions or [],
        artifacts=artifacts or [],
        brand_doc={"doc": {"name": "A Placeholder Name"}},
        orders=orders or [],
        cost=cost or {"calls": [], "total_usd": 0.0},
    )


COSTED_RUN = {"calls": [{"id": "a-call", "cost_usd": 0.0}], "total_usd": 0.0}


@pytest.mark.parametrize("check_id", ["crew-cost-logged", "gate-audit-and-cost"])
def test_a_denied_or_pending_action_carries_a_projection_and_no_actual(check_id: str) -> None:
    """The gate writes `cost_usd` only in the `succeeded` branch. Demanding it of every row
    would turn one denied action into 6 failed required points on a gate doing exactly what
    FR-039 and FR-050 specify."""
    source = StubSource(
        records=[
            record(
                actions=[
                    action("deploy", "succeeded"),
                    action("send_email", "denied"),
                    action("arm_charge_path", "awaiting_approval"),
                ],
                cost=COSTED_RUN,
            )
        ]
    )

    passed, detail = ev.CHECKS[check_id](source)
    assert passed, detail


@pytest.mark.parametrize("check_id", ["crew-cost-logged", "gate-audit-and-cost"])
def test_a_succeeded_action_with_no_actual_cost_still_fails(check_id: str) -> None:
    source = StubSource(
        records=[
            record(
                actions=[action("deploy", "succeeded", cost_usd=None)],
                cost=COSTED_RUN,
            )
        ]
    )

    passed, detail = ev.CHECKS[check_id](source)
    assert not passed
    assert "actual cost" in detail


@pytest.mark.parametrize("check_id", ["crew-cost-logged", "gate-audit-and-cost"])
def test_an_action_with_no_projected_cost_fails(check_id: str) -> None:
    source = StubSource(
        records=[
            record(
                actions=[action("send_email", "denied", projected_cost_usd=None)],
                cost=COSTED_RUN,
            )
        ]
    )

    passed, detail = ev.CHECKS[check_id](source)
    assert not passed
    assert "projected cost" in detail


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
