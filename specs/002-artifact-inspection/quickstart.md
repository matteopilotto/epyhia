# Quickstart: Artifact Inspection & Pack Download

**Feature**: `002-artifact-inspection` | validates the feature end-to-end, one scenario per
user story. Contracts referenced: [rest-api.md](./contracts/rest-api.md),
[pack-manifest.schema.json](./contracts/pack-manifest.schema.json); shapes:
[data-model.md](./data-model.md).

## Prerequisites

- `docker compose up` — Postgres, Mailpit, web, worker from `.env.example` defaults.
- `uv run alembic upgrade head` (no new migrations in this feature; the head is 001's).
- A run with artifacts. Either drive a brief through the deployed pipeline
  (`scripts/submit_brief.py` with a fixture from `tests/fixtures/briefs/`, approvals via
  the console) or seed artifacts directly for view-only checks — the feature is read-only,
  so seeded rows exercise it fully. Video scenarios need real `video`/`video_vertical`
  rows (a pipeline run, or two small mp4s seeded as those kinds).
- Console dev server: `cd console && npm run dev`, Auth0 configured as today.

## Automated verification

```bash
uv run ruff check
uv run pytest                       # includes tests/export/ and the router tests
cd console && npx tsc -b && npm run build
```

Expected: all pass with no API key and no Stripe/Vercel credentials in the environment —
this feature makes no model call and no gated action. `uv run pytest tests/genericity`
must stay green over the new console code (it scans `console/src`).

## US1 — Text deliverables render as what they are (P1)

1. Open `/runs/{runId}/artifacts` for a run with `copy`, `posts`, `email`, `video_props`.
2. Verify: copy shows labelled sections with headline and body prose; posts show one card
   per post with angle, body, character count equal to the body's length, and a working
   copy button (paste somewhere to confirm); email shows bold subject with muted preheader
   beside it and body below, subject and body separately copyable; video props show scenes
   in order with kind, lines, and each on-screen value formatted as money in the currency
   that value carries.
3. Toggle raw on any artifact → the exact stored content, unmodified.
4. Corrupt one seeded artifact's content (invalid JSON) → that artifact falls back to raw;
   the rest of the page is unaffected.
5. Deny clipboard permission in the browser → the copy control reports failure visibly.

## US2 — Site preview and video playback (P2)

1. Open the `site` artifact → it renders inside the sandboxed preview; toggle
   desktop/mobile widths; open-in-new-tab shows the same content. In devtools, confirm the
   preview frame has an opaque origin (sandbox without `allow-same-origin`).
2. Open each video entry → both cuts play to completion with native controls, the vertical
   cut in a phone-aspect frame. The view stays responsive while bytes load.
3. Download a video → file arrives named from `artifact.path`; `shasum -a 256` matches the
   artifact's `sha256`.
4. `curl` the content endpoint without a Bearer token → `401`; with one → bytes whose hash
   matches the row (FR-007, byte-identity contract).

## US3 — Pack download (P3)

1. Click the pack download on a completed run → one `pack-{run_id}.zip` arrives and opens
   with standard tools.
2. Verify against the manifest: every listed `sha256` matches its extracted file
   (`shasum -a 256`), every archive file except `manifest.json` is listed, `record` hashes
   equal the API's artifact `sha256` values (SC-004).
3. Companions: `deliverables/*.md` exist for the structured text kinds and contain the
   same substantive content as their record files, nothing more (FR-011).
4. Flagged run: with a flagged latest revision, the record sits under `flagged/` with its
   `.violations.json`, absent from `deliverables/` (FR-010).
5. In-progress or empty run: the archive contains exactly what exists; an artifact-less
   run yields a valid archive with an empty manifest, not an error.

## US4 — Inline violation marking (P4)

1. Seed a flagged artifact whose violation `quote` occurs verbatim in its content (twice,
   ideally) → every occurrence is visibly marked in the rendered view; the itemised list
   still shows.
2. Seed one whose quote does not occur verbatim → no mark, no error, list intact.

## US5 — Revision grouping (P5)

1. Seed one deliverable kind at revisions 0..2 → the view shows one entry, revision 2 by
   default.
2. Switch to revision 0 → that revision's content, grounding status, and violations render
   — not the group's latest.

## Genericity spot-check (SC-006)

Run the second brief fixture through the system (or seed its outputs) and repeat US1–US3:
every displayed value — currencies, prices, names — must trace to that run's artifacts,
with zero code change. `uv run pytest tests/genericity` is the mechanical half of the same
claim.
