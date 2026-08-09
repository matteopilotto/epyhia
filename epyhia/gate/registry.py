import uuid
from decimal import Decimal
from typing import Protocol, runtime_checkable

from epyhia.config import settings


class GateContext:
    """Carries what an adapter needs to reach the world and prove it happened.

    Deliberately does not carry an agent, a transcript, or a model (contracts/action-gate.md §3).
    """

    def __init__(
        self,
        run_id: uuid.UUID,
        brand_doc: dict | None = None,
        credentials=None,
        session=None,
    ) -> None:
        self.run_id = run_id
        self.brand_doc = brand_doc
        self.credentials = credentials if credentials is not None else settings
        # For the one verification the contract itself defines as a database read: a
        # checkout is proved by the order row, not by anything the processor says
        # (contracts/action-gate.md §4). Every other adapter leaves it untouched.
        self.session = session


@runtime_checkable
class Adapter(Protocol):
    action_type: str
    requires_approval: bool

    # Optional, and false unless an adapter says otherwise: the effect this action proves
    # cannot exist at the moment it is requested, so the gate leaves the row `verifying`
    # instead of burning its five attempts against a world that has not caught up yet.
    # Whatever later observes the effect re-drives `resume()`. It is not a way around
    # verification — there is still no `executing → succeeded` edge, and `succeeded` still
    # requires evidence.
    defer_verification: bool

    # What this provider bills EPYHIA for one such action. Declared by the adapter because
    # the adapter is what knows the provider; the gate only stamps it on the row (FR-050).
    # Every provider here bills zero, and that zero is stated rather than assumed: an adapter
    # that declares nothing leaves the column NULL, which reads as "never priced" instead of
    # quietly claiming the action was free.
    cost_usd: Decimal

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        """Reach the world. Returns the raw provider result.
        Raises CredentialNotConfigured(provider) if its credential is absent."""
        ...

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Prove it happened, independently of `result`. Returns evidence.
        Raises VerificationFailed to trigger a retry."""
        ...


_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    _REGISTRY[adapter.action_type] = adapter


def get_adapter(action_type: str) -> Adapter:
    return _REGISTRY[action_type]


def unregister(action_type: str) -> None:
    _REGISTRY.pop(action_type, None)


def clear() -> None:
    _REGISTRY.clear()
