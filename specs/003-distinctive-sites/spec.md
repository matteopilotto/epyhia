# Feature Specification: Distinctive Generated Sites

**Feature Branch**: `003-distinctive-sites`

**Created**: 2026-08-13

**Status**: Draft

**Input**: User description: "Higher-quality, distinctive generated websites: eliminate the generic 'AI slop' look from the Web Builder's output while keeping cost and latency reasonable. Six coordinated changes: an embedded openly-licensed font library selected by id in the brand doc and injected mechanically after generation; a screenshot–critique–revise loop with a fast vision critic and at most one conditional revision pass; a deterministic design lint that detects default tells at zero model cost; richer archetype spec sheets plus new archetypes and section layouts; a propose-then-pick divergence step in the Strategist; and explicit anti-slop language in the Web Builder prompt. All client-varying values stay in the brand doc per the core invariant; the font library, archetype specs, and lint rules are infrastructure."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pages set in real typefaces (Priority: P1)

A client's brief runs through the pipeline and the published page is set in actual typefaces
chosen for that brand — a display face and a body face picked by the Strategist from a
curated, openly licensed library the agency owns — instead of whatever generic face the
visitor's operating system substitutes. The page remains exactly what it is today: one
self-contained document that makes no external request of any kind. The faces travel inside
the page itself, put there mechanically by the pipeline after generation, never authored by
the model.

**Why this priority**: Typography is the single strongest visual distinctiveness lever, and
today it is amputated — the no-external-requests rule forces every page onto the same handful
of system faces, which makes every page look alike regardless of palette or layout. This
story delivers visible value entirely on its own.

**Independent Test**: Run a brief through the pipeline (or build a site from a seeded brand
doc), open the produced page offline, and confirm the named faces render, the page makes zero
network requests, and the grounding scan of the page is unchanged by the embedded font data.

**Acceptance Scenarios**:

1. **Given** a brand doc naming a type pairing by library id, **When** the site is built,
   **Then** the finished page renders both faces without any external request, and the faces
   are the ones the ids name.
2. **Given** the finished page with embedded faces, **When** its text is scanned for
   grounding, **Then** the embedded font data and style content contribute no entries to the
   scan — the grounding result is identical to the same page without the fonts.
3. **Given** a brand doc naming a pairing id that is not in the library, **When** the site
   stage starts, **Then** it fails fast with a clear error naming the unknown id, before any
   page is generated.
4. **Given** any client brief, **When** the library is inspected, **Then** it contains no
   client-specific data — every face is openly licensed, recorded with its license, and
   selectable by any brief.

---

### User Story 2 - The default tells are detected mechanically (Priority: P2)

After a page is built, a deterministic check — no model involved — inspects it for the
recognisable marks of a generic machine-made page: every section the same centred column,
a gradient hero, one corner-rounding value reused everywhere, the accent colour on too many
elements, a timid type scale, a font pairing other than the one the brand doc named. Each
finding is recorded against the run so an operator can see exactly which tells a page
carries, and the same check runs in CI against fixture output so quality cannot silently
regress.

**Why this priority**: The lint is the measurement layer — it costs nothing per run, it makes
"generic" a named, countable property instead of a vibe, and the revision loop (story 3) is
gated on it. It is independently valuable as pure reporting even if no revision ever runs.

**Independent Test**: Feed the lint a page deliberately built with the default tells and
confirm each named tell is reported; feed it a page that follows a brand doc faithfully and
confirm it reports none.

**Acceptance Scenarios**:

1. **Given** a page whose sections are all the same centred column width, **When** the lint
   runs, **Then** it reports the uniform-structure tell with the sections involved.
2. **Given** a page set in a face other than the brand doc's named pairing, **When** the lint
   runs, **Then** it reports the ignored-pairing tell, judged against that run's own brand
   doc, not against any fixed list of client values.
3. **Given** a lint run with findings, **When** an operator views the run, **Then** the
   findings are visible with the page they describe.
4. **Given** a page with findings, **When** the deploy action is requested and the page is
   otherwise sound, **Then** the findings alone do not refuse the deploy — grounding remains
   the only mechanical check that refuses.

---

### User Story 3 - The builder sees its own work before it ships (Priority: P3)

Once a page is built, the pipeline renders it the way a visitor would — at a phone width and
a desktop width — and a fast visual reviewer examines the result against the brand doc,
producing a short, concrete punch list: where the page ignored the palette, where the rhythm
collapsed into sameness, where the type scale went timid. If the punch list or the design
lint has findings, the builder gets exactly one chance to revise its page against them. The
revised page must pass the same grounding check and lint before it replaces the original; if
rendering or review fails for any reason, the stage completes with the unrevised page and the
skip is recorded — a missing critique never fails a run.

**Why this priority**: This converts blind one-shot generation into verified work — the same
philosophy the Action Gate applies to external actions — and it is the strongest quality
lever after typography. It depends on story 2's lint for its gate, so it lands after it.

**Independent Test**: Build a page that the lint flags, confirm exactly one revision pass
runs and the revised page carries fewer findings; build a clean page and confirm no revision
runs; simulate a render failure and confirm the stage completes with the original page and a
recorded skip.

**Acceptance Scenarios**:

1. **Given** a built page with lint or reviewer findings, **When** the site stage continues,
   **Then** exactly one revision pass runs, and the revised page is re-checked for grounding
   and re-linted before it replaces the original.
2. **Given** a built page with no findings, **When** the site stage continues, **Then** no
   revision pass runs and no revision cost is incurred.
3. **Given** a revised page that fails the grounding re-check, **When** the stage completes,
   **Then** the original page is kept, and the failed revision is recorded.
4. **Given** a render or review failure, **When** the stage completes, **Then** it completes
   with the unrevised page, the skip is recorded, and the run does not fail.
5. **Given** the visual reviewer's output, **When** it is inspected, **Then** it contains
   only findings — the reviewer never edits the page itself, and it read the brand doc and
   the rendered page, never the raw brief.
6. **Given** any run through this loop, **When** its costs are examined, **Then** every added
   model call is metered in the run's cost ledger against the run's budget.

---

### User Story 4 - Structure varies because the archetypes say more (Priority: P4)

The Strategist chooses from a richer library: each page archetype now carries a real
specification — its grid, its spacing rhythm, how sections must alternate, what its hero must
not be, and the one structural move that makes it recognisable — instead of a single
descriptive line. The library also grows new archetypes and new section layouts, so two
different briefs no longer map onto the same four skeletons. The library remains agency
infrastructure: single-sourced, selected from but never invented into, and free of any
client data.

**Why this priority**: With measurement (story 2) and revision (story 3) in place, richer
specs are what give the builder genuinely different structures to build — but the earlier
stories already improve output without it.

**Independent Test**: Render the Strategist's and the Web Builder's prompts and confirm each
archetype presents its full specification; run the two existing brief fixtures and confirm
the two brand docs can and do select different archetypes whose pages differ structurally.

**Acceptance Scenarios**:

1. **Given** the shared archetype library, **When** either the Strategist's or the Web
   Builder's prompt is rendered, **Then** both present the same archetype set from the single
   source, each with its full specification.
2. **Given** the grown library, **When** it is compared to today's, **Then** it contains at
   least three new page archetypes and at least four new section layouts, each specified to
   the same depth as the existing ones.
3. **Given** the rendered prompt templates, **When** CI greps them for client data, **Then**
   nothing client-specific appears — the library is infrastructure.

---

### User Story 5 - The brand doc diverges by design (Priority: P5)

Before committing to a visual direction, the Strategist drafts several genuinely distinct
directions — palette, pairing from the font library, a one-line rationale each — and then
commits to the single one the brief argues for. Only the chosen direction appears in the
brand doc; the alternatives are working material, not output. Alongside this, the Web
Builder's instructions name the generic tells outright — the default font stacks, the
gradient-on-dark hero, the cookie-cutter card rows — so the model cannot claim ignorance of
what "generic" means.

**Why this priority**: This attacks sameness at its source — the single-pass choice that
converges on similar brand docs across different briefs — but it refines the pipeline rather
than adding a capability, so it lands last.

**Independent Test**: Sample the plan stage N ≥ 4 times per fixture through the real handler
(`scripts/sample_directions.py`) and confirm the fixtures' modal directions differ as SC-001
binds them — pairing across every pair, palette and archetype across pairs whose briefs argue
for different directions; confirm the brand doc's shape is unchanged (no new fields leak the
discarded alternatives).

**Acceptance Scenarios**:

1. **Given** two brief fixtures whose voices argue for different directions, **When** each is
   sampled N ≥ 4 times through the Strategist, **Then** their modal directions share no type
   pairing, no page archetype, and no palette direction under the calibrated perceptual
   thresholds. A single run of each cannot settle this — it is a property of the distribution,
   and reading it off one pair produced two conclusions that later samples retracted.
2. **Given** two brief fixtures whose voices argue for the same register, **When** each is
   sampled N ≥ 4 times, **Then** their modal pairings still differ, and a shared palette
   direction is the expected result rather than a failure — the Strategist is following both
   briefs, which say the same thing about how the page should feel.
3. **Given** a produced brand doc, **When** its shape is validated, **Then** it is unchanged
   from today — the drafted alternatives do not appear in it.
4. **Given** the Web Builder's rendered prompt, **When** it is read, **Then** it names the
   generic tells explicitly, and names no client data while doing so.

---

### Edge Cases

- A brand doc produced by an older prompt version carries a free-text type description
  instead of a library id: the site stage must fail fast with a clear error rather than
  silently falling back to system faces (new prompt versions apply to new runs; old runs
  re-run under the new versions).
- The embedded faces push the page past its size budget: the pairing's font data must be
  subsetted so the finished page stays within the budget, and the build fails visibly if it
  cannot.
- The visual reviewer returns an unusable or empty punch list: treated the same as a review
  failure — the stage completes with the unrevised page and records the skip.
- The single revision pass makes the page worse (more lint findings than before): the
  original page is kept and both results are recorded.
- The headless render produces a blank or partial screenshot (the page's own script failed):
  the reviewer sees what a visitor would see — a broken render is itself a finding, not a
  crash.
- A re-run of the same brief after this feature lands: the prompt versions have changed, so
  the deploy identity changes with them; this interacts with the known defect T143 (the
  deploy key cannot see the Web Builder's prompt version), which this feature does not fix
  but makes more visible.
- Two runs of the same brief produce different pages (generation is non-deterministic): the
  lint and reviewer judge each page against its own brand doc, never against another run's
  output.

## Requirements *(mandatory)*

### Functional Requirements

**Font library and injection**

- **FR-001**: The repository MUST carry a curated library of openly licensed typefaces,
  each recorded with a stable id, its role (display, body, or both), and its license. The
  library is agency infrastructure: it contains no client data and any brief may select from
  all of it.
- **FR-002**: The Strategist MUST select the brand doc's type pairing as library ids, and
  the brand doc MUST record those ids. Free-text face names are no longer a valid pairing.
- **FR-003**: The site pipeline MUST embed the selected faces into the finished page
  mechanically, after generation — the model never authors font data — and the finished page
  MUST remain a single self-contained document making zero external requests.
- **FR-004**: Embedded font data and style content MUST contribute nothing to the grounding
  scan of the page. A test MUST prove the grounding result of a page is identical with and
  without its embedded fonts.
- **FR-005**: A brand doc naming a pairing id absent from the library MUST fail the site
  stage before generation, with an error naming the id.
- **FR-006**: The finished page, fonts included, MUST stay within a defined size budget, and
  the build MUST fail visibly when it cannot.

**Design lint**

- **FR-007**: A deterministic check MUST inspect every built page for an enumerated set of
  generic-page tells — at minimum: uniform section structure, gradient hero, single reused
  corner rounding, overused accent colour, weak type scale, and a face other than the brand
  doc's named pairing — with no model call.
- **FR-008**: Lint findings MUST be recorded against the run and visible to an operator
  alongside the page they describe.
- **FR-009**: The lint's rules MUST be enumerated in code once and contain no client data;
  any brand-specific judgement (such as the pairing check) MUST be parameterised by the
  run's own brand doc.
- **FR-010**: Lint findings alone MUST NOT refuse a deploy. Grounding remains the only
  mechanical check that refuses; the lint gates the revision pass and reports.
- **FR-011**: The lint MUST run in CI against fixture output as a regression check, and MUST
  work offline with no credentials.

**Screenshot, critique, revise**

- **FR-012**: After a page is built, the pipeline MUST render it headless at a phone width
  and a desktop width and capture both screenshots. The rendering environment already
  present in the worker MUST be reused rather than a second one introduced.
- **FR-013**: A fast visual reviewer MUST examine the screenshots and the lint findings
  against the brand doc and produce a bounded punch list of concrete findings. The reviewer
  MUST NOT edit the page, MUST NOT hold any gate handle, and MUST NOT read the raw brief.
- **FR-014**: When the punch list or the lint has findings, the builder MUST run at most one
  revision pass against them. The revised page MUST pass the grounding check and be
  re-linted before it replaces the original; a revision that fails grounding, or lints worse
  than the original, MUST be discarded in favour of the original, with both outcomes
  recorded.
- **FR-015**: A failure anywhere in render, review, or revision MUST NOT fail the site
  stage or the run: the stage completes with the best page it has, and the skip or failure
  is recorded.
- **FR-016**: Every model call this loop adds MUST be metered in the run's cost ledger and
  counted against the run's budget.

**Archetype library**

- **FR-017**: Each page archetype MUST carry a full specification — grid, spacing rhythm,
  section alternation rules, hero constraints, and its signature structural move — in the
  single-sourced library both the Strategist and the Web Builder read.
- **FR-018**: The library MUST grow by at least three new page archetypes and at least four
  new section layouts, each specified to the same depth, and MUST remain free of client
  data.

**Strategist divergence and builder prompt**

- **FR-019**: The Strategist MUST draft at least three distinct visual directions — palette,
  pairing, one-line rationale — and commit to exactly one. The brand doc's shape MUST NOT
  change: discarded directions never appear in it.
  *Note (2026-08-14): the drafting is observable but not guaranteed. The Strategist narrates
  all three directions — hexes, pairing, claim, and why each was rejected — in its response
  text, which spans capture in full; it is not in extended thinking, and Opus 5's thinking
  content is unreadable in any case (`evidence.md`, "The drafts were never in thinking").
  Narrating them is the model's choice rather than a contract, so this supports diagnosis, not
  assertion. Do not read `test_the_discarded_directions_have_nowhere_to_land` as a test of the
  first sentence: it asserts the shape constraint in the second.*
- **FR-020**: The Web Builder's prompt MUST name the generic tells explicitly — default font
  stacks as a deliberate choice, gradient-on-dark heroes, cookie-cutter card rows — without
  naming any client data.
- **FR-021**: All prompt changes MUST land as new versions in the versioned prompts tree,
  leaving prior versions intact, and CI's client-data grep over rendered templates MUST
  still pass.

### Key Entities

- **Font library entry**: one typeface the agency owns the right to embed — id, family
  name, role (display / body / both), weights carried, license record.
- **Type pairing**: the brand doc's two library ids — a display face and a body face —
  replacing today's free-text face names.
- **Archetype specification**: a page archetype's full spec — grid, spacing rhythm,
  alternation rules, hero constraints, signature move — single-sourced for both the
  Strategist and the Web Builder.
- **Design finding**: one detected tell — rule id, human-readable description, and where on
  the page it was found; produced by the lint or the visual reviewer.
- **Revision record**: the fact and outcome of the single revision pass — findings before,
  findings after, whether the revision was kept or discarded, or why it was skipped.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across N ≥ 4 sampled runs per fixture, measured by the sampling report
  (`scripts/sample_directions.py`) and never by one pair of runs:

  - **pairing** — every pair of fixtures has disjoint modal type pairings;
  - **palette** — every pair of fixtures *whose briefs argue for different directions* has
    modal palettes that are not same-direction under the calibrated perceptual thresholds;
  - **archetype** — every such pair also has disjoint modal page archetypes.

  Fixtures whose briefs argue for the same register converge in palette, and may share an
  archetype mode. That convergence is the Strategist reading the brief correctly, and
  following the brief wins.

  *Restated 2026-08-14, on the evidence in `evidence.md`.* The original wording asked for two
  runs to share no pairing, palette or skeleton, "verifiable by inspecting the two runs'
  artifacts side by side". Two problems, both observed rather than argued. It made a
  distributional claim checkable only against a single draw, and two conclusions drawn that
  way had to be retracted once a third sample existed. And "no shared palette" was read as
  string inequality, which two palettes one hex digit apart satisfy — the criterion passed on
  a technicality while both pages were a cream ground with a burnt-orange accent.

  *Palette and archetype clauses rebound to disagreeing briefs, 2026-08-14, on the third
  fixture's draw.* The distributional restatement above was still binding two briefs that
  **agree**: one and two are both understated and detail-led, so both reject dark and both
  reject loud, and asking their palettes to differ was asking the Strategist to ignore what it
  was told. A third fixture whose voice argues *for* the dark direction takes it 4/4 at ΔE ≈ 90
  from the cream family and passes every clause against both — so the convergence was never a
  default. The archetype clause moved with the palette clause for a separate, measured reason:
  re-drawing one × two under identical conditions flipped its archetype verdict from PASS to
  FAIL with nothing changed, so that clause is load-bearing across disagreeing briefs and not
  stable across agreeing ones. Pairing keeps binding every pair, because it separated all three
  of them here and its verdict replicated.

  What decides "argue for different directions" is the briefs' own voice fields, read by a
  person. It is deliberately **not** encoded: a table in code saying which fixtures disagree
  would be client data in source, which is the one thing this system may not do.
- **SC-002**: A page built with deliberate default tells is detected: the lint reports every
  seeded tell, and after the single revision pass the finding count strictly decreases.
- **SC-003**: A clean run's added cost is one visual review; a flagged run's added cost is
  bounded by one review plus one rebuild of the page. No run ever incurs more than one
  revision pass.
- **SC-004**: The finished page still makes zero external requests, still works offline, and
  stays within its size budget with fonts embedded.
- **SC-005**: The grounding scan of a page is byte-for-byte identical with and without its
  embedded font data — the feature adds no grounding entries and no new deploy refusals.
- **SC-006**: The site stage's end-to-end latency for a clean run grows by no more than the
  time of one headless render plus one fast review; a run needing revision adds at most one
  further build's time.
- **SC-007**: In a side-by-side comparison of the same brief built before and after this
  feature, an operator can identify the post-feature page, and the design lint reports
  strictly fewer tells on it.

## Assumptions

- The lint is advisory and a revision gate, never a deploy refusal — grounding remains the
  sole mechanical check that refuses a deploy (Principle VI is unchanged).
- The screenshot and visual review run on every built page (they are cheap); the revision
  pass runs only when findings exist, and at most once per build.
- The visual reviewer is a new checking-tier model call inside the site stage. It follows
  the existing tier philosophy — it checks, it never writes — and its boundaries mirror the
  Reviewer's: it may not approve silently, may not rewrite the page, holds no gate handles,
  and reads the brand doc and rendered page, never the raw brief. The constitution's agent
  table will need a row for it at plan time.
- The headless rendering capability already present in the worker image for video rendering
  is reused for screenshots; no new rendering infrastructure is introduced.
- Typeface files are openly licensed (e.g. SIL OFL), stored in the repository with their
  license records, and subsetted so a pairing stays within the page size budget. The
  specific size budget is set at plan time.
- Existing brand docs from prior runs are not migrated. New prompt versions apply to new
  runs; a re-run of an old brief goes through the new prompts.
- This feature bumps Strategist and Web Builder prompt versions, which changes deploy
  identity for re-runs. The known defect T143 (deploy key blind to the Web Builder's prompt
  version) is out of scope here but becomes more visible; it should be fixed independently.
- Cost and latency stay "reasonable" per the constraints above: the worst-case addition per
  run is one fast visual review plus one page rebuild; the typical addition is one review.
