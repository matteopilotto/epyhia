# Phase 1 Data Model: EPYHIA

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

One Postgres database, SQLAlchemy 2.0, Alembic. Every table below is EPYHIA infrastructure.
**No table has a client-specific column**, and no column has a client-specific default —
`briefs.payload` is the single place any client fact exists (Constitution Principle I).

## Entity map

```text
briefs ──1:N──▶ runs ──1:N──▶ tasks ──1:N──▶ actions ──1:N──▶ orders
                 │              │
                 │              └──1:N──▶ agent_calls
                 ├──N:1──▶ brand_docs
                 └──1:N──▶ artifacts

agent_cache   (keyed, no FK — droppable)
sink_posts    (the publish adapter's destination — see research.md R4)
```

---

## `briefs`

**The client-data boundary.** Every fact about a client is here and nowhere else (§5.4).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `payload` | jsonb NOT NULL | The submitted brief, **verbatim**. Schema: [contracts/brief.schema.json](./contracts/brief.schema.json) |
| `content_sha256` | text NOT NULL | **UNIQUE.** Canonical-JSON hash of `payload` |
| `guardrail_decision` | text NOT NULL | `pass` \| `reject` |
| `guardrail_reason` | text | Populated on both outcomes (FR-007) |
| `guardrail_model` | text NOT NULL | Which model judged it |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- `payload` is immutable after insert. Correcting a brief means submitting a new one, which is
  a new hash and therefore a new brief (§7.1).
- `content_sha256` is computed over a canonical serialisation (sorted keys, no insignificant
  whitespace) so that key ordering is not a source of false distinctness. FR-002.
- Resubmitting an identical brief resolves to this row rather than inserting. FR-002, FR-044.
- A `reject` decision still inserts the row — FR-007 requires the decision be logged either
  way — and opens a `runs` row that lands `failed` with no task enqueued. The run exists so the
  screening call has a `run_id` to be recorded against (FR-054) and so its cost counts against
  the daily ceiling (FR-053).

---

## `brand_docs`

The parameterisation layer. Fixed schema, per-client contents (FR-010).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `brief_id` | uuid FK → `briefs.id` NOT NULL | |
| `version` | int NOT NULL | 1-based. **UNIQUE(`brief_id`, `version`)** |
| `doc` | jsonb NOT NULL | Schema: [contracts/brand-doc.schema.json](./contracts/brand-doc.schema.json) |
| `authored_by` | text NOT NULL | `strategist` \| `operator` |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- Rows are append-only. An operator edit inserts `version + 1`; it never updates in place —
  that is what makes the v1→v2 diff a record rather than a claim (§5.3, FR-012).
- `doc.name` is the string the deploy probe asserts, read from this row at verify time
  (§4.5, FR-018, FR-059).
- A new version is a new deploy idempotency key, so a re-run after an edit genuinely deploys
  (§7.2, FR-045, and spec US4 scenario 3 — the case that is *supposed* to fire).

---

## `runs`

One execution against one brief. Its `id` threads through every agent call and every action.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | The `run_id` passed to `Agent.run(...)` and stamped on every Logfire span |
| `brief_id` | uuid FK → `briefs.id` NOT NULL | |
| `brand_doc_id` | uuid FK → `brand_docs.id` | Null until the Strategist writes v1 |
| `prompt_version` | text NOT NULL | Recorded at run open (§8, FR-055) |
| `grounding_set` | jsonb NOT NULL | `{literal: [...], derived: [...]}`, entries `{value, currency}` |
| `budget_usd` | numeric NOT NULL | Per-run ceiling |
| `spend_usd` | numeric NOT NULL DEFAULT 0 | Model spend **plus** action spend, one number (§4.2, FR-052) |
| `status` | text NOT NULL | `running` \| `succeeded` \| `failed` \| `halted_budget` |
| `alias` | text NOT NULL | `epyhia-<brief_hash[:12]>.vercel.app`, derived not stored-by-hand (R2) |
| `created_at` / `updated_at` | timestamptz | |

**Rules**

- `grounding_set` is written at ingest, before any expensive work (FR-004), and is never
  amended afterwards by anything — least of all by model output (FR-005, Principle VI).
- `spend_usd` crossing `budget_usd` moves `status` to `halted_budget` and stops the run
  (FR-053, SC-011).
- `alias` is a pure function of `brief_hash`, so `verify()` and `eval.py` derive the URL they
  probe rather than reading it from the action they are checking (R2).
- A run whose brief was rejected at intake is opened and immediately `failed`, with no task
  enqueued and exactly one `agent_calls` row — the guardrail's.
  `briefs.guardrail_decision` distinguishes it from a run that failed at work (SC-012).

---

## `tasks`

The work queue, the state machine, and the run timeline's source (§5.4, R8).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid FK → `runs.id` NOT NULL | |
| `kind` | text NOT NULL | `plan` \| `copy` \| `site` \| `demand` \| `money` \| `video` \| `resume` |
| `state` | text NOT NULL | `pending` \| `claimed` \| `running` \| `awaiting_approval` \| `done` \| `failed` |
| `depends_on` | uuid[] | Task ids that must be `done` first |
| `payload` | jsonb | Task input, including the action id for `resume` |
| `lease_expires_at` | timestamptz | Null unless claimed |
| `attempts` | int NOT NULL DEFAULT 0 | |
| `error` | text | |
| `created_at` / `updated_at` | timestamptz | Ordering source for the console timeline |

**State transitions**

```text
pending ──claim──▶ claimed ──▶ running ──┬──▶ done
   ▲                                     ├──▶ failed        (attempts > cap)
   │                                     └──▶ awaiting_approval
   └────────── lease expiry / approval resume ──────────────┘
```

**Rules**

- Claimed with `FOR UPDATE SKIP LOCKED` plus a lease; an expired lease returns the row to
  `pending` and increments `attempts` (FR-047, §7.3).
- Delivery is **at-least-once here**; exactly-once lives at the gate (FR-047).
- `awaiting_approval` releases the lease — no worker holds state across a human's pause
  (R7 step 4). The sweeper must not resurrect rows in this state.
- The pipeline shape is fixed in code: `plan` → {`copy` → `site`, `demand`, `money`}. A model
  never composes it (FR-013, §3.3).

---

## `actions`

**Simultaneously the audit log and the idempotency ledger** (§4.3). The most important table
here.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid FK → `runs.id` NOT NULL | |
| `task_id` | uuid FK → `tasks.id` | |
| `requested_by` | text NOT NULL | The agent name. `strategist` must never appear (FR-042) |
| `action_type` | text NOT NULL | `deploy` \| `stripe_product` \| `stripe_price` \| `arm_charge_path` \| `checkout_session` \| `send_email` \| `publish` |
| `idempotency_key` | text NOT NULL | **UNIQUE** (§7.3) |
| `request` | jsonb NOT NULL | The payload as it will be sent |
| `state` | text NOT NULL | `pending` \| `awaiting_approval` \| `executing` \| `verifying` \| `succeeded` \| `failed` \| `denied` |
| `approval_decision` | text | `approved` \| `denied` |
| `approved_by` | text | Auth0 `sub` of the deciding operator |
| `approved_at` | timestamptz | |
| `projected_cost_usd` | numeric | Shown on the approval screen (FR-039) |
| `cost_usd` | numeric | Actual (FR-050) |
| `evidence` | jsonb | The verification result. Never null on `succeeded` (FR-040) |
| `verify_attempts` | int NOT NULL DEFAULT 0 | Caps at 5 (FR-041, §4.5) |
| `error` | text | |
| `created_at` / `updated_at` | timestamptz | |

**State transitions** — see §4.3. Two constraints are non-negotiable:

- **There is no `executing → succeeded` edge.** Every transition into `succeeded` passes
  through `verifying` (FR-035, Principle IV).
- **`succeeded` requires `evidence IS NOT NULL`.** Enforced as a CHECK constraint, not by
  convention, because SC-002 is "zero actions can reach a successful state on self-report" and
  a convention is not a proof.

**Idempotency keys** (§7.2, FR-044–FR-046)

| Action | Key |
|---|---|
| `deploy` | `sha256(brief_hash + brand_doc_version + prompt_version)` — **excludes site bytes** |
| `arm_charge_path` | `sha256(brief_hash + resolved_catalogue_hash)` |
| `stripe_product` / `stripe_price` | `sha256(brief_hash + product_name + price_minor + billing)` |
| `checkout_session` | `sha256(brief_hash + product + buyer_session)` |
| `video_render` | `sha256(archetype_id + props + remotion_version)` |
| `send_email` | `sha256(brief_hash + template + recipient)` |

**Evidence shapes** — what `verify()` stores per type (FR-040, §4.5):

| Action | `evidence` |
|---|---|
| `deploy` | `{status, matched_name, matched_build_marker, url}` |
| `arm_charge_path` | `{prices: [{price_id, active, unit_amount, currency}]}` |
| `checkout_session` | `{order_id, paid}` |
| `send_email` | `{message_id, recipient, subject}` |
| `publish` | `{permalink, status, payload_sha256}` |

---

## `agent_calls`

One row per model call — the per-call half of "what did it do and what did it cost" (§8).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid FK → `runs.id` NOT NULL | |
| `task_id` | uuid FK → `tasks.id` | |
| `agent` | text NOT NULL | `strategist` \| `web_builder` \| `marketer` \| `reviewer` \| `ops` \| `guardrail` |
| `model_id` | text NOT NULL | Exact id, e.g. `claude-opus-5` |
| `tier` | text NOT NULL | Read from `pricing.yaml`, not inferred (R9) |
| `prompt_version` | text NOT NULL | |
| `input_tokens` / `output_tokens` / `cache_write_tokens` / `cache_read_tokens` | int NOT NULL | Four counts, because there are four rates (§8) |
| `cost_usd` | numeric NOT NULL | Derived via the effective-dated rate for `created_at` |
| `latency_ms` | int NOT NULL | |
| `cache_hit` | bool NOT NULL | Whether `agent_cache` served this (a cost fact, not a correctness one) |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- `tier` and `cost_usd` are NOT NULL because SC-007 asserts 100% coverage. A model id with no
  applicable rate row is a hard error, never a silent `0.00` (R9).
- Every row carrying the planning tier has `agent = 'strategist'` (SC-007, §3.1). More than one
  such row means the plan task was retried, which FR-047 permits and FR-048 makes affordable; a
  planning-tier row for any *other* agent is the defect this rule exists to catch.
- This table, not Logfire, is what `eval.py` reads — it must assert with no Logfire account
  and no network (§8).

---

## `artifacts`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid FK → `runs.id` NOT NULL | |
| `kind` | text NOT NULL | `copy` \| `posts` \| `email` \| `video_props` \| `video` \| `site` |
| `path` | text NOT NULL | Logical name within the run |
| `content_type` | text NOT NULL | |
| `bytes` | bytea NOT NULL | Behind one `ArtifactStore` interface (§5.4) |
| `sha256` | text NOT NULL | Doubles as a dedup key |
| `grounding_status` | text NOT NULL | `clean` \| `flagged` |
| `violations` | jsonb | Numeric findings **and** Reviewer findings, itemised |
| `revision` | int NOT NULL DEFAULT 0 | Caps at 2 (FR-024, §13) |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- Every kind carrying words or on-screen values is set-differenced against
  `runs.grounding_set` before any model is asked an opinion (FR-022, Principle VI). What
  counts as a numeral is per-kind and decided in code — see [research.md R5](./research.md).
- **The gate refuses `deploy` for a run whose `site` artifact is `flagged`** (FR-016, §3.4).
  This is a gate precondition, not an agent's responsibility.
- `revision` reaching 2 without going `clean` stores the artifact `flagged` and surfaces it in
  the console. Never an unbounded loop (FR-024).
- Flagged artifacts are read-only in the console; the remedy is to correct the brief or the
  brand doc and re-run (spec Assumptions).

---

## `orders`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid FK → `runs.id` NOT NULL | |
| `stripe_event_id` | text NOT NULL | **UNIQUE** — the dedup key (FR-032) |
| `stripe_session_id` | text NOT NULL | What `verify()` selects on |
| `product_slug` | text NOT NULL | Traces to a product in that run's brief |
| `amount_minor` | int NOT NULL | |
| `currency` | text NOT NULL | |
| `paid` | bool NOT NULL | |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- Written in the same transaction that records the webhook event, so a repeat arriving while
  the first is still in flight cannot produce a second order (FR-032, §7.3). Stripe delivers
  at-least-once.
- `amount_minor` and `currency` are copied from the Stripe event, not from the brief — the
  order records what was actually charged.

---

## `agent_cache`

Memoised structured results. **A cache, not a ledger** (§7.3, FR-048).

| Column | Type | Notes |
|---|---|---|
| `key` | text PK | `sha256(agent + model + prompt_version + brand_doc_version + scoped_inputs)` |
| `result` | jsonb NOT NULL | |
| `created_at` | timestamptz NOT NULL | |

**Rules**

- Droppable at any time. Never read for a correctness decision — a miss costs money, not
  correctness (FR-048, Principle V).
- That is only true because no gate key derives from generated bytes (§7.2). If the deploy key
  ever included the site artifact hash, this cache would become load-bearing for idempotency,
  and a cache allowed to miss must never be load-bearing for a guarantee.
- `prompt_version` and `brand_doc_version` in the key are what make the §5.3 edit-and-re-run
  demo actually regenerate instead of serving a stale hit.

---

## `sink_posts`

The publish adapter's destination (research.md R4). EPYHIA infrastructure, not client data.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | The permalink is `/sink/posts/{id}` |
| `payload` | jsonb NOT NULL | |
| `payload_sha256` | text NOT NULL | What `verify()` compares against |
| `created_at` | timestamptz NOT NULL | |

---

## Cross-cutting invariants

These are assertions the schema and the eval both carry, listed together because each is a
guarantee the spec names:

1. **No client value in any DDL, default, constraint, or seed.** Verified by the genericity
   eval (FR-062) and the prompt lint (FR-060, research.md R10). Principle I.
2. **`actions.succeeded ⇒ evidence IS NOT NULL`**, as a CHECK constraint. FR-040, SC-002.
3. **No `actions` row has `requested_by = 'strategist'`.** Asserted by the eval over a full
   run; the mechanism is that the Strategist is constructed with no gate handles at all.
   FR-042, SC-007's sibling in §3.3.
4. **`UNIQUE(actions.idempotency_key)`** is the only thing standing between a re-run and a
   duplicate charge. Application logic never resolves the race. FR-044, §7.3.
5. **`runs.spend_usd` is one number** covering model spend and action spend. Two columns would
   make FR-052 a half-truth. §4.2.
6. **Every `agent_calls` row has a tier and a cost.** NOT NULL, not convention. SC-007.
