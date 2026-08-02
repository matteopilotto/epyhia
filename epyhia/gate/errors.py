from epyhia.config import CredentialNotConfigured

__all__ = ["CredentialNotConfigured", "PreconditionFailed", "VerificationFailed"]


class VerificationFailed(Exception):
    """Raised by an adapter's verify() to trigger a retry, capped at 5 attempts (FR-041)."""


class PreconditionFailed(Exception):
    """Raised by the gate when a precondition fails in step 1, before any row is written."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
