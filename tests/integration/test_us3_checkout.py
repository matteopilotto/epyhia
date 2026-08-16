import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import ops
from epyhia.api.app import create_app
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.stripe import (
    ArmChargePathAdapter,
    CheckoutSessionAdapter,
    StripePriceAdapter,
    StripeProductAdapter,
)
from epyhia.gate.keys import alias_for
from epyhia.ingest.catalogue import resolve_catalogue
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.orders import Order
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service
from epyhia.queue.worker import run_once
from tests.stripe_stub import FakeStripe

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"

WEBHOOK_SECRET = "whsec_test"


def load_brief(name: str = "one.json") -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keys the gate requires. They are never real and never leave the gate — the stub
    below is what actually answers."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_stub")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def register_stripe(api: FakeStripe) -> None:
    for adapter in (
        StripeProductAdapter,
        StripePriceAdapter,
        ArmChargePathAdapter,
        CheckoutSessionAdapter,
    ):
        registry.register(adapter(client_factory=lambda _: api))


def _ops_model() -> FunctionModel:
    """Ops, offline. It emits one line per catalogue entry it was handed, and it has no
    amount to emit even if it wanted to: the request it receives carries none."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for part in reversed(messages[-1].parts):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                payload = json.loads(content)
                break
        else:  # pragma: no cover - the agent always sends a prompt
            raise AssertionError("no user prompt found")

        lines = [
            {"slug": row["slug"], "description": row["description"]}
            for row in payload["catalogue"]
        ]
        return ModelResponse(parts=[TextPart(json.dumps({"lines": lines}))])

    return FunctionModel(respond)


async def open_run(session: AsyncSession, brief_payload: dict) -> Run:
    """Ingest, minus the HTTP and the guardrail's model call, plus the brand doc the money
    stage reads. The Strategist's own path is US1's to prove."""
    brief_hash = content_sha256(brief_payload)
    brief = Brief(
        id=uuid.uuid4(),
        payload=brief_payload,
        content_sha256=brief_hash,
        guardrail_decision="pass",
        guardrail_reason="fixture brief, screened offline",
        guardrail_model="test-model",
    )
    session.add(brief)
    await session.flush()

    brand_doc = BrandDoc(
        id=uuid.uuid4(),
        brief_id=brief.id,
        version=1,
        doc={
            "name": brief_payload["business_name"],
            "voice": brief_payload["voice"],
            "offerings": [
                {k: v for k, v in product.items() if k != "currency_charge"}
                for product in brief_payload["products"]
            ],
        },
        authored_by="strategist",
    )
    session.add(brand_doc)
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brand_doc_id=brand_doc.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(brief_payload, datetime.now(UTC).year),
        resolved_catalogue=resolve_catalogue(brief_payload["products"]),
        budget_usd=25,
        status="running",
        alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.flush()
    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="money", state="pending"))
    await session.commit()
    return run


async def arm(session: AsyncSession, run: Run) -> Action:
    """Run the money stage and take the one approval it stops at."""
    with ops.agent.override(model=_ops_model()):
        assert await run_once(session, kind="money")

    action = (
        await session.execute(
            select(Action).where(
                Action.run_id == run.id, Action.action_type == "arm_charge_path"
            )
        )
    ).scalar_one()
    assert action.state == "awaiting_approval"

    await gate.record_approval(session, action.id, "auth0|operator")
    session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run.id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await session.commit()
    assert await run_once(session, kind="resume")
    await session.refresh(action)
    return action


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    )


def signed(event: dict) -> tuple[bytes, dict]:
    """A genuinely signed body, so the endpoint's own verification is what lets it through
    rather than a patched-out check."""
    payload = json.dumps(event).encode("utf-8")
    timestamp = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return payload, {
        "Stripe-Signature": f"t={timestamp},v1={signature}",
        "content-type": "application/json",
    }


def completed_event(
    *, event_id: str, session_id: str, run_id: uuid.UUID, row: dict, key: str
) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "client_reference_id": key,
                "metadata": {"run_id": str(run_id), "slug": row["slug"]},
                # As the processor reports it, in the currency actually charged — never
                # copied back out of the brief (data-model.md "orders").
                "amount_total": row["price_minor"],
                "currency": row["currency_charge"].lower(),
                "payment_status": "paid",
            }
        },
    }


async def test_buying_before_the_run_is_armed_is_refused(
    integration_session: AsyncSession,
) -> None:
    """The page is live and the button is real, but nobody has agreed to these prices yet.
    A typed 409 is what the site's script branches on (FR-031, research.md R11)."""
    register_stripe(FakeStripe())
    run = await open_run(integration_session, load_brief())
    slug = run.resolved_catalogue[0]["slug"]

    async with client_for(integration_session) as client:
        response = await client.post(
            "/checkout", json={"run_id": str(run.id), "slug": slug}
        )

    assert response.status_code == 409
    assert response.json()["error"] == "not_armed"

    # And nothing was created on the way to refusing.
    sessions = (
        await integration_session.execute(
            select(func.count())
            .select_from(Action)
            .where(Action.action_type == "checkout_session")
        )
    ).scalar_one()
    assert sessions == 0


async def test_an_armed_run_takes_a_buyer_through_with_no_operator_in_the_way(
    integration_session: AsyncSession,
) -> None:
    """SC-009: between the button and the payment form there is no human step. The one
    approval was `arm_charge_path`, and it was taken before the buyer arrived."""
    api = FakeStripe()
    register_stripe(api)
    run = await open_run(integration_session, load_brief())
    armed = await arm(integration_session, run)

    assert armed.state == "succeeded"
    # Arming proved itself by re-reading every price, not by reporting that it had.
    assert [p["unit_amount"] for p in armed.evidence["prices"]] == [
        row["price_minor"] for row in run.resolved_catalogue
    ]

    row = run.resolved_catalogue[0]
    async with client_for(integration_session) as client:
        response = await client.post(
            "/checkout", json={"run_id": str(run.id), "slug": row["slug"]}
        )

    assert response.status_code == 200
    checkout_url = response.json()["checkout_url"]

    action = (
        await integration_session.execute(
            select(Action).where(Action.action_type == "checkout_session")
        )
    ).scalar_one()
    assert action.approval_decision is None
    assert action.state == "verifying"

    created = next(
        s for s in api.checkout.sessions.rows.values() if s["url"] == checkout_url
    )
    assert created["line_items"][0]["price"] == armed.request["catalogue"][0]["price_id"]
    assert created["metadata"]["slug"] == row["slug"]

    # An unknown slug on an armed run is the other typed answer, and it is not a 500.
    async with client_for(integration_session) as client:
        unknown = await client.post(
            "/checkout", json={"run_id": str(run.id), "slug": f"{row['slug']}-x"}
        )
    assert unknown.status_code == 404
    assert unknown.json()["error"] == "unknown_product"


async def test_a_replayed_webhook_writes_exactly_one_order(
    integration_session: AsyncSession,
) -> None:
    """Stripe delivers at least once. The order row and the event id are the same row, so a
    repeat cannot produce a second order (FR-032, §7.3)."""
    api = FakeStripe()
    register_stripe(api)
    run = await open_run(integration_session, load_brief())
    await arm(integration_session, run)

    row = run.resolved_catalogue[0]
    async with client_for(integration_session) as client:
        await client.post("/checkout", json={"run_id": str(run.id), "slug": row["slug"]})

    action = (
        await integration_session.execute(
            select(Action).where(Action.action_type == "checkout_session")
        )
    ).scalar_one()
    session_id = next(iter(api.checkout.sessions.rows))
    event = completed_event(
        event_id="evt_test_1",
        session_id=session_id,
        run_id=run.id,
        row=row,
        key=action.idempotency_key,
    )

    async with client_for(integration_session) as client:
        payload, headers = signed(event)
        first = await client.post("/webhooks/stripe", content=payload, headers=headers)
        payload, headers = signed(event)
        replay = await client.post("/webhooks/stripe", content=payload, headers=headers)

    assert first.status_code == 200 and first.json()["recorded"] is True
    assert replay.status_code == 200 and replay.json()["recorded"] is False

    orders = (
        await integration_session.execute(select(Order).where(Order.run_id == run.id))
    ).scalars().all()
    assert len(orders) == 1
    assert orders[0].product_slug == row["slug"]
    assert orders[0].amount_minor == row["price_minor"]
    assert orders[0].currency == row["currency_charge"].lower()

    # The click could not prove itself until the money landed. Now it can, and the proof is
    # the order row rather than anything the session reported (contracts/action-gate.md §4).
    await integration_session.refresh(action)
    assert action.state == "succeeded"
    assert action.evidence["order_id"] == str(orders[0].id)


async def test_a_signed_webhook_for_a_run_this_database_lacks_is_acknowledged(
    integration_session: AsyncSession,
) -> None:
    """Stripe test mode is one account shared by every environment holding the key, so a
    signed event can name a run that only exists elsewhere. It is acknowledged rather than
    500ed and retried for days, and the foreign key that caught the incident is untouched
    because nothing is inserted."""
    register_stripe(FakeStripe())
    run = await open_run(integration_session, load_brief())
    row = run.resolved_catalogue[0]

    foreign = completed_event(
        event_id="evt_test_foreign",
        session_id="cs_test_foreign",
        run_id=uuid.uuid4(),
        row=row,
        key="cs-key-from-another-stack",
    )
    garbage = completed_event(
        event_id="evt_test_garbage",
        session_id="cs_test_garbage",
        run_id=uuid.uuid4(),
        row=row,
        key="cs-key-from-another-stack",
    )
    garbage["data"]["object"]["metadata"]["run_id"] = "not-a-uuid"

    async with client_for(integration_session) as client:
        for event in (foreign, garbage):
            payload, headers = signed(event)
            response = await client.post(
                "/webhooks/stripe", content=payload, headers=headers
            )
            assert response.status_code == 200
            assert response.json() == {"received": True, "recorded": False}

    orders = (
        await integration_session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert orders == 0


async def test_an_unsigned_webhook_writes_nothing(
    integration_session: AsyncSession,
) -> None:
    register_stripe(FakeStripe())
    run = await open_run(integration_session, load_brief())
    row = run.resolved_catalogue[0]
    event = completed_event(
        event_id="evt_test_2",
        session_id="cs_test_forged",
        run_id=run.id,
        row=row,
        key="whatever",
    )

    async with client_for(integration_session) as client:
        response = await client.post(
            "/webhooks/stripe",
            content=json.dumps(event).encode("utf-8"),
            headers={"Stripe-Signature": "t=1,v1=deadbeef", "content-type": "application/json"},
        )

    assert response.status_code == 400
    orders = (
        await integration_session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert orders == 0
