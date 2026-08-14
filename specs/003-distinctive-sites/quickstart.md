# Quickstart: Distinctive Generated Sites

Validation scenarios proving the feature end-to-end. Offline checks run free and
credential-less; the live checks need `ANTHROPIC_API_KEY` and the docker-compose stack.

## Prerequisites

```bash
uv sync
uv run alembic upgrade head        # no new migration — must be a no-op for this feature
docker compose up                  # Postgres + Mailpit + web + worker (live scenarios only)
```

## 1. Offline gates (CI-equivalent, no credentials)

```bash
uv run ruff check
uv run pytest
```

What must hold inside that run:

- **Genericity scans** (`tests/genericity/`) pass over the grown prompt tree — the new
  `strategist/v3`, `web_builder/v4`, `web_builder_revise/v1`, `site_critic/v1`
  templates and the extended `_archetypes.jinja` render with no client token and no
  currency symbol (FR-021, US4 scenario 3).
- **Font library loader** validates `fonts/library.json`: unique ids, roles, every
  woff2 and every license file present (contract: [font-library.md](contracts/font-library.md)).
- **Grounding neutrality** (FR-004, SC-005): `extract_site_text(page)` equals
  `extract_site_text(embed_fonts(page, pairing))`, and the grounding set-difference is
  identical with and without fonts.
- **Design lint fixtures** (FR-011, US2): the deliberately tell-laden synthetic page
  reports every seeded rule; the clean synthetic page reports none.
- **Site handler paths** (US3, with `FunctionModel`): findings → exactly one revision,
  re-grounded and re-linted before it replaces the original; clean page → no revision
  call; render failure → stage completes, skip recorded; revision that lints worse or
  fails grounding → original kept, both outcomes in the design report.
- **Fail-fast** (FR-005): a brand doc naming an unknown pairing id fails the site
  stage before any model call, naming the id.
- **Size budget** (FR-006): a page pushed past 1 MiB with fonts embedded fails the
  build visibly.

## 2. Local visual check (one brief, real models)

```bash
uv run python scripts/submit_brief.py tests/fixtures/briefs/<fixture>.json
# approve the deploy in the console when the action reaches awaiting_approval
```

Expected:

- The run's artifacts include `site` (revision 0, possibly revision 1) **and** a
  `design_report` (JSON, schema: [design-report.schema.json](contracts/design-report.schema.json)),
  visible in the console's artifact inspection (US2 scenario 3).
- Open the site artifact offline (`scripts/preview_site.py`), with networking
  disabled in devtools: the brand doc's two faces render, zero network requests
  (US1 independent test, SC-004).
- The cost view shows `site_critic` rows (and `web_builder_revise` rows only if a
  revision ran) inside the run's one budget (FR-016, SC-003).

## 3. The two-fixture divergence check (US4/US5, SC-001)

Sample the plan stage, do not eyeball two runs — SC-001 is a property of a
distribution, and reading it off a single pair produced two conclusions that later
samples retracted.

```sh
docker exec epyhia-postgres-1 psql -U epyhia -d postgres -c "CREATE DATABASE epyhia_sample OWNER epyhia"
DATABASE_URL=…/epyhia_sample uv run alembic upgrade head
DATABASE_URL=…/epyhia_sample uv run python scripts/sample_directions.py --real --samples 4
```

A scratch database because the harness never truncates: each draw is its own run row.
Four draws per fixture costs about $2.90 and half an hour. The report — printed and
written to `samples/report.md` — gives the within-fixture distributions, the
cross-fixture ΔE matrix per palette slot, and the verdict: modal pairings disjoint,
modal archetypes disjoint, and modal palettes not same-direction under
`epyhia/design/colour.py`'s calibrated thresholds. This is a live-model property — it
belongs to the evidence pass, not CI. The thresholds themselves are unit-tested and do
run in CI.

## 4. Regression guard (SC-007)

Keep one pre-feature site artifact for a fixture brief. After the feature, re-run the
same brief: the design lint reports strictly fewer tells on the new page, and a
side-by-side eyeball can tell which page is which.

## Expected failure modes worth provoking

| Provocation | Expected |
|---|---|
| Brand doc with free-text face names (old prompt era) | Site stage fails fast: `unknown font id: …` — no silent system-face fallback |
| Chromium absent (e.g. bare CI runner) | Screenshot skipped, critique skipped, run completes; `design_report.screenshots.captured=false` |
| Critic returns unusable output | `critique.status="skipped"` with reason; unrevised page ships |
| Revision lints worse | `revision.outcome="discarded_worse"`, original deployed, both counts recorded |
| Revision comes back truncated (no page in it) | `revision.outcome="discarded_empty"`, original deployed — the existence check runs ahead of grounding and lint, which a stub would otherwise pass |
