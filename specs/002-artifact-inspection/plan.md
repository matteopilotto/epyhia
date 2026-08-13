# Implementation Plan: Artifact Inspection & Pack Download

**Branch**: `002-artifact-inspection` | **Date**: 2026-08-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-artifact-inspection/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Make every artifact a run produces inspectable in the console in its natural form, and the
whole deliverable pack downloadable in one action. Server side, two new authenticated reads:
`GET /artifacts/{id}/content` (verbatim bytes, correct content type — the delivery path for
video playback, site preview, and downloads) and `GET /runs/{id}/pack` (an in-memory zip
with a hash-carrying manifest, flagged artifacts segregated with their violations, and
mechanical Markdown companions for the structured text deliverables). Console side, per-kind
renderers with a guarded parse and raw fallback, blob-URL media delivery so auth stays on
the one Bearer path, a sandboxed site preview, revision grouping, and inline marking of
violation quotes. No new persistent data, no migration, no new dependency on either side;
every added operation is a read (FR-015).

## Technical Context

**Language/Version**: Python ≥3.13 (backend); TypeScript 5.7 / React 18 (console)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, stdlib `zipfile` (backend — no
additions); TanStack Router/Query, Tailwind, shadcn/ui primitives (console — no additions)

**Storage**: Postgres — the existing `artifacts` table, read-only; no schema change, no
migration

**Testing**: `uv run pytest` (+ `pytest-asyncio`, httpx ASGI, `dependency_overrides` for
auth, per `tests/integration/` precedent); console verified by `tsc -b && vite build` plus
quickstart scenarios — no JS test runner exists and none is introduced

**Target Platform**: Fly.io `web` process (same image) + operator's browser (SPA)

**Project Type**: Web application — existing `epyhia/` backend + `console/` SPA

**Performance Goals**: Pack assembly and media transfer proportionate to the spec's size
assumption (text deliverables, short launch videos; whole-content transfer per artifact);
media loads asynchronously so the console view never freezes during transfer

**Constraints**: Read-only against run state (FR-015); single auth path — Bearer on every
retrieval including media, no token in query strings, no cookies (FR-007/FR-057); no client
data in code, enforced by `tests/genericity` which scans `epyhia`, `console/src`, and
`video/src` (Constitution I); CI keyless — this feature makes no model call

**Scale/Scope**: Single-operator console; ~7 artifact kinds, a handful of revisions per
run; two API endpoints, one export module, one reworked console route

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | How this plan complies |
| --- | --- | --- |
| I. Client Data Never in Code | PASS | Renderers switch on `artifact.kind` — the system's own closed vocabulary, not client data. Currency comes from each `OnScreenValue` in the artifact (FR-003), formatted via the existing exponent-aware helpers (research R7). Filenames derive from `artifact.path` and `run_id`. The genericity source scan covers all new code paths (`console/src` included) and the console renders a second client's run with no code change (SC-006). |
| II. Design-First, Sequenced Build Order | PASS | DESIGN.md's build order (§12) governs feature 001, complete through Phase 8; this is a new specced feature layered on those records. Nothing here touches architecture DESIGN.md fixes — the gate, pipeline, grounding, and idempotency layers are untouched. The auth stance for media follows DESIGN.md §10's token-plus-Bearer reasoning (the SSE precedent). |
| III. Fixed Pipeline, Tiered Agents | PASS | No agent is added, called, or modified; the feature makes zero model calls. |
| IV. Action Gate Governs Consequential Egress | PASS | Both new endpoints are operator-authenticated reads of stored records — the same class as the existing `GET /artifacts/{id}`. Nothing deploys, charges, sends, or publishes; the gate's line (§4.1: egress with consequences) is not crossed by an operator pulling bytes the system already holds. No credential is touched; the app still starts without Stripe/Vercel configured. |
| V. Idempotency by Brief Hash | PASS | No gate action, no idempotency key, no write. The pack is assembled per request and never stored, so there is nothing to key. |
| VI. Grounding Before Opinion | PASS | Grounding is read, never altered: statuses and violations are displayed (inline marks are exact-substring matches against stored quotes, research R8), and flagged artifacts remain visible — now segregated-and-included in the pack too (FR-010), extending feature 001's FR-024 guarantee rather than weakening it. |
| VII. Simplicity, Surgical, Goal-Driven | PASS | No new dependency (stdlib zip, hand-rolled type guards, native `<video>`); no new knob, so no config/`.env.example` change; the only touch outside feature files is extracting `formatAmount` into `console/src/lib/format.ts` for reuse (two call sites). Export logic is pure and credential-free — tested like the gate is. Verification bar: `uv run ruff check`, `uv run pytest`, console build, quickstart. |

**Post-design re-check** (after Phase 1): still PASS — the contracts introduce reads only,
the manifest schema carries no client value, and the archive layout names come from
`artifact.path`/`kind`. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-artifact-inspection/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── rest-api.md
│   └── pack-manifest.schema.json
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
epyhia/
├── api/routers/
│   ├── artifacts.py         # MODIFIED: add GET /artifacts/{id}/content
│   └── export.py            # NEW: GET /runs/{id}/pack (module named to avoid
│                            #   colliding with queue/handlers/pack.py; route path
│                            #   keeps the spec's name)
├── export/                  # NEW: pure, credential-free assembly logic
│   ├── __init__.py
│   ├── archive.py           # zip layout, manifest, flagged segregation
│   └── companions.py        # mechanical Markdown from the stored records
└── ingest/normalise.py      # MODIFIED: minor-exponent table made importable (R7)

console/src/
├── routes/
│   ├── artifacts.tsx        # REWORKED: revision grouping, renderer dispatch,
│   │                        #   raw toggle, pack download control
│   └── approvals.tsx        # MODIFIED: import formatAmount from lib/format
├── components/artifacts/    # NEW: per-kind renderers
│   ├── CopyDoc.tsx          # sectioned document
│   ├── PostCards.tsx        # cards with angle/body/char count/copy
│   ├── EmailPreview.tsx     # inbox-style subject/preheader/body
│   ├── Storyboard.tsx       # ordered scenes, money via lib/format
│   ├── SitePreview.tsx      # sandboxed iframe, width toggle, new-tab wrapper
│   ├── VideoPlayers.tsx     # both cuts, vertical in phone frame
│   └── guards.ts            # hand-rolled shape guards → raw fallback
└── lib/
    ├── format.ts            # NEW: formatAmount extracted from approvals.tsx
    ├── content.ts           # NEW: authenticated fetch → Blob/object URL helpers
    └── highlight.ts         # NEW: exact-substring violation marking

tests/
├── export/                  # NEW: archive layout, manifest hashes, segregation,
│   │                        #   companions, empty run, unparseable content
└── integration/
    └── test_us_artifact_views.py  # NEW: content endpoint byte-identity + auth,
                                   #   pack endpoint end-to-end over seeded rows
```

**Structure Decision**: Extend the existing two-tier layout in place — backend logic in a
new `epyhia/export/` module kept pure so it tests without the app, thin routers in
`epyhia/api/routers/`, and all display work inside `console/src` with new components under
`components/artifacts/`. No new top-level project, no new process.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations to justify.
