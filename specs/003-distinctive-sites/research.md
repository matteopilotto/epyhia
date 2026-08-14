# Research: Distinctive Generated Sites

Every decision below was resolved against the code as it stands on `003-distinctive-sites`
(branched from `main` at 6c0953c). No NEEDS CLARIFICATION items remain.

## R1 — Font library: format, location, single source

**Decision**: A top-level `fonts/` asset tree — `fonts/library.json` (the registry),
`fonts/files/<id>-<weight>.woff2` (pre-subsetted binaries), `fonts/licenses/<family>.txt`
(one license text per family) — loaded and validated by a typed loader in
`epyhia/design/fonts.py`. Each registry entry carries: `id` (stable, kebab-case),
`family` (the CSS family name), `role` (`display` | `body` | `both`), `weights`
(list of `{weight, style, file}`), `license` (`{name, file}`), and a one-line
`character` string the Strategist's prompt shows beside the id.

The registry is the single source for three consumers: the Strategist's prompt (the
selectable list is passed as render context — `prompt_service.render(agent, version,
fonts=...)`, which the genericity lint's Sentinel-render already tolerates), the
Strategist's output validation (pairing ids checked for membership), and the injector
(ids → files → `@font-face` CSS).

**Rationale**: The archetype library's single source is `_archetypes.jinja` because
prompts are its only consumers. Fonts have a Python consumer (the injector) as well as
prompt consumers, so the single source must be data Python owns, with templates
rendering what they are handed. JSON over a Python literal keeps the registry
greppable and structurally validated by the loader at import time.

**Alternatives considered**: A `prompts/_fonts.jinja` mirror of `_archetypes.jinja` —
rejected: the injector would have to parse Jinja or a second copy would exist.
Font files inside the `epyhia/` package — rejected: binary assets follow the `video/`
and `prompts/` top-level precedent, and the loader resolves paths the same way
`PromptService` resolves `PROMPTS_DIR`.

**Curation**: ~10 SIL-OFL faces spanning real contrast of era/width/warmth (e.g. a
high-contrast display serif, a geometric grotesque, a humanist text face, a slab, a
monospace — concrete faces chosen at implementation from the Google Fonts OFL corpus).
Two weights per body face (regular, bold), one or two per display face. Every entry
records its license; no face without one enters the tree.

## R2 — Subsetting and the size budget

**Decision**: Subsetting happens **at curation time**, not at build time. Checked-in
woff2 files are latin-subset (`pyftsubset --unicodes="U+0000-00FF,U+2000-206F,U+20A0-20CF,
U+2122,U+2212" --flavor=woff2 --layout-features=...`), giving ~15–40 KB per weight file.
The exact command is documented in `contracts/font-library.md` so curation is
reproducible; `fonttools` is a curation tool, **not** a runtime or dev dependency.
The finished page budget is **1 MiB (1,048,576 bytes)**, enforced in
`epyhia/design/fonts.py` after injection; a page over budget fails the site stage
visibly (a named exception, the task fails, the operator sees it) per FR-006.

**Rationale**: Build-time per-page subsetting would minimise bytes but adds a heavy
runtime dependency, nondeterminism across builds, and a failure mode (a glyph the page
uses missing from the subset). Curation-time subsetting is deterministic, testable
offline, and satisfies the spec's edge case ("the pairing's font data must be
subsetted so the finished page stays within the budget") with the budget check as the
backstop. 1 MiB comfortably holds a hand-authored page (~30–80 KB) plus a worst-case
pairing (6 weight files ≈ 240 KB raw ≈ 320 KB base64) with wide margin, while still
catching runaway generation.

**Alternatives considered**: Runtime `pyftsubset` against the page's own text —
rejected as above. A smaller budget (256 KB) — rejected: it would make the budget a
tuning knob the first time a pairing legitimately exceeded it.

## R3 — Injection mechanics and grounding neutrality

**Decision**: `embed_fonts(html, pairing) -> str` inserts one
`<style id="epyhia-fonts">` block containing `@font-face` rules (woff2 as
`data:font/woff2;base64,` URIs) immediately after the opening `<head>` tag, by string
insertion on the first `<head[^>]*>` match. It runs after generation (and after the
revision, when one runs) and **before** the grounding check, so the artifact of record
is the exact bytes that were checked and deployed. The Web Builder never sees font
bytes; it receives the resolved family names (and generic fallbacks) inside its
scoped-inputs JSON and writes ordinary `font-family` declarations against them.

**Grounding neutrality is already structural**: `extract_site_text` skips `<script>`
and `<style>` subtrees entirely, so the injected block contributes nothing. FR-004's
test asserts `extract_site_text(page) == extract_site_text(embed_fonts(page, pairing))`
and that the grounding set-difference is identical — proving the property rather than
assuming it, so a future extractor change that starts reading `<style>` fails loudly.

**Alternatives considered**: Having the model author `@font-face` with a placeholder
the pipeline fills — rejected: the model authoring font plumbing is exactly what
"injected mechanically, never authored by the model" forbids, and a malformed
placeholder would be invisible until deploy. Serving fonts as separate deployed files —
rejected: the page is one self-contained document by contract, and a second file is a
second thing to deploy and verify.

## R4 — Screenshots: reuse the worker's Chromium

**Decision**: `epyhia/design/screenshot.py` shells out to the Chromium binary directly —
`<chromium> --headless=new --disable-gpu --no-sandbox --hide-scrollbars
--virtual-time-budget=5000 --window-size=<W,H> --screenshot=<out.png> file://<page>` —
once per width: **390×2200** (phone) and **1440×2400** (desktop). The binary path
resolves from `PUPPETEER_EXECUTABLE_PATH` (set to `/usr/bin/chromium` in the worker
image, where it exists for Remotion) and falls back to a short fixed list of common
locations for local dev (darwin Chrome/Chromium paths, `chromium`/`google-chrome` on
PATH). No new config knob. If no binary is found, or the subprocess fails or times out
(wall-clock timeout via `asyncio.wait_for`, same subprocess pattern as the video
renderer), the screenshot step reports "unavailable" and the stage records the skip
and continues — the degraded path FR-015 requires anyway.

**Rationale**: FR-012 mandates reusing the rendering environment already present in
the worker. The image carries system Chromium precisely for headless rendering;
driving it via its own CLI adds zero dependencies (no Puppeteer, no Playwright) and
matches the `asyncio.create_subprocess_exec` pattern `handle_video` already uses.
Fixed tall viewports rather than true full-page capture: Chromium's `--screenshot`
captures the viewport, tall windows capture the page's establishing flow, and the
critic is judging design rhythm, not auditing every pixel to the footer. A blank or
partial capture (the page's own script failed) is delivered to the critic as-is — a
broken render is a finding, not a crash (spec edge case).

**Alternatives considered**: Remotion programmatic APIs — rejected: Remotion renders
compositions, not arbitrary HTML files. Adding Playwright — rejected: a second
rendering environment is exactly what FR-012 forbids.

## R5 — The Site Critic

**Decision**: A new agent module `epyhia/agents/site_critic.py` mirroring
`reviewer.py`'s shape: `claude-haiku-4-5` (checking tier; vision-capable), prompt at
`prompts/site_critic/v1.jinja`, no toolset, `PromptedOutput` of a typed
`Critique{findings: list[CritiqueFinding]}` with `findings` bounded (`max_length=8`).
Each `CritiqueFinding` carries `kind` (a closed Literal: `palette_ignored`,
`rhythm_uniform`, `type_timid`, `accent_overused`, `hierarchy_flat`, `broken_render`,
`other`), `where` (which region/section, in words), and `what` (the concrete
observation). There is deliberately **no field for replacement markup or copy** — the
"never rewrites" boundary is a property of the output shape, exactly as the Reviewer's
is. Inputs: the brand doc, the lint findings, and the two screenshots as
`BinaryContent(media_type="image/png")` items in the user message. It never receives
the raw brief or the page source. Cost is metered through `record_call` /
`limits_for_run` like every other agent (FR-016), with explicit thinking budget and
`max_tokens` headroom per the Reviewer's precedent.

**Empty vs unusable punch list**: a schema-valid `{"findings": []}` is a clean review —
approval derived from emptiness, mirroring `Review.approved`, and satisfying US3
scenario 2 (clean page → no revision, no revision cost). An output that fails to
produce the typed shape after the standard retry, or a render/call failure, is a
**skip**, recorded as such (spec edge case "unusable or empty punch list"). The two
are behaviourally identical for gating (neither triggers a revision by itself) but are
recorded distinctly in the design report, so an operator can tell "the critic approved"
from "the critic never usefully ran".

**Alternatives considered**: Sonnet-tier critic — rejected: tiers follow the shape of
the work; this checks, it does not write. Sending the HTML source alongside the
screenshots — rejected: the critic judges what a visitor sees; source access invites
prescribing code edits, which its output shape forbids anyway.

## R6 — The design lint

**Decision**: `epyhia/design/lint.py`, a pure function
`lint(html, *, brand_doc, pairing) -> list[DesignFinding]` using stdlib `html.parser`
for structure and regex over the page's single `<style>` block for CSS-level rules
(the output contract fixes one style block, hand-authored CSS — a full CSS parser is
not warranted). Six rules, ids fixed in code once:

| Rule id | Detects | Parameterised by |
|---|---|---|
| `uniform_sections` | ≥ 4 top-level sections resolving to the same centred max-width container pattern | — |
| `gradient_hero` | `linear-gradient`/`radial-gradient` in the hero/first section's background | — |
| `single_radius` | one non-zero `border-radius` value reused across ≥ 3 distinct declarations with no other radius on the page | — |
| `accent_overuse` | the brand doc's accent hex appearing in more than a fixed share of colour declarations | brand doc `palette.accent` |
| `weak_type_scale` | max declared font-size / body font-size below a fixed ratio (≈ 2.5) | — |
| `ignored_pairing` | `font-family` declarations not led by the resolved families of the brand doc's pairing ids | brand doc `type` + font library |

Thresholds are constants beside the rules — enumerated in code once, never extended at
runtime by anything a model says, and containing no client data (the two
brand-parameterised rules read the run's own brand doc at call time). Each
`DesignFinding` carries `rule`, `detail` (human-readable), and `where` (selector or
section index). The lint runs in CI via `tests/design/` against two synthetic fixture
pages — one deliberately built with every tell, one clean against a synthetic brand
doc — asserting every seeded tell is reported and the clean page reports none (FR-011,
US2 independent test). Fixture pages use invented, client-free content so the
genericity harvest stays silent on them.

**Rationale**: Deterministic heuristics over hand-shaped output are reliable exactly
because the output contract is narrow (one document, one style block, no framework).
The lint gates the revision pass and reports; it never refuses a deploy (FR-010).

**Alternatives considered**: a CSS parser dependency (tinycss2) — rejected: new
dependency for regex-tractable, self-authored CSS. Rendering-based metrics (computed
styles via CDP) — rejected: couples the zero-cost check to the browser and makes CI
need one.

## R7 — Site-stage orchestration and the revision pass

**Decision**: `handle_site` becomes the fixed-in-code orchestrator:

1. **Resolve pairing** from the brand doc's `type` ids against the library. Unknown or
   role-invalid id → the stage fails immediately with an error naming the id, before
   any model call (FR-005; also the "older brand doc carries free text" edge case —
   free text simply fails the lookup by name).
2. **Build** (`build_site`, prompt v4; scoped inputs now include the resolved family
   names). **Embed fonts**, **check size budget** (fail visibly if over).
3. **Grounding check** on the embedded page (unchanged extractor); store the `site`
   artifact at revision 0 exactly as today. A flagged page still stores and still
   never deploys — unchanged.
4. **Lint** the stored page.
5. **Screenshot + critique**, wrapped so any failure records a skip and continues
   (FR-015).
6. **Revision gate**: if lint findings ∪ critique findings is non-empty, run exactly
   one `revise_site` pass (same Sonnet model, `web_builder_revise/v1` prompt, streamed,
   memoised under its own key) with the original page, the findings, and the same
   scoped inputs. Embed fonts, size-check, grounding-check, re-lint. **Keep the
   revision** only if grounding is clean, the budget holds, and its lint finding count
   is not greater than the original's; otherwise keep the original. The kept page is
   stored as `site` revision 1 (only when the revision is kept; the existing
   `revision.desc()` reads and the export path pick it up unchanged), and the deploy
   request carries the kept page's bytes.
7. **Write the `design_report` artifact** (schema in `contracts/`): lint findings,
   critique outcome (clean / findings / skipped, with reason), revision record
   (not-needed / kept / discarded-grounding / discarded-worse / skipped, with before
   and after finding counts). Then request the deploy exactly as today.

The report is written on every path, including full-skip paths, so US2's operator
visibility holds even when the loop degrades.

**Grounding posture of the report**: `design_report` is stored with
`grounding_status="clean"` without a scan. Principle VI governs artifacts on the path
to publication; the report is internal telemetry about the page — it is never
deployed, sent, or published, and the only grounding check that guards the world (the
site artifact's) runs on the actual deployed bytes both before and after revision.
The MP4 artifacts set the precedent of a kind whose status is asserted by
construction rather than scanned.

**Rationale**: One pass, gated on findings, keep-only-if-not-worse implements FR-014
and SC-003 with the smallest possible state machine, entirely inside the existing
handler — no new task kinds, no queue changes, crash recovery unchanged (a re-claimed
site task replays from the top; the generation memo and revision memo absorb the
model-cost of the replay).

## R8 — Archetype spec sheets and library growth

**Decision**: `prompts/_archetypes.jinja` remains the single source and remains
prompt-only (its only consumers are the two prompts, so the Jinja single-source
precedent stands). Each page archetype's one-line `for` grows into a spec:
`grid`, `rhythm` (spacing cadence), `alternation` (how sections must vary),
`hero_must_not` (the constraint), and `signature` (the one structural move that makes
it recognisable). Three new page archetypes and four new section layouts are added at
the same depth — infrastructure-named, client-free (final names chosen at
implementation; working set: `asymmetric_editorial`, `dense_index`,
`full_bleed_poster` pages; `stat_band`, `numbered_process`, `split_manifesto`,
`sticky_rail` sections). Video archetypes are untouched. Both prompts render the full
spec sheets (US4 scenario 1); the genericity scans already cover `_archetypes.jinja`
raw and every rendered template.

## R9 — Strategist divergence and pairing-by-id

**Decision**: `prompts/strategist/v3.jinja`. Two changes: the `type` field's
instruction becomes "select a display id and a body id from the font library below"
(the library rendered from context per R1, ids with their `character` lines and
roles), and a divergence step instructs drafting at least three genuinely distinct
directions — palette, pairing, one-line rationale — before committing to exactly one.
Opus 5's extended thinking (on by default) is where the drafts live; the brand doc
shape is unchanged and the discarded directions never appear in it (FR-019; the
existing `BrandDocument` model is the enforcement — there is no field to leak them
into). `TypePairing` in `strategist.py` gains validation against the library so an
invalid id raises `ModelRetry` inside the Strategist's own run (self-correction),
with the site stage's fail-fast (R7 step 1) as the durable backstop for docs authored
by older prompt versions.

**Divergence verification**: the two-fixture divergence assertions (US5 scenario 1,
SC-001) are live-model properties; they land in the eval/quickstart evidence pass, not
CI. CI asserts the mechanical half: prompt renders, schema unchanged, no client data.

## R10 — Web Builder prompt v4 and the revise prompt

**Decision**: `prompts/web_builder/v4.jinja` — carries the full archetype spec sheets,
names the generic tells outright (default font stacks as a deliberate-choice framing
removed entirely: the instruction "use a system font stack that carries the same
character" is **replaced** by "set `font-family` with the family names given in your
inputs; the pipeline embeds the faces"), and keeps every existing fact/checkout/
self-containment rule verbatim. `prompts/web_builder_revise/v1.jinja` is a separate
prompt directory (so `active_version()` and the genericity globs treat it as any other
agent's tree) for a second agent instance in `web_builder.py`: same model, streamed,
same max-tokens ceiling, input = scoped inputs + original page + findings, output =
the full revised document. Its ledger rows record `agent="web_builder_revise"` so cost
views separate build from revision spend honestly. Prior prompt versions stay intact
(FR-021).

## R11 — Recording: no migration

**Decision**: No schema change. Findings and the revision record are one
`design_report` artifact per site build (R7 step 7); the revised page is a `site`
artifact `revision=1` using the column and ordering already in place. Operator
visibility comes free through feature 002's artifact inspection (a JSON artifact
alongside the site artifact for the run — US2 scenario 3). A dedicated console panel
is explicitly out of scope for this feature.

**Alternatives considered**: a `design_findings` JSONB column on `artifacts` or a new
`design_reports` table — both rejected: a migration and new read paths for what is,
structurally, an artifact of the run like any other.
