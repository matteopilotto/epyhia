from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, Undefined

from epyhia.ingest.normalise import _CURRENCY_SYMBOLS
from tests.genericity.harvest import fixture_paths, harvest, harvest_all, load, matches

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

SENTINEL = "<<sentinel>>"


class _Sentinel(Undefined):
    """One recursive stand-in for every value a template asks for.

    Attribute access, item access and iteration all yield it again, so a template renders
    all the way through its conditionals and loops with no client data in the context at
    all — and its string form is a fixed marker that belongs to no client.

    `PromptService` builds its own Environment with `StrictUndefined` and keeps it: raising
    on a missing value is a production guard against a prompt quietly rendering half its
    context away. Relaxing that to make this test easier would trade a real protection for a
    convenience, so the lint brings its own Environment instead.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> "_Sentinel":
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __getitem__(self, key: object) -> "_Sentinel":
        return self

    def __iter__(self):
        return iter((self,))

    def __len__(self) -> int:
        return 1

    def __str__(self) -> str:
        return SENTINEL


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=_Sentinel,
        keep_trailing_newline=True,
    )


def prompt_files() -> list[Path]:
    """Every file under `prompts/`, `_archetypes.jinja` included.

    The raw scan is the stronger of R10's two passes — a template that does not contain the
    token cannot render it — and the import library is as capable of naming a client as an
    agent's own template is.
    """
    return sorted(path for path in PROMPTS_DIR.rglob("*") if path.is_file())


def template_names() -> list[str]:
    """Every `<agent>/<version>.jinja` on disk, not only `active_version()`.

    A superseded v1 is still a tracked prompt and still rendered by any run pinned to it.
    `_archetypes.jinja` has no `<agent>/<version>` path of its own and reaches the rendered
    output through the imports in these.
    """
    return sorted(f"{path.parent.name}/{path.name}" for path in PROMPTS_DIR.glob("*/v*.jinja"))


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda path: path.stem)
def test_every_fixture_yields_tokens(path: Path) -> None:
    """A fixture with a placeholder name weakens both scans silently (R10), so every class
    has to carry something — not merely the harvest as a whole."""
    empty = sorted(name for name, tokens in harvest(load(path)).items() if not tokens)
    assert not empty, f"{path.name} harvests nothing for: {empty}"


@pytest.mark.parametrize(
    "path", prompt_files(), ids=lambda path: str(path.relative_to(PROMPTS_DIR))
)
def test_no_client_token_in_the_prompt_tree(path: Path) -> None:
    tokens = set().union(*harvest_all().values())
    found = matches(path.read_text(), tokens)
    assert not found, f"{path.relative_to(PROMPTS_DIR)} names client data from a fixture: {found}"


@pytest.mark.parametrize("name", template_names())
def test_no_client_token_survives_an_empty_render(name: str) -> None:
    """The pass that catches what the raw scan cannot: a default inlined in a filter or a
    conditional, which is client data the template only produces once rendered."""
    rendered = _environment().get_template(name).render()

    found = matches(rendered, set().union(*harvest_all().values()))
    assert not found, f"{name} renders client data from a fixture: {found}"

    # The symbols the normaliser understands — a template naming money at all is naming
    # something only the brief may decide (research.md R6).
    symbols = sorted(symbol for symbol in _CURRENCY_SYMBOLS if symbol in rendered)
    assert not symbols, f"{name} renders a currency symbol: {symbols}"
