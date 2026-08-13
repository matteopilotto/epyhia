# Tasks: Artifact Inspection & Pack Download

**Input**: Design documents from `/specs/002-artifact-inspection/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Backend tests are REQUIRED — research R10 defines them as the verification bar
(pure export-module tests plus httpx ASGI router tests, keyless CI). The console has no JS
test runner and none is introduced (Constitution VII); console verification is
`npx tsc -b && npm run build` plus the quickstart's per-story scenarios.

**Organization**: Tasks are grouped by user story. US1 is console-only; US2 adds the
content endpoint; US3 adds the export module and pack endpoint; US4 and US5 refine the
console views. Each story is independently completable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US5)

---

## Phase 1: Setup

**Purpose**: Branch and a verified-green starting point. No scaffolding is needed — the
backend (`epyhia/`) and console (`console/`) exist; this feature adds files within them.

- [x] T001 Create branch `002-artifact-inspection` off `main` (per spec.md's feature branch; never implement on `main`)
- [x] T002 Confirm green baseline before any change: `uv run ruff check`, `uv run pytest`, and `cd console && npx tsc -b && npm run build` all pass with no API key and no Stripe/Vercel credentials in the environment

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The one shared extraction other phases build on. Everything else in this
feature is story-scoped.

- [x] T003 Extract `formatAmount` from `console/src/routes/approvals.tsx` into new `console/src/lib/format.ts` (keeping its `Intl.NumberFormat` + minor-unit-exponent behavior exactly — no two-decimal guess, research R7) and update `console/src/routes/approvals.tsx` to import it; verify `npx tsc -b && npm run build` still passes

**Checkpoint**: Foundation ready — user story phases can begin.

---

## Phase 3: User Story 1 - Read each deliverable in its natural form (Priority: P1) 🎯 MVP

**Goal**: Each text deliverable renders as what it is — copy as a sectioned document,
posts as cards with angle/body/char count/copy button, email as an inbox-style preview
with separately copyable subject and body, video props as a scene-by-scene storyboard
with money formatted from the artifact's own currency — with a raw toggle on every
artifact and raw fallback on any parse failure (FR-001, FR-002, FR-003, FR-014).

**Independent Test**: Seed (or run) a run with `copy`, `posts`, `email`, and
`video_props` artifacts; open `/runs/{runId}/artifacts`; confirm each kind renders in its
described form, copy-to-clipboard puts the expected text on the clipboard with visible
success/failure feedback, the raw toggle shows the exact stored content, and a corrupted
artifact falls back to raw without affecting the rest of the page (quickstart § US1).

### Implementation for User Story 1

- [x] T004 [P] [US1] Create `console/src/components/artifacts/guards.ts` — hand-rolled shape guards (no schema library, R6) over `JSON.parse` for the four parse targets in data-model.md: copy `{ sections: [{ section, headline, body }] }`, posts `{ posts: [{ angle, body }] }`, email `{ subject, preheader, body }`, video_props assembled shape with `content.scenes[].values[]` carrying `label`/`amount_minor`/`currency`; each guard returns the typed value or `null` (never throws), `null` meaning raw fallback
- [x] T005 [P] [US1] Create `console/src/components/artifacts/CopyDoc.tsx` — sectioned document renderer: each section with its label, headline, and body as readable prose (acceptance scenario 1)
- [x] T006 [P] [US1] Create `console/src/components/artifacts/PostCards.tsx` — one card per post showing angle, body, a character count equal to the body's length, and a copy-to-clipboard control using `navigator.clipboard.writeText` with visible success AND failure feedback (denied clipboard access must not report silent success — edge case)
- [x] T007 [P] [US1] Create `console/src/components/artifacts/EmailPreview.tsx` — inbox-style preview: subject bold with preheader in muted text beside it (the mail-client pairing), body below; subject and body each copyable in one click with the same visible feedback rule as T006
- [x] T008 [P] [US1] Create `console/src/components/artifacts/Storyboard.tsx` — ordered scene list showing each scene's kind and lines, and each `OnScreenValue` formatted as money via `formatAmount` from `console/src/lib/format.ts` using the `currency` carried by that value in the artifact — no hardcoded currency, symbol, or locale (FR-003, Constitution I)
- [x] T009 [US1] Rework `console/src/routes/artifacts.tsx`: renderer dispatch keyed on `artifact.kind` (the system's closed vocabulary) mapping copy/posts/email/video_props to T005–T008 through T004's guards; a rendered/raw toggle on every artifact whose raw side shows the stored `content` verbatim in a `<pre>` (FR-002); guard failure or unknown kind falls back to raw for that artifact only, the rest of the page unaffected (FR-014); keep the existing itemised violation list rendering (depends on T004–T008)
- [x] T010 [US1] Verify US1: `cd console && npx tsc -b && npm run build` passes; `uv run pytest tests/genericity` stays green over the new console code; walk quickstart § US1 steps 1–5 (rendered forms, copy paste-check, raw verbatim, corrupt-content fallback, denied-clipboard feedback)

**Checkpoint**: US1 fully functional — the MVP. Text deliverables are inspectable without
reading JSON.

---

## Phase 4: User Story 2 - Preview the site and watch both video cuts (Priority: P2)

**Goal**: Binary artifacts become viewable: the site renders in a sandboxed in-console
preview with width toggle and open-in-new-tab, both video cuts play side by side in
native players (vertical in a phone-aspect frame), and any single artifact downloads with
a sensible filename — all delivered over one new authenticated content endpoint so auth
stays on the single Bearer path (FR-004, FR-005, FR-006, FR-007).

**Independent Test**: On a run with `site`, `video`, and `video_vertical` artifacts,
confirm the site preview renders at both widths with an opaque origin and opens in a new
tab; both videos play to completion; a downloaded video's `shasum -a 256` matches the
row's `sha256`; `curl` of the content endpoint returns 401 without a Bearer token and
byte-identical content with one (quickstart § US2).

### Tests for User Story 2

- [x] T011 [P] [US2] Create `tests/integration/test_us_artifact_views.py` with content-endpoint tests over seeded artifact rows via httpx ASGI + `app.dependency_overrides[require_operator]` (the `tests/integration/test_us4_brand_doc_edit.py` pattern): 200 body is byte-identical to the row (`sha256(body) == artifact.sha256`) for a text and a binary artifact, `Content-Type` equals the stored `content_type`, `Content-Disposition` is `attachment; filename="<artifact.path>"`, unknown id → 404 in the standard error shape, no auth → 401; confirm the tests fail before T012

### Implementation for User Story 2

- [x] T012 [US2] Add `GET /artifacts/{artifact_id}/content` to `epyhia/api/routers/artifacts.py` per contracts/rest-api.md: return `artifact.bytes` unmodified with the stored `content_type` and `Content-Disposition: attachment; filename="<artifact.path>"`; same operator auth dependency as the existing routes, no second auth path (FR-007); T011 passes
- [x] T013 [P] [US2] Create `console/src/lib/content.ts` — authenticated content helpers: fetch the content endpoint with the same Auth0 Bearer header as every other call (per `console/src/lib/api.ts`; no token in query strings, R1), wrap bytes in a `Blob`, return object URLs plus a revoke helper for unmount cleanup, and a download helper that saves via an anchor named from `artifact.path` (FR-006)
- [x] T014 [US2] Create `console/src/components/artifacts/SitePreview.tsx` — `<iframe sandbox="allow-scripts">` deliberately WITHOUT `allow-same-origin` (opaque origin — the isolation FR-004 requires, R2) over the site's blob URL; desktop/mobile container-width toggle; open-in-new-tab opens a small static console-authored wrapper document embedding the same sandboxed iframe so the opaque origin holds top-level too (depends on T013)
- [x] T015 [P] [US2] Create `console/src/components/artifacts/VideoPlayer.tsx` — each cut in a native `<video controls>` element fed by a blob URL under its own artifact entry, `video_vertical` inside a 9:16 phone-aspect frame; asynchronous fetch with a visible loading state so the view never freezes during transfer (edge case); revoke object URLs on unmount (R3; depends on T013)
- [x] T016 [US2] Wire `site`, `video`, and `video_vertical` kinds into the dispatch in `console/src/routes/artifacts.tsx` (T014/T015) and add a per-artifact download control using T013's download helper on every artifact including binary ones (FR-006) (depends on T009, T013–T015)
- [x] T017 [US2] Verify US2: `uv run pytest tests/integration/test_us_artifact_views.py` passes; console builds; walk quickstart § US2 steps 1–4 (opaque-origin check in devtools, playback to completion, download hash match, curl 401/byte-identity)

**Checkpoint**: US1 and US2 both work — every artifact kind is now inspectable in the
console.

---

## Phase 5: User Story 3 - Download the whole pack in one action (Priority: P3)

**Goal**: One click downloads `pack-{run_id}.zip`: latest revision per kind under each
artifact's own filename, a hash-carrying `manifest.json`, flagged artifacts segregated
under `flagged/` with their itemised violations, and mechanical Markdown companions for
the structured text deliverables — assembled in memory per request, never stored
(FR-008, FR-009, FR-010, FR-011).

**Independent Test**: Download the pack for a completed run, open it with standard tools,
and verify every manifest `sha256` matches its extracted file, `record` hashes equal the
rows' stored hashes, companions carry identical substantive content to their records,
flagged artifacts sit only under `flagged/` with their `.violations.json`, and an
artifact-less run yields a valid archive with an empty manifest (quickstart § US3).

### Tests for User Story 3

- [x] T018 [P] [US3] Make the minor-unit exponent table in `epyhia/ingest/normalise.py` importable (`_MINOR_EXPONENT` per research R7) with no behavior change to ingest; `uv run pytest` stays green
- [x] T019 [P] [US3] Create `tests/export/test_companions.py` — pure-function tests, zero credentials/agents/network: copy/posts/email/video_props records render to Markdown whose every string is a field of the record (FR-011: no content introduced); storyboard money renders `amount_minor` + `currency` through the exponent table including a zero-decimal currency case; content that fails to parse as its kind's shape yields NO companion (skip, never fabricate); confirm failing before T021
- [x] T020 [P] [US3] Create `tests/export/test_archive.py` — pure-function tests: layout matches data-model.md (`manifest.json`, `deliverables/<artifact.path>` + `<stem>.md`, `flagged/<artifact.path>` + `<stem>.violations.json` + `<stem>.md`); "latest" is max `revision` per `kind`; a flagged latest revision ships under `flagged/` even when an earlier revision was clean, and never under `deliverables/`; manifest entries match contracts/pack-manifest.schema.json with `record` hashes copied from the rows and `companion`/`violations` hashes computed over emitted bytes, every hash matching its member's bytes; a run with no artifacts yields a valid archive with an empty `files` list; confirm failing before T022

### Implementation for User Story 3

- [x] T021 [US3] Create `epyhia/export/__init__.py` and `epyhia/export/companions.py` — mechanical Markdown rendered by parsing stored content through the same Pydantic models the Marketer emits (`LandingCopy`, `SocialPosts`, `LaunchEmail` from `epyhia/agents/marketer.py`; video_props through its assembled dict shape): copy → label/headline/body sections, posts → one section per post with angle and body, email → subject/preheader/body, video props → ordered scenes with kind, lines, and money via T018's exponent table; parse failure → no companion (R5); T019 passes
- [x] T022 [US3] Create `epyhia/export/archive.py` — pure zip assembly over `Artifact` rows with stdlib `zipfile` (no new dependency, R4): select latest revision per kind, segregate by `grounding_status`, write record bytes verbatim, attach companions from T021 and `<stem>.violations.json` for flagged items, and emit `manifest.json` (`run_id`, `generated_at` UTC ISO 8601, `files[]` with `archive_path`/`kind`/`role`/`revision`/`grounding_status`/`content_type`/`sha256`); T020 passes (depends on T021)
- [x] T023 [US3] Extend `tests/integration/test_us_artifact_views.py` with pack-endpoint tests over seeded rows: 200 returns `application/zip` with `Content-Disposition: attachment; filename="pack-{run_id}.zip"`, the archive opens with `zipfile` and matches its manifest, flagged segregation holds end-to-end, an artifact-less run returns a valid empty-manifest archive not an error, unknown run → 404, no auth → 401; confirm failing before T024
- [x] T024 [US3] Create `epyhia/api/routers/export.py` (module named to avoid colliding with `epyhia/queue/handlers/pack.py`; route path keeps the spec's name) — `GET /runs/{run_id}/pack` querying the run's artifacts and returning T022's in-memory zip; register the router in the FastAPI app alongside the existing operator routers, same auth dependency; T023 passes (depends on T022)
- [x] T025 [US3] Add the pack download control to `console/src/routes/artifacts.tsx` — single action fetching `/runs/{id}/pack` with the Bearer header (via `console/src/lib/content.ts` if US2 has landed; otherwise the same authenticated-fetch-to-blob inline) and saving `pack-{run_id}.zip`; when the run has no artifacts the view says so and the control is disabled with an explanation, never an opaque error (edge case) (depends on T009)
- [x] T026 [US3] Verify US3: `uv run ruff check` and `uv run pytest` pass (tests/export/ and the router tests included, keyless); console builds; walk quickstart § US3 steps 1–5 (`shasum -a 256` manifest verification, companion fidelity, flagged segregation, empty run)

**Checkpoint**: All three core stories work — inspect everything, download anything,
hand off the pack.

---

## Phase 6: User Story 4 - See what is wrong, on the words that are wrong (Priority: P4)

**Goal**: Where a violation's `quote` appears verbatim in rendered text, every occurrence
is visibly marked inline in the copy sections, post bodies, email fields, and storyboard
lines — on top of the itemised list, which remains in all cases; a quote with no verbatim
occurrence degrades to the list alone without error (FR-012).

**Independent Test**: Seed a flagged artifact whose violation quotes a string occurring
(twice) in its content and confirm every occurrence is marked in the rendered view with
the list intact; seed one whose quote does not occur verbatim and confirm no mark, no
error (quickstart § US4).

### Implementation for User Story 4

- [x] T027 [P] [US4] Create `console/src/lib/highlight.ts` — pure helper: given a text string and the set of violation `quote` strings for the artifact revision in view, split on exact substring occurrences (no fuzzy or normalised matching, R8) and wrap each match in a visible `<mark>`-styled span; a quote with zero occurrences marks nothing and raises nothing
- [x] T028 [US4] Apply T027 inside the text renderers — `console/src/components/artifacts/CopyDoc.tsx` (headlines and bodies), `PostCards.tsx` (post bodies), `EmailPreview.tsx` (subject, preheader, body), `Storyboard.tsx` (scene lines) — driven by the selected revision's own `violations[].quote`; the itemised violation list in `console/src/routes/artifacts.tsx` remains rendered in all cases; a flagged `video_props` storyboard still renders with its marks, never hidden (edge case) (depends on T005–T008, T027)
- [x] T029 [US4] Verify US4: console builds; walk quickstart § US4 (every occurrence marked including duplicates; non-matching quote → list-only degradation, no error)

**Checkpoint**: Violations are visible in context, not just in a list.

---

## Phase 7: User Story 5 - Revisions grouped, latest first (Priority: P5)

**Goal**: One entry per deliverable kind, showing the latest revision by default, with a
control to switch to earlier revisions — the selected revision's own grounding status and
violations driving the badge, list, and inline marks. Pure client-side grouping; no API
change (FR-013, R9).

**Independent Test**: Seed one deliverable kind at revisions 0..2 and confirm the view
shows a single entry at revision 2 by default, and switching to revision 0 renders that
revision's content, grounding status, and violations — not the group's latest
(quickstart § US5).

### Implementation for User Story 5

- [x] T030 [US5] Implement `DeliverableGroup` grouping in `console/src/routes/artifacts.tsx` per data-model.md: group the existing list response by `kind`, order each group's `revisions` by `revision`, default `selected` to max revision with an operator control to select earlier ones; the selected revision's `grounding_status` and `violations` are what drive the badge, itemised list, and inline marking — never another member's (depends on T009; touches the same file as T016/T025 — run after them if those stories have landed)
- [ ] T031 [US5] Verify US5: console builds; walk quickstart § US5 (one entry, latest default, earlier revision shows its own content and grounding state)

**Checkpoint**: All five stories functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Whole-feature verification and the genericity claim.

- [ ] T032 Full verification sweep: `uv run ruff check`, `uv run pytest` (tests/export/, tests/integration/test_us_artifact_views.py, and tests/genericity all green, no API key and no Stripe/Vercel credentials in the environment), `cd console && npx tsc -b && npm run build`
- [ ] T033 Genericity spot-check (SC-006, quickstart § final): run or seed the second brief fixture's outputs and repeat the US1–US3 walkthroughs — every displayed value (currencies, prices, names) traces to that run's own artifacts with zero code change

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: T003 depends on Setup; blocks US1 (Storyboard money formatting)
- **US1 (Phase 3)**: Depends on T003. Console-only; no backend work
- **US2 (Phase 4)**: Depends on Setup only for the backend half (T011–T012); T016 depends on US1's T009 (shared route file). Independently testable via the endpoint tests + seeded rows
- **US3 (Phase 5)**: Backend half (T018–T024) independent of US1/US2; T025 depends on T009 (same route file) and prefers T013's helpers when present
- **US4 (Phase 6)**: Depends on US1 (marks live inside T005–T008's renderers)
- **US5 (Phase 7)**: Depends on US1 (T009's route rework); run T030 after T016/T025 when those stories have landed, since all touch `artifacts.tsx`
- **Polish (Phase 8)**: After all desired stories

### Key task-level dependencies

- T009 ← T004–T008; T016 ← T009, T013–T015; T025 ← T009; T030 ← T009
- T012 ← T011 (test first); T021 ← T019; T022 ← T020, T021; T024 ← T022, T023
- `console/src/routes/artifacts.tsx` is touched by T009, T016, T025, T030 — never in parallel
- `tests/integration/test_us_artifact_views.py` is touched by T011 and T023 — never in parallel

### Parallel Opportunities

- **US1**: T004–T008 (five files, no interdependencies) can all run in parallel
- **US2**: T011 and T013 in parallel; then T014 and T015 in parallel after T013
- **US3**: T018, T019, T020 in parallel; the whole backend half can proceed in parallel with US1/US2's console work
- **US4**: T027 can be written in parallel with any US2/US3 work
- **Across stories**: US2's backend (T011–T012) and US3's backend (T018–T024) are independent of all console tasks and of each other until integration

---

## Parallel Example: User Story 1

```bash
# After T003, launch all five renderer-layer files together:
Task: "Create guards.ts shape guards in console/src/components/artifacts/guards.ts"
Task: "Create CopyDoc.tsx in console/src/components/artifacts/CopyDoc.tsx"
Task: "Create PostCards.tsx in console/src/components/artifacts/PostCards.tsx"
Task: "Create EmailPreview.tsx in console/src/components/artifacts/EmailPreview.tsx"
Task: "Create Storyboard.tsx in console/src/components/artifacts/Storyboard.tsx"
# Then T009 (artifacts.tsx dispatch) alone, then T010 verification.
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (branch, baseline) → Phase 2 (T003 formatAmount extraction)
2. Phase 3: US1 — the four text renderers, guards, dispatch, raw toggle
3. **STOP and VALIDATE**: quickstart § US1 + genericity scan. This alone turns the
   artifacts view from JSON dumps into readable deliverables — deployable value

### Incremental Delivery

1. US1 → validate → MVP: text deliverables readable
2. US2 → validate → binaries viewable, single-artifact download (content endpoint lands)
3. US3 → validate → one-click pack handoff (export module + pack endpoint land)
4. US4 → validate → violations marked in context
5. US5 → validate → revision grouping
6. Polish: full sweep + SC-006 genericity spot-check

Each story is a complete increment; stopping after any checkpoint leaves the console
strictly better than before.

### Notes

- Commit progressively per the repo's git workflow — one concern per commit, no
  `Co-Authored-By` trailer, never commit `.claude/DECISIONS.md` or `.env*`
- Everything here is read-only against run state (FR-015): no migration, no new
  dependency on either side, no new knob (so no config/`.env.example` change)
- CI stays keyless by construction — no task makes a model call
