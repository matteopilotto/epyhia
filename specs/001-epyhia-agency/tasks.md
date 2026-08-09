# Tasks: EPYHIA — An Agency Staffed by Agents

**Input**: Design documents from `/specs/001-epyhia-agency/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test tasks ARE included. They are not speculative TDD — each one is named by the spec
or the constitution: [quickstart.md](./quickstart.md) S0 enumerates seven gate assertions,
FR-060/[research.md R10](./research.md) mandates the prompt-tree lint, FR-061–FR-063 mandate the
eval, and Constitution Principle VII says the gate "has no excuse for being untested".

**Organization**: Tasks are grouped by user story. Two constraints override pure story
independence, both from Constitution Principle II (`DESIGN.md` §12 build order is binding):

1. **The Action Gate is built before any agent exists** (§12 step 2). It sits at the top of
   Phase 2, ahead of the rest of the schema.
2. **`agent_calls` ships on day one, not backfilled** (§12 step 3). The cost *ledger* is
   foundational; the cost *budgets, endpoint and console view* are US5.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Include exact file paths in descriptions

## Path Conventions

Single repository, one installable Python package `epyhia/`, three sibling non-Python trees
([research.md R1](./research.md)). Paths below are repo-root relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Reach a clean clone that starts, lints and tests — with no credentials configured
(FR-064, FR-065, SC-010).

- [X] T001 Create the package skeleton per [plan.md](./plan.md) "Source Code": `epyhia/{gate/adapters,ingest,queue,agents,models,api,cost,artifacts}/__init__.py`, plus empty `prompts/`, `console/`, `video/`, `eval/`, `migrations/`, `tests/{gate,ingest,queue,cost,genericity,integration,fixtures/briefs}/`
- [X] T002 Author `pyproject.toml` — one distribution, `uv`-managed, pinning `pydantic-ai==2.22.0`, `logfire==4.39.0`, plus `fastapi`, `uvicorn`, `sqlalchemy>=2.0`, `alembic`, `asyncpg`, `jinja2`, `pyyaml`, `httpx`, `stripe`, `pytest`, `pytest-asyncio`, `ruff`
- [X] T003 [P] Configure `ruff` and `pytest` (`asyncio_mode = "auto"`) in the `[tool.ruff]` / `[tool.pytest.ini_options]` sections of `pyproject.toml`
- [X] T004 [P] Write `.gitignore` covering `.env`, `.env.*` (except `.env.example`), `.venv/`, `node_modules/`, `dist/`, `__pycache__/`, `video/out/`, and `.claude/DECISIONS.md` (Constitution §Git Workflow)
- [X] T005 [P] Write `.env.example` — variable names and safe local defaults only, never a real key: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VERCEL_TOKEN`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `MAILPIT_API_URL`, `SINK_BASE_URL`, `SINK_TOKEN`, `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `RUN_BUDGET_USD`, `DAILY_CEILING_USD`
- [X] T006 Implement `epyhia/config.py` — a `Settings` object where an absent credential is a stored `None`, never a start-time failure; expose `require(provider)` returning the value or raising `CredentialNotConfigured(provider)` (FR-064)
- [X] T007 Write `Dockerfile` — Python 3.13 + Node 22 + headless Chrome in one image; Node stage builds `console/` and installs `video/` deps; single image serves both Fly processes
- [X] T008 Write `docker-compose.yml` — Postgres, Mailpit, `web`, `worker`, all defaults from `.env.example` so `docker compose up` is the whole setup with no account signup (FR-065)
- [X] T009 [P] Write `fly.toml` — `[processes] web`/`worker` off one image, `release_command = "alembic upgrade head"`
- [X] T010 Initialise Alembic in `migrations/` with `migrations/env.py` reading the URL from `epyhia.config`
- [X] T011 Create the FastAPI app factory in `epyhia/api/app.py` — router mounting, Logfire init with `run_id` as a span field, and a static mount serving the built SPA from one origin (no CORS)
- [X] T012 [P] Write `tests/conftest.py` — a transactional Postgres session fixture and an `anyio`/asyncio event-loop fixture; no network, no API key, no credentials

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The gate, the schema, the queue, the cost ledger and brief ingest — everything every
user story stands on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### 2a · The Action Gate — `DESIGN.md` §12 step 2, "the door before the rooms"

- [X] T013 Define the `actions` model in `epyhia/models/actions.py` per [data-model.md](./data-model.md) — all columns, `UNIQUE(idempotency_key)`, and a CHECK constraint `state <> 'succeeded' OR evidence IS NOT NULL`
- [X] T014 Generate the Alembic migration for `actions` in `migrations/versions/` and confirm the CHECK constraint and unique index are present in the emitted DDL
- [X] T015 [P] Implement `epyhia/gate/keys.py` — the six derivations from [data-model.md](./data-model.md) "Idempotency keys". The `deploy` key MUST exclude the site artifact hash; the `video_render` key MUST include the pinned Remotion version (FR-045, FR-046)
- [X] T016 [P] Define the `Adapter` protocol and the `action_type → adapter` registry in `epyhia/gate/registry.py` per [contracts/action-gate.md](./contracts/action-gate.md) §3 — `action_type`, `requires_approval`, `async execute(request, ctx)`, `async verify(request, result, ctx)`
- [X] T017 [P] Define the gate's typed errors in `epyhia/gate/errors.py` — `CredentialNotConfigured(provider)` rendering as `credential not configured: <provider>`, `VerificationFailed`, `PreconditionFailed`
- [X] T018 Implement `epyhia/gate/gate.py` — `request()` in the exact order of [contracts/action-gate.md](./contracts/action-gate.md) §2: preconditions → `INSERT ... ON CONFLICT DO NOTHING RETURNING id` → short-circuit terminal rows → set `awaiting_approval` **durably before** raising `ApprovalRequired` → `executing` → `verifying` with backoff capped at 5 → `succeeded` with evidence stored. No `executing → succeeded` edge exists in the code (FR-035, R7)
- [X] T019 Implement the precondition table in `epyhia/gate/gate.py` — `deploy` requires the run's `site` artifact to be `clean`; `checkout_session` requires the run's `arm_charge_path` action to be `succeeded`; every action requires its credential (contracts/action-gate.md §5)
- [X] T020 Write the configurable fake adapter in `epyhia/gate/adapters/fake.py` — modes for succeed, fail-in-execute, always-fail-verify, and record-calls; used by every test below
- [X] T021 [P] Test in `tests/gate/test_approval.py`: an approval-required action lands `awaiting_approval` in Postgres **before** anything is raised, and the row survives a fresh session (FR-038, R7)
- [X] T022 [P] Test in `tests/gate/test_concurrency.py`: two concurrent `request()` calls on one key produce one execution and one row; the second reads the first's result (FR-044, SC-003)
- [X] T023 [P] Test in `tests/gate/test_verify_retry.py`: a `verify()` that always raises retries to the cap of 5 and lands `failed`, never `succeeded` (FR-041, SC-002)
- [X] T024 [P] Test in `tests/gate/test_evidence_constraint.py`: writing `state='succeeded'` with null `evidence` is rejected by the database, not by application code (FR-040)
- [X] T025 [P] Test in `tests/gate/test_deny.py`: deny is terminal — `state='denied'`, `approved_by` recorded, and a subsequent `request()` on the same key executes nothing, ever (FR-036)
- [X] T026 [P] Test in `tests/gate/test_credentials.py`: an action whose credential is absent raises `CredentialNotConfigured` and surfaces as `credential not configured: <provider>`, with no adapter registered and no stack trace (FR-064, SC-010)
- [X] T027 [P] Test in `tests/gate/test_crash_resume.py`: a row abandoned mid-`executing` resumes into `verifying` and the outcome comes from the probe, not the stored status (§7.4, SC-008)
- [X] T133 [P] Test in `tests/gate/test_keys.py`: the `deploy` key is unchanged when only the generated site bytes differ, and the `video_render` key changes when the pinned Remotion version is bumped — a version upgrade must never serve stale output as a cache hit (FR-045, FR-046)

**Checkpoint**: `uv run pytest tests/gate/` passes with zero agents, zero credentials and zero
network. If it needs any of those, the gate has been built wrong.

### 2b · Schema, queue and cost ledger — `DESIGN.md` §12 step 3

- [X] T028 Define the remaining models per [data-model.md](./data-model.md) in `epyhia/models/`: `briefs.py`, `runs.py`, `brand_docs.py`, `tasks.py`, `agent_calls.py`, `artifacts.py`, `orders.py`, `agent_cache.py`, `sink_posts.py` — no column carries a client-specific default (Principle I)
- [X] T029 Generate the Alembic migration for all remaining tables in `migrations/versions/`, including `UNIQUE(briefs.content_sha256)`, `UNIQUE(brand_docs.brief_id, version)` and `UNIQUE(orders.stripe_event_id)`
- [X] T030 [P] Implement the `ArtifactStore` interface and its Postgres `bytea` backend in `epyhia/artifacts/store.py`, writing in the same transaction as the task row that produced the artifact (§5.4)
- [X] T031 Implement task claiming in `epyhia/queue/claim.py` — the single `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` statement from [research.md R8](./research.md), with `depends_on` satisfaction and a **per-`kind`** lease interval
- [X] T032 Implement the lease sweeper in `epyhia/queue/sweeper.py` — expired leases return to `pending` and increment `attempts`; past the cap the row lands `failed`; rows in `awaiting_approval` are never resurrected (R8, R7 step 4)
- [X] T033 Implement the worker loop in `epyhia/queue/worker.py` — claim, dispatch by `kind`, release the lease on `awaiting_approval`, and the `worker` process entrypoint
- [X] T034 [P] Test in `tests/queue/test_claim.py`: two workers claiming concurrently each get a distinct row; an expired lease is re-claimable; an `awaiting_approval` row is left alone by the sweeper (FR-047)
- [X] T035 [P] Write `epyhia/cost/pricing.yaml` in the [research.md R9](./research.md) shape — per model a `tier` and a list of `effective_from` rate rows carrying `input`, `output`, `cache_write`, `cache_read`
- [X] T036 Implement `epyhia/cost/pricing.py` — load `pricing.yaml`, select the greatest `effective_from` not after a call's timestamp, and raise a hard error when no rate row applies (never a silent `0.00`)
- [X] T037 Implement `epyhia/cost/ledger.py` — write one `agent_calls` row per model call with agent, model id, `tier` read from `pricing.yaml`, four token counts from `RunUsage`, derived cost, latency and `cache_hit`; both columns NOT NULL (FR-049, R9)
- [X] T038 [P] Test in `tests/cost/test_pricing.py`: effective-dated selection picks the right row across a rate change, and an unknown model id raises rather than costing zero (FR-051, R9)

### 2c · Brief ingest — `DESIGN.md` §12 step 4, before anything expensive runs

- [X] T039 [P] Implement `epyhia/ingest/hashing.py` — canonical JSON serialisation (sorted keys, no insignificant whitespace) → `content_sha256` (FR-002)
- [X] T040 [P] Implement numeral normalisation in `epyhia/ingest/normalise.py` — strip separators and currency symbols, reduce amounts to minor units in a named currency, map locale-scoped number words to digits; a grounding entry is `(value: Decimal, currency: str | None)` (FR-006, R6)
- [X] T041 Implement the **closed** derivation set in `epyhia/ingest/grounding.py` — exactly the five families of [research.md R6](./research.md) (×12/×52 annualisation, pairwise sums and absolute differences, list cardinalities, `current_year − established`, the same minor-unit amount restated under the product's other currency label with **no FX conversion**), plus the standalone `set_difference(extracted, grounding_set)` function with currency-compatibility matching. Nothing extends this set at runtime (FR-005, Principle VI)
- [X] T042 Implement per-artifact-kind extractors in `epyhia/ingest/extractors.py` per the [research.md R5](./research.md) table — structured string values for `copy`/`posts`/`email`; for `site`, text nodes outside `<script>`/`<style>` plus `alt`, `title`, `aria-label` and `<meta name="description">` and nothing else; for `video_props`, every leaf under `content` and nothing under `style`
- [X] T043 Implement the input guardrail in `epyhia/ingest/guardrail.py` — a bounded Haiku judge over the raw brief that logs its decision and reason on **both** outcomes and stops a rejected brief before expensive work (FR-007)
- [X] T044 [P] Test in `tests/ingest/test_grounding.py`: the five derivation families are produced exactly, the same number written four ways all match after normalisation, the currency-label restatement matches without conversion, and a fabricated numeral is reported as a violation (FR-006, SC-004, R6)
- [X] T045 [P] Test in `tests/ingest/test_extractors.py`: the site extractor ignores `#0a0a0a`, `1.5rem`, `0.3s`, `viewBox` and `data-product`, and the `video_props` extractor reads `content` leaves while skipping every `style` value (R5)
- [X] T132 [P] Test in `tests/ingest/test_guardrail.py` using PydanticAI `FunctionModel`: a brief carrying instructions aimed at the system is rejected before any expensive work begins, an accepted brief logs its decision and reason too, and the screening decision is retrievable from the record on **both** outcomes (FR-007, SC-012)

### 2d · Shared API surface

- [X] T046 [P] Implement the Auth0 Bearer validator in `epyhia/api/auth.py` — JWKS validation on every operator route, with **no second path in**: no bypass key, no cookie session (FR-057)
- [X] T047 [P] Implement the single error shape `{error, detail}` and its exception handlers in `epyhia/api/errors.py` (contracts/rest-api.md §Errors)
- [X] T048 [P] Implement `PromptService` in `epyhia/prompts_service.py` — renders `prompts/<agent>/<version>.jinja` and exposes the active `prompt_version`; no prompt text exists as a string literal in source (FR-060)
- [X] T049 [P] Implement the SSE helper in `epyhia/api/sse.py` emitting `task`, `action`, `artifact`, `agent_call` and `cost` events, designed for `fetch` + `ReadableStream` consumption (§10)
- [X] T050 Implement `POST /briefs` in `epyhia/api/routers/briefs.py` — validate the payload against [contracts/brief.schema.json](./contracts/brief.schema.json), returning `400` with itemised violations; then synchronously canonicalise and hash, run the guardrail, extract the grounding set, open the run with its derived `alias`, enqueue the `plan` task; returns `201` or `422 {error: "guardrail_rejected"}` (FR-001, FR-004, FR-007)
- [X] T051 [P] Implement `GET /runs` and `GET /runs/{id}` in `epyhia/api/routers/runs.py` returning status, brand doc version, prompt version, spend against budget and alias
- [X] T052 [P] Add the first brief fixture at `tests/fixtures/briefs/one.json` conforming to [contracts/brief.schema.json](./contracts/brief.schema.json), with both a `subscription` and a `one_time` product and a `currency_display` differing from `currency_charge`. It is **input data**, so it carries real client-shaped values — no test may assert against a value copied out of it

**Checkpoint**: Foundation ready. A brief can be submitted, hashed, grounded and queued; the gate
governs a fake action end to end; every model call has somewhere to record its cost.

---

## Phase 3: User Story 1 - Brief to a verified live website (Priority: P1) 🎯 MVP

**Goal**: One plain-language brief becomes a publicly reachable site whose liveness is proved by
an independent probe asserting that run's own business name and build marker.

**Independent Test**: Submit a brief for a previously unseen business, approve go-live, open the
returned URL, then read `actions.evidence` and confirm `matched_name` equals
`brand_docs.doc->>'name'` for that run — with zero source files changed.

**Note**: The `copy` artifact is **stubbed from the brand doc's composition plan** in this phase
(`DESIGN.md` §12 step 6). The seam is what matters — US2 fills it in without the Web Builder
changing.

- [X] T053 [P] [US1] Write `prompts/strategist/v1.jinja` — reads the brief as named fields, emits a brand doc conforming to [contracts/brand-doc.schema.json](./contracts/brand-doc.schema.json). Contains **no aesthetic direction for any client** and no client token of any kind
- [X] T054 [US1] Implement the Strategist in `epyhia/agents/strategist.py` — `claude-opus-5`, brief passed as a **typed object** never as prose (FR-008), toolset is exactly `write_brand_doc` + `enqueue_tasks` and **nothing else** (FR-042). Never set `temperature`/`top_p`/`top_k`
- [X] T055 [US1] Implement the fixed pipeline in `epyhia/queue/pipeline.py` — the task set `plan → {copy → site, demand, money}` is constructed in code; `enqueue_tasks` selects from it and cannot compose a graph (FR-013, Principle III)
- [X] T056 [US1] Implement the interim `copy` artifact stub in `epyhia/agents/copy_stub.py`, derived from `brand_doc.composition_plan`, writing a `copy` artifact of the same shape the Marketer will later write (§12 step 6)
- [X] T057 [P] [US1] Write `prompts/web_builder/v1.jinja` — describes the composition mechanism and the anti-slop bar, consumes the section-level `composition_plan` and the reviewed `copy` artifact, and forbids authoring any price, feature or claim not present in them (FR-015)
- [X] T058 [US1] Implement the Web Builder in `epyhia/agents/web_builder.py` — `claude-sonnet-5`, **streamed** at ~64K `max_tokens` because non-streaming truncates into plausible HTML that would then be deployed; emits a single-page HTML + CSS + one vanilla JS artifact with no build step and no credentials (FR-014, §8.1)
- [X] T059 [US1] Wire the site-artifact grounding check into the `site` task in `epyhia/queue/handlers/site.py` — run `extractors.site` then `set_difference` against `runs.grounding_set`, storing `grounding_status` and itemised `violations` before any model is asked an opinion (FR-016, FR-022)
- [X] T060 [US1] Implement `runs.alias` derivation in `epyhia/gate/keys.py` — `epyhia-<brief_hash[:12]>.vercel.app`, a pure function of the brief hash so `verify()` computes the URL it probes rather than being told it (R2)
- [X] T061 [US1] Implement `execute()` in `epyhia/gate/adapters/vercel.py` — `POST /v13/deployments` with inline files, `target: "production"`, `projectSettings: {framework: null, buildCommand: null, outputDirectory: "."}`; poll `readyState` to `READY`/`ERROR`; `POST /v2/deployments/{id}/aliases`, treating `409` as success (R2)
- [X] T062 [US1] Implement build-marker injection in `epyhia/gate/adapters/vercel.py` — the adapter inserts `<meta name="epyhia-build" content="<brief_hash[:8]>.<brand_doc_version>.<prompt_version>">` into `<head>` **at upload time**, so the stored artifact's `sha256` stays a pure function of the brief and brand doc (R3, FR-019)
- [X] T063 [US1] Implement `verify()` in `epyhia/gate/adapters/vercel.py` — `GET` the **derived alias**, not the URL the API returned; assert `200`, that `brand_doc.name` read from the run's row appears in the body, and that this build's marker is present; store `{status, matched_name, matched_build_marker, url}` (FR-018, FR-019)
- [X] T064 [P] [US1] Test in `tests/gate/test_vercel_adapter.py` against a stubbed HTTP transport: the happy path, the `409`-on-alias path, and the **stale-alias** path where the body lacks this build's marker and the action must land `failed` rather than `succeeded` (US1 scenario 6)
- [X] T065 [US1] Implement `GET /runs/{id}/events` in `epyhia/api/routers/runs.py` — the live timeline sourced from `tasks`, `actions`, `artifacts` and `agent_calls` ordering
- [X] T066 [P] [US1] Implement `GET /runs/{id}/actions` in `epyhia/api/routers/actions.py` — every action with state, idempotency key, projected and actual cost, and **its stored evidence** (FR-040)
- [X] T067 [US1] Implement `POST /actions/{id}/approve` and `POST /actions/{id}/deny` in `epyhia/api/routers/actions.py` — write `approval_decision`, `approved_by` (Auth0 `sub`) and `approved_at`, enqueue the `resume` task carrying the action id, and return `409 {error: "not_awaiting_approval"}` on a second click (FR-038, R7 step 5)
- [X] T068 [US1] Scaffold the console in `console/` — Vite + React + TanStack Router/Query + Tailwind + shadcn/ui + Auth0, consuming SSE via `fetch` + `ReadableStream` rather than `EventSource` (§10)
- [X] T069 [US1] Build the brief submit form and the live run timeline in `console/src/routes/runs.tsx`
- [X] T070 [US1] Build the approval view in `console/src/routes/approvals.tsx` showing what is about to happen, the concrete target, the projected cost, **the idempotency key**, and approve/deny controls (FR-039, SC-005)
- [X] T071 [US1] Integration test in `tests/integration/test_us1_brief_to_site.py` using PydanticAI `TestModel`/`FunctionModel` and the fake deploy adapter: submit → brand doc → site → `awaiting_approval` → approve → `succeeded` with `matched_name` read from the brand doc row, plus the deny path leaving nothing published (US1 scenarios 1–4)

**Checkpoint**: US1 is fully functional. A brief becomes a proved-live URL, and the audit row
carries the evidence that the check ran.

---

## Phase 4: User Story 2 - A marketing pack that cannot state a fact the business did not give it (Priority: P2)

**Goal**: Landing copy, 3–5 posts, a launch email and a launch video with a vertical cut — every
numeral mechanically checked against the brief before any model is asked an opinion, and anything
failing held rather than sent.

**Independent Test**: Let the pack generate, confirm every numeral traces to
`runs.grounding_set`, then inject a fabricated price into a draft and confirm the piece is held.
Separately inject one into the *site* and confirm the **gate** refuses the deploy.

**⚠️ Ordering, revised after the US1 smoke run**: T072–T077 are a **blocking prefix**. Nothing
in 4b starts until the copy stub is gone.

A real-model US1 run showed why. The interim stub (T056) can only emit the composition plan's
layout intent, so the Web Builder was handed a section whose own intent read *"this is the
page's argument"* with no argument in it — and it invented one: offering names, pickup days and
inclusions that contradicted the brief, with none of the brief's prices anywhere. The page still
stored `grounding_status = clean`, because the grounding check is **numeral-only by design**
(FR-004, R6) and every fabricated fact was a word.

That is the stub starving the seam, not a defect in US1 — but it means every judgement about
site quality made before T077 is made through a starved input, and the pack work in 4b neither
depends on that nor tells us anything about it.

### 4a · Close the copy seam first (blocking)

- [X] T072 [P] [US2] Write `prompts/marketer/v1.jinja` — brand doc in; landing copy, 3–5 posts, launch email and video props out. No client token, no fixed archetype, no numeral
- [X] T073 [P] [US2] Write `prompts/reviewer/v1.jinja` — emits itemised violations `{kind, quote, why}`, never a rewrite and never a bare approval (FR-023)
- [X] T074 [US2] Implement the Marketer in `epyhia/agents/marketer.py` — `claude-sonnet-5`, reads only the brand doc, writes `copy`, `posts`, `email` and `video_props` artifacts; gate handles are exactly `send_email` and `publish`
- [X] T075 [US2] Implement the Reviewer in `epyhia/agents/reviewer.py` — `claude-haiku-4-5`, inputs scoped to draft + brand doc + **raw brief** and explicitly **not** the run transcript; returns the structured violation list (FR-011, FR-023)
- [X] T076 [US2] Implement the revision loop in `epyhia/queue/handlers/pack.py` — the deterministic numeric check runs first, then the Reviewer; at most **two** revisions, after which the artifact is stored `flagged` with its violations and surfaced rather than delivered (FR-024)
- [X] T077 [US2] Replace the `copy` stub — delete `epyhia/agents/copy_stub.py` and its call site (`epyhia/queue/handlers/copy.py`) so the `copy` task produces real reviewed copy that **blocks** the `site` task, with the Web Builder unchanged (FR-021, US2 scenario 6)

**Checkpoint 4a — re-run the US1 smoke before going further.** Drive one brief through
`plan → copy → site` against real models and read the rendered page against **that brief's own
`products[]`**: every offering name, every stated day, time and inclusion, and every price on
the page must trace to the brief. This is the assertion the pre-T077 run failed, and it is not
covered by the numeral check — so it is read here, once, by a person. If the page still states
facts the brief did not give it, that is a prompt or a copy-shape problem and it is cheaper to
find now than after 4b exists.

### 4b · The rest of the pack

- [X] T078 [P] [US2] Implement the email adapter in `epyhia/gate/adapters/email.py` — `execute()` sends SMTP to Mailpit; `verify()` reads the message **back out of Mailpit's API** and stores `{message_id, recipient, subject}` (FR-037, §4.5)
- [X] T079 [P] [US2] Implement the recording sink in `epyhia/api/routers/sink.py` — token-authenticated `POST /sink/posts` → `{id, permalink}` and `GET /sink/posts/{id}`, backed by `sink_posts` (R4)
- [X] T080 [US2] Implement the publish adapter in `epyhia/gate/adapters/publish.py` — approval-gated (`requires_approval = true`: a stand-in channel still gets real approval, FR-043); a real HTTP round trip to the sink's configured base URL, never an in-process call; `verify()` fetches the permalink and asserts the stored `payload_sha256` matches (R4)
- [X] T081 [P] [US2] Create the Remotion project in `video/` — pinned `4.0.503`, 3–4 parameterised composition archetypes consuming [contracts/video-props.schema.json](./contracts/video-props.schema.json), each with a 1080×1920 vertical variant of the same archetype
- [X] T082 [US2] Implement the `video` task handler in `epyhia/queue/handlers/video.py` — render the primary and vertical cuts locally from **one** `video_props` artifact, store both as artifacts, and use the long per-`kind` lease from R8 (FR-025)
- [X] T083 [US2] Wire the `video_props` grounding check into `epyhia/queue/handlers/pack.py` — extract every leaf under `content`, set-difference it, and never render a `flagged` props artifact (FR-026, R5)
- [X] T084 [P] [US2] Implement `GET /runs/{id}/artifacts` and `GET /artifacts/{id}` in `epyhia/api/routers/artifacts.py` — including `grounding_status` and itemised `violations`; flagged artifacts are **listed and readable**, read-only (FR-024)
- [X] T085 [P] [US2] Build the artifacts view in `console/src/routes/artifacts.tsx`, rendering flagged artifacts with their violations rather than hiding them
- [X] T086 [P] [US2] Test in `tests/integration/test_us2_grounding_hold.py`: a fabricated numeral in a draft is held through two revisions then stored `flagged`; the Reviewer's output is itemised and is never a rewrite (FR-023, FR-024)
- [X] T087 [US2] Test in `tests/gate/test_deploy_precondition.py`: a run whose `site` artifact is `flagged` has its `deploy` **refused by the gate**, with no adapter invoked and no agent involved (FR-016, §3.4)
- [X] T088 [P] [US2] Test in `tests/integration/test_us2_send_verify.py`: `send_email` and `publish` **each** halt for approval (FR-043), and after approval `verify()` proves the email by reading it back from Mailpit and the post by fetching the sink permalink

**Checkpoint**: US1 and US2 both work independently. Nothing leaves the system carrying a number
the brief did not give it — including the site.

---

## Phase 5: User Story 3 - A checkout that takes a real test payment and records the order (Priority: P3)

**Goal**: `brief.products[]` becomes a live Stripe test catalogue behind one approval, and a buyer
completes a purchase with zero operator interaction.

**Independent Test**: With a brief carrying both a recurring and a one-time product, approve the
catalogue, click buy on the live site, complete with a test card, and confirm an `orders` row
matching a product in that brief.

- [X] T089 [P] [US3] Write `prompts/ops/v1.jinja` — near-mechanical translation of `brief.products[]` into catalogue rows; no product, price, currency or billing type may appear in the template (FR-027)
- [X] T090 [US3] Implement Ops in `epyhia/agents/ops.py` — `claude-haiku-4-5`, reads the brand doc plus the run's **resolved catalogue** from T091 (derived from `brief.products[]` at ingest — Ops never reads the raw brief, FR-011); gate handles are exactly `stripe_product`, `stripe_price` and `arm_charge_path`. It may never deploy, publish or touch markup. Depends on T091
- [X] T091 [US3] Implement slug derivation in `epyhia/ingest/catalogue.py` — `slugify(product.name)` computed at ingest and stored on the run's resolved catalogue, so the site's `data-product` and Ops's price rows both derive from the same brief field rather than from each other (R11, §6.2)
- [X] T092 [US3] Implement the `stripe_product` and `stripe_price` adapters in `epyhia/gate/adapters/stripe.py` — create from brief fields, `verify()` reads the object back by id and asserts it exists (contracts/action-gate.md §4)
- [X] T093 [US3] Implement the `arm_charge_path` adapter in `epyhia/gate/adapters/stripe.py` — approval-gated; `verify()` re-reads **every** price from Stripe and asserts each is `active` with a matching `unit_amount` and `currency` (FR-029)
- [X] T094 [US3] Implement the `checkout_session` adapter in `epyhia/gate/adapters/stripe.py` — **not** approval-gated by design; `verify()` selects the order by `stripe_session_id` and asserts it exists and is paid (§4.4)
- [X] T095 [US3] Implement `POST /checkout` in `epyhia/api/routers/checkout.py` — resolution order per R11: unarmed run → `409 {error: "not_armed"}`, unknown slug → `404 {error: "unknown_product"}`, otherwise create the session through the gate. Armed-ness is read from the `actions` table, never from a boolean on `runs`
- [X] T096 [US3] Extend `prompts/web_builder/v1.jinja` and the site's vanilla JS so buy buttons carry `data-product="<slug>"` and **no Stripe identifier ever enters the deployed bytes** (FR-030)
- [X] T097 [US3] Specify the buyer-side branch in `prompts/web_builder/v1.jinja` — the generated site's one vanilla JS file must render a legible unavailable state on `409 not_armed`, not an error page and not a session against a nonexistent price (FR-031)
- [X] T098 [US3] Implement `POST /webhooks/stripe` in `epyhia/api/routers/webhooks.py` — signature-verified, writing the `orders` row in the **same transaction** that records `stripe_event_id`, so a repeat arriving mid-flight cannot produce a second order (FR-032)
- [X] T099 [P] [US3] Build the arm-charge-path approval screen in `console/src/routes/approvals.tsx`, showing every product, amount, currency and billing type as it will be charged (FR-028)
- [X] T100 [P] [US3] Test in `tests/integration/test_us3_checkout.py` with a stubbed Stripe client: clicking buy before arming returns `409 not_armed`; after arming a session is created with zero operator interaction; a replayed webhook event id writes exactly one order (FR-031, FR-032, SC-009)
- [X] T101 [P] [US3] Test in `tests/integration/test_us3_currency.py`: a product whose `currency_display` differs from `currency_charge` is displayed and charged from the brief's own fields, with no conversion performed anywhere (FR-003, R6)

**Checkpoint**: All three deliverables — site, pack, checkout — work independently.

---

## Phase 6: User Story 4 - Re-runs and crashes never duplicate anything (Priority: P4)

**Goal**: A byte-identical resubmission, or a crash at any point, produces no second site, no
second catalogue, no second charge and no second order.

**Independent Test**: Run a brief to completion, resubmit it byte-identical, and confirm one live
site, one catalogue, one order, and short-circuited actions carrying the first run's keys.

- [X] T102 [US4] Implement the dedup path in `epyhia/api/routers/briefs.py` — an identical `content_sha256` resolves to the existing brief and returns `200 {..., deduplicated: true}` rather than inserting (FR-002, contracts/rest-api.md)
- [X] T103 [US4] Implement the `resume` task handler in `epyhia/queue/handlers/resume.py` — rebuild `deferred_tool_results` **from the `actions` row**, never from anything a previous process held in memory (R7 step 6)
- [X] T104 [US4] Implement the memoisation cache in `epyhia/agents/memo.py` — read/write `agent_cache` keyed on `agent + model + prompt_version + brand_doc_version + scoped_inputs`; it is a cache permitted to miss and no correctness path may read it (FR-048, Principle V)
- [X] T105 [P] [US4] Implement `GET /runs/{id}/brand-doc`, `PUT /runs/{id}/brand-doc` and `GET /briefs/{id}/brand-docs/diff?from=&to=` in `epyhia/api/routers/brand_docs.py` — `PUT` **inserts version + 1** and never updates in place (FR-012)
- [X] T106 [P] [US4] Build the brand doc read/edit/diff view in `console/src/routes/brand-doc.tsx`
- [X] T107 [P] [US4] Test in `tests/integration/test_us4_rerun.py`: a re-run whose generated bytes differ still produces **one** deploy, because the deploy key excludes the site artifact hash (FR-045, US4 scenario 2)
- [X] T108 [P] [US4] Test in `tests/integration/test_us4_brand_doc_edit.py`: editing the brand doc and re-running produces a **genuine second publication**, distinguishable in the audit trail from a duplicate, and the first publication's immutable deployment URL still serves the first build marker after the second goes live (FR-012, FR-017, US1 scenario 5, US4 scenario 3)
- [X] T109 [P] [US4] Test in `tests/integration/test_us4_crash.py`: killing the worker while an action sits `awaiting_approval` leaves the pending action actionable after restart, and the operator's click resumes that same action rather than starting a second (FR-038, SC-008)
- [X] T110 [P] [US4] Test in `tests/integration/test_us4_memo.py`: dropping `agent_cache` entirely changes cost and nothing else — every idempotency key and every action outcome is unchanged (FR-048)

**Checkpoint**: Re-runs and crashes are proved safe, not merely claimed safe.

---

## Phase 7: User Story 5 - Every run answers "what did it do and what did it cost" (Priority: P5)

**Goal**: Timeline, actions with evidence, per-call cost with tier, one combined total against one
budget — all from the console.

**Independent Test**: From the console alone, answer which model tier planned the run, what each
stage cost, what the run cost in total, and what evidence proves the site is live.

- [X] T111 [US5] Implement per-run token enforcement in `epyhia/cost/limits.py` — PydanticAI `UsageLimits` is token-denominated; dollars are derived from `RunUsage` through `pricing.yaml` and never passed as a ceiling (§8.1)
- [X] T112 [US5] Implement the per-run budget in `epyhia/cost/budget.py` — `runs.spend_usd` is **one number** covering model spend and action spend; crossing `budget_usd` moves the run to `halted_budget` and stops it (FR-052, FR-053)
- [X] T113 [P] [US5] Implement the system-wide daily ceiling in `epyhia/cost/budget.py` — when reached, `POST /briefs` refuses to open new runs (FR-053)
- [X] T114 [P] [US5] Implement `GET /runs/{id}/cost` in `epyhia/api/routers/cost.py` — per-`agent_calls` rows with agent, model id, tier, four token counts, derived cost and latency, plus **one** combined total against one budget (FR-052)
- [ ] T115 [P] [US5] Build the cost view in `console/src/routes/cost.tsx` — per-call table and the single combined total
- [ ] T116 [P] [US5] Test in `tests/integration/test_us5_cost.py`: every `agent_calls` row carries a non-null tier and cost, and **exactly one** row per run carries the planning tier (SC-007)
- [ ] T117 [P] [US5] Test in `tests/integration/test_us5_budget.py`: a run crossing its budget halts rather than continuing to spend, and the daily ceiling prevents a new run from starting (FR-053)

**Checkpoint**: Cost is observable per call, per stage and per run, in one total.

---

## Phase 8: User Story 6 - A second, unrelated business proves it is an agency (Priority: P6)

**Goal**: An unrelated brief produces a genuinely different site, identity and pack with zero
source changes — proved both statically (the prompt lint) and dynamically (the eval).

**Independent Test**: `git status` before and after running a second unrelated brief must be
identical, and the two runs must share no artifact hash, no palette and no alias.

- [ ] T118 [P] [US6] Add a second, **unrelated** brief fixture at `tests/fixtures/briefs/two.json` sharing no facts with `one.json` — a different kind of business entirely. It must be real enough to harvest tokens from; a placeholder name silently weakens the lint (R10)
- [ ] T119 [US6] Implement the prompt-tree lint in `tests/genericity/test_prompt_lint.py` per [research.md R10](./research.md) — harvest business names, taglines, one-liners, product names, `price_minor` as strings, currency codes and voice adjectives from **every** fixture; assert each fixture yields a non-empty token set; assert no token appears in any file under `prompts/` (raw scan); assert no token and no currency symbol appears in any template rendered against a sentinel context (empty render). Match on **word boundaries** — a voice adjective like `direct` otherwise hits `directory`/`directly` in ordinary source and the lint is red forever
- [ ] T120 [P] [US6] Add the companion source scan in `tests/genericity/test_source_scan.py` — the same harvested tokens must not appear anywhere under `epyhia/`, `console/src/` or `video/src/`
- [ ] T121 [US6] Write `eval/rubric.json` conforming to [contracts/eval-rubric.schema.json](./contracts/eval-rubric.schema.json) — every check carries `id`, `area`, `points`, `title`, `kind`, `assertion`, `evidence` and `required`; `evidence`-kind rows carry no score field
- [ ] T122 [US6] Implement `eval/eval.py` — authenticates via Auth0 **machine-to-machine** through the same validator as the console, with no bypass path (FR-058); reads **stored records** rather than re-probing the world; writes `PRODUCT_EVAL.md`
- [ ] T123 [US6] Implement the FR-061 assertions in `eval/eval.py` — publication succeeded with its stored evidence; an order exists matching a product in that brief; a re-run produced one publication and one order; every action and every model call carries a cost and a tier with exactly one top-tier call; nothing flagged reached publication; no purchase exists for an unarmed run; **zero actions carry `requested_by = 'strategist'`**
- [ ] T124 [US6] Implement the FR-062 second-brief assertions in `eval/eval.py` — the two runs differ in brand doc palette and alias and share no artifact `sha256`, with each run's deploy probe having read its expected name from **its own** brand doc row
- [ ] T125 [US6] Implement the report split in `eval/eval.py` — `automated` rows render pass/fail plus the evidence read; `evidence` rows render links and **no self-awarded score**; `PRODUCT_EVAL.md` states the distinction plainly at the top (FR-063, SC-013)

**Checkpoint**: The genericity claim is proved statically and dynamically, over two unrelated
businesses.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T126 Deploy to Fly using `fly.toml` — one image, `web` + `worker` processes, `release_command = "alembic upgrade head"`, with a real Auth0 tenant configured (§12 step 12)
- [ ] T127 [P] Polish the console limited to the approval view in `console/src/routes/approvals.tsx` — design effort belongs in the generated client site, not here (spec Assumptions)
- [ ] T128 [P] Write `README.md` — the clone-to-running path from [quickstart.md](./quickstart.md) Prerequisites, and the explicit statement that the app starts with no credentials
- [ ] T129 Run every section of [quickstart.md](./quickstart.md) S0–S6 against the running system and record the evidence each table asks for
- [ ] T130 [P] Update `CLAUDE.md` — the "Repository state: design-first, no code yet" section is false once Phase 1 lands; replace it with the real layout and the working commands (`uv run ruff check`, `uv run pytest`, `uv run alembic upgrade head`, `docker compose up`)
- [ ] T131 Record the 60–90s demo and link it from the header of `PRODUCT_EVAL.md` as an `evidence`-kind row (§12 step 13)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS every user story. Internally ordered by
  `DESIGN.md` §12: 2a (gate) → 2b (schema, queue, cost ledger) → 2c (ingest) → 2d (API surface).
  2a is first by constitutional mandate, not convenience
- **US1 (Phase 3)**: Depends on Phase 2 only
- **US2 (Phase 4)**: Depends on Phase 2. Touches US1's `site` task once (T077, removing the copy
  stub) — that is the seam §12 step 6 designed for, and the Web Builder itself does not change.
  Internally ordered 4a (T072–T077, the copy seam) → 4b (everything else); 4a blocks 4b because
  until the stub is gone the `site` artifact is built from layout intent rather than facts
- **US3 (Phase 5)**: Depends on Phase 2. Needs a published site for the *buyer* path (T096–T097
  write into the site's markup and JS), so full end-to-end validation follows US1
- **US4 (Phase 6)**: Depends on Phase 2 and on real actions existing to be repeated — meaningfully
  testable once US1 lands, fully once US3 does
- **US5 (Phase 7)**: Depends on Phase 2's `agent_calls` ledger. Independently testable against any
  completed run
- **US6 (Phase 8)**: T119–T120 (the static lint) depend only on Phase 2 and the prompt tree, and
  can run as soon as the first prompt exists. T121–T125 (the eval) depend on US1–US5
- **Polish (Phase 9)**: Depends on the desired stories being complete

### Within Each User Story

- Prompts and schemas before the agents that render them
- Models before services; services before routes
- Adapters before the integration tests that exercise them
- The deterministic grounding check always before any model is asked an opinion (Principle VI)

### Parallel Opportunities

- **Phase 1**: T003, T004, T005, T009, T012 are independent files
- **Phase 2a**: T015, T016, T017 in parallel after T014; then **T021–T027 and T133 all in
  parallel** — eight separate test files against one fake adapter
- **Phase 2b**: T030 and T035 in parallel; T034 and T038 in parallel
- **Phase 2c**: T039 and T040 in parallel; T044, T045 and T132 in parallel
- **Phase 2d**: T046, T047, T048, T049 are four independent modules
- **Phase 3**: T053 and T057 (two prompt files) in parallel; T064 and T066 in parallel
- **Phase 4**: within the 4a prefix, only T072 and T073 are parallel — T078, T079 and T081 are
  4b and **must not** be pulled forward, however independent their files look. Then within 4b:
  T078, T079, T081 in parallel; T084, T085, T086, T088 in parallel
- **Phase 5**: T099, T100, T101 in parallel
- **Phase 6**: T105, T106 in parallel; T107–T110 are four independent test files
- **Phase 7**: T113, T114, T115, T116, T117 in parallel
- **Phase 8**: T118 and T120 in parallel
- **Across stories**: once Phase 2 is done, US1, US2's pack agents, US3's Ops agent and US5's cost
  surface can be staffed in parallel

---

## Parallel Example: Phase 2a gate tests

```bash
# Eight independent test files, one fake adapter, zero credentials, zero network:
Task: "Approval durable before raise in tests/gate/test_approval.py"
Task: "Key collision under concurrency in tests/gate/test_concurrency.py"
Task: "Verify retry cap in tests/gate/test_verify_retry.py"
Task: "succeeded ⇒ evidence CHECK in tests/gate/test_evidence_constraint.py"
Task: "Denial is terminal in tests/gate/test_deny.py"
Task: "Missing credential names the provider in tests/gate/test_credentials.py"
Task: "Crash mid-executing → probe decides in tests/gate/test_crash_resume.py"
Task: "Key stability and Remotion-version sensitivity in tests/gate/test_keys.py"
```

## Parallel Example: User Story 2

The 4a prefix is deliberately narrow — two prompt files, then a sequence. Separate files are
not a reason to start 4b, because the point of 4a is to close the copy seam before anything
else is judged through it:

```bash
# 4a, the only parallelism available before T077 lands:
Task: "Write prompts/marketer/v1.jinja"
Task: "Write prompts/reviewer/v1.jinja"
# then T074 → T075 → T076 → T077 in order, and re-run the US1 smoke.

# 4b, only after checkpoint 4a passes:
Task: "Email adapter in epyhia/gate/adapters/email.py"
Task: "Recording sink router in epyhia/api/routers/sink.py"
Task: "Remotion archetypes in video/"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1: Setup
2. Phase 2: Foundational — **gate first**, and stop at the S0 checkpoint until
   `uv run pytest tests/gate/` passes with no credentials
3. Phase 3: US1
4. **STOP and VALIDATE**: [quickstart.md](./quickstart.md) S1, including the stale-alias negative
   case. A deploy check that only asserts `200` passes the happy path and is wrong
5. This is `DESIGN.md` §12 step 7 — the Week 1 demo

### Incremental Delivery

1. Setup + Foundational → the gate governs a fake action end to end
2. US1 → a brief becomes a proved-live URL (MVP)
3. US2 → the pack, and the site's own numerals now gate the deploy
4. US3 → money
5. US4 → re-runs and crashes proved harmless
6. US5 → cost visible per call and in one total
7. US6 → the agency claim proved over two unrelated businesses

### The two checkpoints that are not negotiable

- **After Phase 2a**: the gate is testable with zero agents, zero credentials and zero network. If
  a gate test needs any of them, the boundary leaked and the fix is cheaper now than after five
  agents call it (Principle VII)
- **After T059 + T087**: the deploy refusal for a flagged site artifact lives in the **gate**, not
  in the Web Builder. A control that guards outbound copy while the same fabricated price sits in
  an `<h2>` on the live site is a report, not a control (§9.2)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete work
- **Never set `temperature`, `top_p` or `top_k`** on any agent — removed on Opus 5 and Sonnet 5, a
  non-default value returns 400
- **Stream the Web Builder** — non-streaming truncates into plausible HTML that would be deployed
- Every task that writes a prompt, a fixture, a constant or an assertion is subject to Principle I:
  if the value varies by client, it comes from the brief or the brand doc at the moment it is used
- Commit progressively, one concern per commit, on a `<type>/<short-kebab-summary>` branch off
  `main`. No `Co-Authored-By` trailer
