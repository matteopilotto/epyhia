import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import memo

_BASE = {
    "agent": "web_builder",
    "model_id": "claude-sonnet-5",
    "prompt_version": "v1",
    "brand_doc_version": 1,
    "scoped_inputs": {"a": 1},
}


def test_key_is_stable_across_calls() -> None:
    assert memo.memo_key(**_BASE) == memo.memo_key(**_BASE)


@pytest.mark.parametrize(
    "field, value",
    [
        ("prompt_version", "v2"),
        ("brand_doc_version", 2),
        ("scoped_inputs", {"a": 2}),
        ("model_id", "claude-opus-5"),
        ("agent", "marketer"),
    ],
)
def test_every_component_of_the_key_moves_it(field: str, value: object) -> None:
    """`prompt_version` and `brand_doc_version` most of all: edit the brand doc and re-run,
    and the §5.3 demo must actually regenerate rather than serve a stale hit (FR-012)."""
    assert memo.memo_key(**{**_BASE, field: value}) != memo.memo_key(**_BASE)


@pytest.mark.asyncio
async def test_a_miss_is_none_rather_than_an_error(db_session: AsyncSession) -> None:
    """A miss is never a decision — it costs a model call and nothing else (FR-048)."""
    assert await memo.read(db_session, memo.memo_key(**_BASE)) is None


@pytest.mark.asyncio
async def test_write_then_read_replays_the_stored_result(db_session: AsyncSession) -> None:
    key = memo.memo_key(**_BASE)
    await memo.write(db_session, key, {"html": "<main></main>"})
    assert await memo.read(db_session, key) == {"html": "<main></main>"}


@pytest.mark.asyncio
async def test_a_second_write_under_one_key_does_not_raise(db_session: AsyncSession) -> None:
    """Two workers memoising the same inputs are memoising the same result; the first one
    there keeps its row and there is nothing to reconcile."""
    key = memo.memo_key(**_BASE)
    await memo.write(db_session, key, {"html": "<main></main>"})
    await memo.write(db_session, key, {"html": "<main></main>"})
    assert await memo.read(db_session, key) == {"html": "<main></main>"}
