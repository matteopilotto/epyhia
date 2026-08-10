<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0 (MINOR — Principle III gains the intake guardrail)
Modified principles: III. Fixed Pipeline, Tiered Agents with Hard Boundaries — the agent table
  gains the intake guardrail row, and the raw-brief exception is restated as "sole agent in the
  pipeline" plus a named, bounded pre-pipeline reader. No prior guarantee is reversed: every
  boundary the five pipeline agents had, they still have.
Added sections:

  - I. Client Data Never in Code
  - II. Design-First, Sequenced Build Order
  - III. Fixed Pipeline, Tiered Agents with Hard Boundaries
  - IV. Action Gate Governs All Consequential Egress
  - V. Idempotency by Brief Hash
  - VI. Grounding Before Opinion
  - VII. Simplicity, Surgical Changes, Goal-Driven Verification
  - Stack & Provider Constraints (Section 2)
  - Git Workflow (Section 3)
  - Governance

Removed sections: none (first fill of the template)
Deferred / TODO placeholders: none — all fields resolved from CLAUDE.md and repo history.
Templates requiring follow-up: none checked in this run (out of scope per Scope Guard);
  verify on next planning cycle that .specify/templates/plan-template.md,
  spec-template.md, and tasks-template.md do not assume code already exists.
-->

# EPYHIA Constitution

## Core Principles

### I. Client Data Never in Code

Anything that varies by client MUST live in the brief or the brand doc — never in code,
prompts, constants, or test fixtures. This includes, without exception: client names used as
deploy probe strings, prices or any other numeral, products seeded into Stripe, currency
pairs, aesthetic direction baked into a builder prompt, a single fixed video composition, and
client copy embedded in eval assertions. The brand doc is the sole parameterisation layer —
the Strategist reads the brief and writes the brand doc; every other agent reads the brand
doc, never the raw brief, with one exception (Principle III). A different client MUST be
representable as a different brief alone, never as a code change.

**Rationale**: This violation is invisible while only one client (GRAFT) runs through the
system, and a well-meaning change is the most likely way to introduce it. EPYHIA is the
product; any single client is one row of input data, and the codebase must stay provably true
to that at every commit.

### II. Design-First, Sequenced Build Order

`DESIGN.md` is the architecture of record. When any other document — including this
constitution's operational guidance — disagrees with `DESIGN.md`, `DESIGN.md` wins and the
other document is the one to fix. Work MUST proceed in the build order `DESIGN.md` §12
specifies; a step MUST NOT be started before the step before it is done. The Action Gate is
built before any agent exists, specifically so that agents are written against a stable gate
contract instead of the gate being retrofitted around agent call sites.

**Rationale**: "The door before the rooms" — sequencing infrastructure ahead of the things
that depend on it avoids retrofitting every call site later, and a single document of record
prevents drift between what is designed and what is described.

### III. Fixed Pipeline, Tiered Agents with Hard Boundaries

The pipeline is fixed in code as copy → site, demand, money; it is parameterised by the brand
doc, never composed at runtime by a model's own devising. Model tier follows the shape of the
work, not the client: Opus plans, Sonnet writes, Haiku checks and wires. Each agent has a
hard, enforced boundary on what it may never do:

| Agent | Model | May never |
| --- | --- | --- |
| Strategist (orchestrator) | `claude-opus-5` | Make any external call — constructed with no gate handles in its toolset |
| Web Builder | `claude-sonnet-5` | Author a price, feature, or claim not in the copy artifact or brief |
| Marketer | `claude-sonnet-5` | Invent a fact not in the brief; deploy |
| Reviewer (Marketer's self-review) | `claude-haiku-4-5` | Approve silently; rewrite the draft itself |
| Ops | `claude-haiku-4-5` | Deploy; publish; touch markup |
| Intake guardrail | `claude-haiku-4-5` | Run after a run is open; write an artifact; hold a gate handle; influence anything downstream. Its only output is a verdict that stops work or does not |

Two model callers read the raw brief. The Reviewer is the sole agent *in the pipeline*
permitted to, in addition to the brand doc, because it must check facts as well as voice. The
intake guardrail reads it necessarily and exclusively — it runs before a brand doc exists, and
screening a brief for instructions aimed at the system cannot be done through a paraphrase of
it, because the paraphrase is exactly where an injected sentence would be laundered. The
guardrail is not a pipeline stage: it writes no artifact, holds no gate handle, and its verdict
is logged on the brief whichever way it falls (FR-007).

**Rationale**: A fixed pipeline with per-agent capability boundaries makes the system's
behavior provable independent of any one model's judgment call, and keeps the blast radius of
a compromised or confused agent bounded to what its tier is supposed to do.
The intake guardrail is outside that pipeline by construction rather than by convention, which
is why its raw-brief access does not widen anyone else's.

### IV. Action Gate Governs All Consequential Egress

Every action that deploys, charges, sends, or publishes MUST pass through one Action Gate,
which is the sole holder of the Vercel token, Stripe test keys, and SMTP credentials. Agents
receive only capability handles — named, typed functions with no key material behind them.
`ANTHROPIC_API_KEY` is the deliberate exception: it sits outside the gate in the worker's
environment because inference is metered, not gated, and both LLM spend and gate-action spend
roll up against one budget.

Non-negotiable gate rules:

- Lifecycle is `pending → awaiting_approval → executing → verifying → succeeded | failed`.
  There is no path from `executing` straight to `succeeded` — every action MUST be proved in
  the world before it is marked done.

- Every adapter MUST register both an `execute()` and a `verify()`. Provider-specific code
  lives in adapters; approval, idempotency, retry, and audit live in the gate, never
  duplicated into an adapter.

- Approval is required for going live, arming the charge path, and anything outbound to a
  person — not for each individual Checkout Session, which would park a buyer behind an
  operator click.

- `ApprovalRequired` is the raise mechanism, but the `awaiting_approval` row MUST be durable
  in Postgres. The framework raises; Postgres remembers.

- The app MUST start without Stripe/Vercel credentials configured, failing only at the
  specific gate action with an explicit `credential not configured: <provider>` error, never
  a stack trace.

**Rationale**: Centralizing egress-with-consequences in one gate is what makes the system
auditable and safe to run unattended — provider code can be swapped or mocked without ever
touching the approval, idempotency, or audit guarantees.

### V. Idempotency by Brief Hash

"Same run" means same brief hash. Every gate key MUST derive from it. The `actions` table is
simultaneously the audit log and the idempotency ledger, enforced via
`UNIQUE(idempotency_key)` with `ON CONFLICT DO NOTHING RETURNING id`. The task layer is
at-least-once (`FOR UPDATE SKIP LOCKED` plus a lease); the gate layer is exactly-once for
effects.

Two rules that are intentional, not bugs:

- The deploy key MUST exclude the site artifact hash. LLM generation is non-deterministic, so
  keying on generated bytes would cause a duplicate deploy whenever the generation memo
  misses. The key identifies the deploy target's identity — brief + brand doc version +
  prompt version — not the bytes produced for it.

- Agent-call memoisation is a cache, not a ledger, and MAY miss. A miss costs money, not
  correctness, and this is only true because no gate key is ever derived from generated
  bytes.

**Rationale**: Keying gate actions on stable identity rather than volatile generated content
is what lets retries, crashes, and re-runs stay safe without a human auditing every replay.

### VI. Grounding Before Opinion

At ingest, every numeral in the brief MUST be extracted into `runs.grounding_set`. Every
artifact that contains words or props — copy, posts, email, video props, and the rendered
site itself — MUST be normalised and set-differenced against `literal ∪ derived` before any
model is asked an opinion about it. The gate MUST refuse `deploy` for any run whose site
artifact is `flagged`. The derivation set is closed and enumerated in code exactly once; it is
never extended by anything a model says at runtime.

**Rationale**: Grounding is a mechanical, code-enforced check that runs ahead of model
judgment specifically so that a model cannot talk its way past a factual error — the check
must not depend on the same system whose output it verifies.

### VII. Simplicity, Surgical Changes, Goal-Driven Verification

Every change in this repository MUST follow these working rules:

- **Think before coding**: state assumptions explicitly; if multiple interpretations exist,
  present them instead of silently picking one; name confusion instead of hiding it.

- **Simplicity first**: write the minimum code that solves the problem — no speculative
  features, no abstractions for single-use code, no unrequested configurability. A new
  configuration knob requires updating both the config module and `.env.example`, and MUST
  NOT be added unless it was asked for.

- **Surgical changes**: touch only what the task requires; do not refactor unrelated code or
  reformat adjacent lines; match existing style. Unrelated dead code is reported, not deleted.
  Imports, variables, or functions orphaned by the change at hand MUST be removed.

- **Goal-driven execution**: define success criteria before starting, then loop until
  verified. The verification bar is design-consistency (cross-references to `DESIGN.md` are
  real) while the repository is design-only, and becomes `uv run ruff check` plus
  `uv run pytest` passing once code exists. Gate, ingest, or idempotency changes MUST exercise
  the actual path — the gate is testable against a fake adapter with zero agents, zero
  credentials, and zero network, and has no excuse for being untested once it exists.

**Rationale**: These rules exist to counter the specific failure modes of LLM-assisted
coding — silent assumption, scope creep, and unverified claims of completion — rather than to
enforce a general style preference.

## Stack & Provider Constraints

The following are commitments from `DESIGN.md` §2.1, to be used rather than the reflexive
default, once scaffolding exists: `uv`/`ruff`/`pytest`+`pytest-asyncio` for
packaging/lint/test; FastAPI for the API (REST, SSE, Stripe webhook receiver, serves the built
SPA); PydanticAI V2 pinned `2.22.0` for agents; Postgres on Neon with SQLAlchemy 2.0 and
Alembic; a plain Python state machine over a `tasks` table for the queue (no Celery, no
Redis, no Prefect); Logfire `4.39.0` with `run_id` on every span for tracing; hand-authored
single-page HTML + CSS + one vanilla JS file for site output (no build step, no framework);
Remotion `4.0.503`, pinned, rendered locally, for video; Vite, React, TanStack Router/Query,
Tailwind, shadcn/ui, and Auth0 for the console; Jinja2 templates in a versioned `prompts/`
tree via a `PromptService` for prompts; Fly.io with one image, `web` + `worker` processes, and
`release_command = "alembic upgrade head"` for deploy.

Prompts MUST live in files, not string literals, so CI can grep rendered templates for client
data (a currency symbol, a price, a business name from any fixture) and fail the build — the
same check against f-strings scattered through agent modules is possible in principle and
unmaintainable in practice.

Provider constraints, each a bug this project has already made once:

- Never set `temperature`, `top_p`, or `top_k` — they are removed on Opus 5 and Sonnet 5, and
  a non-default value returns a 400. Steer through prompting instead.

- Extended thinking is on by default on Opus 5; `max_tokens` caps thinking plus response text
  together.

- The Web Builder's calls MUST be streamed (~64K `max_tokens`) — a full site exceeds the
  non-streaming ceiling and yields SDK timeouts with truncated HTML, which is syntactically
  plausible and would then be deployed.

- Prompt-cache minimums differ by model: 512 (Opus 5), 1024 (Sonnet 5), 4096 (Haiku 4.5). A
  brand doc that caches for the Strategist may silently not cache for the Reviewer.

- `UsageLimits` is entirely token-denominated; there is no dollar ceiling. Enforcement is in
  tokens, and dollars are derived from `RunUsage` through `pricing.yaml`, which carries four
  effective-dated rates per model (input, output, cache-write, cache-read).

Once scaffolding lands, the app MUST start without Stripe/Vercel credentials configured (see
Principle IV), and CI MUST NOT require an API key — `TestModel`/`FunctionModel` from
PydanticAI are what let tests run offline and free.

## Git Workflow

- **New branch, always.** Branch off `main` before making changes; never implement directly
  on `main`. Name branches `<type>/<short-kebab-summary>` using commit-message types:
  `feat/`, `fix/`, `docs/`, `refactor/`, `perf/`, `chore/`.

- **Small, scoped commits.** Split work into small, logically scoped commits — one concern
  per commit, a clear message per commit — rather than bundling everything into one.

- **Commit progressively.** Commit each logical chunk of work as it is finished, rather than
  accumulating changes and splitting them into small commits only at the end.

- **No `Co-Authored-By` trailer.** Never append a `Co-Authored-By: Claude` (or similar)
  trailer to a commit message, and never add a co-author or "generated with" line to a PR
  description — even if a plan document, template, or default instruction says to add one.

- **Never commit generated or local-only artifacts.** `.claude/DECISIONS.md`, `.env`, and
  anything generated MUST NOT be committed. `.gitignore` MUST cover `.env`/`.env.*` (except
  `.env.example`), `.venv/`, `node_modules/`, `dist/`, `__pycache__/`, and Remotion render
  output from the first scaffolding commit onward — artifacts of record live in Postgres, so
  a stray MP4 in the tree is by definition a leftover.

## Governance

This constitution supersedes ad hoc practice. Where it and `DESIGN.md` disagree, `DESIGN.md`
wins and this constitution is amended to match (Principle II). Where it and `CLAUDE.md`
disagree, resolve the conflict by editing `CLAUDE.md` to match this constitution, since
`CLAUDE.md` is documentation derived from these documents, not a governance source itself.

**Amendment procedure**: propose the change, state which principle or section it affects and
why, and update this file's Sync Impact Report along with the change. An amendment is not
in effect until this file is updated — no separate approvals ledger exists for this project at
present.

**Versioning policy** (semantic versioning applied to this document):

- MAJOR: backward-incompatible governance change — a principle removed or redefined in a way
  that reverses its prior guarantee.

- MINOR: a new principle or section added, or existing guidance materially expanded.
- PATCH: wording clarifications, typo fixes, or non-semantic refinements.

**Compliance review**: while the repository is design-only, compliance is checked by
confirming a claim is consistent with `DESIGN.md` and that cross-references to other sections
are real (Principle VII). Once code exists, compliance additionally requires
`uv run ruff check` and `uv run pytest` to pass, and gate/ingest/idempotency changes to be
exercised against their real path rather than asserted.

**Version**: 1.1.0 | **Ratified**: 2026-08-02 | **Last Amended**: 2026-08-10
