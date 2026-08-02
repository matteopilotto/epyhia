# Phase 0 Research: EPYHIA — An Agency Staffed by Agents

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Date**: 2026-08-02

## How to read this document

`DESIGN.md` is the architecture of record (Constitution Principle II), and it already resolves
most of what a Phase 0 would normally research. Re-deciding those here would create a second
source of truth, which is the exact drift Principle II exists to prevent. So this document has
two parts:

- **Part A — Inherited decisions**: a pointer table. Each row is already decided in `DESIGN.md`
  with its own rationale; nothing is restated or revisited.
- **Part B — Decisions made here**: the items `DESIGN.md` leaves open, that the plan cannot be
  written without. Each carries Decision / Rationale / Alternatives / Consequence.

Part B is where the actual research went. Nine of the eleven items are things that only become
visible once you try to write the adapter or the checker rather than describe it.

---

## Part A — Inherited decisions (no research needed)

| Question | Answer | Source |
|---|---|---|
| Language, packaging, lint, test | Python 3.13, `uv`, `ruff`, `pytest` + `pytest-asyncio` | §2.1, §11 |
| API framework | FastAPI — REST, SSE, Stripe webhook, serves the built SPA | §2.1 |
| Agent framework | PydanticAI V2, pinned `2.22.0`; `run_id` native; `ApprovalRequired` built in | §2.1, §2.2 |
| Datastore | Postgres on Neon, SQLAlchemy 2.0, Alembic | §2.1, §5.4 |
| Queue | Python state machine over a `tasks` table, `FOR UPDATE SKIP LOCKED` + lease. No Celery/Redis/Prefect | §2.1, §7.3 |
| Tracing | Logfire `4.39.0`, `run_id` on every span; **tables, not Logfire, are the system of record** | §2.1, §8 |
| Site output | Hand-authored single-page HTML + CSS + one vanilla JS file, no build step | §6.1, §6.3 |
| Video | Remotion `4.0.503`, pinned, rendered locally, 3–4 parameterised archetypes, props JSON only | §6.4 |
| Console | Vite + React + TanStack Router/Query + Tailwind + shadcn/ui, Auth0 | §2.1 |
| Prompts | Jinja2 templates in a versioned `prompts/` tree behind a `PromptService` | §2.1 |
| Deploy | Fly.io, one image, `web` + `worker` processes, `release_command = "alembic upgrade head"` | §11 |
| Model tiers | Opus plans, Sonnet writes, Haiku checks and wires — by work shape, not client | §3, §3.1 |
| What the gate governs | Deploy, charge, send, publish. Not inference, not artifact writes, not local render | §4.1 |
| Why `ANTHROPIC_API_KEY` is outside the gate | Inference is metered, not gated; one combined budget makes the split honest | §4.2 |
| Action lifecycle | `pending → awaiting_approval → executing → verifying → succeeded \| failed`; no `executing → succeeded` | §4.3 |
| What needs approval | Go-live, arming the charge path, anything outbound to a person. Not per-Checkout-Session | §4.4 |
| Idempotency keys | Table of six, all derived from `brief_hash`; deploy key excludes site bytes; video key includes Remotion version | §7.2 |
| Idempotency mechanism | `UNIQUE(idempotency_key)` + `ON CONFLICT DO NOTHING RETURNING id` | §7.3 |
| Agent-call memoisation | A cache, allowed to miss; keyed on `agent + model + prompt_version + brand_doc_version + scoped inputs` | §7.3 |
| Cost model | `pricing.yaml`, four effective-dated rates per model; tokens enforced, dollars derived | §8 |
| Artifact storage | Postgres `bytea` behind one `ArtifactStore` interface | §5.4 |
| Eval auth | Auth0 M2M client credentials — no bypass key | §10 |
| SSE transport | `fetch` + `ReadableStream`, not `EventSource` (needs an `Authorization` header) | §10 |
| Local dev | `docker compose up` → Postgres + Mailpit + web + worker from `.env.example` | §11 |
| Provider constraints | Never set `temperature`/`top_p`/`top_k`; stream the Web Builder; cache minima differ; `UsageLimits` is token-only | §8.1 |

---

## Part B — Decisions made here

### R1 · Repository layout

**Decision**: A single repository, one installable Python package `epyhia/` plus three
non-Python trees that each have a different toolchain.

```text
epyhia/            one Python package, imported by both Fly processes
console/           Vite + React SPA (Node)
video/             Remotion project (Node)
prompts/           Jinja2 tree, versioned — deliberately outside epyhia/
eval/              rubric.json + eval.py, runs against the deployed agency
tests/             pytest
```

**Rationale**: `web` and `worker` are the same image with different commands (§2, §11), so
splitting the Python into two distributions would create a packaging boundary the deployment
explicitly does not have. `prompts/` sits outside the package because Principle I's
enforcement is a CI check that scans that directory as a directory — burying it inside
`epyhia/` invites someone to reach for an f-string next door and stay technically compliant.

**Alternatives considered**: `src/` layout with `backend/` and `frontend/` siblings — rejected
because there is one backend, and the template's Option 2 web-app split implies two deploy
targets. Separate `gate/` distribution to physically enforce the credential boundary —
rejected as speculative packaging for a boundary that is already enforced by construction
(agents are built with no gate handles in their toolset, §3.3) and by a test.

**Consequence**: One `pyproject.toml`, one lockfile, one `uv run pytest`.

---

### R2 · How the deploy adapter actually reaches Vercel

**Decision**: One Vercel **project per brief**, named `epyhia-<brief_hash[:12]>`. Deploy is
`POST /v13/deployments` with the site files inlined, `target: "production"`,
`projectSettings: {framework: null, buildCommand: null, outputDirectory: "."}`. Then poll
`readyState` until `READY` or `ERROR`. Then `POST /v2/deployments/{id}/aliases` with the
brief's stable alias `epyhia-<brief_hash[:12]>.vercel.app`. Then `verify()` probes the alias.

**Rationale**: The v13 endpoint accepts inline files (`{file, data, encoding}`) for non-git
deployments, which is exactly the shape of a static single-page artifact and needs no upload
round-trip, no CLI, and no Node in the gate's execution path (§6.1). A project per brief makes
"one brief, one URL" (§7.2) a property of the namespace rather than of bookkeeping, and it
makes the alias derivable from `brief_hash` alone — which is what lets `verify()` and `eval.py`
compute the URL they should be probing without reading it back from the action they are
checking.

The explicit alias call is kept even though a production deploy to a per-brief project would
land on `<project>.vercel.app` anyway. §4.5's second assertion exists precisely because "the
deployment succeeded but the alias still serves the previous build" is a real failure; keeping
the alias switch as its own observable step is what keeps that failure detectable rather than
theoretical. `409` on alias assign means "already assigned to this deployment" and is treated
as success, not as an error — the alias endpoint reassigns from the old deployment when the
alias is held elsewhere, which is the behaviour a v2 deploy needs.

**Alternatives considered**: One shared Vercel project with per-brief aliases — rejected
because production deploys within one project fight over the project's own production domain,
and prior versions' immutable URLs become harder to reason about. Vercel CLI — rejected in
§6.1 (Node in the gate, token in a subprocess env). Upload-by-SHA then reference — rejected as
an extra round trip for an artifact measured in tens of kilobytes.

**Consequence**: The deploy adapter is three HTTP calls plus a poll loop, all inside
`execute()`; `verify()` is one `GET` against a URL it derives, not one it is told.

**Sources**: [Create a new deployment](https://vercel.com/docs/rest-api/reference/endpoints/deployments/create-a-new-deployment),
[Assign an Alias](https://vercel.com/docs/rest-api/aliases/assign-an-alias)

---

### R3 · Where the build marker is injected

**Decision**: The deploy adapter injects
`<meta name="epyhia-build" content="<brief_hash[:8]>.<brand_doc_version>.<prompt_version>">`
into the `<head>` of the site artifact **at upload time**, operating on the bytes it is handed.
The Web Builder never sees it and it is never part of the stored `site` artifact.

**Rationale**: §4.5 requires the marker to be computed by the adapter, not the agent, so it
stays out of the generated bytes — and it must stay out of the generated bytes because the
memoisation cache is keyed on those bytes' inputs and the artifact `sha256` is a dedup key
(§5.4). If the marker were generated, editing the brand doc would change the artifact hash for
a reason unrelated to content. Injecting on the wire keeps the artifact a pure function of the
brief and brand doc.

**Alternatives considered**: A separate `/_epyhia_build.json` file in the deployment —
rejected because the probe already fetches the page body and a second fetch is a second thing
that can pass while the page is stale. Marker in an HTTP header — not available; Vercel serves
the static file, we do not control response headers without config.

**Consequence**: The site artifact's `sha256` is stable across redeploys of the same content;
the deployed bytes differ from the stored artifact by exactly one `<meta>` tag, and that
difference is auditable because the adapter computes it deterministically.

---

### R4 · What `publish` publishes to

**Decision**: A **recording sink** implemented as a FastAPI router in the `web` process at
`POST /sink/posts` → `GET /sink/posts/{id}`, backed by a `sink_posts` table. The gate's publish
adapter posts to it over HTTP using its own configured base URL and a shared token, exactly as
it would post to a real social API. `verify()` fetches the returned permalink and asserts the
payload is stored and readable.

**Rationale**: §4.1 requires the sink be "a registered adapter pair with a real approval step,
a real key and a real audit row, not a `pass` with a comment." The thing that makes that true
is that the adapter goes over the network to something it does not share a process with — an
in-process function call that writes a row would make the adapter's `execute()` and `verify()`
tautological. Putting it in `web` rather than in a fourth container keeps `docker compose up`
to the four services §11 commits to, and requires no account signup, for the same reason
Mailpit was chosen over a hosted catcher.

**Alternatives considered**: A separate tiny container — rejected as a fifth service for no
isolation gain. Writing directly to the `artifacts` table — rejected: it makes `verify()` a
read of a row the same transaction wrote, which is the "status field is not evidence" failure
in miniature (§4.5).

**Consequence**: Swapping in a real social API is replacing one adapter's `execute()`/
`verify()` and one base URL. The `sink_posts` table is EPYHIA infrastructure, not client data.

---

### R5 · What counts as a numeral, per artifact kind

**Decision**: The grounding checker is one function over a **list of extracted strings**, and
each artifact kind has its own extractor that decides what text is in scope:

| Kind | In scope | Explicitly out of scope |
|---|---|---|
| `copy`, `posts`, `email` | All string values in the structured artifact | — |
| `site` | Text nodes outside `<script>`/`<style>`, plus `alt`, `title`, `aria-label`, and `<meta name="description">` content | Every CSS value, hex colour, `viewBox`, `px`/`rem`/`s`/`ms` unit, class name, `data-product` slug, id, href |
| `video_props` | Every leaf under `props.content` | Everything under `props.style` (palette hex, type sizes, fps, durations, easing) |

**Rationale**: `DESIGN.md` §3.4 says the check runs over the rendered site and does not say
what "over" means. Run naively over raw HTML it fails on `#0a0a0a`, `1.5rem`, `translateY(24px)`
and `transition: 0.3s` on the first honest page, and a check that cries wolf on every run is a
check that gets turned off — which is worse than not having it, because §9.2 depends on it.
Deciding scope per kind, in code, once, keeps the check exact and keeps the closed derivation
set (§5.2) from being quietly widened to absorb false positives.

The `video_props` split is the stronger half of this decision, because it makes the video props
schema carry it: **`content` and `style` are separate objects in the props contract**, so the
Marketer cannot put an on-screen price somewhere the checker does not look. That is a schema
guarantee rather than an extractor heuristic.

**Alternatives considered**: Check raw bytes of everything — rejected above. Ask a model which
numerals are content — rejected outright: §5.2 requires the check be deterministic and run
*before* any model is asked an opinion. Whitelist numeric CSS patterns with a regex — rejected
as an unbounded arms race against a generator that invents new CSS every run.

**Consequence**: `contracts/video-props.schema.json` splits `content` from `style`, and the
site extractor needs an HTML parser in the checker's dependency set.

---

### R6 · The closed derivation set, enumerated

**Decision**: A grounding entry is a pair `(value: Decimal, currency: str | None)`. The literal
set is every numeral extracted from the brief. The derived set is exactly these five families
over the literals, computed at ingest, enumerated in code once:

1. `×12` and `×52` annualisation of each product price
2. Pairwise sums and pairwise absolute differences of stated prices
3. Cardinality of every list in the brief (`products`, and per product `features`,
   `not_covered`; `voice.adjectives`, `voice.do`, `voice.dont`)
4. `current_year − established`
5. Each literal restated under the other currency label of the product it came from — **the
   same minor-unit amount, never converted**

Matching is `value` equality plus currency compatibility: a currency-less numeral in an
artifact matches an entry of any currency; a currency-tagged numeral must match the entry's
currency.

**Rationale**: Items 1–4 are §5.2's list made concrete. Item 5 is the one §5.2 implies without
stating: a product with `currency_display: EDDIE` and `currency_charge: USD` legitimately
appears as both `€$120` and `$120` in copy, and those are one fact. Crucially this performs
**no FX conversion** — inventing a rate would be exactly the fabrication the whole check exists
to prevent, and no rate exists anywhere in the brief to use. The currency-compatibility rule is
what lets bare `120` match without weakening the tagged case.

**Alternatives considered**: A tolerance window on values — rejected; a price is exact or it is
wrong. A configurable derivation set — rejected by FR-005 and Principle VI ("never extended by
anything a model says"), and by Principle VII's rule against unrequested knobs.

**Consequence**: The over-flagging risk in §13 is accepted as designed. Copy computing a
three-year total trips the check and lands `flagged` in the console.

---

### R7 · Reconciling `ApprovalRequired` with the durable `actions` row

**Decision**: The gate is the source of truth and PydanticAI is the raise mechanism, in this
order:

1. The capability handle calls `gate.request(action_type, payload, key)`.
2. The gate inserts the `actions` row (`ON CONFLICT DO NOTHING RETURNING id`). If the row
   already exists in a terminal state, it returns that result and **nothing is raised**.
3. If the action type needs approval and the row is `awaiting_approval`, the handle raises
   `ApprovalRequired`. The row is already durable before the raise.
4. The worker catches the resulting `DeferredToolRequests`, marks the task `awaiting_approval`
   with the action id, and **releases its lease**. No process holds in-memory state across the
   pause.
5. The operator's approve/deny writes the decision to the `actions` row and enqueues a
   `resume` task carrying the action id.
6. Resume re-enters the agent with `deferred_tool_results` built **from the `actions` row**,
   not from anything the previous process held.

**Rationale**: §4.4 states the requirement ("framework raises, Postgres remembers") but not the
ordering, and the ordering is the whole thing. Inserting before raising is what makes a
redeploy during the pause safe; raising first and inserting on approval would give the
operator's click a chance to create a second, unkeyed attempt — losing idempotency through the
approval feature, which §4.4 names as the sour way to lose it. Releasing the lease at step 4
matters too: a task that holds its lease across a human's coffee break either expires
mid-approval or blocks a worker for an hour.

**Alternatives considered**: Keeping the agent run suspended in memory — rejected; ephemeral Fly
filesystems and redeploys are the stated failure. Persisting PydanticAI's message history and
replaying it — deferred, not adopted: the memoisation cache (§7.3) already makes the re-entry
cheap, and message-history replay would make the framework's serialisation format load-bearing
for a correctness guarantee.

**Consequence**: Every gated capability handle is written to be re-entered. FR-038 is testable
with zero agents: insert an `awaiting_approval` row, restart, approve, assert one execution.

---

### R8 · Task states and lease mechanics

**Decision**: `tasks` carries `kind`, `state`, `run_id`, `depends_on`, `lease_expires_at`,
`attempts`, `payload`, `error`. States: `pending → claimed → running → done | failed |
awaiting_approval`. Claim is a single statement:

```text
UPDATE tasks SET state='claimed', lease_expires_at=now()+interval '<lease>' 
WHERE id = (SELECT id FROM tasks 
            WHERE state='pending' AND depends_on_satisfied 
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *
```

A sweeper returns rows whose lease expired to `pending` and increments `attempts`; past a fixed
cap the row lands `failed`.

**Rationale**: §7.3 commits to `FOR UPDATE SKIP LOCKED` plus a lease but not to the state set,
and the state set is what the run timeline renders (§5.4). `awaiting_approval` is a task state
as well as an action state because R7 step 4 releases the lease — the task has to be parked
somewhere the sweeper will not resurrect it.

**Alternatives considered**: Heartbeat-extended leases — rejected as unnecessary once the
long-pole waits (approval, video render) are handled by parking rather than by holding.
`SELECT ... FOR UPDATE` without `SKIP LOCKED` — rejected; it serialises the workers.

**Consequence**: The video render task holds its lease for minutes, which is the one legitimate
long lease and the reason the lease interval is per-`kind` rather than global.

---

### R9 · `pricing.yaml` shape

**Decision**:

```yaml
models:
  claude-opus-5:
    tier: planning
    rates:
      - effective_from: 2026-01-01
        input: <usd per million>
        output: <usd per million>
        cache_write: <usd per million>
        cache_read: <usd per million>
```

Cost for a call selects the rate row with the greatest `effective_from` not after the call's
timestamp. A model id with no applicable row is a hard error at call-record time, not a silent
zero.

**Rationale**: §8 commits to four rates and to effective dating; this pins the selection rule
and the failure mode. A missing rate silently costing `0.00` would corrupt the budget check and
the eval assertion "every `agent_calls` row carries a cost" simultaneously, and it would do so
in the direction that looks fine.

**Alternatives considered**: Rates in the database — rejected; they are code-versioned config,
not runtime state, and a YAML diff is the review artifact. Fetching prices from the provider —
no such API, and it would put a network dependency in the cost path.

**Consequence**: `tier` lives here rather than being inferred from the model id, so FR-049's
tier column and SC-007's "exactly one top-tier call" have one definition.

---

### R10 · How CI proves no client data reached a prompt

**Decision**: One test, two passes, both driven by the brief fixtures:

1. **Token harvest**: collect from every fixture in `tests/fixtures/briefs/*.json` the
   business name, tagline, one-liner, every product name, every `price_minor` rendered as a
   string, every currency code, and every voice adjective.
2. **Raw scan**: assert no harvested token appears in any file under `prompts/`.
3. **Empty render**: render every template with a sentinel context and assert the output
   contains no harvested token and no currency symbol.

**Rationale**: §2.1 says CI greps rendered templates but does not say against what. Against a
hand-maintained blocklist, the check rots the first time a fixture changes. Deriving the tokens
from the fixtures themselves means adding a bakery fixture automatically strengthens the check
— and the genericity eval (§10.1) already requires that second fixture to exist. The raw scan
is the stronger of the two passes (a template that lacks the token cannot render it), and the
empty render catches a template that inlines a default in a filter or a conditional.

**Alternatives considered**: Scanning Python source for the same tokens — kept as a smaller
companion assertion but not relied on; §2.1 already argues why f-string scanning is
unmaintainable, and the point of the prompt tree is that it makes the real check cheap.

**Consequence**: Fixture briefs must be real enough to harvest from — a fixture with a
placeholder name weakens the check silently. The test asserts each fixture yields a non-empty
token set.

---

### R11 · Checkout resolution and the armed gate

**Decision**: `POST /checkout {run_id, slug}` resolves in this order, all server-side:

1. Load the run. If its `arm_charge_path` action is not `succeeded` → `409` with a typed body
   `{error: "not_armed"}`; the page renders an unavailable state.
2. Resolve `slug` against that run's Ops output (the `stripe_price` action rows for that run).
   Unknown slug → `404 {error: "unknown_product"}`.
3. Create the session through the gate, auto-tier, keyed per §7.2, one audit row with cost.

The slug is `slugify(product.name)` computed at ingest and stored on the run's resolved
catalogue, so the site's `data-product` attribute and Ops's price rows are both derived from
the same brief field rather than from each other (§6.2).

**Rationale**: §6.2 fixes the mechanism; what it leaves open is where "armed" is read from.
Reading it from the `actions` table rather than a boolean column on `runs` means the armed
state and its evidence are the same record — FR-029's re-read-every-price verification is what
made it `succeeded`, so nothing can be armed without that check having passed.

**Alternatives considered**: A `runs.armed` boolean — rejected; a second place for a truth the
`actions` table already holds, and the exact "status field the system trusted more than
reality" shape (§10.2).

**Consequence**: SC-009's "zero operator interaction between the button and the payment form"
holds, and FR-031's refusal is a typed `409` the vanilla JS file can branch on.

---

## Unresolved

None blocking. Two items are deliberately deferred with the seam named:

- **Splitting the Remotion render into its own Fly process** — §6.4 sizes and locates the seam
  (a third `[processes]` entry plus a predicate on the claim query) and defers it. R8's
  per-`kind` lease interval is the piece that keeps that deferral cheap.
- **Replaying PydanticAI message history across an approval pause** (R7) — not adopted; the
  memoisation cache makes re-entry cheap enough that making a framework serialisation format
  load-bearing for correctness is not worth it.
