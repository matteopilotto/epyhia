import json
import re
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "specs" / "001-epyhia-agency" / "contracts"
RUBRIC_PATH = REPO_ROOT / "eval" / "rubric.json"
GRADING_TABLE = CONTRACTS / "grading-rubric.md"
SCHEMA_PATH = CONTRACTS / "eval-rubric.schema.json"

# `| `<id>` | <area> | <points> |` — the shape of every row in the area-id table.
_ROW = re.compile(r"^\|\s*`([a-z-]+)`\s*\|[^|]*\|\s*(\d+)\s*\|\s*$", re.MULTILINE)
_TOTAL = re.compile(r"^\*\*Total:\s*(\d+)\.\*\*", re.MULTILINE)
_SECTION_2 = re.compile(r"^## 2 · Area ids$(.*?)^## ", re.MULTILINE | re.DOTALL)


def budgets() -> dict[str, int]:
    """The six area ids and their point budgets, read out of §2 of the grading contract.

    Parsed rather than restated: a copy of the table inside this file would be a copy
    grading a copy, and the one thing this check exists to catch — an area quietly missing
    from `rubric.json` — is exactly what a restatement would carry along with it (FR-067).
    """
    section = _SECTION_2.search(GRADING_TABLE.read_text())
    assert section, f"{GRADING_TABLE.name} has no '## 2 · Area ids' section"
    return {area: int(points) for area, points in _ROW.findall(section.group(1))}


def rubric() -> dict:
    return json.loads(RUBRIC_PATH.read_text())


def test_the_grading_table_parses() -> None:
    """The guard on every other assertion here: a regex that silently matched nothing would
    make all of them pass vacuously."""
    parsed = budgets()
    assert len(parsed) == 6, f"expected six areas in {GRADING_TABLE.name}, parsed {parsed}"

    stated = _TOTAL.search(GRADING_TABLE.read_text())
    assert stated, f"{GRADING_TABLE.name} states no total"
    assert sum(parsed.values()) == int(stated.group(1))


def test_rubric_validates_against_the_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.Draft202012Validator(schema).validate(rubric())


def test_every_area_named_is_one_of_the_six() -> None:
    unknown = sorted({check["area"] for check in rubric()["checks"]} - set(budgets()))
    assert not unknown, f"rubric.json names areas the grading table does not: {unknown}"


def test_every_one_of_the_six_areas_is_covered() -> None:
    """Three of the six are entirely human-judged and are the easiest to leave out — an
    omitted area is the failure the tracked table exists to catch."""
    missing = sorted(set(budgets()) - {check["area"] for check in rubric()["checks"]})
    assert not missing, f"rubric.json covers no check for: {missing}"


@pytest.mark.parametrize("area", sorted(budgets()))
def test_area_points_reconcile(area: str) -> None:
    """Per area, not merely in total, so a surplus in one cannot mask a deficit in another.

    `points` on an `evidence` row is that area's budget for a judgement, not a score the
    evaluation awarded itself — the schema forbids a `score` field on those rows and the
    report renders none.
    """
    totals = Counter()
    for check in rubric()["checks"]:
        totals[check["area"]] += check["points"]
    assert totals[area] == budgets()[area]
