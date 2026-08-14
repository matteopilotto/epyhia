# Implementation Plan: Distinctive Generated Sites

**Branch**: `003-distinctive-sites` | **Date**: 2026-08-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-distinctive-sites/spec.md`

## Summary

Six coordinated changes that remove the generic "AI slop" look from the Web Builder's
output while keeping cost and latency bounded: (1) an embedded, openly licensed font
library selected by id in the brand doc and injected mechanically after generation;
(2) a deterministic design lint that detects the default tells at zero model cost;
(3) a screenshot → critique → revise loop — headless Chromium (already in the worker
image for Remotion) captures a phone and a desktop render, a Haiku-tier Site Critic
produces a bounded punch list, and the builder gets at most one revision pass, gated on
findings; (4) archetype spec sheets plus three new page archetypes and four new section
layouts in the single-sourced `prompts/_archetypes.jinja`; (5) a propose-then-pick
divergence step in the Strategist's prompt; (6) explicit anti-slop language in the Web
Builder's prompt. All client-varying values stay in the brand doc; the font library,
archetype specs, and lint rules are agency infrastructure. No schema migration is
needed: findings and the revision record travel as a new `design_report` artifact kind,
and the revised page is a `site` artifact revision.

## Technical Context

**Language/Version**: Python 3.13 (pipeline, lint, injection, agents); Jinja2 prompt
templates; no new JavaScript — the console needs no change (the `design_report`
artifact is visible through the existing artifact-inspection views from feature 002)

**Primary Dependencies**: PydanticAI `2.22.0` (Site Critic with image input via
`BinaryContent`; `TestModel`/`FunctionModel` for offline tests), stdlib `html.parser`
plus regex over the page's single `<style>` block for the lint, `base64` for font
embedding. **No new runtime dependency.** Subsetting is a curation-time step
(`fonttools`/`pyftsubset`, documented, not a dependency of the app); screenshots use
the Chromium binary already present in the worker image for Remotion
(`PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium`)

**Storage**: Postgres via existing tables — `artifacts` gains a new `kind` value
(`design_report`) and uses the existing `revision` column for the revised page.
**No Alembic migration.**

**Testing**: `uv run pytest`, offline and credential-free. Lint and injection are pure
functions tested against synthetic HTML fixtures; the Site Critic and revision pass are
tested with `FunctionModel`; the CI genericity scans (`tests/genericity/`) automatically
cover the new prompt directories via their `*/v*.jinja` glob

**Target Platform**: Fly.io worker image (linux, Chromium + Node 22 present) and local
dev (darwin — Chromium binary discovered, screenshot step degrades to a recorded skip
when absent, which FR-015 requires surviving anyway)

**Project Type**: Existing single Python project (`epyhia/` package + `prompts/` tree +
top-level asset dirs, matching `video/`)

**Performance Goals**: Clean run adds one headless render (two captures) plus one Haiku
call; flagged run adds at most one further Web Builder pass (SC-003, SC-006). No run
ever incurs more than one revision

**Constraints**: Finished page ≤ 1 MiB (1,048,576 bytes) with fonts embedded, zero
external requests, grounding scan byte-identical with and without fonts (the extractor
already skips `<style>`); lint findings never refuse a deploy; render/review/revision
failures never fail the run

**Scale/Scope**: Two brief fixtures; ~6 lint rules; a curated library of ~10 typefaces
(pre-subsetted woff2, ~15–40 KB per weight file); 4 existing + 3 new page archetypes;
9 existing + 4 new section layouts

## Constitution Check

*GATE: evaluated against Constitution v1.1.1 before Phase 0; re-evaluated after Phase 1.*

**I. Client Data Never in Code — PASS.** The font library, archetype specs, lint rules,
size budget, and screenshot widths are agency infrastructure: no client name, price,
palette, or face choice appears in any of them. Every brand-specific judgement is
parameterised by the run's own brand doc at run time (the pairing check reads the ids
the brand doc names; the accent-overuse check reads the brand doc's accent hex). The
CI genericity scans extend automatically: new prompt files match the existing globs,
and the lint's test fixtures are synthetic pages carrying no fixture tokens.

**II. Design-First — PASS.** DESIGN.md §6.3 already frames not-slop as art direction
delivered through client-agnostic mechanisms (a specific brand doc, a composition plan,
an anti-slop bar with no client aesthetics). This feature deepens both levers and adds
a third (verify the page visually before shipping it) without contradicting anything in
DESIGN.md; §6.4's gate posture for local renders ("a local render spends nothing and
sends nothing, so rendering does not route through the gate") covers the screenshot
step by the same argument.

**III. Fixed Pipeline, Tiered Agents — PASS, with one planned amendment.** The pipeline
remains copy → site, demand, money; the revision loop is fixed in code inside the site
stage (bounded to one pass), not composed by a model. The Site Critic is a new
checking-tier model caller (`claude-haiku-4-5`) whose boundaries mirror the Reviewer's:
it may never edit the page (its output shape has no field for markup), never approve
silently (approval is derived from an empty findings list, exactly as `Review.approved`
is), holds no gate handles (no toolset), and reads the brand doc and rendered page,
never the raw brief. **The constitution's agent table needs a Site Critic row — a MINOR
amendment (1.1.1 → 1.2.0), anticipated by the spec's assumptions, to be made as the
first implementation task.** No prior guarantee is reversed.

**IV. Action Gate — PASS.** Nothing new deploys, charges, sends, or publishes. The
screenshot render is local and free (same posture as the video render, DESIGN.md §6.4);
the Site Critic and revision calls are inference — metered, not gated — and both roll
up against the run's one budget via the existing `record_call` / `limits_for_run`
plumbing (FR-016).

**V. Idempotency by Brief Hash — PASS.** The deploy key still derives from brief hash +
brand doc version + prompt version and still excludes generated bytes, so the revision
changing the bytes changes nothing about deploy identity. The revision call gets its
own memo key (agent, model, prompt version, findings, original page), a cache not a
ledger. The Strategist prompt bump changes `run.prompt_version` for new runs, which
changes deploy identity for re-runs — intended, and it makes the known defect T143
(deploy key blind to the Web Builder's prompt version) more visible; T143 stays out of
scope per the spec.

**VI. Grounding Before Opinion — PASS.** The grounding extractor already skips
`<style>`, so mechanically injected font CSS contributes nothing; FR-004's test proves
it byte-for-byte. The revised page passes the same grounding check before it can
replace the original, and the check still runs before any model (the critic) is asked
an opinion. Lint findings never refuse a deploy — grounding remains the only mechanical
refusal (FR-010). The derivation set is untouched.

**VII. Simplicity — PASS.** No migration, no new runtime dependency, no new config
knob (the Chromium path resolves from `PUPPETEER_EXECUTABLE_PATH`, already set in the
image, with a fixed fallback list for dev; absence is a recorded skip, not an error).
The design report reuses the artifact store and the existing console artifact views.

**Post-design re-check (after Phase 1)**: PASS on all seven principles. The design
added two decisions worth naming against the gates: the `design_report` artifact
carries `grounding_status="clean"` by construction rather than by scan — consistent
with Principle VI, whose refusal guards the publication path, because the report is
never deployed, sent, or published and the deployed bytes themselves are scanned both
before and after revision (research R7); and the revised page lands as `site`
artifact revision 1 only after passing the same grounding check as revision 0, so no
path exists on which unchecked bytes reach the deploy request. The Site Critic
amendment to Principle III's table remains the single governance action.

## Project Structure

### Documentation (this feature)

```text
specs/003-distinctive-sites/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── font-library.md          # Library entry shape, licensing, selection, failure modes
│   ├── design-report.schema.json# The design_report artifact's JSON shape
│   └── site-critic.md           # The Site Critic's IO contract and boundaries
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
fonts/                          # NEW — asset tree, matching prompts/ and video/ precedent
├── library.json                # The registry: id, family, role, weights, license, files
├── files/<id>-<weight>.woff2   # Pre-subsetted (latin) at curation time
└── licenses/<family>.txt       # One OFL text per family

epyhia/
├── design/                     # NEW package — deterministic site-quality infrastructure
│   ├── __init__.py
│   ├── fonts.py                # Registry loader, pairing resolution, embed_fonts(), size budget
│   ├── lint.py                 # The six rules; (html, brand_doc, pairing) → findings
│   └── screenshot.py           # Chromium subprocess: html → (phone.png, desktop.png)
├── agents/
│   ├── strategist.py           # TypePairing ids validated against the library (ModelRetry)
│   ├── web_builder.py          # + revise_site(): second agent instance, revise prompt
│   └── site_critic.py          # NEW — Haiku vision critic, mirrors reviewer.py's shape
└── queue/handlers/
    └── site.py                 # Orchestrates: resolve pairing → build → embed → ground →
                                # lint → screenshot → critique → (one revision) → report

prompts/
├── _archetypes.jinja           # Spec sheets added; +3 page archetypes, +4 section layouts
├── strategist/v3.jinja         # NEW — divergence step, pairing by library id
├── web_builder/v4.jinja        # NEW — spec sheets, named tells, given family names
├── web_builder_revise/v1.jinja # NEW — the one revision pass
└── site_critic/v1.jinja        # NEW — the punch-list critic

tests/
├── design/                     # NEW — lint rules, font embedding, size budget, screenshots
│   └── fixtures/               # Synthetic tell-laden and clean pages (no client tokens)
├── agents/test_site_critic.py  # NEW
└── queue/test_site_handler.py  # Extended: revision kept/discarded/skipped paths
```

**Structure Decision**: Everything lands in the existing single-project layout. Font
assets get a top-level `fonts/` directory (the `prompts/` and `video/` precedent for
non-Python trees the pipeline reads); all new Python lives in a new `epyhia/design/`
package plus one new agent module; the site handler remains the sole orchestrator of
the site stage. No console changes: the `design_report` artifact is a JSON artifact,
already viewable through feature 002's artifact inspection.

## Complexity Tracking

No constitution violations to justify. The one governance action is the planned MINOR
amendment adding the Site Critic row to Principle III's agent table (anticipated in the
spec's assumptions, scheduled as the first implementation task).
