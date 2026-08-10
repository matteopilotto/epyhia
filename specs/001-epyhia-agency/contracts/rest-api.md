# Contract: HTTP surface

FastAPI, one origin (the SPA is served by the same app), therefore **no CORS** on the API or
the SSE stream (§11).

**Auth**: Auth0 Bearer on every operator route. There is no second path in — no bypass key,
no cookie session (FR-057). `eval.py` uses an Auth0 **machine-to-machine** client through the
same validator (FR-058, §10). Buyer and webhook routes are unauthenticated by necessity and are
marked below.

---

## Operator routes

### `POST /briefs`

Submit a brief. Body: [brief.schema.json](./brief.schema.json).

Synchronously, before returning: canonicalise and hash the payload, run the input guardrail,
extract the grounding set, open the run, enqueue the `plan` task (§3.5, FR-004, FR-007).

| Response | Meaning |
|---|---|
| `201 {run_id, brief_id, content_sha256, alias}` | New brief, run opened |
| `200 {run_id, brief_id, content_sha256, alias, deduplicated: true}` | **Identical hash** — resolves to the existing brief; no second run's worth of effects will occur (FR-002, US4) |
| `422 {error: "guardrail_rejected", reason}` | Brief carries instructions aimed at the system. The decision is logged either way (FR-007) |
| `400` | Schema violation |
| `503 {error: "daily_ceiling_reached"}` | The system-wide daily spend ceiling is reached, so no new run opens. A deduplicated resubmission opens no run and is unaffected (FR-053) |

### `GET /runs` · `GET /runs/{id}`

The run record: status, brand doc version, prompt version, spend against budget, alias.

### `GET /runs/{id}/events` — SSE

The live timeline. Consumed with `fetch` + `ReadableStream`, **not `EventSource`**, because
`EventSource` cannot send an `Authorization` header and the alternatives are a JWT in the query
string (which leaks into access and proxy logs) or a parallel cookie session (§10).

Event kinds: `task`, `action`, `artifact`, `agent_call`, `cost`.

### `GET /runs/{id}/actions`

Every action with its state, key, projected and actual cost, and **its stored evidence**. This
is what makes "deployed" non-self-reportable anywhere in the system (FR-040, SC-002).

### `POST /actions/{id}/approve` · `POST /actions/{id}/deny`

The approval decision. Writes `approval_decision`, `approved_by` (the Auth0 `sub`) and
`approved_at` to the row, then enqueues a `resume` task carrying the action id (research.md R7).

| Response | Meaning |
|---|---|
| `200 {state}` | Recorded |
| `409 {error: "not_awaiting_approval"}` | Already decided — a second click is not a second action |

Idempotent by construction: the decision is a transition on a keyed row, so a double-click,
a reload, or a click after a redeploy all resolve to the same single execution (FR-038).

### `GET /runs/{id}/brand-doc` · `PUT /runs/{id}/brand-doc` · `GET /briefs/{id}/brand-docs/diff?from=&to=`

Read, edit, and diff. `PUT` **inserts a new version**; it never updates in place (FR-012, §5.3).
A subsequent run against the new version is a new deploy key and therefore a genuine second
publication — the case that is supposed to fire (§7.2, US4 scenario 3).

### `GET /runs/{id}/artifacts` · `GET /artifacts/{id}`

Includes `grounding_status` and itemised `violations`. **Flagged artifacts are listed and
readable** — surfacing them is the remedy path, not hiding them (FR-024). Read-only: the fix is
to correct the brief or the brand doc and re-run.

### `GET /runs/{id}/cost`

Per-`agent_calls` rows with agent, model id, tier, four token counts, derived cost and latency;
plus **one combined total** covering model spend and action spend against one budget (FR-052,
§4.2). Two separate views would make the budget half-blind.

---

## Buyer routes (unauthenticated)

### `POST /checkout`

Body `{run_id, slug}`. Resolution order per research.md R11:

| Response | Meaning |
|---|---|
| `200 {checkout_url}` | Session created — **no operator interaction** (SC-009) |
| `409 {error: "not_armed"}` | The run's charge path was never armed. The page renders a legible unavailable state, not a 500 and not a session against a price that does not exist (FR-031, §6.2) |
| `404 {error: "unknown_product"}` | Slug not in this run's resolved catalogue |

The site's button carries `data-product="<slug>"` derived from the brief. **No Stripe
identifier ever enters the deployed bytes** (FR-030, §6.2), which is what keeps the generated
site credential-free by construction and lets the site and money tasks run in parallel.

### `POST /webhooks/stripe` (unauthenticated; signature-verified)

Writes the order row in the **same transaction** that records the event id. A repeat arriving
while the first is still in flight cannot produce a second order (FR-032, §7.3).

---

## Recording sink (research.md R4)

### `POST /sink/posts` → `{id, permalink}` · `GET /sink/posts/{id}`

The `publish` adapter's destination — a real HTTP round trip to something the adapter does not
share a process with, so `execute()` and `verify()` are not tautological. Token-authenticated.
Swapping in a real social API replaces one adapter and one base URL (§4.6).

---

## Errors

One shape everywhere: `{error: "<machine_slug>", detail: "<human string>"}`.

The credential case is named explicitly because FR-064 and SC-010 turn on it: a gate action
whose credential is absent returns `credential not configured: vercel` — never a stack trace
three layers deep. The app **starts** without Stripe or Vercel credentials; the console works;
the failure appears only at the point of the action (§11).
