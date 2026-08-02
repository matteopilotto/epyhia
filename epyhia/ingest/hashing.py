import hashlib
import json


def canonical_json(payload: dict) -> str:
    """Sorted keys, no insignificant whitespace, so key ordering is never a source of
    false distinctness (FR-002)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def content_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
