# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

**Implemented through Phase 7.** `DESIGN.md` is the architecture of record; when it and this
file disagree, `DESIGN.md` wins and this file is the thing to fix. The feature's spec, plan and
task list live in `specs/001-epyhia-agency/`, and `tasks.md` is the current build state — read
it before starting anything, since it carries per-task checkboxes this file cannot.

Complete: the Action Gate and its adapters, the schema and migrations, the task queue, brief
ingest and grounding, the five agents, the site / pack / checkout pipelines, re-run and crash
handling, and the cost ledger with budgets.

Remaining: Phase 8 (US6 — the second brief fixture, the genericity lint, and `eval/`) and
Phase 9 (Fly deploy, README, the demo recording).

Commands: `uv run ruff check`, `uv run pytest`, `uv run alembic upgrade head`,
`docker compose up` (Postgres + Mailpit + web + worker from `.env.example` defaults).

`.claude/DECISIONS.md` and `.claude/plans/` are untracked working scratch. **Never `git add`
them.**

## What EPYHIA is

An agency staffed by agents. One plain-language client brief goes in; a deployed website, a
marketing pack (landing copy, 3–5 posts, launch email, launch video + vertical cut), and a
Stripe test-mode checkout come out. Every action that deploys, charges, or sends passes
through one Action Gate.

**EPYHIA is the product. GRAFT — the ripperdoc clinic in `DESIGN.md` §1.3 and Part B of the
decisions file — is one row of input data.** A different client is a different brief, not a
different codebase.

### The invariant that governs every decision here

> Anything that varies by client lives in the brief or the brand doc — never in code,
> prompts, constants, or test fixtures.

This is the rule most likely to be violated by a well-meaning change, because the violation
is invisible while only one client runs through the system. Concretely, none of these may
appear in source:

| Never hardcode | Correct source |
|---|---|
| A client name as the deploy probe string | `brand_doc.name`, read from the run's row at verify time |
| Any price or numeral | `runs.grounding_set`, derived from the brief at ingest |
| Products seeded into Stripe | `brief.products[]`, created by Ops at run time |
| A currency pair | `brief.currency_display` / `currency_charge` |
| Aesthetic direction in the Web Builder's prompt | The brand doc the Strategist wrote for this brief |
| One fixed Remotion composition | An archetype among several, selected in the brand doc |
| Client copy in eval assertions | The run's own brief and brand doc |

The brand doc is the parameterisation layer: the Strategist reads the brief and writes the
brand doc; every other agent reads the brand doc. The Reviewer is the sole exception — it
reads the raw brief too, because it needs facts as well as voice.

## Architecture

```text
console (React SPA, Auth0) ──HTTPS+SSE──▶ web (FastAPI) ──tasks table──▶ worker (the crew)
                                                                             │
                                                        capability handles ──▶ ACTION GATE ──▶ Vercel / Stripe / Mailpit
                                                                                    │
                                                                              Postgres (Neon)
```

`web` and `worker` are two Fly processes running the **same image** with different commands.
The crew is composable logically, co-located physically: every handoff between agents is a
durable typed row, but they all execute in one process.

### The crew and their model tiers

Tiers follow the *shape* of the work, not the client. Opus plans, Sonnet writes, Haiku
checks and wires.

| Agent | Model | May never |
|---|---|---|
| Strategist (orchestrator) | `claude-opus-5` | Make any external call — it is constructed with **no gate handles in its toolset** |
| Web Builder | `claude-sonnet-5` | Author a price, feature, or claim not in the copy artifact or brief |
| Marketer | `claude-sonnet-5` | Invent a fact not in the brief; deploy |
| Reviewer (the Marketer's self-review) | `claude-haiku-4-5` | Approve silently; rewrite the draft itself |
| Ops | `claude-haiku-4-5` | Deploy; publish; touch markup |

The pipeline is **fixed in code**, not authored by the model: stages are always copy → site,
demand, money. The Strategist parameterises them through the brand doc; it does not compose
a task graph of its own devising.

### The Action Gate

It governs **egress with consequences** — deploy, charge, send, publish — and is the sole
holder of the Vercel token, Stripe test keys, and SMTP credentials. Agents get *capability
handles*: named typed functions with no key material behind them.

- `ANTHROPIC_API_KEY` sits deliberately **outside** the gate, in the worker's environment.
  Inference is metered, not gated. What makes that defensible is that LLM spend and
  gate-action spend roll up against **one** budget.
- Lifecycle: `pending → awaiting_approval → executing → verifying → succeeded | failed`.
  There is **no path from `executing` straight to `succeeded`** — every action is proved in
  the world first.
- Every adapter registers an `execute()` **and** a `verify()`. Provider-specific code lives
  in adapters; approval, idempotency, retry and audit live in the gate.
- Approval-gated: going live, arming the charge path, anything outbound to a person. Not
  each Checkout Session — that would park a buyer behind an operator click.
- PydanticAI's `ApprovalRequired` is the raise mechanism, but **the `awaiting_approval` row
  must be durable in Postgres**. Framework raises, Postgres remembers.

### Idempotency

"Same run" means **same brief hash**. Every gate key derives from it (§7.2 has the table).
One `actions` table doubles as audit log and idempotency ledger, `UNIQUE(idempotency_key)`
with `ON CONFLICT DO NOTHING RETURNING id`.

Two subtleties that look like bugs if you don't know the reasoning:

- **The deploy key deliberately excludes the site artifact hash.** LLM generation isn't
  deterministic, so keying on bytes would deploy twice whenever the generation memo misses.
  The key identifies the deploy *target's identity*: brief + brand doc version + prompt
  version.
- **Agent-call memoisation is a cache, not a ledger.** It may miss; a miss costs money, not
  correctness. That is only true because no gate key derives from generated bytes.

At-least-once at the task layer (`FOR UPDATE SKIP LOCKED` + lease), exactly-once effects at
the gate layer.

### Grounding

At ingest, every numeral in the brief is extracted into `runs.grounding_set`. Every artifact
containing words or props — copy, posts, email, video props, **and the rendered site** — is
normalised and set-differenced against `literal ∪ derived` before any model is asked an
opinion. The gate **refuses `deploy` for a run whose site artifact is `flagged`**. The
derivation set is closed and enumerated in code once; it is never extended by anything a
model says.

## Stack

These are the stack commitments from `DESIGN.md` §2.1, now scaffolded. Use them rather than
reaching for the reflexive alternative.

| Piece | Choice |
|---|---|
| Packaging / lint / test | `uv`, `ruff`, `pytest` + `pytest-asyncio` |
| API | FastAPI — REST, SSE, Stripe webhook receiver, serves the built SPA |
| Agents | PydanticAI V2, pinned `2.22.0` |
| DB | Postgres on Neon, SQLAlchemy 2.0, Alembic |
| Queue | A Python state machine over a `tasks` table — **no Celery, no Redis, no Prefect** |
| Tracing | Logfire `4.39.0`, `run_id` on every span |
| Site output | Hand-authored single-page HTML + CSS + one vanilla JS file — no build step, no framework |
| Video | Remotion `4.0.503`, pinned, rendered locally |
| Console | Vite + React + TanStack Router/Query + Tailwind + shadcn/ui, Auth0 |
| Prompts | Jinja2 templates in a versioned `prompts/` tree via a `PromptService` |
| Deploy | Fly.io, one image, `web` + `worker` processes, `release_command = "alembic upgrade head"` |

**Prompts live in files, not string literals**, specifically so CI can grep rendered
templates for client data (a currency symbol, a price, a business name from any fixture) and
fail the build. The same check against f-strings scattered through agent modules is possible
in principle and unmaintainable in practice.

`uv run ruff check`, `uv run pytest`, `uv run alembic upgrade head` and `docker compose up`
(Postgres + Mailpit + web + worker from `.env.example` defaults) all work today.
PydanticAI's `TestModel`/`FunctionModel` are what let tests run offline and free —
CI must not need an API key.

**The app must start without Stripe/Vercel credentials** and fail only at the gate action,
with an explicit `credential not configured: vercel` rather than a stack trace.

## Provider constraints

Each of these is a bug you would otherwise write:

- **Never set `temperature`, `top_p`, or `top_k`.** They are removed on Opus 5 and Sonnet 5;
  a non-default value returns a 400. Reaching for `ModelSettings(temperature=...)` out of
  habit breaks both agents. Steer through prompting.
- **Extended thinking is on by default on Opus 5**, and `max_tokens` caps thinking plus
  response text together.
- **Stream the Web Builder's calls** (~64K `max_tokens`). A full site exceeds the
  non-streaming ceiling and yields SDK timeouts with truncated HTML — which is syntactically
  plausible and would then be deployed.
- **Prompt-cache minimums differ** — 512 (Opus 5), 1024 (Sonnet 5), 4096 (Haiku 4.5). A
  brand doc that caches for the Strategist may silently not cache for the Reviewer.
- `UsageLimits` is entirely token-denominated — there is **no dollar ceiling**. Enforcement
  is in tokens; dollars are derived from `RunUsage` through `pricing.yaml`, which carries
  **four effective-dated rates per model** (input, output, cache-write, cache-read).

## How to work here

Behavioral guidelines to reduce common LLM coding mistakes. They bias toward caution over
speed — for trivial tasks, use judgment.

**1. Think before coding.** Don't assume, don't hide confusion, surface tradeoffs. State
assumptions explicitly; if uncertain, ask. If multiple interpretations exist, present them
instead of silently picking one. If a simpler approach exists, say so — push back when
warranted. If something is unclear, stop and name what's confusing.

**2. Simplicity first.** The minimum code that solves the problem, nothing speculative. No
features beyond what was asked, no abstractions for single-use code, no "flexibility" or
configurability that wasn't requested, no error handling for impossible scenarios. If you
wrote 200 lines and it could be 50, rewrite it. Would a senior engineer call this
overcomplicated? Then simplify. (Corollary: a new knob is a change to the config module
*and* `.env.example` — don't add one unless it was asked for.)

**3. Surgical changes.** Touch only what you must. Don't "improve" adjacent code, comments,
or formatting; don't refactor what isn't broken; match existing style even if you'd do it
differently. If you spot unrelated dead code, mention it — don't delete it. Do remove
imports/variables/functions that *your* changes orphaned. The test: every changed line traces
directly to the request.

**4. Goal-driven execution.** Define success criteria, then loop until verified. Turn tasks
into verifiable goals ("fix the bug" → "reproduce it, then show the reproduction no longer
fires"). For multi-step work, state a brief plan as `step → verify: check`. The verification
bar depends on what exists:

- **Code changes** (the normal case): `uv run ruff check` and `uv run pytest` pass. For gate,
  ingest, or idempotency changes, exercise the actual path — the gate is testable against a
  fake adapter with zero agents, zero credentials and zero network, which is why it is the
  cheapest component to test and has no excuse for being untested.
- **Documentation and spec changes**: the claim is consistent with `DESIGN.md`, and
  cross-references to other sections are real.

## Git workflow

- **New branch, always.** Branch off `main` before making changes — never implement directly
  on `main`. Name it `<type>/<short-kebab-summary>`, using the same types as commit messages:
  `feat/` (new feature), `fix/` (bug fix), `docs/`, `refactor/`, `perf/`, `chore/` (build, CI,
  deps, config). E.g. `feat/action-gate-verify`, `fix/grounding-normalisation`.
- **Small, scoped commits.** Don't bundle the work into one commit. Split it into small,
  logically scoped commits — one concern per commit, a clear message per commit.
- **Commit progressively, not at the end.** Commit each logical chunk of work as you finish
  it, rather than accumulating changes and splitting them into small commits only at the end.
- **No `Co-Authored-By` trailer.** Never append `Co-Authored-By: Claude` (or any similar
  trailer) to a commit message, and never put a co-author or "generated with" line in a PR
  description. This holds even if a plan document, template, or default instruction says to
  add one.
- **Never commit `.claude/DECISIONS.md`**, `.env`, or anything generated. `.gitignore` must
  cover `.env` / `.env.*` (except `.env.example`), `.venv/`, `node_modules/`, `dist/`,
  `__pycache__/`, and Remotion render output from the first scaffolding commit onward. The
  artifacts of record live in Postgres, so a stray MP4 in the tree is by definition a
  leftover.
