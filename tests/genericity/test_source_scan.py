from pathlib import Path

import pytest

from tests.genericity.harvest import harvest_all, matches

REPO_ROOT = Path(__file__).resolve().parents[2]

# The three trees the task names, and no more. `eval/` and this tree are deliberately not
# here: both read the fixtures by construction, so scanning them would flag the harvest
# itself. Their genericity is a review question, not a grep one.
TREES = ("epyhia", "console/src", "video/src")

# Token classes this scan does not apply, each by an explicit rule. A class is excluded here
# by name or not at all — never by quietly dropping tokens from the harvest until the build
# goes green, which would weaken every scan at once and leave no record of the decision.
EXCLUDED_CLASSES = {
    "currency_code": (
        "An ISO 4217 code in source is the unit label on money the system itself moves, not "
        "a fact read from a brief: the normaliser's symbol and word tables, the cost "
        "ledger's own denomination in pricing.yaml, and the console's rendering of a spend "
        "figure. A brief naming a different currency changes none of them, so a match here "
        "carries no information. The prompt scan keeps the class, where a template naming a "
        "currency is choosing one on behalf of a client who was never asked."
    ),
}


def scanned_classes() -> dict[str, set[str]]:
    return {
        name: tokens
        for name, tokens in harvest_all().items()
        if name not in EXCLUDED_CLASSES
    }


def source_files() -> list[Path]:
    return sorted(
        path
        for tree in TREES
        for path in (REPO_ROOT / tree).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def test_every_excluded_class_is_a_real_token_class() -> None:
    """A rule naming a class the harvest no longer produces excludes nothing while still
    reading like a considered exemption."""
    unknown = sorted(set(EXCLUDED_CLASSES) - set(harvest_all()))
    assert not unknown, f"exclusion rules name no such token class: {unknown}"


@pytest.mark.parametrize(
    "path", source_files(), ids=lambda path: str(path.relative_to(REPO_ROOT))
)
def test_no_client_token_in_source(path: Path) -> None:
    """The smaller companion to the prompt lint (research.md R10). Scanning source for
    client data is not relied on — f-strings make it unmaintainable in general — but a
    business name, a price or a voice adjective reaching a module is exactly the violation
    that is invisible while only one client has ever run through the system."""
    found = {
        name: hits
        for name, tokens in scanned_classes().items()
        if (hits := matches(path.read_text(errors="ignore"), tokens))
    }
    assert not found, f"{path.relative_to(REPO_ROOT)} names client data from a fixture: {found}"
