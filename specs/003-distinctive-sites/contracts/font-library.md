# Contract: The Font Library

The curated, openly licensed typeface library the agency owns (`fonts/` at the
repository root). Agency infrastructure under Principle I: it contains no client data,
and any brief may select from all of it.

## Layout

```text
fonts/
├── library.json          # The registry — the single source
├── files/                # Pre-subsetted woff2, one file per (face, weight, style)
│   └── <id>-<weight>[-italic].woff2
└── licenses/             # One license text per family (SIL OFL or equivalent)
    └── <family>.txt
```

## Registry entry

```json
{
  "id": "example-display",
  "family": "Example Display",
  "role": "display",
  "character": "high-contrast transitional serif; editorial, warm",
  "weights": [
    {"weight": 400, "style": "normal", "file": "files/example-display-400.woff2"},
    {"weight": 700, "style": "normal", "file": "files/example-display-700.woff2"}
  ],
  "license": {"name": "SIL OFL 1.1", "file": "licenses/example-display.txt"}
}
```

Rules (enforced by the loader in `epyhia/design/fonts.py` at import time):

- `id` is unique, kebab-case, and stable — never reused for a different face, because
  brand docs from prior runs name it.
- `role` ∈ `display` | `body` | `both`. A pairing must resolve to one display-capable
  and one body-capable entry.
- Every `file` exists and is woff2; every entry has a `license` whose `file` exists.
  No license, no entry.
- `character` is one line of infrastructure prose (shown beside the id in the
  Strategist's prompt) and, like every field here, names no client.

## Consumers

| Consumer | What it reads | How |
|---|---|---|
| Strategist prompt | `id`, `role`, `character` | Passed as render context by `strategist.py`; the template lists selectable ids |
| Strategist output validation | `id`, `role` | `TypePairing` membership + role check → `ModelRetry` on failure |
| Site stage (fail-fast) | `id`, `role` | Pairing resolved before any model call; unknown id fails the stage naming it |
| Injector (`embed_fonts`) | `family`, `weights`, files | ids → `@font-face` rules with base64 `data:font/woff2` URIs, one `<style id="epyhia-fonts">` block after `<head>` |
| Web Builder scoped inputs | `family` | Resolved family names (with generic fallbacks) handed in the user-message JSON; the model writes `font-family` against them and never sees font bytes |
| Design lint (`ignored_pairing`) | `family` | The run's brand doc ids resolved to families; the page's `font-family` declarations checked against them |

## Curation (reproducible, out-of-band)

Faces enter the library pre-subsetted; subsetting is a curation step, not a build
step, and `fonttools` is not a project dependency.

Sources are the OFL directories of `google/fonts`. Most upstream sources are variable
fonts, so each registry weight is first pinned to a static instance — a registry entry
is one file per (face, weight, style), never an axis range:

```bash
fonttools varLib.instancer -o <id>-<weight>.ttf "<source>[wght].ttf" wght=<weight>
```

Then, for every weight file (and directly for sources that ship static):

```bash
pyftsubset <source>.ttf \
  --unicodes="U+0000-00FF,U+2000-206F,U+20A0-20CF,U+2122,U+2212" \
  --layout-features="kern,liga,calt" \
  --flavor=woff2 --output-file=fonts/files/<id>-<weight>.woff2
```

Target: ≤ ~40 KB per weight file, so a worst-case pairing stays far inside the page
budget.

## Failure modes

| Condition | Behaviour |
|---|---|
| Brand doc names an id not in the library | Site stage fails before generation: `unknown font id: <id>` (FR-005) |
| Brand doc predates ids (free-text face name) | Same failure — free text never matches an id (spec edge case) |
| Id resolves but role is incompatible | Same fail-fast, naming id and role |
| Finished page + fonts exceeds 1 MiB (1,048,576 bytes) | Build fails visibly; the task fails and the operator sees it (FR-006) |
| Registry invalid (missing file, missing license, duplicate id) | Loader raises at import — a repository defect, not a run-time condition |

## Guarantees

- The finished page remains one self-contained document making zero external requests
  (FR-003, SC-004); the faces travel as data URIs inside it.
- Embedded font data contributes nothing to the grounding scan: the extractor skips
  `<style>`, and a test proves scan equality with and without fonts (FR-004, SC-005).
- The model never authors font data; injection is mechanical and post-generation.
