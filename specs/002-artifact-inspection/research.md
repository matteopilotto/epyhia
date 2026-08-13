# Research: Artifact Inspection & Pack Download

**Feature**: `002-artifact-inspection` | **Date**: 2026-08-12

Every decision below was resolved against the existing codebase; no NEEDS CLARIFICATION
markers remain. File references are to the repository at the time of planning.

---

## R1 — Authenticated content delivery for media elements (FR-007)

**Decision**: One new read-only endpoint, `GET /api/artifacts/{id}/content`, returns the
stored bytes with the artifact's own `content_type` and a `Content-Disposition` filename
derived from `artifact.path`. The console retrieves it with `fetch` carrying the same Auth0
Bearer header as every other call, wraps the bytes in a `Blob`, and hands
`URL.createObjectURL` results to `<video>`, `<iframe>`, and download anchors.

**Rationale**: `<video src>` and `<iframe src>` cannot attach an `Authorization` header. The
project already faced exactly this with SSE and chose `fetch` + stream over `EventSource`,
explicitly rejecting a JWT in the query string (leaks into access and proxy logs) and a
parallel cookie session (the second path in that FR-057 forbids) — see the comment in
`console/src/lib/api.ts` and DESIGN.md §10's reasoning. Blob URLs keep that single auth
path: the bytes cross the wire exactly once, through the same validator as every operator
route. The spec's size assumption (text deliverables and short launch videos; whole-content
transfer acceptable) is what makes blob-based delivery viable — no range requests or
streaming playback needed.

**Alternatives considered**:
- *Short-lived signed URLs*: a second authentication mechanism to mint, expire, and audit;
  the token still appears in logs. Rejected as the FR-057 violation the checklist warned
  about.
- *Service-worker header injection*: lets media elements fetch directly, but adds a
  registration lifecycle and a cache layer for no capability blob URLs don't already give.
- *Token in query string*: rejected already, for the record, in `api.ts`.

## R2 — Site preview isolation (FR-004)

**Decision**: The in-console preview is an `<iframe sandbox="allow-scripts">` — deliberately
without `allow-same-origin` — whose `src` is the blob URL of the site bytes. The sandbox
gives the document an opaque origin: the site's own JS runs (it needs its one vanilla JS
file), but it cannot reach the console's origin, storage, or the operator's session.
Desktop/mobile is a container-width toggle on the frame. Open-in-new-tab opens a small
wrapper document (authored by the console, static) that itself embeds the same sandboxed
iframe, so the site's script keeps its opaque origin even when viewed top-level — a
top-level blob document would otherwise inherit the console's origin.

**Rationale**: The sandbox attribute is the isolation guarantee the spec asks for, enforced
by the browser rather than by trust in the generated content. The wrapper keeps that
guarantee identical in both viewing modes for a few lines of static HTML.

**Alternatives considered**:
- *Bare blob URL in a new tab*: inherits the console's origin; generated site JS would run
  where the operator's session lives. Rejected — it is precisely what FR-004 excludes.
- *`srcdoc`*: equivalent isolation with `sandbox`, but the open-in-new-tab control still
  needs a URL, so blob URLs are needed anyway; using them for both keeps one mechanism.
- *Preview against the deployed Vercel URL*: only exists after deploy; inspection must work
  before anything goes live.

## R3 — Video playback (FR-005)

**Decision**: Both cuts load through R1's endpoint into native `<video controls>` elements
fed by blob URLs, laid out side by side, the `video_vertical` cut inside a 9:16 aspect
frame. Fetching is asynchronous with a visible loading state; object URLs are revoked on
unmount. No streaming, no range requests — whole-file transfer per the spec's size
assumption.

**Rationale**: Native players satisfy "standard playback controls" with zero dependencies;
the async fetch answers the edge case that a large video must not freeze the console while
content transfers.

**Alternatives considered**: HLS/range streaming (unwarranted for short launch videos;
new server surface), a player library (a dependency for controls the browser already has).

## R4 — Pack assembly and archive layout (FR-008, FR-009, FR-010)

**Decision**: `GET /api/runs/{run_id}/pack` assembles a zip in memory with stdlib
`zipfile` and returns it as `application/zip`, filename `pack-{run_id}.zip`. Assembly
logic lives in a new `epyhia/export/` module (named to avoid colliding with
`epyhia/queue/handlers/pack.py`, which *generates* the marketing pack) as pure functions
over `Artifact` rows — buildable and testable with zero credentials, zero agents, zero
network. Layout:

```text
manifest.json
deliverables/<artifact.path>              # latest revision of each clean deliverable
deliverables/<stem>.md                    # human-readable companion (structured text kinds)
flagged/<artifact.path>                   # latest revision of each flagged deliverable
flagged/<stem>.violations.json            # that revision's itemised violations
flagged/<stem>.md                         # companion, when the kind has one
```

"Latest" is max `revision` per `kind`. A latest-revision artifact that is flagged goes to
`flagged/`, never to `deliverables/` — included, segregated, and accompanied by its
violations (FR-010; also the edge case where an earlier revision was clean: the latest is
still what ships, as flagged). A run with no artifacts yields a valid archive whose
manifest lists zero files. Record files keep the stored `sha256` from the artifact row, so
each is checkable against the audit trail; companion and violations files are hashed at
assembly time.

**Rationale**: In-memory zip is proportionate to the spec's size assumption and keeps the
endpoint a plain authenticated read — no temp files, no background task, no state (the pack
is "assembled per request from the records; not itself stored", per the spec's entity
definition). stdlib `zipfile` means no new dependency (Constitution VII).

**Alternatives considered**: streaming zip (complexity without need at these sizes); a
worker task producing a stored archive (would add run state, contradicting FR-015);
tar (zip opens with standard tools everywhere, per SC-003).

## R5 — Human-readable companions (FR-011)

**Decision**: `epyhia/export/companions.py` renders Markdown mechanically from the stored
JSON, parsed through the same Pydantic models the Marketer emits (`LandingCopy`,
`SocialPosts`, `LaunchEmail` in `epyhia/agents/marketer.py`; `video_props` through its
assembled dict shape). Copy → sections with label/headline/body; posts → one section per
post with angle and body; email → subject/preheader/body; video props → ordered scene list
with kind, lines, and money values formatted per R7. If content fails to parse as its
kind's shape, the companion is skipped and the record file still ships — never a fabricated
rendering. Site and video kinds get no companion; they are already human-usable forms.

**Rationale**: Parsing through the emitting models is the strongest available guarantee
that the rendering "introduces no content of its own" — every string in the Markdown is a
field read from the record. Markdown opens on a machine with no access to the system
(SC-003).

**Alternatives considered**: HTML companions (heavier, no added fidelity for copy-paste
handoff); rendering in the console and uploading (would put a write path in the console;
the server already holds the bytes and the models).

## R6 — Per-kind renderers with raw fallback (FR-001, FR-002, FR-014)

**Decision**: A renderer registry in the console keyed on `artifact.kind`:
`copy` → sectioned document, `posts` → per-post cards with angle, body, character count,
copy-to-clipboard, `email` → inbox-style preview (bold subject, muted preheader beside it,
body below; subject and body separately copyable), `video_props` → scene-by-scene
storyboard, `site` → R2's preview, `video`/`video_vertical` → R3's players. Content is
parsed with hand-rolled type guards (no schema library — the console has none today and
the shapes are four small objects); a guard failure or unknown kind falls back to the raw
`<pre>` view for that artifact only. Every text artifact keeps a rendered/raw toggle whose
raw side shows `content` verbatim, unmodified. Clipboard writes use
`navigator.clipboard.writeText` with visible success/failure feedback (edge case: denied
clipboard access must not report silent success).

**Rationale**: The kinds are a closed set named by the system's own vocabulary
(spec assumption; `DELIVERABLES` in code), so a switch on `kind` is not client data in
code. Hand-rolled guards keep `package.json` untouched (Constitution VII: no new
dependency for single-use validation).

**Alternatives considered**: zod/valibot (new dependency for four guards); trusting
`JSON.parse` output without guards (FR-014 requires graceful fallback, and acceptance
scenario 6 tests a malformed artifact explicitly).

## R7 — Money formatting from the artifact's own currency (FR-003)

**Decision**: Console side: extract the existing `formatAmount` from
`console/src/routes/approvals.tsx` into `console/src/lib/format.ts` and reuse it — it
already uses `Intl.NumberFormat` with the currency's own minor-unit exponent, exactly the
"no two-decimal guess" rule the video renderer also follows (`video/src/props.ts`). Server
side (the storyboard companion): reuse the minor-exponent table in
`epyhia/ingest/normalise.py` (`_MINOR_EXPONENT`, made importable) to render
`amount_minor` + `currency` from the artifact.

**Rationale**: Both formatters already exist and already encode the zero-decimal-currency
case; adding a third divergent one is the bug. The currency string comes from the
`OnScreenValue` in the artifact — nothing client-derived enters code, and the genericity
source scan (`tests/genericity/test_source_scan.py`, which covers `console/src`) enforces
that mechanically.

**Alternatives considered**: formatting minor units with `/100` (wrong for zero-decimal
currencies — the codebase comments call this out twice); passing a locale (unnecessary;
`undefined` locale follows the operator's browser).

## R8 — Inline violation marking (FR-012)

**Decision**: A pure highlight helper: given a rendered text node's string and the set of
violation `quote` strings for the artifact revision being viewed, split on exact substring
occurrences and wrap each match in a visible `<mark>`-styled span. Applied inside the text
renderers (copy bodies/headlines, post bodies, email subject/preheader/body, storyboard
lines). Every occurrence is marked (edge case: a quote appearing more than once). A quote
with no verbatim occurrence marks nothing and raises nothing — the itemised violation list
(already rendered today in `artifacts.tsx`) remains in all cases.

**Rationale**: Violations quote against stored bytes, so exact substring match is the
correct semantics — fuzzy matching would mark words the check never flagged. Degradation to
the list alone is the spec's own fallback (acceptance scenario 2 of US4).

**Alternatives considered**: offset-based positions from the checker (violations don't
carry offsets today, and adding them would touch grounding — out of bounds per FR-015);
fuzzy/normalised matching (marks text the violation didn't quote; false precision).

## R9 — Revision grouping (FR-013)

**Decision**: Client-side grouping of the existing list response by `kind`: one entry per
deliverable, showing max `revision` by default, with a control to select earlier revisions;
the selected revision's own `grounding_status` and `violations` are what render. No API
change — `GET /runs/{run_id}/artifacts` already returns every revision with its fields.

**Rationale**: The data is already complete in one response; grouping is a presentation
concern. Kind is the grouping key the review loop itself uses (`Artifact.kind` +
`revision` ordering in `epyhia/queue/handlers/video.py` and `site.py`).

**Alternatives considered**: a grouped API shape (server change for a client-side concern;
would ripple into eval and any other consumer of the list).

## R10 — Verification approach

**Decision**: Backend: pytest against the export module as pure functions (layout, manifest
accuracy, hash identity, flagged segregation, companion fidelity, empty-run manifest,
unparseable-content skip) plus router tests through httpx ASGI with
`app.dependency_overrides[require_operator]` — the established pattern in
`tests/integration/test_us4_brand_doc_edit.py` — asserting byte-identity and content-type
on the content endpoint and archive correctness on the pack endpoint. No model calls exist
anywhere in this feature, so CI stays keyless by construction. Console: no JS test runner
exists in `console/package.json` and this feature does not introduce one (Constitution
VII); verification is `tsc -b && vite build` passing plus the quickstart's per-story
scenarios. The genericity source scan already covers `console/src` and will lint every new
renderer for client tokens harvested from all brief fixtures.

**Rationale**: Matches the constitution's verification bar (`uv run ruff check`,
`uv run pytest`) and the repo's existing test topology; the export module is this feature's
gate-analogue — pure, credential-free, and therefore without excuse for being untested.
