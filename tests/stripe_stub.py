"""The Stripe resources the adapters touch, in memory.

Shared by the adapter tests and the US3 integration test so both drive the same stand-in:
no key, no network, no account, and nothing in CI that costs money (contracts/action-gate.md
§8).
"""


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
        self.rows: dict[str, dict] = {}

    async def create_async(self, params: dict) -> dict:
        obj = {
            **params,
            "id": f"cs_test_{len(self.rows)}",
            "url": f"https://checkout.stripe.test/{len(self.rows)}",
        }
        self.rows[obj["id"]] = obj
        return obj


class FakeResource:
    def __init__(self, *, assigns_ids: bool) -> None:
        self.rows: dict[str, dict] = {}
        self._assigns_ids = assigns_ids

    async def create_async(self, params: dict) -> dict:
        obj = {**params, "active": True}
        if self._assigns_ids:
            # Stripe names prices itself, which is why the price pair verifies through a
            # derived lookup key rather than an id.
            obj["id"] = f"price_{len(self.rows)}"
        self.rows[obj["id"]] = obj
        return obj

    async def retrieve_async(self, object_id: str) -> dict | None:
        return self.rows.get(object_id)

    async def list_async(self, params: dict) -> dict:
        wanted = params["lookup_keys"]
        return {"data": [p for p in self.rows.values() if p.get("lookup_key") in wanted]}
