from decimal import Decimal

from epyhia.gate.errors import VerificationFailed
from epyhia.gate.registry import GateContext


class FakeAdapter:
    """Zero agents, zero credentials, zero network — every gate behaviour is exercisable
    against this one adapter (contracts/action-gate.md §8)."""

    def __init__(
        self,
        action_type: str = "fake_action",
        *,
        requires_approval: bool = False,
        fail_execute: bool = False,
        always_fail_verify: bool = False,
        cost_usd: Decimal = Decimal("0"),
    ) -> None:
        self.action_type = action_type
        self.requires_approval = requires_approval
        # Settable so the roll-up into `runs.spend_usd` is exercisable with a cost that is
        # actually non-zero — every real provider here bills nothing, so nothing else can.
        self.cost_usd = cost_usd
        self.fail_execute = fail_execute
        self.always_fail_verify = always_fail_verify
        self.execute_calls: list[dict] = []
        self.verify_calls: list[dict] = []
        # What verify() was handed as `result`, so a test can prove a re-drive read the
        # stored execute() return rather than an empty dict (T146).
        self.verify_results: list[dict] = []

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        self.execute_calls.append(request)
        if self.fail_execute:
            raise RuntimeError("fake adapter: execute failed")
        return {"ok": True}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        self.verify_calls.append(request)
        self.verify_results.append(result)
        if self.always_fail_verify:
            raise VerificationFailed("fake adapter: verify always fails")
        return {"status": "ok"}
