from collections.abc import Callable

import stripe

from epyhia.gate.errors import VerificationFailed
from epyhia.gate.registry import GateContext, register

# One namespace per brief, so a re-run lands on the same objects and two clients never
# collide. Nothing client-shaped is in the string itself — both halves are read from the
# request at the moment they are used (Principle I).
ID_PREFIX = "epyhia"

# The brief's own name for a recurring charge. The cadence it maps to is never here: a
# subscription row carries its own `billing_interval` (contracts/brief.schema.json), because
# a cadence chosen in this file would be one cadence chosen for every client at once.
RECURRING = "subscription"


class StripeCallFailed(Exception):
    """`execute()` could not create the object. The gate marks the action failed and no
    verification runs (contracts/action-gate.md §7)."""


ClientFactory = Callable[[str], stripe.StripeClient]


def _default_client(api_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(api_key)


def product_id_for(request: dict) -> str:
    """`epyhia_<brief_hash[:8]>_<slug>` — derived identically on both halves of the pair, so
    `verify()` retrieves the object it expects rather than the one `execute()` reported
    (contracts/action-gate.md §3)."""
    return f"{ID_PREFIX}_{request['brief_hash'][:8]}_{request['slug'].replace('-', '_')}"


def price_lookup_key(request: dict) -> str:
    """Stripe assigns price ids itself, so the derived handle is a lookup key instead. It
    carries the amount and currency, which is what makes a repriced catalogue a different
    price rather than a silent reuse of the old one."""
    return (
        f"{ID_PREFIX}_{request['brief_hash'][:8]}_{request['slug']}"
        f"_{request['price_minor']}_{request['currency_charge'].lower()}"
    )


def recurring_for(request: dict) -> dict | None:
    """The processor's recurring clause, read field by field from the brief's own row.

    An absent `billing_interval_count` is left off the call entirely rather than defaulted
    here — the processor's own meaning of "every interval" is the honest reading, and a
    default written here would be a billing decision made in code.
    """
    if request["billing"] != RECURRING:
        return None
    recurring = {"interval": request["billing_interval"]}
    if request.get("billing_interval_count") is not None:
        recurring["interval_count"] = request["billing_interval_count"]
    return recurring


class _StripeAdapter:
    """Shared plumbing only: the key is required at execute time and never leaves the gate,
    and the client is injectable so the pair is exercisable with no key and no network."""

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client

    def _client(self, ctx: GateContext) -> stripe.StripeClient:
        return self._client_factory(ctx.credentials.require("stripe"))


class StripeProductAdapter(_StripeAdapter):
    action_type = "stripe_product"
    # Creating a catalogue entry charges nobody. The decision a human makes is arming the
    # charge path, once, over the resolved catalogue (§4.4).
    requires_approval = False

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        client = self._client(ctx)
        product_id = product_id_for(request)
        try:
            product = await client.v1.products.create_async(
                {
                    "id": product_id,
                    "name": request["name"],
                    "description": request["description"],
                    "metadata": {"slug": request["slug"]},
                }
            )
        except stripe.InvalidRequestError as exc:
            # The id is derived, so a re-run reaches an object that already exists. That is
            # the intended outcome of the same brief twice, not a failure — the truth still
            # comes from verify().
            if "already exists" not in str(exc):
                raise StripeCallFailed(str(exc)) from exc
            product = await client.v1.products.retrieve_async(product_id)
        return {"product_id": product["id"]}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Read the object back by the id this adapter derives, not the one `execute()`
        returned — which is also what makes the probe work on a resumed action, where there
        is no `result` to trust (§7.4)."""
        product_id = product_id_for(request)
        try:
            product = await self._client(ctx).v1.products.retrieve_async(product_id)
        except stripe.StripeError as exc:
            raise VerificationFailed(f"product {product_id}: {exc}") from exc
        if product is None or not product.get("active"):
            raise VerificationFailed(f"product {product_id} is not active")
        return {
            "product_id": product["id"],
            "name": product["name"],
            "slug": (product.get("metadata") or {}).get("slug"),
        }


class StripePriceAdapter(_StripeAdapter):
    action_type = "stripe_price"
    requires_approval = False

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        client = self._client(ctx)
        payload = {
            "product": request["product_id"],
            # Straight from the run's resolved catalogue, which is the brief's own row. No
            # conversion happens anywhere: `currency_display` is what the page says and
            # `currency_charge` is what this charges, as given (FR-003, research.md R6).
            "unit_amount": request["price_minor"],
            "currency": request["currency_charge"].lower(),
            "lookup_key": price_lookup_key(request),
            "metadata": {"slug": request["slug"]},
        }
        recurring = recurring_for(request)
        if recurring is not None:
            payload["recurring"] = recurring
        try:
            price = await client.v1.prices.create_async(payload)
        except stripe.StripeError as exc:
            raise StripeCallFailed(str(exc)) from exc
        return {"price_id": price["id"]}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        price = await find_price(self._client(ctx), price_lookup_key(request))
        if price is None:
            raise VerificationFailed(f"no price for {price_lookup_key(request)}")
        assert_matches(price, request)
        return {
            "price_id": price["id"],
            "unit_amount": price["unit_amount"],
            "currency": price["currency"],
            "recurring": price.get("recurring"),
        }


class ArmChargePathAdapter(_StripeAdapter):
    action_type = "arm_charge_path"
    # *May this run take money, at these prices?* — the one money decision a human can make
    # in advance, and therefore the one that is gated (FR-037, §4.4).
    requires_approval = True

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        """Nothing is created here: the products and prices already exist, and armed-ness is
        the state of this row rather than a flag written somewhere else. Which is the point —
        the run is armed because FR-029's re-read passed, so the armed state and its evidence
        are one record (research.md R11)."""
        return {"armed": [row["slug"] for row in request["catalogue"]]}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Re-read **every** price from the processor and hold each against the brief's own
        row. Not a sample and not the ones that changed: a catalogue is armed as a whole, and
        one price that drifted is a customer charged the wrong amount (FR-029)."""
        client = self._client(ctx)
        prices = []
        for row in request["catalogue"]:
            try:
                price = await client.v1.prices.retrieve_async(row["price_id"])
            except stripe.StripeError as exc:
                raise VerificationFailed(f"price {row['price_id']}: {exc}") from exc
            if price is None:
                raise VerificationFailed(f"price {row['price_id']} does not exist")
            assert_matches(price, row)
            prices.append(
                {
                    "slug": row["slug"],
                    "price_id": price["id"],
                    "unit_amount": price["unit_amount"],
                    "currency": price["currency"],
                }
            )
        return {"prices": prices}


async def find_price(client: stripe.StripeClient, lookup_key: str) -> dict | None:
    """The price carrying this derived lookup key, or None. Listed rather than retrieved by
    id because Stripe assigns price ids and this must not depend on what `execute()` said."""
    listing = await client.v1.prices.list_async({"lookup_keys": [lookup_key], "limit": 1})
    data = listing["data"]
    return data[0] if data else None


def assert_matches(price: dict, expected: dict) -> None:
    """The catalogue row, re-read from the processor. Both fields are compared against the
    brief's own values — an amount or a currency that drifted is what FR-029 exists to
    catch, and it must fail rather than be reported."""
    if not price.get("active"):
        raise VerificationFailed(f"price {price['id']} is not active")
    if price["unit_amount"] != expected["price_minor"]:
        raise VerificationFailed(
            f"price {price['id']} is {price['unit_amount']}, expected {expected['price_minor']}"
        )
    if price["currency"] != expected["currency_charge"].lower():
        raise VerificationFailed(
            f"price {price['id']} charges {price['currency']}, "
            f"expected {expected['currency_charge'].lower()}"
        )


register(StripeProductAdapter())
register(StripePriceAdapter())
register(ArmChargePathAdapter())
