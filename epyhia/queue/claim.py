from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.tasks import Task

DEFAULT_LEASE_MINUTES = 2

# Per-`kind` lease interval (research.md R8): the video render task is the one legitimate
# long lease, so the interval is chosen by `kind` rather than global.
LEASE_MINUTES_BY_KIND: dict[str, int] = {
    "plan": 10,  # Strategist, Opus 5, extended thinking on by default
    "copy": 15,  # Marketer + Reviewer, up to two revisions (T076)
    "site": 15,  # Web Builder, streamed ~64K max_tokens
    "demand": 15,
    "money": 10,
    # Two cuts through headless Chrome, CPU-bound for minutes — the one legitimate long
    # lease, and the whole reason the interval is per-`kind` rather than global (R8).
    "video": 30,
}

_LEASE_CASE = "CASE kind {whens} ELSE interval '{default} minutes' END".format(
    whens=" ".join(
        f"WHEN '{kind}' THEN interval '{minutes} minutes'"
        for kind, minutes in LEASE_MINUTES_BY_KIND.items()
    ),
    default=DEFAULT_LEASE_MINUTES,
)

_CLAIM_SQL = text(
    f"""
    UPDATE tasks
    SET state = 'claimed',
        lease_expires_at = now() + ({_LEASE_CASE})
    WHERE id = (
        SELECT t.id
        FROM tasks t
        WHERE t.state = 'pending'
          AND (
            t.depends_on IS NULL
            OR NOT EXISTS (
                SELECT 1
                FROM unnest(t.depends_on) AS dep_id
                LEFT JOIN tasks d ON d.id = dep_id
                WHERE d.state IS DISTINCT FROM 'done'
            )
          )
          AND t.kind = COALESCE(:kind, t.kind)
        ORDER BY t.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, run_id, kind, state, depends_on, payload, lease_expires_at, attempts, error,
              created_at, updated_at
    """
)


async def claim_task(session: AsyncSession, *, kind: str | None = None) -> Task | None:
    """Claim one pending task whose dependencies are satisfied, in the single statement
    from research.md R8. `kind` narrows which queue a worker draws from; leaving it unset
    claims across all kinds, with the lease length still chosen per the claimed row's own
    `kind`.

    Returns a transient `Task` built from the `RETURNING` row — not attached to `session`,
    so the caller decides when and whether to persist further changes to it.
    """
    result = await session.execute(_CLAIM_SQL, {"kind": kind})
    row = result.mappings().first()
    if row is None:
        return None
    return Task(**dict(row))
