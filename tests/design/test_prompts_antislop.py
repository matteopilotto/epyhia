"""The two prompts that decide how a page looks say the anti-sameness part out loud.

FR-019 and FR-020 are prompt properties, and a prompt property is only real once it survives
a render — an instruction inside a conditional that never fires is an instruction the model
never reads. The divergence itself (two briefs, two genuinely different directions) is a
live-model claim and belongs to the evidence pass, not here; what CI can hold is that the
words are on the page.

The other half of FR-021 — that neither updated template names client data — is the
genericity suite's job and is left there: it scans every version of every prompt with a
sentinel context, and a weaker copy of that scan here would only be a second thing to keep
green.
"""

from epyhia.design.fonts import library
from epyhia.prompts_service import prompt_service

# The six tells the lint counts, named in the builder's own prompt. Phrases rather than rule
# ids: the model is told what the move looks like, and the lint measures the same move.
NAMED_TELLS = (
    "default font stack",
    "gradient-on-dark hero",
    "Cookie-cutter card rows",
    "One border radius everywhere",
    "accent on everything",
    "timid type scale",
    "Sections of identical height",
)


def _builder() -> str:
    return prompt_service.render("web_builder", "v4")


def _strategist() -> str:
    return prompt_service.render("strategist", "v3", fonts=library.faces)


def test_the_builder_prompt_names_every_tell() -> None:
    """FR-020. "Make it look designed" is not an instruction; the specific moves are."""
    rendered = _builder()

    missing = [tell for tell in NAMED_TELLS if tell not in rendered]
    assert not missing, f"web_builder/v4 does not name: {missing}"


def test_the_builder_prompt_forbids_a_stand_in_for_the_given_faces() -> None:
    """The v3 instruction this replaced offered a system font stack as a legitimate choice,
    which is the single most visible generic tell. The replacement has to close it, not
    merely discourage it (research R10)."""
    rendered = _builder()

    assert "system stack standing in" in rendered
    assert "use a system font stack that carries the same character" not in rendered


def test_the_strategist_prompt_asks_for_divergence_before_commitment() -> None:
    """FR-019. Three directions drafted, one committed to — and nothing said about recording
    the other two, because there is nowhere in the brand document to record them."""
    rendered = _strategist()

    assert "at least three genuinely distinct directions" in rendered
    assert "commit to exactly one" in rendered
