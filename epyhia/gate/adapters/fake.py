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
    ) -> None:
        self.action_type = action_type
        self.requires_approval = requires_approval
        self.fail_execute = fail_execute
        self.always_fail_verify = always_fail_verify
        self.execute_calls: list[dict] = []
        self.verify_calls: list[dict] = []

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        self.execute_calls.append(request)
        if self.fail_execute:
            raise RuntimeError("fake adapter: execute failed")
        return {"ok": True}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        self.verify_calls.append(request)
        if self.always_fail_verify:
            raise VerificationFailed("fake adapter: verify always fails")
        return {"status": "ok"}
