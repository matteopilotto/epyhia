# Quickstart: validating EPYHIA

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

How to prove each user story actually works. Nothing here is implementation — it is the run
guide and the evidence to read. Implementation lands in `tasks.md`.

**Nothing in this file names a client.** Every expected value is read from the run's own brief
or brand doc, exactly as the system's own probes do. That is deliberate: a quickstart that
grepped for a business name would be the first violation of Principle I.

---

## Prerequisites

| | |
|---|---|
| Required | Docker, `uv`, Node 22 |
| Not required to start | Stripe keys, Vercel token, an Anthropic key, any account signup |

The last row is the point. The app **starts** without credentials and fails only at the
specific gate action (FR-064, SC-010).

```bash
git clone <repo> && cd epyhia
cp .env.example .env          # names and safe local defaults only — no real keys
docker compose up             # Postgres + Mailpit + web + worker
```

`docker compose up` is the whole setup (FR-065, §11). Migrations run via
`alembic upgrade head`, the same ones that run on Fly.

To exercise the paths that reach the world, add to `.env`: `ANTHROPIC_API_KEY`,
`STRIPE_SECRET_KEY` (test mode), `VERCEL_TOKEN`.

```bash
uv run ruff check && uv run pytest    # must pass with no API key set
```

---

## S0 · The gate, before any agent exists

Build-order step 2 (§12), and the only scenario that needs nothing at all — no agents, no
credentials, no network.

```bash
uv run pytest tests/gate/
```

| Assert | Requirement |
|---|---|
| An approval-required action lands `awaiting_approval` **before** anything is raised | FR-038, R7 |
| Kill the process mid-pause, restart, approve → **one** execution, same key | FR-038, SC-008 |
| Two concurrent requests on one key → one execution, one row, second reads the first's result | FR-044, SC-003 |
| `verify()` that never passes → retry cap → `failed`, never `succeeded` | FR-041, SC-002 |
| `succeeded` with null evidence → rejected by the CHECK constraint | FR-040 |
| Deny is terminal; nothing executes for that key, ever | FR-036 |
| Missing credential → `credential not configured: <provider>`, not a stack trace | FR-064, SC-010 |

Run these against a **fake adapter**. If they need an agent or a key, the gate has been built
wrong (§4.6).

---

## S1 · Brief → verified live website (US1, P1)

```bash
# submit a brief for a business the system has never seen
curl -X POST localhost:8000/briefs -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' --data @<your-brief>.json
# → 201 {run_id, brief_id, content_sha256, alias}
```

Watch `GET /runs/{id}/events`. When the deploy reaches `awaiting_approval`, the console shows
the target URL, the projected cost and **the idempotency key** (FR-039). Approve it.

**Verify — read the record, do not trust the timeline:**

```sql
SELECT state, evidence FROM actions WHERE action_type='deploy' AND run_id=:run;
```

| Assert | Requirement |
|---|---|
| `state = 'succeeded'` **and** `evidence` holds `{status: 200, matched_name, matched_build_marker}` | FR-018, FR-019, SC-002 |
| `matched_name` equals `brand_docs.doc->>'name'` for this run — **read from the row, never a literal** | FR-059, SC-001 |
| Opening the alias in a browser presents that business | SC-001 |
| Zero source files changed to get here | SC-001 |

**The negative case that matters most.** Force the alias to keep serving the previous build,
re-run: the action must land `failed`, because the probe asserts *this build's* marker and not
merely that some page exists (US1 scenario 6). A deploy that only checks for `200` passes this
and is wrong.

**Deny path**: deny instead of approving → nothing published, row permanently `denied` with the
deciding identity recorded (US1 scenario 4).

---

## S2 · A pack that cannot state a fact the brief did not give it (US2, P2)

Let the run produce `copy`, `posts`, `email` and `video_props`.

| Assert | How | Requirement |
|---|---|---|
| Every numeral in every delivered artifact traces to `runs.grounding_set` (`literal ∪ derived`) | Set-difference each artifact against the run's own row | FR-022, SC-004 |
| The numeric check ran **before** any model was asked an opinion | Ordering is deterministic in code, not a prompt instruction | Principle VI |
| The Reviewer returned **itemised** violations, never a silent approval, and never a rewrite | `artifacts.violations` | FR-023 |
| A failing draft got **at most two** revisions, then stored `flagged` and surfaced | `artifacts.revision ≤ 2` | FR-024 |
| The vertical cut consumes the **same** props as the primary cut | one `video_props` artifact, two renders | FR-025 |
| The site uses the reviewed `copy` artifact rather than authoring its own claims | `copy` task completes before `site` starts | FR-021, US2 scenario 6 |

**Injection test** — inject a fabricated price into a draft and confirm it is **held**, not
sent (US2 Independent Test).

**The one people forget**: inject a fabricated price into the *site* rather than into an email.
`deploy` must be **refused by the gate**, not by the agent (FR-016, §3.4). A control that
guards outbound copy while the same price sits in an `<h2>` on the live site is a report, not a
control.

**Email send**: halts for approval showing recipient and content, then `verify()` reads the
message **back out of Mailpit** (FR-037, §4.5).

---

## S3 · A checkout that takes a real test payment (US3, P3)

Use a brief with **both** a recurring and a one-time product, and a display currency that
differs from the charge currency — those properties are what stress the pipeline.

1. Approve `arm_charge_path` on a screen showing every product, amount, currency and billing
   type as it will be charged (FR-028).
2. Open the live site, click buy, complete with a Stripe test card.

| Assert | Requirement |
|---|---|
| The catalogue came entirely from `brief.products[]` — no product, price or currency in EPYHIA's config | FR-027, US3 scenario 1 |
| Arming verified by **re-reading every price from Stripe** as `active` with matching amount and currency | FR-029 |
| An `orders` row exists matching a product in that brief | SC-009 |
| **Zero operator interaction** between the buy button and Stripe's form | FR-037, SC-009 |
| No Stripe identifier appears anywhere in the deployed bytes | FR-030 |
| Displayed and charged currencies both came from the brief; no conversion was performed | FR-003, R6 |

**Before arming**: click buy → `409 {"error":"not_armed"}` and a legible unavailable state on
the page. Not a 500, and not a session against a price that does not exist (FR-031).

**Webhook replay**: `stripe trigger checkout.session.completed` twice with the same event id →
**one** order (FR-032).

---

## S4 · Re-runs and crashes duplicate nothing (US4, P4)

```bash
# resubmit the byte-identical brief
curl -X POST localhost:8000/briefs ... --data @<same-brief>.json
# → 200 {deduplicated: true}
```

| Assert | Requirement |
|---|---|
| One live site, one alias, one catalogue, one order — and the same keys as the first run | SC-003 |
| It short-circuits **even though the generated bytes differ**, because the deploy key excludes the site artifact hash | FR-045, US4 scenario 2 |
| Editing the brand doc and re-running produces a **genuine second publication**, distinguishable in the audit trail | FR-012, US4 scenario 3 |

**Crash drills** (SC-008):

| Kill the worker | Expected on resume |
|---|---|
| mid-`executing`, before the result is recorded | The keyed row exists; retry lands on `verifying` and **the world decides**, not a status field (§7.4) |
| while an action sits `awaiting_approval` | The pending action is still there on reload; the operator's click resumes **that same action** (FR-038) |
| after an expensive generation | The memo replays it where it can — but correctness never depends on that hit (FR-048) |

---

## S5 · What did it do, what did it cost (US5, P5)

Answer entirely from `GET /runs/{id}/cost`, without leaving the console:

| Assert | Requirement |
|---|---|
| Every model call lists agent, model id, **tier**, four token counts, derived cost, latency | FR-049 |
| **Exactly one** top-tier call in the run | SC-007, §3.1 |
| Model spend and action spend appear as **one** total against **one** budget | FR-052, SC-011 |
| Exceeding the run budget stops the run; the daily ceiling stops new runs starting | FR-053 |
| Costs use **effective-dated** rates; a rate change on a known date does not silently misreport | FR-051, R9 |
| A rate lookup miss is a hard error, never a silent `0.00` | R9 |

---

## S6 · A second, unrelated business (US6, P6)

The strongest available evidence that this is an agency and not a one-client script, and much
harder to fake than any single-client demo.

```bash
git status                 # before
# submit a brief for a completely different kind of business
git status                 # after — must be identical
```

| Assert | Requirement |
|---|---|
| **Zero source files changed** between the two runs | SC-006, §10.1 |
| Different brand-doc palettes, different aliases, **no shared artifact hashes** | FR-062, SC-006 |
| Each run's deploy probe read its expected name from **its own** brand doc row | FR-059, US6 scenario 2 |
| **Zero `actions` rows with `requested_by = 'strategist'`** across both runs | FR-042, §3.3 |

**The static half**, which finds violations the runs cannot:

```bash
uv run pytest tests/genericity/
```

Harvests client tokens from every brief fixture and asserts none appears in `prompts/` — raw
source and empty-context render both (FR-060, R10). Adding a fixture strengthens the check
automatically.

---

## The eval

```bash
uv run python eval/eval.py     # against the DEPLOYED agency, Auth0 M2M — no bypass key
```

Writes `PRODUCT_EVAL.md` from `rubric.json`
([schema](./contracts/eval-rubric.schema.json)), reading **stored records** rather than
re-probing the world (§4.5, §10).

The one thing to check about the report itself: a reader can tell, for **every** line, whether
it was mechanically checked or left to human judgement. Automated rows carry pass/fail and the
evidence read; judged rows carry links and no self-awarded score, and the document says which
is which at the top (FR-063, SC-013). A mixed report that hides the difference is the "status
field the system trusted more than reality" failure in report form.
