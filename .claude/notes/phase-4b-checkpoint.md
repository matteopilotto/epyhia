# Phase 4b checkpoint — findings

**Date**: 2026-08-05 · **remediated 2026-08-08**
**Branch**: `feat/phase-4b-rest-of-pack` (T078–T088 complete, `aeac8e3`)

**Original verdict**: **FAIL — do not start Phase 5.** The mechanical half passes in full.
The two checks that need real models and a person both fail, and one of them found a live
path to a wrong page.

**Current verdict**: **PASS.** Every blocking finding below is closed on
`feat/phase-4b-remediation` and proved by one real end-to-end run — §8. §5.2 is the only
finding still open, and it does not block Phase 5.

> Sections 2–7 stand as written. They are the record of what the checkpoint found, not a
> description of the code today; each finding since closed carries a **Resolved** line
> naming the commit and where the evidence is.

---

## 1 · Results

| Check | Source | Result |
|---|---|---|
| Non-negotiable #1 — the gate needs no agents, credentials or network | tasks.md §"two checkpoints" | ✓ verified |
| Non-negotiable #2 — the deploy refusal lives in the gate, not the Web Builder | tasks.md §"two checkpoints" | ✓ verified |
| Independent test (a) — every numeral traces to `runs.grounding_set` | Phase 4 header | ✓ 7 traced, 0 ungrounded |
| Independent test (b) — a fabricated numeral in a draft is held | Phase 4 header | ✓ T086 |
| Independent test (c) — a fabricated numeral in the site → the gate refuses | Phase 4 header | ✓ T087 |
| **Checkpoint 4a — read the page against that brief's own `products[]`** | after T077 | ✗ FAIL → ✓ **passes** (§8) |
| **Checkpoint 4b — US1 and US2 both work independently** | after T088 | ✗ cannot pass → ✓ **passes** (§8) |

Non-negotiable #1 was verified rather than asserted: `tests/gate/` was run with every
provider credential emptied on the command line (`load_dotenv()` does not override an
already-set variable, so this genuinely hides `.env`), under a socket guard rejecting any
non-loopback connect, with `sys.modules` inspected at session end. 19 passed, zero agent
modules imported, zero credentials configured, zero non-loopback egress.

---

## 2 · BLOCKING — a flagged artifact reached a deployable page

The most serious finding, and the reason the checkpoint exists.

On a real run of `my-brief.json` (Ashgrove Bakehouse), the Reviewer flagged the `copy`
artifact with three violations. One of them:

```json
{
  "kind": "unsupported_claim",
  "quote": "Your bread is reserved under your name until 2pm.",
  "why": "The brief states the loaf is 'Reserved under your name until 2pm' only for the
          Weekend Loaf Preorder product. The draft presents this as a universal statement
          ... the Pastry Box Preorder has no stated hold time, and the Standing Bread Order
          is a weekly subscription with different terms."
}
```

That artifact was stored `grounding_status = 'flagged'`. The `site` task then consumed it
anyway, and the sentence is on the rendered page in an `<h3>`:

```html
<h3>Your bread is reserved under your name until 2pm.</h3>
```

The resulting `site` artifact is `grounding_status = 'clean'` — correctly, since the numeral
check is numeral-only by design and `2pm` does trace to the brief. The **scope** of the claim
is what is unsupported, and no numeral check can see that. The `deploy` action was created
and parked at `awaiting_approval`: one operator click from live.

### Root cause

[`epyhia/queue/handlers/site.py:47-53`](../../epyhia/queue/handlers/site.py) — the copy
artifact is selected by revision with **no `grounding_status` filter**:

```python
copy_artifact = (
    await session.execute(
        select(Artifact)
        .where(Artifact.run_id == run.id, Artifact.kind == "copy")
        .order_by(Artifact.revision.desc())
    )
).scalars().first()
```

T077 made `copy` *block* `site` as a dependency edge. Blocking is ordering, not gating — a
flagged copy is consumed silently.

### Why it matters

This is `DESIGN.md` §9.2's own argument one level up:

> A control that guards outbound copy while the same fabricated price sits in an `<h2>` on
> the live site is not a control; it is a report.

The numeral hold works. The Reviewer's hold does not: FR-024 says a flagged artifact is
"surfaced rather than delivered", and being consumed by the Web Builder is delivery.

### Suggested fix

The site task should refuse a `copy` artifact that is not `clean`, in the same shape as the
gate's existing `deploy` precondition. Cheapest of the three fixes and verifiable with no
model spend.

**Resolved** — `7840168`. `handle_site` raises `UpstreamNotClean` for a missing or non-clean
copy artifact, before `build_site`, so a flagged copy costs no model call and produces no
site artifact and no deploy request. `tests/queue/test_site_handler.py` covers both cases
with zero model spend. It fired for real three times during the remediation, which is how
the convergence problem in §8 was found — the guard held every time.

---

## 3 · Checkpoint 4a — the page states almost nothing the brief gave it

The 4a assertion is: *"every offering name, every stated day, time and inclusion, and every
price on the page must trace to the brief."* Read against `my-brief.json`:

| From the brief | On the page |
|---|---|
| `Weekend Loaf Preorder` / `Pastry Box Preorder` / `Standing Bread Order` | **none of the three named** |
| £6.50 · £15.00 · £12.00 | **absent** |
| 900g · 7am · 9am · 24 hours · six pastries · two loaves | **absent** |
| — | 895 words, no `data-product` slug |

Put beside what `tasks.md` recorded of the **pre-T077** run:

> "…it invented one: offering names, pickup days and inclusions that contradicted the brief,
> **with none of the brief's prices anywhere**."

T077 fixed the fabrication. **The omission is unchanged** — the prices are still missing, and
now the offering names are too. The brief's own voice rule is *"Talk about the bake and the
pickup time in concrete terms"*, and nothing on the page does.

Note the grounding check structurally cannot catch this: it only finds numerals that should
not be there, never numerals that should. A page stating no facts is trivially `clean`.

**Resolved** — `b463f8f`, `5501fb1`, `131d0a8`. Not a prompt problem: the brand doc schema
had no field for products, prices or times, and the Marketer is given only the brand doc, so
the fact channel did not exist and the prompts' anti-fabrication pressure was working
correctly on empty input. `offerings[]` is that channel. All three names and all three
prices are now on the page and in every pack deliverable — §8.

---

## 4 · Checkpoint 4b — cannot pass as written

There is **no `demand` task handler**. `posts`, `email` and `video_props` are unreachable
through the pipeline; only `copy` runs, as part of US1's chain. Every pack artifact in this
checkpoint was produced by calling `epyhia.queue.handlers.pack.produce` directly from a
driver script.

So "US2 works independently" is currently true of the hold and gate behaviours, and false of
the pack itself. `video` is registered as a handler and works, but nothing enqueues it.

This was flagged as an open item when Phase 4b closed; it is now a checkpoint blocker.

**Resolved** — `635da0d`. `epyhia/queue/handlers/demand.py` produces `posts`, `email` and
`video_props` through `pack.produce`, then enqueues the `video` task in the same commit as
its own `done` transition. The enqueue is **unconditional**, including when `video_props` is
flagged: the refusal already lives in `video.py`, and duplicating it at the enqueue would be
the inverse of the §2 mistake — a failed task naming its reason is surfaced, a task never
created is invisible. `tests/integration/test_demand_pack.py` covers both.

---

## 5 · Secondary findings

### 5.1 `uv run pytest` destroys real run data

[`tests/integration/conftest.py:25`](../../tests/integration/conftest.py) runs
`TRUNCATE actions, artifacts, agent_calls, tasks, runs, brand_docs, briefs CASCADE` against
`settings.database_url` — the **same** database the app uses. There is no separate test
database.

Two real runs (~$0.60 of model spend) were wiped by running the test suite between them.
Sequence real runs *after* test runs, and export anything worth keeping. Worth considering a
separate `DATABASE_URL` for tests before more real-model work happens.

**Resolved for the app database** — `7af64be`. A `TEST_DATABASE_URL` knob, defaulting to
`epyhia_test`, with `tests/conftest.py` raising `RuntimeError` rather than skipping if it
equals `settings.database_url`; schema comes from alembic run once per session in a
subprocess with the override in its env.

**The hazard is not gone, it has moved.** Real runs are now pointed at `epyhia_test` too, so
`uv run pytest` still truncates the ledger the run just wrote. This bit twice during the
remediation and destroyed the cost rows both times. Export before running the suite — the
run driver writes `preview/` only after *all* stages succeed, so a mid-run crash leaves the
artifacts in Postgres and nowhere else.

### 5.2 The video archetypes load no fonts

No `@font-face`, no `@remotion/google-fonts`, no font loading of any kind in `video/src`. The
brand doc's `type.display` / `type.body` are passed straight to CSS `fontFamily`, so an
uninstalled face silently falls back to the browser default.

Observed: brand docs asked for `Bodoni Moda` / `Söhne` and `Fraunces` / `Karla`; none were
installed; all four renders used Chrome's default serif. This also means the same props
produce different output on a Mac and in the Fly container — the render is not reproducible.

The design treats page and video archetypes as **closed libraries the Strategist selects
from**. Type arguably needs the same treatment: a shipped pairing library rather than a free
string, since a commercial face like Söhne cannot be loaded at all.

**Still open** — deferred by decision; does not block Phase 5. Unchanged by the remediation:
the §8 run's brand doc asked for `Fraunces` / `Karla`, and its `video` task was enqueued but
never run, so the render remains the one part of the pipeline no real run has exercised.

### 5.3 The Marketer never populates `values` in video props

Two real runs, two different businesses, **zero** `values` entries — so no price, weight or
time ever appears on screen, and the archetypes' priced chips and spec rows go unexercised in
practice. Same abstraction problem as §3, in the pack rather than the site.

Candidate causes, not yet established:
- `prompts/marketer/v1.jinja` does not push toward concrete specifics or toward `values`
- `prompts/reviewer/v1.jinja` has no check for "states the brand doc's facts concretely", so
  vagueness is never a violation

**Resolved** — same root cause as §3, and it closed with it. Both candidates were real but
secondary: the prompts now push toward `values` (`5501fb1`) and the Reviewer gained a
`missing_fact` kind (`131d0a8`), but neither would have helped while the Marketer had no
prices to state. In the §8 run every offering scene carries its price in `values` as a
labelled minor-unit amount with a currency.

### 5.4 Fixed in passing

The console dev server never reached the API: `API_BASE` was
`VITE_API_BASE_URL ?? ""` and an empty override is a string rather than nullish, so requests
went to relative paths Vite answered with `index.html`. Meanwhile the dev proxy forwarded
`/api`, which nothing requested. Fixed on `fix/console-dev-proxy` (`1891707`), cherry-picked
onto this branch as `32eb0d2`.

---

## 6 · Reproducing

Scripts live in the session scratchpad and are **not** committed:

| Script | What it does |
|---|---|
| `checkpoint.sh` | The 9 mechanical checks. No model spend. |
| `netguard.py` | pytest plugin: socket guard + agent-import + credential assertions |
| `drive_checkpoint.py` | `plan → copy → site` + the pack, exports artifacts, traces every numeral. ~$0.94 |
| `drive_video.py` | Brief → brand doc → video props → both cuts rendered. ~$0.22–0.38 |

The drivers stand in for the missing `demand` handler; everything they call is production
code.

**Superseded** — `d33d46a` gave the committed driver a `--stages` flag, so one command now
covers both checkpoints and nothing stands in for a handler:

```sh
DATABASE_URL="postgresql+asyncpg://epyhia:epyhia@localhost:5432/epyhia_test" \
  uv run python scripts/preview_site.py --real --brief my-brief.json --stages site,demand --open
```

`site` closes over `copy` through the fixed dependency edges, so the selection above runs
`copy → site → demand`. The deploy is a `FakeDeploy` and `money` is not selected, so nothing
leaves the machine. Two scratch harnesses were also useful and are **not** committed:
`replay_reviewer.py` (~$0.008/call, reviews a frozen draft) and `replay_copy_loop.py`
(~$0.09–0.21/trial, the full draft → check → revise loop with no strategist and no site) —
worth rebuilding before any further prompt work, since they cost ~1/10th of a run per data
point.

Run of record: `f1f28a7b-7dd3-48f6-b61b-c58d4c27fc67`, 17 literal / 26 derived grounding
entries, $0.9414 model spend, archetypes `catalogue_grid` / `editorial_warm`.

---

## 7 · Recommended order

1. **`site.py` must refuse a flagged `copy` artifact.** Small, structural, no model spend to
   verify. Arguably a missed part of T077. Closes the live path to a wrong page.
2. **Prompt work so the page and pack state the brief's concrete facts.** This is what
   checkpoint 4a exists to catch; touches Phase 4a's deliverables (`prompts/web_builder`,
   `prompts/marketer`, possibly `prompts/reviewer`).
3. **A `demand` task handler.** Makes US2 independently runnable and closes checkpoint 4b.

Items 5.1 and 5.2 are worth scheduling but do not block Phase 5.

**All three done**, in that order, plus 5.1. Item 2 was misdiagnosed here as prompt work —
see §3. The plan as executed is `.claude/plans/phase-4b-remediation.md`.

---

## 8 · Remediation and the verifying run (2026-08-08)

Branch `feat/phase-4b-remediation`, 17 commits on top of `32eb0d2`.

### What the fixes turned out to be

**The 4a failure was structural, not prompt-level** — see §3. `offerings[]` in the brand doc
is the fact channel that did not exist: each entry mirrors `brief.products[]` field for
field minus `currency_charge` (Ops' charging detail), copied verbatim by the Strategist, and
required with `minItems: 1` so it cannot be quietly omitted. Typed named fields keep the
containment argument intact — there is still no free-prose channel into the Marketer.

Three further defects only appeared under real models, none of them visible offline:

- **The copy loop would not converge.** The Reviewer was using `why` as a scratchpad,
  shipping entries that read "this is correct" or retracted themselves inside their own
  sentence, and each one spent one of the writer's two revisions on nothing. Extended
  thinking gave it somewhere else to work (`05a89d7`): 0/3 converging → 4/4, three of them
  on the first round. Haiku 4.5 predates adaptive thinking, so the budget is the explicit
  `{"type": "enabled", "budget_tokens": N}` form.
- **Then that ceiling was too tight** (`3af1d86`). The thinking budget is a *target*, not a
  stop, and `max_tokens` caps thinking and response together. On identical input the
  Reviewer's output ran 3,752 / 10,240 / 6,820 / 5,848 tokens against a nominal 4,096 — so
  at `max_tokens=8192` roughly one call in four came back holding only thinking, which
  PydanticAI raises as `UnexpectedModelBehavior` and which fails the whole stage. Raised to
  16,384; unused ceiling costs nothing, a dead run costs a run.
- **`find_amounts` crashed the demand handler** (`db84d6b`). The digit-token regex matched
  runs across `\s`, but `_parse_digit_token` strips with `_SEPARATOR_CHARS`, which knows
  only a literal space — so a line break survived the strip, reached `Decimal` intact and
  raised `ConversionSyntax`. `"ready 6.50\n15.00 box"` was one token. This is the digit-side
  twin of `c8a631e`, which had fixed the same defect on the number-word side; only half of
  it was fixed then. The word side lied (invented a phantom numeral), the digit side raised.

Two prompt-level findings worth keeping, both of which cost real runs before being caught:
the Strategist hardened a brief's `do: "Keep sentences short"` into a `dont` stated as a
word count and then miscounted against it (`a0f2c04` — a `dont` must be checkable by
reading, never by measuring); and the Marketer read a `dont`'s examples as the whole of what
it forbids, rephrasing a flagged line into another wording of the same move (`0c839b0`).

### The run

`fdddde71-e19a-4fbf-9264-7a1f533bb1d8` · `my-brief.json` · `--stages site,demand` against
`epyhia_test` · 17 literal / 26 derived grounding entries · **$0.7933**, computed through
`epyhia/cost/pricing.yaml`.

| Artifact | Revision | Grounding |
|---|---|---|
| `copy` | 0 | clean |
| `site` | 0 | clean, 20,211 bytes |
| `posts` | 1 | clean |
| `email` | 0 | clean |
| `video_props` | 0 | clean |

Four of the five passed review on the first attempt; only `posts` spent a revision.

**Checkpoint 4a** — all three offering names and all three prices are on the page, and in
every one of the four deliverables. `900g`, `7am`, `2pm`, `24 hours` all present. Every
specific checked traces to the brief: "Nut-free box on request in the order notes" is
verbatim from that product's `features`.

**Checkpoint 4b** — `demand` ran through `run_once` and produced the whole pack; the `video`
task was enqueued `pending`.

**Deploy** — `awaiting_approval → succeeded`, evidence
`{"status": 200, "matched_name": "Ashgrove Bakehouse"}`. The probe string was read from
`brand_doc.name` at verify time, which is the invariant holding in the place it is easiest
to break.

Spend by agent: `web_builder` $0.3806 · `marketer` $0.1706 · `strategist` $0.1479 ·
`reviewer` $0.0942.

### Open, and not blocking

- **§5.2 fonts**, and with them the Remotion render — the only stage no real run has
  exercised.
- **The Web Builder returned 24,349 output tokens in 240s on one non-streamed call.** Under
  the ceiling, but `DESIGN.md` calls for streaming it precisely because a truncated site is
  syntactically plausible and would deploy. Worth checking whether `build_site` streams.
- **The T118/T119 genericity lint does not exist.** Prompts and tests were checked by grep
  for client tokens; two hits were confirmed pre-existing and unrelated (a `360px` CSS
  breakpoint, and a currency literal inside the currency normaliser's own unit test).
