# Tasks: Distinctive Generated Sites

**Input**: Design documents from `/specs/003-distinctive-sites/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — the spec mandates them (FR-004 "a test MUST prove", FR-011 "MUST run
in CI", the US3 handler-path independent tests). All tests run offline with
`TestModel`/`FunctionModel`; CI never needs a key or a browser.

**Organization**: Tasks are grouped by user story so each story is an independently
testable increment. Priority order US1 → US5 keeps the pipeline runnable end-to-end at
every checkpoint (US1 moves both prompts to the new versions minimally; US4/US5 deepen
those same new versions — prior versions stay intact per FR-021).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5, mapping to spec.md's user stories

---

## Phase 1: Setup

**Purpose**: Governance and skeletons — no behavior yet.

- [x] T001 Amend the constitution: add the Site Critic row to Principle III's agent table (model `claude-haiku-4-5`; may never: edit the page, approve silently, hold a gate handle, read the raw brief, fail the run) and bump version 1.1.1 → 1.2.0 with a sync impact report, in `.specify/memory/constitution.md` (the plan's single governance action, scheduled first)
- [x] T002 [P] Create the `epyhia/design/` package skeleton: empty `epyhia/design/__init__.py`
- [x] T003 [P] Create the design test tree: `tests/design/__init__.py` and `tests/design/fixtures/` directory

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The font library — the single asset three stories consume (US1 embeds it,
US2's `ignored_pairing` rule resolves against it, US5's Strategist prompt lists it).

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 Curate ~10 SIL-OFL typefaces spanning real contrast of era/width/warmth (research R1: e.g. a high-contrast display serif, a geometric grotesque, a humanist text face, a slab, a monospace; two weights per body face, one or two per display face): subset each source at curation time with the exact `pyftsubset` command in `contracts/font-library.md` (latin unicodes, woff2, ≤ ~40 KB per weight file — `fonttools` is a curation tool, never a project dependency) into `fonts/files/<id>-<weight>.woff2`, and place one OFL license text per family in `fonts/licenses/<family>.txt`
- [x] T005 Author the registry `fonts/library.json`: one entry per face with `id` (kebab-case, unique, stable), `family`, `role` (`display`|`body`|`both`), `character` (one line of infrastructure prose), `weights` (`{weight, style, file}` pointing under `fonts/files/`), `license` (`{name, file}` pointing under `fonts/licenses/`) per `contracts/font-library.md` — no client data anywhere (FR-001)
- [x] T006 Implement the typed registry loader in `epyhia/design/fonts.py`: load and validate `fonts/library.json` at import (unique ids, valid roles, every weight file and license file exists — a bad registry raises at import, never per-run), path resolution following the `PromptService`/`PROMPTS_DIR` precedent, plus `resolve_pairing(display_id, body_id)` that checks membership and role compatibility and raises a named error `unknown font id: <id>` (or the role-incompatibility variant) for FR-005
- [x] T007 Loader tests in `tests/design/test_fonts.py`: valid registry loads; duplicate id, missing woff2, missing license each fail at load; `resolve_pairing` accepts a valid display+body pair, rejects an unknown id naming it, rejects a role-incompatible pair naming id and role

**Checkpoint**: `uv run pytest tests/design/test_fonts.py` green — library is real, validated, and resolvable.

---

## Phase 3: User Story 1 — Pages set in real typefaces (Priority: P1) 🎯 MVP

**Goal**: The published page renders the brand doc's two library faces, embedded
mechanically after generation, with zero external requests, unchanged grounding, and a
1 MiB size budget enforced.

**Independent Test**: Build a site from a seeded brand doc naming library ids; open the
page offline and confirm the named faces render with zero network requests; confirm the
grounding scan is byte-identical with and without the fonts; confirm an unknown pairing id
fails the stage before any model call.

### Implementation for User Story 1

- [x] T008 [US1] Implement `embed_fonts(html, pairing) -> str` in `epyhia/design/fonts.py`: one `<style id="epyhia-fonts">` block of `@font-face` rules (woff2 as `data:font/woff2;base64,` URIs) inserted by string insertion immediately after the first `<head[^>]*>` match (research R3) — mechanical, post-generation, the model never sees font bytes (FR-003)
- [x] T009 [US1] Add the size budget to `epyhia/design/fonts.py`: constant `1_048_576` bytes, a named exception (e.g. `PageOverBudget`) raised when the embedded page exceeds it, so the site stage fails visibly (FR-006, research R2)
- [x] T010 [P] [US1] Embedding and budget tests in `tests/design/test_embed.py`: the block lands right after `<head>`, contains one `@font-face` per weight file with the correct `family`, the page stays a single document with no external URL introduced; a synthetic page pushed past 1 MiB raises the named exception (FR-006)
- [x] T011 [P] [US1] Grounding-neutrality test in `tests/design/test_grounding_neutrality.py`: `extract_site_text(page) == extract_site_text(embed_fonts(page, pairing))` and the grounding set-difference is identical with and without fonts — proving the property so a future extractor change that reads `<style>` fails loudly (FR-004, SC-005)
- [x] T012 [P] [US1] Create `prompts/strategist/v3.jinja` from v2: the `type` field's instruction becomes "select a display id and a body id from the font library below", rendering the library (ids, roles, `character` lines) from a `fonts` render-context variable (research R1/R9) — the US5 divergence step comes later, on this same new version
- [x] T013 [US1] Update `epyhia/agents/strategist.py`: pass the loaded library as `fonts=...` render context, point at prompt v3, and add `TypePairing` validation against the library (membership + role compatibility) raising `ModelRetry` on an invalid id so the Strategist self-corrects (data-model "Validation, two layers")
- [x] T014 [P] [US1] Create `prompts/web_builder/v4.jinja` from v3: **replace** the "use a system font stack that carries the same character" instruction with "set `font-family` with the family names given in your inputs; the pipeline embeds the faces", keeping every existing fact/checkout/self-containment rule verbatim (research R10) — the US4 spec sheets and US5 tell-naming come later, on this same new version
- [x] T015 [US1] Update `epyhia/agents/web_builder.py`: point at prompt v4 and put the resolved family names (with generic fallbacks) into the scoped-inputs JSON handed to the model (contracts/font-library.md "Web Builder scoped inputs")
- [x] T016 [US1] Rework the site stage in `epyhia/queue/handlers/site.py` (research R7 steps 1–3): resolve the pairing from the brand doc's `type` ids **before any model call**, failing the stage with the loader's named error (FR-005 — free-text names from an old brand doc fail this lookup by construction); then build → `embed_fonts` → size check (visible failure) → grounding check on the embedded page → store the `site` artifact at revision 0, so the artifact of record is the exact bytes checked and deployed
- [x] T017 [US1] Site-handler tests in `tests/queue/test_site_handler.py` (with `FunctionModel`, offline): unknown pairing id fails the stage before any model call, naming the id; fonts are embedded before the grounding check runs; an over-budget page fails the task visibly (FR-005, FR-006, quickstart §1)
- [x] T018 [US1] Verify the CI genericity scans (`tests/genericity/`) cover and pass over `strategist/v3` and `web_builder/v4` via the existing `*/v*.jinja` glob, extending the Sentinel-render context with `fonts` if the render harness needs it (FR-021)

**Checkpoint**: Full offline suite green; a seeded brand doc produces a self-contained page in real faces. MVP delivered.

---

## Phase 4: User Story 2 — The default tells are detected mechanically (Priority: P2)

**Goal**: A zero-model-cost deterministic lint reports the six enumerated generic-page
tells against each built page, recorded in a `design_report` artifact an operator can see,
regression-checked in CI — and never refusing a deploy.

**Independent Test**: Feed the lint the tell-laden synthetic fixture and confirm every
seeded tell is reported; feed it the clean fixture and confirm zero findings; confirm a
flagged-by-lint page still gets its deploy requested.

### Implementation for User Story 2

- [x] T019 [P] [US2] Implement `epyhia/design/lint.py`: `DesignFinding` (`rule`, `detail`, `where`) and the pure function `lint(html, *, brand_doc, pairing) -> list[DesignFinding]` using stdlib `html.parser` for structure and regex over the page's single `<style>` block, with the six rules and their thresholds as constants fixed in code once (research R6): `uniform_sections`, `gradient_hero`, `single_radius`, `accent_overuse` (reads the brand doc's accent hex), `weak_type_scale` (ratio ≈ 2.5), `ignored_pairing` (reads the brand doc's pairing ids resolved to families) — the only brand-parameterised inputs are the run's own brand doc (FR-007, FR-009)
- [x] T020 [P] [US2] Author the synthetic lint fixtures in `tests/design/fixtures/`: one page deliberately carrying every tell, one clean page faithful to a synthetic brand doc, plus that synthetic brand doc — invented, client-free content so the genericity harvest stays silent on them (research R6)
- [x] T021 [US2] Lint tests in `tests/design/test_lint.py`: every seeded tell on the tell-laden fixture is reported with its rule id and location; the clean fixture reports none; `ignored_pairing` and `accent_overuse` judge against the passed brand doc, not any fixed value (FR-009, FR-011, US2 independent test)
- [x] T022 [US2] Extend `epyhia/queue/handlers/site.py`: lint the stored revision-0 page, then write one `design_report` artifact (new artifact `kind="design_report"`, stored via the existing `PostgresArtifactStore` with `grounding_status="clean"` by construction, `revision` matching the site build) on **every** path, shaped per `contracts/design-report.schema.json` — `lint` findings, `critique.status="skipped"` (loop not built until US3), `revision.outcome="not_needed"` with `findings_before`, `screenshots.captured=false` (FR-008, research R7 step 7, R11)
- [x] T023 [US2] Handler tests in `tests/queue/test_site_handler.py`: the design report is written and validates against `contracts/design-report.schema.json`; a page with lint findings still has its deploy requested — lint findings alone never refuse, grounding remains the only mechanical refusal (FR-010)

**Checkpoint**: Every site build now carries an operator-visible design report; "generic" is a counted property in CI.

---

## Phase 5: User Story 3 — The builder sees its own work before it ships (Priority: P3)

**Goal**: Headless phone + desktop screenshots, a Haiku Site Critic punch list, and at
most one gated revision pass — every failure a recorded skip, never a failed run, every
model call metered.

**Independent Test**: With `FunctionModel`: a lint-flagged page triggers exactly one
revision whose kept result carries fewer findings; a clean page triggers no revision call;
a simulated render failure completes the stage with the original page and a recorded skip.

### Implementation for User Story 3

- [x] T024 [P] [US3] Implement `epyhia/design/screenshot.py`: resolve the Chromium binary from `PUPPETEER_EXECUTABLE_PATH` with a short fixed fallback list (darwin Chrome/Chromium paths, `chromium`/`google-chrome` on PATH — no new config knob), then `asyncio.create_subprocess_exec` per width with `--headless=new --disable-gpu --no-sandbox --hide-scrollbars --virtual-time-budget=5000 --window-size=<W,H> --screenshot=<out.png> file://<page>` at 390×2200 (phone) and 1440×2400 (desktop), wall-clock timeout via `asyncio.wait_for`; no binary / failure / timeout → an "unavailable" result, never an exception that escapes (research R4, FR-012, FR-015)
- [x] T025 [P] [US3] Create `prompts/site_critic/v1.jinja`: judge the two renders against the brand doc and the lint findings; corroborate or extend, produce at most 8 concrete findings; a blank or broken render is itself a `broken_render` finding (contracts/site-critic.md)
- [x] T026 [US3] Implement `epyhia/agents/site_critic.py` mirroring `reviewer.py`'s shape: `claude-haiku-4-5`, no toolset, `PromptedOutput` of `Critique{findings: list[CritiqueFinding] (max_length=8)}` with `CritiqueFinding{kind: Literal["palette_ignored","rhythm_uniform","type_timid","accent_overused","hierarchy_flat","broken_render","other"], where, what}` — deliberately no field for markup or copy; inputs are the brand doc, the lint findings, and the two screenshots as `BinaryContent(media_type="image/png")`, never the raw brief; metered via `record_call` under `limits_for_run`, explicit thinking budget and `max_tokens` headroom per the Reviewer's precedent, no `temperature`/`top_p`/`top_k` (research R5, FR-013, FR-016)
- [ ] T027 [P] [US3] Create `prompts/web_builder_revise/v1.jinja` as its own prompt directory (so `active_version()` and the genericity globs treat it as any agent tree): input is the scoped inputs, the original page, and the findings; output is the full revised document (research R10)
- [ ] T028 [US3] Add `revise_site()` to `epyhia/agents/web_builder.py`: a second agent instance on the same Sonnet model, streamed with the same max-tokens ceiling, memoised under its own key (agent, model, prompt version, findings, original page — a cache, not a ledger), ledger rows recording `agent="web_builder_revise"` so cost views separate build from revision spend (research R10, plan idempotency notes)
- [ ] T029 [US3] Complete the site-stage orchestration in `epyhia/queue/handlers/site.py` (research R7 steps 5–7, data-model state diagram): screenshot + critique wrapped so any failure records a skip and continues (schema-valid empty punch list = `clean`; unusable output after the standard retry, or render/call failure = `skipped` with reason); if lint ∪ critique findings is non-empty, run exactly one `revise_site` pass, then embed fonts → size check → grounding check → re-lint the revision; **keep it** only if grounding is clean, the budget holds, and its lint count is not greater than the original's — stored as `site` revision 1, picked up by the existing `ORDER BY revision DESC` readers — else keep revision 0; write the full `design_report` (`critique` status/findings/skip_reason, `revision` outcome `not_needed|kept|discarded_grounding|discarded_worse|skipped` with `findings_before`/`findings_after`, `screenshots.captured`/`widths`) on every path, then request the deploy exactly as today (FR-014, FR-015)
- [x] T030 [P] [US3] Screenshot tests in `tests/design/test_screenshot.py`: no binary found → "unavailable" result, no exception; subprocess failure and timeout paths report unavailable (offline, subprocess faked)
- [x] T031 [P] [US3] Site Critic tests in `tests/agents/test_site_critic.py` with `FunctionModel`: a valid punch list parses into the bounded typed shape; `findings: []` is a clean review; unusable output after retry surfaces as the skip signal; the output shape has no field capable of carrying markup (FR-013)
- [ ] T032 [US3] Extend `tests/queue/test_site_handler.py` for every loop path: findings → exactly one revision, re-grounded and re-linted before replacing the original; clean page → no revision call and no revision cost; revision failing grounding → original kept, `discarded_grounding` recorded; revision linting worse → original kept, `discarded_worse` with both counts; render failure → stage completes, skip recorded, run does not fail; every added model call lands in the run's cost ledger against its budget (FR-014, FR-015, FR-016, US3 acceptance scenarios, SC-003)

**Checkpoint**: Blind one-shot generation is now verified work; the loop degrades to a recorded skip, never a failed run.

---

## Phase 6: User Story 4 — Structure varies because the archetypes say more (Priority: P4)

**Goal**: Every page archetype carries a full spec sheet; the single-sourced library grows
by 3 page archetypes and 4 section layouts; both prompts render the same specs.

**Independent Test**: Render the Strategist's and Web Builder's prompts and confirm each
archetype presents its full specification from the single source; genericity scans stay
silent.

### Implementation for User Story 4

- [ ] T033 [US4] Grow each existing page archetype in `prompts/_archetypes.jinja` from `{id, for}` to the full spec — `grid`, `rhythm`, `alternation`, `hero_must_not`, `signature` — keeping ids stable and video archetypes untouched (FR-017, data-model "Archetype specification")
- [ ] T034 [US4] Add three new page archetypes and four new section layouts to `prompts/_archetypes.jinja` at the same spec depth, infrastructure-named and client-free (research R8 working set: `asymmetric_editorial`, `dense_index`, `full_bleed_poster` pages; `stat_band`, `numbered_process`, `split_manifesto`, `sticky_rail` sections; final names at implementation) (FR-018)
- [ ] T035 [US4] Ensure `prompts/strategist/v3.jinja` and `prompts/web_builder/v4.jinja` both render the full spec sheets from the single `_archetypes.jinja` source (US4 acceptance scenario 1)
- [ ] T036 [P] [US4] Archetype render test in `tests/agents/test_archetype_specs.py`: both rendered prompts present the identical archetype set, each entry carrying all five spec fields; the library counts ≥ 3 new page archetypes and ≥ 4 new section layouts over the pre-feature set (US4 acceptance scenarios 1–2; scenario 3 is the existing genericity scan)

**Checkpoint**: Two briefs no longer map onto the same four skeletons.

---

## Phase 7: User Story 5 — The brand doc diverges by design (Priority: P5)

**Goal**: The Strategist drafts ≥ 3 distinct directions and commits to one (brand doc
shape unchanged); the Web Builder's prompt names the generic tells outright.

**Independent Test**: Validate the brand doc shape is unchanged (no field can leak the
alternatives); read the rendered builder prompt and confirm it names the tells and no
client data. (The two-fixture divergence itself is a live-model property — quickstart §3,
evidence pass, not CI.)

### Implementation for User Story 5

- [ ] T037 [US5] Add the divergence step to `prompts/strategist/v3.jinja`: draft at least three genuinely distinct directions — palette, pairing from the library, one-line rationale each — then commit to exactly one; the drafts live in extended thinking and only the chosen direction reaches the brand doc (FR-019, research R9)
- [ ] T038 [US5] Add explicit anti-slop language to `prompts/web_builder/v4.jinja`: name the generic tells outright — default font stacks, the gradient-on-dark hero, cookie-cutter card rows — naming no client data while doing so (FR-020)
- [ ] T039 [P] [US5] Tests in `tests/agents/test_strategist.py` (extend) and `tests/design/test_prompts_antislop.py`: the `BrandDocument` model's shape is unchanged — no field exists for discarded alternatives to leak into (FR-019); the rendered v4 builder prompt contains the named tells; genericity scans still pass over both updated templates (US5 acceptance scenarios 2–3, FR-021)

**Checkpoint**: All five stories functional; sameness attacked at its source.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T040 Run the full offline gate from quickstart §1: `uv run ruff check` and `uv run pytest` green, and confirm `uv run alembic upgrade head` is a no-op (this feature ships no migration)
- [ ] T041 Run the live evidence pass from quickstart §2–§4 (needs `ANTHROPIC_API_KEY` + the docker-compose stack): one fixture brief end-to-end — `site` and schema-valid `design_report` artifacts visible in the console, the two faces render offline with zero network requests, `site_critic` (and any `web_builder_revise`) rows in the cost view; both fixtures for the divergence check (SC-001: no shared palette, pairing, or archetype); the pre/post regression guard (SC-007: strictly fewer lint tells on the post-feature page); record outcomes in the feature's evidence notes
- [ ] T042 [P] Provoke the quickstart failure modes table and confirm each recorded behaviour: free-text face names fail fast naming the id; Chromium absent → `screenshots.captured=false`, run completes; unusable critic output → `critique.status="skipped"`; worse revision → `discarded_worse` with both counts (covered by the offline suite — verify each has an explicit test and none regressed)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately; T002 and T003 in parallel after T001
- **Foundational (Phase 2)**: sequential chain T004 → T005 → T006 → T007 (registry names files; loader validates registry; tests exercise loader). **Blocks all user stories.**
- **User Stories (Phases 3–7)**: all depend on Phase 2. US1 first (it moves both prompts to v3/v4 and reworks the site handler that US2/US3 extend). US2 before US3 (the lint gates the revision pass). US4 and US5 edit the same two prompt files US1 created — sequence them after US1 (US4 ∥ US5 is possible with care: they touch `_archetypes.jinja`+renders vs. divergence/tell language, but both edit `web_builder/v4.jinja` — coordinate or serialize).
- **Polish (Phase 8)**: after all stories; T040 before T041; T042 parallel with T041.

### Within Each Story

- **US1**: T008 → T009 (same file); T010, T011 parallel after T009; T012 ∥ T014 (different prompt files); T013 after T012; T015 after T014; T016 after T009 + T013 + T015; T017 after T016; T018 after T012 + T014
- **US2**: T019 ∥ T020; T021 after both; T022 after T019 (handler consumes the lint); T023 after T022
- **US3**: T024 ∥ T025 ∥ T027 first; T026 after T025; T028 after T027; T029 after T024 + T026 + T028; T030 ∥ T031 as their modules land; T032 after T029
- **US4**: T033 → T034 (same file) → T035; T036 after T035
- **US5**: T037 ∥ T038 (different files); T039 after both

### Parallel Opportunities

- Phase 1: T002 ∥ T003
- US1: T010 ∥ T011 (tests), T012 ∥ T014 (the two new prompt versions)
- US2: T019 ∥ T020 (lint module vs. fixtures)
- US3: T024 ∥ T025 ∥ T027 (screenshot module, critic prompt, revise prompt), then T030 ∥ T031
- Cross-story (with two people): once US1 lands, US2 (lint) and the US3 leaf modules (T024, T025/T026, T027/T028) can proceed concurrently — only T029 needs US2's lint in the handler first

---

## Parallel Example: User Story 3

```bash
# After US2's checkpoint, launch the three independent US3 leaves together:
Task: "Implement epyhia/design/screenshot.py (Chromium subprocess, phone+desktop, skip on absence)"
Task: "Create prompts/site_critic/v1.jinja"
Task: "Create prompts/web_builder_revise/v1.jinja"

# Then, once agents land, the two test modules together:
Task: "Screenshot tests in tests/design/test_screenshot.py"
Task: "Site Critic tests in tests/agents/test_site_critic.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (constitution amendment + skeletons) and Phase 2 (the font library)
2. Phase 3: US1 — real typefaces, fail-fast pairing, size budget, grounding neutrality
3. **STOP and VALIDATE**: full offline suite green; open a built page offline and watch the named faces render with zero requests
4. This alone visibly de-generifies output — typography is the strongest lever

### Incremental Delivery

1. Setup + Foundational → library validated
2. US1 → real faces (MVP) — pipeline still runs end-to-end
3. US2 → measurement: every build carries a design report; CI regression-checks the tells
4. US3 → verification: screenshot, critique, one gated revision
5. US4 → structural variety: full spec sheets, grown library
6. US5 → divergence at the source + anti-slop language
7. Polish → offline gate, live evidence pass, failure-mode provocations

Each story leaves prior stories' guarantees intact: grounding remains the only deploy
refusal throughout (FR-010), no migration lands at any point, and every prompt change is a
new version beside the old (FR-021).
