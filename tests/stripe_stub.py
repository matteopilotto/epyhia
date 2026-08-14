"""The Stripe resources the adapters touch, in memory.

Shared by the adapter tests and the US3 integration test so both drive the same stand-in:
no key, no network, no account, and nothing in CI that costs money (contracts/action-gate.md
§8).

Every row is handed back as a real `StripeObject`, which is the whole point: it supports
indexing and **not** `.get`, exactly as the SDK's parsed objects do. Returning plain dicts
made the stub more permissive than the thing it stands for, and a `product.get("active")`
in the product adapter passed CI for four phases before crashing the worker in production.
A stub that accepts what the real client rejects is not a stub, it is a second
implementation.
"""

import stripe
from stripe._stripe_object import StripeObject


def _as_stripe_object(values: dict) -> StripeObject:
    return StripeObject.construct_from(values, None)


def _read(obj: StripeObject, name: str):
    """Indexing with a default — the stub's own reads must not use `.get` either."""
    try:
        return obj[name]
    except KeyError:
        return None


class FakeStripe:
    def __init__(self) -> None:
        self.products = FakeResource(assigns_ids=False)
        self.prices = FakeResource(assigns_ids=True)
        self.checkout = FakeCheckout()
        # `client.v1.products` reaches the same store as `client.products`, as on the real
        # client.
        self.v1 = self


class FakeCheckout:
    def __init__(self) -> None:
        self.sessions = FakeSessions()


class FakeSessions:
    def __init__(self) -> None:
        self.rows: dict[str, StripeObject] = {}

    async def create_async(self, params: dict) -> StripeObject:
        values = {
            **params,
            "id": f"cs_test_{len(self.rows)}",
            "url": f"https://checkout.stripe.test/{len(self.rows)}",
        }
        obj = _as_stripe_object(values)
        self.rows[obj["id"]] = obj
        return obj


class FakeResource:
    def __init__(self, *, assigns_ids: bool) -> None:
        self.rows: dict[str, StripeObject] = {}
        self._assigns_ids = assigns_ids

    async def create_async(self, params: dict) -> StripeObject:
        values = {**params, "active": True}
        if self._assigns_ids:
            # Stripe names prices itself, which is why the price pair verifies through a
            # derived lookup key rather than an id.
            values["id"] = f"price_{len(self.rows)}"
        self._reject_duplicate(values)
        obj = _as_stripe_object(values)
        self.rows[obj["id"]] = obj
        return obj

    def _reject_duplicate(self, values: dict) -> None:
        """The two uniqueness constraints the adapters have to survive.

        Both are the same brief run twice: the ids and lookup keys are derived from the brief
        hash, so a second run against one account asks for objects the first run already made.
        A stub that stored them silently was the reason neither adapter's idempotent path had
        ever run — and the price adapter's was missing entirely.
        """
        if not self._assigns_ids and values["id"] in self.rows:
            raise stripe.InvalidRequestError("Product already exists.", "id")
        lookup_key = values.get("lookup_key")
        if lookup_key is None:
            return
        for row in self.rows.values():
            # Stripe holds a lookup key unique across *active* prices only: archiving one
            # frees the key, which is why an archived row may share it with a live one.
            if _read(row, "lookup_key") == lookup_key and _read(row, "active"):
                raise stripe.InvalidRequestError(
                    f"A price (`{row['id']}`) already uses that lookup key.", "lookup_key"
                )

    async def retrieve_async(self, object_id: str) -> StripeObject | None:
        return self.rows.get(object_id)

    async def list_async(self, params: dict) -> dict:
        wanted = params["lookup_keys"]
        found = [p for p in self.rows.values() if _read(p, "lookup_key") in wanted]
        # `limit` is honoured because the caller's choice of limit is the whole question when
        # two rows can share a key: asking for one row means the provider picks which.
        return {"data": found[: params["limit"]] if "limit" in params else found}
