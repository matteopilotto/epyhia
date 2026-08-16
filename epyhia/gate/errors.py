import uuid

from epyhia.config import CredentialNotConfigured

__all__ = [
    "ActionInProgress",
    "ActionTerminallyFailed",
    "CredentialNotConfigured",
    "PreconditionFailed",
    "VerificationFailed",
]


class VerificationFailed(Exception):
    """Raised by an adapter's verify() to trigger a retry, capped at 5 attempts (FR-041)."""


class PreconditionFailed(Exception):
    """Raised by the gate when a precondition fails in step 1, before any row is written."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ActionTerminallyFailed(Exception):
    """The keyed row already ended `failed` or `denied`, and a request must say so.

    Returning the stored result here is what manufactured false greens (T147): every caller
    ignores `request()`'s return value, so a re-queued task completed and the worker wrote
    `done` over an unproved effect — the exact inversion of the gate's promise. Raised, so
    the task lands `failed` naming the stuck action, which is the state the re-verify
    affordance (T146) acts on. Only `succeeded` short-circuits silently.
    """

    def __init__(self, action_id: uuid.UUID, state: str) -> None:
        self.action_id = action_id
        self.state = state
        super().__init__(f"action {action_id} already ended {state}")


class ActionInProgress(Exception):
    """The keyed row exists and is owned by an execution that has not finished.

    The caller cannot proceed, and must not re-request: a stuck row is unstuck through
    `resume()`, never by a second `request()` racing the first (§7.2).

    Raised rather than returned. A caller handed a result-shaped dict without an `evidence`
    key reaches straight past the distinction into a `KeyError` — which is what
    `wire_catalogue` did to a run whose worker was killed mid-verify.
    """

    def __init__(self, action_id: uuid.UUID, state: str) -> None:
        self.action_id = action_id
        self.state = state
        super().__init__(f"action {action_id} is already {state}")
