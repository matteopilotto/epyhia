import json
import re
from collections.abc import Iterable
from functools import cache
from pathlib import Path

BRIEFS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"


def fixture_paths() -> list[Path]:
    """Every brief fixture on disk.

    The tokens are derived from the fixtures rather than from a hand-maintained blocklist,
    so adding a fixture strengthens both scans automatically and a blocklist cannot rot the
    first time a fixture changes (research.md R10).
    """
    return sorted(BRIEFS_DIR.glob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def harvest(brief: dict) -> dict[str, set[str]]:
    """R10's token classes, one entry per class.

    Kept apart by name rather than merged into one set so that a scan which cannot apply a
    whole class says so by naming it — never by deleting tokens until it goes green.
    """
    products = brief["products"]
    return {
        "business_name": {brief["business_name"]},
        "tagline": {brief["tagline"]},
        "one_liner": {brief["one_liner"]},
        "product_name": {product["name"] for product in products},
        # As strings, because that is the form a hardcoded price would take in source.
        "price_minor": {str(product["price_minor"]) for product in products},
        "currency_code": {
            product[field]
            for product in products
            for field in ("currency_display", "currency_charge")
        },
        "voice_adjective": set(brief["voice"]["adjectives"]),
    }


def harvest_all() -> dict[str, set[str]]:
    """Every fixture's tokens, merged class by class."""
    merged: dict[str, set[str]] = {}
    for path in fixture_paths():
        for name, tokens in harvest(load(path)).items():
            merged.setdefault(name, set()).update(tokens)
    return merged


@cache
def _pattern(token: str) -> re.Pattern[str]:
    """Word boundaries as lookarounds, not `\\b`.

    Two reasons. A one-word voice adjective like a fixture's would otherwise match inside
    `directly` and `directory` and the lint would be red forever against ordinary English in
    source. And `\\b` is defined between a word and a non-word character, so a token that
    ends in a full stop — every tagline does — has no `\\b` after it and would never match at
    all.
    """
    return re.compile(rf"(?<!\w){re.escape(token)}(?!\w)")


def matches(text: str, tokens: Iterable[str]) -> list[str]:
    """Which of `tokens` appear in `text`, on word boundaries."""
    return sorted(token for token in tokens if _pattern(token).search(text))
