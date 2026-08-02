import uuid
from typing import Protocol, runtime_checkable

from epyhia.config import settings


class GateContext:
    """Carries what an adapter needs to reach the world and prove it happened.

    Deliberately does not carry an agent, a transcript, or a model (contracts/action-gate.md §3).
    """

    def __init__(self, run_id: uuid.UUID, brand_doc: dict | None = None, credentials=None) -> None:
        self.run_id = run_id
        self.brand_doc = brand_doc
        self.credentials = credentials if credentials is not None else settings


@runtime_checkable
class Adapter(Protocol):
    action_type: str
    requires_approval: bool

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
