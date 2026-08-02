from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

_PRICING_PATH = Path(__file__).parent / "pricing.yaml"


class UnknownModel(Exception):
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"no pricing rate applies to model: {model_id}")


@dataclass(frozen=True)
class Rate:
    tier: str
    input: float
    output: float
    cache_write: float
    cache_read: float


def _load_models() -> dict:
    with _PRICING_PATH.open() as f:
        return yaml.safe_load(f)["models"]


_MODELS = _load_models()


def rate_for(model_id: str, at: datetime) -> Rate:
    """Select the rate row with the greatest `effective_from` not after `at`
    (research.md R9). A model id with no applicable row is a hard error —
    never a silent 0.00.
    """
    model = _MODELS.get(model_id)
    if model is None:
        raise UnknownModel(model_id)

    at_date = at.date()
    applicable = [r for r in model["rates"] if r["effective_from"] <= at_date]
    if not applicable:
        raise UnknownModel(model_id)

    chosen = max(applicable, key=lambda r: r["effective_from"])
    return Rate(
        tier=model["tier"],
        input=chosen["input"],
        output=chosen["output"],
        cache_write=chosen["cache_write"],
        cache_read=chosen["cache_read"],
    )
