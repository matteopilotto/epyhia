# Data Model: Distinctive Generated Sites

No new tables and no Alembic migration. Two entities live in repository data files
(agency infrastructure), one is a semantic tightening of an existing brand-doc field,
and two travel inside a new artifact `kind` on the existing `artifacts` table.

## Font library entry (repository data: `fonts/library.json`)

One typeface the agency owns the right to embed. Validated at load by
`epyhia/design/fonts.py`; the loader failing is an import-time error, never a
per-run surprise.

| Field | Type | Rules |
|---|---|---|
| `id` | string | Stable, kebab-case, unique across the library. The value brand docs name. |
| `family` | string | The CSS `font-family` name the embedded face registers as. |
| `role` | `display` \| `body` \| `both` | A pairing must resolve to a display-capable and a body-capable face. |
| `weights` | array of `{weight, style, file}` | ≥ 1; `file` is a path under `fonts/files/`, pre-subsetted woff2, and must exist. |
| `license` | `{name, file}` | Required. `file` is a path under `fonts/licenses/` and must exist. No license, no entry. |
| `character` | string | One line shown beside the id in the Strategist's prompt. Infrastructure prose, never client data. |

**Invariants**: the library contains no client data (Principle I); any brief may
select any entry; entries are append-friendly but an `id` is never reused for a
different face (brand docs from prior runs name it).

## Type pairing (existing brand doc field, semantics tightened)

`brand_doc.type.{display, body}` — shape unchanged (two non-empty strings; the
`brand-doc.schema.json` structure is untouched), but the values are now **library
ids**, not free-text face names.

**Validation, two layers**:

- *Authoring*: `TypePairing` in `epyhia/agents/strategist.py` validates both ids
  against the library, and role-compatibility (`display` id must have role
  `display`/`both`; `body` id must have role `body`/`both`) — an invalid id raises
  `ModelRetry` inside the Strategist's run.
- *Consumption*: the site stage resolves the pairing before any model call and fails
  fast, naming the unknown id, for any brand doc that predates this validation
  (FR-005; the free-text edge case fails this lookup by construction).

**State note**: existing brand docs are not migrated; a re-run of an old brief goes
through the new prompts and produces a new brand doc version (spec assumption).

## Archetype specification (repository data: `prompts/_archetypes.jinja`)

Each page archetype entry grows from `{id, for}` to:

| Field | Meaning |
|---|---|
| `id` | Unchanged, stable. |
| `for` | Unchanged one-liner (what the archetype suits). |
| `grid` | The grid it commits to. |
| `rhythm` | Spacing cadence between and inside sections. |
| `alternation` | How consecutive sections must differ. |
| `hero_must_not` | The hero constraint (what its hero must not be). |
| `signature` | The one structural move that makes it recognisable. |

Section layout entries keep `{id, for}`. Library grows by ≥ 3 page archetypes and
≥ 4 section layouts at full spec depth. Single-sourced; both the Strategist's and the
Web Builder's prompts import it; client-free (FR-017/FR-018).

## Design finding (value object, inside the design report)

One detected tell, produced by the lint or by the Site Critic.

| Field | Type | Rules |
|---|---|---|
| `source` | `lint` \| `critic` | Which check produced it. |
| `rule` / `kind` | string | Lint: one of the six fixed rule ids. Critic: one of the closed `kind` literals (see `contracts/site-critic.md`). |
| `detail` / `what` | string | Human-readable observation. |
| `where` | string | Selector / section index (lint) or region in words (critic). |

Rule ids and thresholds are enumerated in code once; the only brand-parameterised
inputs (`accent_overuse`, `ignored_pairing`) read the run's own brand doc (FR-009).

## Design report (new artifact `kind="design_report"`)

One JSON artifact per site build, written by the site handler on **every** path
(clean, flagged, skipped, revised). Schema: `contracts/design-report.schema.json`.
Content summary:

| Field | Meaning |
|---|---|
| `lint` | Findings on the original page (possibly empty). |
| `critique` | `{status: clean \| findings \| skipped, findings[], skip_reason?}` — a valid empty punch list is `clean`; unusable output or render/call failure is `skipped` with the reason (research R5). |
| `revision` | `{outcome: not_needed \| kept \| discarded_grounding \| discarded_worse \| discarded_empty \| skipped, findings_before, findings_after?, skip_reason?}` — `discarded_empty` is checked first: a truncated generation satisfies each other keep condition rather than failing one. |
| `screenshots` | `{captured: bool, widths[]}` — whether the render step ran. |

Stored via the existing `PostgresArtifactStore` with `grounding_status="clean"`
asserted by construction — the report is internal telemetry, never published (research
R7). Visible to operators through feature 002's artifact views, alongside the site
artifact it describes (FR-008). Its `revision` column matches the site build it
describes.

## Site artifact (existing `kind="site"`, revision semantics now used)

- Revision 0: the original embedded page, grounding-checked and linted — written
  exactly as today.
- Revision 1: written **only** when a revision pass ran and was kept (grounding clean,
  within budget, lint count not worse). The existing `ORDER BY revision DESC` readers
  (export, console, deploy request) pick up the kept page with no change.
- A discarded revision is not stored as a site artifact; its outcome and finding
  counts live in the design report ("both results are recorded" — the record is the
  report, the artifact of record is the kept page).

## State transitions (site stage, fixed in code)

```text
resolve pairing ──unknown id──▶ stage fails (named error, no model call)
      │
      ▼
build ▶ embed fonts ▶ size check ──over budget──▶ stage fails (visible)
      │
      ▼
grounding check ▶ store site rev 0 ▶ lint
      │
      ▼
screenshot ▶ critique          (any failure here ⇒ skip recorded, continue)
      │
      ▼
findings? ──no──▶ write design_report ▶ request deploy (rev 0)
      │
     yes
      ▼
one revision ▶ embed ▶ size ▶ grounding ▶ re-lint
      │
      ├─ clean & not worse ──▶ store site rev 1 ▶ report ▶ deploy (rev 1)
      └─ else ──────────────▶ keep rev 0 ▶ report (discarded_*) ▶ deploy (rev 0)
```

There is no path with a second revision, and no path where lint findings alone block
the deploy request (FR-010, SC-003).
