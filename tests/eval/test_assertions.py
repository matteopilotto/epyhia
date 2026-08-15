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
from epyhia.ingest.hashing import content_sha256


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
    brief: dict | None = None,
    posts: dict | None = None,
) -> ev.RunRecord:
    """A stored run carrying no client data — placeholder strings and integers only."""
    return ev.RunRecord(
        label="a-brief",
        brief=brief or {"products": []},
        brief_sha256="0" * 64,
        run={"id": "a-run", "alias": "an-alias"},
        actions=actions or [],
        artifacts=artifacts or [],
        brand_doc={"doc": {"name": "A Placeholder Name"}},
        orders=orders or [],
        cost=cost or {"calls": [], "total_usd": 0.0},
        posts=posts,
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


ALIAS = "https://an-alias.invalid"


def published(created_at: str, **overrides) -> dict:
    """A proved deploy: the evidence a `verify()` stores, at the run's one alias."""
    return action(
        "deploy",
        "succeeded",
        id=f"deploy-{created_at}",
        created_at=created_at,
        evidence={
            "status": 200,
            "url": ALIAS,
            "matched_name": "A Placeholder Name",
            "matched_build_marker": True,
        }
        | overrides,
    )


def deduplicated_response() -> httpx.Response:
    return httpx.Response(200, json={"deduplicated": True, "run_id": "a-run"})


def test_a_second_publication_is_a_brand_doc_edit_not_a_duplicate() -> None:
    """`deploy_key` includes the brand doc version, so an operator edit and a re-run publish
    again by design (§5.3, §7.2, US4 scenario 3). Both checks must survive that flow."""
    two = record(
        actions=[published("2020-01-01T00:00:00+00:00"), published("2020-01-02T00:00:00+00:00")]
    )
    source = StubSource(records=[two], response=deduplicated_response(), after=two)

    published_passed, published_detail = ev.CHECKS["deliverables-site-published"](source)
    assert published_passed, published_detail
    # Visible rather than silently tolerated.
    assert "2 succeeded deploy(s)" in published_detail

    rerun_passed, rerun_detail = ev.CHECKS["gate-rerun-is-idempotent"](source)
    assert rerun_passed, rerun_detail
    assert "publications 2 → 2" in rerun_detail


def test_the_newest_publication_is_the_one_read() -> None:
    """The live site is the latest by `created_at`, not by row order — so a superseded
    publication can neither carry this check nor sink it."""
    superseded = published("2020-01-01T00:00:00+00:00", matched_name="A Superseded Name")
    live = published("2020-01-02T00:00:00+00:00")
    assert ev.CHECKS["deliverables-site-published"](
        StubSource(records=[record(actions=[superseded, live])])
    )[0]

    # The same two rows, with the mismatch as the newest: now it is what a visitor sees.
    republished = published("2020-01-03T00:00:00+00:00", matched_name="A Superseded Name")
    assert not ev.CHECKS["deliverables-site-published"](
        StubSource(records=[record(actions=[republished, live])])
    )[0]


def test_no_publication_at_all_still_fails() -> None:
    source = StubSource(records=[record(actions=[])])

    passed, detail = ev.CHECKS["deliverables-site-published"](source)
    assert not passed
    assert detail.endswith("no succeeded deploy action")


POSTS = [
    {"angle": "a", "body": "one"},
    {"angle": "b", "body": "two"},
    {"angle": "c", "body": "three"},
]


def posts_artifact(*, grounding_status: str = "clean", revision: int = 0) -> dict:
    return {
        "id": "a-posts-artifact",
        "kind": "posts",
        "revision": revision,
        "grounding_status": grounding_status,
        "sha256": "2" * 64,
    }


def publish(post: dict, **overrides) -> dict:
    evidence = {
        "post_id": post["angle"],
        "permalink": "https://sink.invalid",
        "payload_sha256": content_sha256(post),
    } | overrides.pop("evidence", {})
    return action(
        "publish", "succeeded", id=f"publish-{post['angle']}", evidence=evidence, **overrides
    )


def test_posts_published_when_every_post_was_published() -> None:
    rec = record(
        artifacts=[posts_artifact()],
        actions=[publish(post) for post in POSTS],
        posts={"posts": POSTS},
    )

    passed, detail = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert passed, detail
    assert "3 succeeded publish action(s), 3 distinct payload(s) matching 3 post(s)" in detail


def test_posts_published_fails_when_a_post_was_never_published() -> None:
    rec = record(
        artifacts=[posts_artifact()],
        actions=[publish(post) for post in POSTS[:2]],
        posts={"posts": POSTS},
    )

    passed, _ = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert not passed


def test_posts_published_fails_on_a_payload_sha_mismatch() -> None:
    tampered = publish(POSTS[0], evidence={"payload_sha256": "not-the-right-sha"})
    rec = record(
        artifacts=[posts_artifact()],
        actions=[tampered, publish(POSTS[1]), publish(POSTS[2])],
        posts={"posts": POSTS},
    )

    passed, _ = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert not passed


def test_posts_published_fails_for_a_succeeded_publish_beside_a_flagged_artifact() -> None:
    """The `gate-refuses-flagged-and-unarmed` symmetry: publication against a flagged posts
    artifact is itself the violation, however clean any one payload looks."""
    rec = record(
        artifacts=[posts_artifact(grounding_status="flagged")],
        actions=[publish(POSTS[0])],
    )

    passed, detail = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert not passed
    assert "flagged" in detail


def test_posts_published_does_not_fail_a_flagged_artifact_that_published_nothing() -> None:
    """The gate refusing a flagged artifact's publish is the system working as built, not a
    failure to publish."""
    rec = record(artifacts=[posts_artifact(grounding_status="flagged")], actions=[])

    passed, _ = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert passed


def test_posts_published_fails_when_no_posts_artifact_exists_at_all() -> None:
    rec = record(artifacts=[], actions=[])

    passed, detail = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert not passed
    assert detail.endswith("no posts artifact for this run")


def test_posts_published_fails_when_approvals_were_never_worked() -> None:
    """§6/§7 of the outreach plan, accepted deliberately: a clean posts artifact whose
    publish actions were simply never approved reads as an incomplete deliverable."""
    rec = record(artifacts=[posts_artifact()], actions=[], posts={"posts": POSTS})

    passed, _ = ev.CHECKS["deliverables-posts-published"](StubSource(records=[rec]))
    assert not passed


def email_sent(recipient: str, **overrides) -> dict:
    return action(
        "send_email",
        "succeeded",
        evidence={"message_id": "a-message-id", "recipient": recipient, "subject": "A subject"},
        **overrides,
    )


def test_email_sent_to_the_briefs_own_contact_address() -> None:
    rec = record(
        brief={"contact": {"email": "hello@example.invalid"}},
        actions=[email_sent("hello@example.invalid")],
    )

    passed, detail = ev.CHECKS["deliverables-email-sent"](StubSource(records=[rec]))
    assert passed, detail


def test_email_sent_fails_when_the_recipient_does_not_match_the_brief() -> None:
    rec = record(
        brief={"contact": {"email": "hello@example.invalid"}},
        actions=[email_sent("someone-else@example.invalid")],
    )

    passed, _ = ev.CHECKS["deliverables-email-sent"](StubSource(records=[rec]))
    assert not passed


def test_email_sent_fails_when_nothing_was_sent() -> None:
    rec = record(brief={"contact": {"email": "hello@example.invalid"}}, actions=[])

    passed, detail = ev.CHECKS["deliverables-email-sent"](StubSource(records=[rec]))
    assert not passed
    assert "0 succeeded send_email action(s)" in detail


def test_a_resubmission_that_published_again_fails_the_rerun_check() -> None:
    """The delta is the claim: a re-run that added a publication is not idempotent, however
    many the run legitimately had before it."""
    before = record(actions=[published("2020-01-01T00:00:00+00:00")])
    after = record(
        actions=[published("2020-01-01T00:00:00+00:00"), published("2020-01-02T00:00:00+00:00")]
    )
    source = StubSource(records=[before], response=deduplicated_response(), after=after)

    passed, detail = ev.CHECKS["gate-rerun-is-idempotent"](source)
    assert not passed
    assert "publications 1 → 2" in detail


def test_a_second_alias_fails_the_rerun_check() -> None:
    """`alias_for` is a pure function of the brief hash, so two aliases are two runs."""
    elsewhere = published("2020-01-02T00:00:00+00:00", url="https://another-alias.invalid")
    two = record(actions=[published("2020-01-01T00:00:00+00:00"), elsewhere])
    source = StubSource(records=[two], response=deduplicated_response(), after=two)

    passed, detail = ev.CHECKS["gate-rerun-is-idempotent"](source)
    assert not passed
    assert "2 alias(es)" in detail


def test_a_resubmission_that_created_an_order_fails_the_rerun_check() -> None:
    order = {"paid": True, "product_slug": "a-product", "amount_minor": 1}
    before = record(actions=[published("2020-01-01T00:00:00+00:00")], orders=[order])
    source = StubSource(
        records=[before],
        response=deduplicated_response(),
        after=record(actions=before.actions, orders=[order, order]),
    )

    passed, detail = ev.CHECKS["gate-rerun-is-idempotent"](source)
    assert not passed
    assert "orders 1 → 2" in detail


def site(grounding_status: str = "clean") -> dict:
    return {
        "id": "a-site-artifact",
        "kind": "site",
        "revision": 1,
        "grounding_status": grounding_status,
        "sha256": "1" * 64,
    }


def sold(*, armed: bool, grounding_status: str = "clean") -> ev.RunRecord:
    """One test purchase against a published run: one order row and the one session that
    created it."""
    actions = [published("2020-01-01T00:00:00+00:00"), action("checkout_session", "succeeded")]
    if armed:
        actions.append(action("arm_charge_path", "succeeded"))
    return record(
        actions=actions,
        artifacts=[site(grounding_status)],
        orders=[{"paid": True, "product_slug": "a-product", "amount_minor": 1}],
    )


def test_one_sale_counts_as_one_order_from_one_session() -> None:
    """Summing the two reported "2 purchases" for one sale. The verdict was unaffected; the
    number a grader reads was wrong."""
    passed, detail = ev.CHECKS["gate-refuses-flagged-and-unarmed"](
        StubSource(records=[sold(armed=True)])
    )

    assert passed, detail
    assert "1 order(s) from 1 session(s)" in detail


def test_a_sale_against_an_unarmed_run_still_fails() -> None:
    passed, _ = ev.CHECKS["gate-refuses-flagged-and-unarmed"](
        StubSource(records=[sold(armed=False)])
    )
    assert not passed


def test_a_published_flagged_site_still_fails() -> None:
    passed, _ = ev.CHECKS["gate-refuses-flagged-and-unarmed"](
        StubSource(records=[sold(armed=True, grounding_status="flagged")])
    )
    assert not passed


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
