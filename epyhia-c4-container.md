# EPYHIA — architecture companion

Companion to `epyhia-c4-container.drawio` (C4 container view). One plain-language client
brief goes in; a deployed website, a marketing pack (landing copy, posts, launch email,
launch video), and a Stripe test-mode checkout come out. Everything that varies by client
lives in the brief or the brand doc — never in code, prompts, or fixtures.

Source of truth: `DESIGN.md`. Verified against the repo at `main` (Phase 9), 2026-08-15.

## Actors

| Actor | Role |
|---|---|
| **Operator** | Runs the agency from the console: submits briefs, watches runs, grants approvals, retries failed stages. |
| **Buyer** | Visits the deployed client site and pays through Stripe Checkout (test mode). Never sees EPYHIA itself. |

## Containers

### Console — React SPA
Vite + React, TanStack Router/Query, Tailwind + shadcn/ui. The operator UI for runs,
artifacts, approvals, and cost. Logs in via **Auth0** (OIDC); the built bundle is served by
`web` and runs in the operator's browser.

### `web` — FastAPI (Fly process)
The HTTP face of the system: REST under `/api` (runs, briefs, tasks, actions, artifacts,
orders, cost, export), an SSE stream for live run updates, the Stripe webhook receiver, the
checkout redirect, and static serving of the console bundle. Two components worth naming:

- **Brief ingest** — hashes the brief ("same run" = same brief hash), extracts every numeral
  into `runs.grounding_set`, and screens the brief with an LLM guardrail
  (`claude-haiku-4-5`). This means `web` calls the Anthropic API too, not just the worker.
- **Demand sink (`/sink`)** — a stand-in social channel owned by EPYHIA. The gate's publish
  adapter reaches it over real HTTP with a machine token (deliberately not in-process), so
  publish's `execute()` and `verify()` are never two halves of one transaction.

### `worker` — Python asyncio (Fly process, same image)
The crew's runtime. `web` and `worker` never call each other; every handoff is a durable row
in the `tasks` table — at-least-once at the task layer, exactly-once effects at the gate.

- **Queue loop** — claims tasks with `FOR UPDATE SKIP LOCKED` + a lease, sweeps expired
  leases and orphaned actions, and settles a run `succeeded`/`failed` where its last stage
  ends. No Celery, no Redis: the queue is a Postgres table and a state machine.
- **Agent crew** (PydanticAI, pinned 2.22.0) — tiers follow the shape of the work:
  | Agent | Model | Job |
  |---|---|---|
  | Strategist | `claude-opus-5` | Reads the brief, writes the brand doc. No gate handles — it can never touch the outside world. |
  | Web Builder | `claude-sonnet-5` | Authors the single-page site (streamed, ~64K tokens). |
  | Marketer | `claude-sonnet-5` | Writes the pack: copy, posts, email, video props. |
  | Reviewer | `claude-haiku-4-5` | The Marketer's self-review; reads the raw brief as well as the brand doc. |
  | Site Critic | `claude-haiku-4-5` | Judges the rendered site against lint findings. |
  | Ops | `claude-haiku-4-5` | Wires the Stripe catalogue; never deploys or publishes. |

  The pipeline is fixed in code, not authored by the model: `plan` fans out to
  `copy → site`, with `demand` and `money` in parallel; `demand` queues the video render
  and the outreach tasks — one `publish` per post plus one `send_email`, gated behind the
  site being live.
- **Grounding checks** — every word-bearing artifact (copy, posts, email, video props, the
  rendered site) is normalised and set-differenced against `literal ∪ derived` from the
  grounding set; the result is `clean` or `flagged`.
- **Remotion renderer** — the launch video, rendered locally via an
  `npx remotion render` subprocess (pinned 4.0.503).

### Action Gate — the credential boundary
Lives in the worker but is drawn (and reasoned about) as its own boundary. It governs egress
with consequences — deploy, charge, send, publish — and is the **sole holder** of the
Vercel, Stripe, and SMTP credentials; agents get typed capability handles with no key
material. It owns approval, idempotency (every key derives from the brief hash), retry, and
audit. Four adapters, each registering `execute()` **and** `verify()`:

| Adapter | Target | Effect |
|---|---|---|
| Vercel | Vercel | Deploy the site; verify with a probe for the brand name read from the run's row. |
| Stripe | Stripe (test mode) | Create products/prices, arm the charge path; verify against the API. |
| Email | Mailpit (SMTP) | Send the launch email; verify via Mailpit's API. |
| Publish | `web`'s `/sink` | Post the pack over HTTP; verify by reading it back. |

Action lifecycle: `pending → awaiting_approval → executing → verifying → succeeded | failed`.
There is no path from `executing` straight to `succeeded` — every effect is proved in the
world first. `awaiting_approval` is durable in Postgres, and the gate refuses `deploy` for a
run whose site artifact is `flagged`.

### Postgres — Neon (managed)
The system of record and the queue in one: `runs`, `briefs`, `brand_docs`, `artifacts`,
`tasks` (the queue), `actions` (audit log **and** idempotency ledger,
`UNIQUE(idempotency_key)`), `agent_calls` / `agent_cache`, `orders`, `sink_posts`, and the
cost ledger. Migrations are Alembic, run as the Fly release step.

## External services

| Service | Role |
|---|---|
| **Anthropic API** | Opus 5 / Sonnet 5 / Haiku 4.5 inference. The key lives in the process environment, deliberately **outside** the gate — inference is metered, not gated, and LLM spend and gate-action spend roll up against one budget. |
| **Vercel** | Hosts the deployed client site — static HTML/CSS/JS, no framework, no build step. |
| **Stripe** (test mode) | Products and prices, Checkout Sessions, webhooks (`checkout.session.completed` → `orders`). |
| **Mailpit** | SMTP sink + API, deployed as a separate Fly app; the launch email lands here. |
| **Auth0** | OIDC login for the console; JWTs with audience `epyhia.fly.dev/api`. |
| **Logfire** | Tracing from both processes, `run_id` on every span. |

## Deployment

One Fly.io app (`epyhia`), one image, two processes: `web` (uvicorn) and `worker`
(`python -m epyhia.queue.worker`), with `alembic upgrade head` as the release command.
The app starts without Stripe/Vercel credentials and fails only at the gate action, with an
explicit `credential not configured: <provider>` error.
