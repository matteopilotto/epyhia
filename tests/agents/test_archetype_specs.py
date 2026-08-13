"""The archetype library is single-sourced, fully specified, and rendered by both prompts.

Two prompts read `_archetypes.jinja`, and the reason it is one file is that the Strategist
must not be able to select a page archetype the Web Builder does not implement. That holds
only while both templates render the same entries at the same depth, so the specs are read
out of the library itself and looked for in both renders — never spelled out again here.
"""

from jinja2 import Environment, FileSystemLoader

from epyhia.design.fonts import library
from epyhia.prompts_service import PROMPTS_DIR, prompt_service

# What the library held before the archetypes grew: four page archetypes, nine section
# layouts. FR-018 is a floor over these, not a count of what happens to be there today.
PAGE_ARCHETYPES_BEFORE = 4
SECTION_LAYOUTS_BEFORE = 9

SPEC_FIELDS = ("grid", "rhythm", "alternation", "hero_must_not", "signature")


def _library() -> object:
    """The library's own exported lists.

    `_archetypes.jinja` is imported, never rendered, so its `{% set %}` values are read the
    way the two prompts read them rather than parsed back out of prose.
    """
    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
    return env.get_template("_archetypes.jinja").make_module()


def _renders() -> dict[str, str]:
    return {
        "strategist/v3": prompt_service.render("strategist", "v3", fonts=library.faces),
        "web_builder/v4": prompt_service.render("web_builder", "v4"),
    }


def test_both_prompts_present_the_identical_archetype_set() -> None:
    """US4 scenario 1. A page archetype offered to one and not the other is a selection the
    builder cannot honour; a section layout is the same defect one level down."""
    lib = _library()
    ids = [item["id"] for item in lib.page_archetypes] + [
        item["id"] for item in lib.section_layouts
    ]

    for name, rendered in _renders().items():
        missing = [archetype_id for archetype_id in ids if f"`{archetype_id}`" not in rendered]
        assert not missing, f"{name} does not present: {missing}"


def test_every_page_archetype_carries_its_full_specification() -> None:
    """FR-017. `{id, for}` is a mood; the five spec lines are what makes two archetypes
    produce two different pages, so both prompts have to carry them verbatim."""
    lib = _library()
    renders = _renders()

    for item in lib.page_archetypes:
        for field in SPEC_FIELDS:
            value = item.get(field)
            assert value, f"{item['id']} has no `{field}`"
            for name, rendered in renders.items():
                assert value in rendered, f"{name} omits {item['id']}'s `{field}`"


def test_the_library_grew_by_the_required_margin() -> None:
    """US4 scenario 2 / FR-018: at least three new page archetypes and four new section
    layouts over the pre-feature set — two briefs cannot map onto the same four skeletons if
    there are not four skeletons to land on."""
    lib = _library()

    assert len(lib.page_archetypes) >= PAGE_ARCHETYPES_BEFORE + 3
    assert len(lib.section_layouts) >= SECTION_LAYOUTS_BEFORE + 4


def test_archetype_ids_are_unique_and_infrastructure_shaped() -> None:
    """Ids are the contract between the two prompts and the brand documents already written
    against them: kebab-free, lower snake, and never two of the same."""
    lib = _library()

    for group in (lib.page_archetypes, lib.section_layouts, lib.video_archetypes):
        ids = [item["id"] for item in group]
        assert len(ids) == len(set(ids)), f"duplicate archetype id in {ids}"
        assert all(archetype_id.replace("_", "").isalnum() for archetype_id in ids)
        assert all(archetype_id == archetype_id.lower() for archetype_id in ids)
