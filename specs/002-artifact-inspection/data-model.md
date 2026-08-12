# Data Model: Artifact Inspection & Pack Download

**Feature**: `002-artifact-inspection` | **Date**: 2026-08-12

**No new persistent data.** This feature reads the existing `artifacts` table
(`epyhia/models/artifacts.py`) and writes nothing — no new table, no new column, no
migration (FR-015, spec assumption "no new persistent data"). What follows are the read
models and transient structures the feature derives from that one table.

## Existing entity (read-only)

### Artifact — `artifacts` table, unchanged

| Field | Type | Used by this feature for |
| --- | --- | --- |
| `id` | UUID | Content endpoint address, React keys |
| `run_id` | UUID | Scoping the list and the pack to a run |
| `kind` | str | Renderer selection, revision grouping, manifest, companion selection |
| `path` | str | Download filename, archive member name |
| `content_type` | str | HTTP content type on the content endpoint, inline-vs-binary split |
| `bytes` | bytea | The content itself — served verbatim, zipped verbatim |
| `sha256` | str | Manifest hash for record files (ties archive to audit trail) |
| `grounding_status` | str | clean/flagged split in views and archive segregation |
| `violations` | JSONB | Itemised list, `flagged/*.violations.json`, inline-mark quotes |
| `revision` | int | Grouping (max = latest), manifest, revision selector |
| `created_at` | timestamptz | Display ordering |

Kinds are the closed set the pipeline writes: `copy`, `posts`, `email`, `video_props`
(JSON, from `epyhia/queue/handlers/pack.py`), `site` (`text/html`, `index.html`),
`video` / `video_vertical` (`video/mp4`). An unknown kind is legal input and renders raw
(FR-014).

## Deliverable content shapes (parse targets, not storage)

The source of truth is `epyhia/agents/marketer.py`; the console's type guards and the
export module's companion renderers parse against these shapes and fall back on mismatch.

- **copy** — `{ sections: [{ section, headline, body }] }` (≥1 section)
- **posts** — `{ posts: [{ angle, body }] }` (3–5 posts)
- **email** — `{ subject, preheader, body }`
- **video_props** — assembled form (`assemble_video_props`):
  `{ archetype_id, content: { headline, subhead?, scenes: [{ kind, lines[], values?: [{ label, amount_minor, currency }] }], cta? }, style }`.
  Money rendering reads `amount_minor` + `currency` from each `OnScreenValue` — the
  currency is data carried by the artifact, never by code (FR-003).

## Derived view models (console, transient)

### DeliverableGroup (FR-013)

Client-side grouping of the list response, no API change:

| Field | Derivation |
| --- | --- |
| `kind` | Grouping key |
| `revisions` | All artifacts of the kind, ordered by `revision` |
| `selected` | Defaults to max `revision`; operator-switchable |

The selected revision's own `grounding_status` and `violations` drive the badge, the
itemised list, and inline marking — never the group's other members'.

### RenderOutcome (FR-001, FR-014)

Per artifact: `rendered` (kind-specific component over guarded parse) or `raw`
(verbatim `content` in a `<pre>`). Raw is always reachable via toggle (FR-002); it becomes
the *only* state when the guard fails or the kind is unknown. Failure is contained to the
one artifact.

### Inline marks (FR-012)

For the artifact revision in view: the set of `violations[].quote` strings. A text node's
render splits on exact occurrences and wraps each in a mark. No offsets are stored or
added; quotes that never occur verbatim produce zero marks and no error.

## Transient archive structures (server, per request — never stored)

### Deliverable pack (FR-008, FR-010)

Assembled in memory by `epyhia/export/` from one query: latest revision per kind for the
run.

```text
pack-{run_id}.zip
├── manifest.json
├── deliverables/                 # grounding_status == "clean" only
│   ├── <artifact.path>           # record file, bytes verbatim
│   └── <stem>.md                 # companion (copy, posts, email, video_props only)
└── flagged/                      # everything not clean — included, segregated (FR-010)
    ├── <artifact.path>
    ├── <stem>.violations.json    # that revision's itemised violations
    └── <stem>.md                 # companion, when the kind has one and content parses
```

Rules: a flagged latest revision ships in `flagged/` even when an earlier revision was
clean; nothing is silently dropped; a run with no artifacts produces a valid archive whose
manifest lists zero files; a record whose content fails to parse ships without a companion
(the record is the artifact of record — spec assumption).

### Pack manifest (FR-009)

`manifest.json` at archive root — schema in
[contracts/pack-manifest.schema.json](./contracts/pack-manifest.schema.json):

| Field | Content |
| --- | --- |
| `run_id` | The run the pack was assembled from |
| `generated_at` | Assembly timestamp (UTC, ISO 8601) |
| `files[]` | One entry per contained file, `manifest.json` excepted |

Each `files[]` entry: `archive_path`, `kind`, `role` (`record` \| `companion` \|
`violations`), `revision`, `grounding_status`, `content_type`, `sha256`. For `record`
entries the hash is copied from the artifact row — equality with the zipped bytes is what
ties the archive back to the audit trail (SC-004). For derived files (`companion`,
`violations`) the hash is computed at assembly over the emitted bytes.

## State transitions

None. Every operation this feature adds is a read; no status field anywhere changes value
because of it (FR-015).
