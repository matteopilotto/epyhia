# EPYHIA — an agency staffed by agents

One plain-language client brief goes in; a deployed website, a marketing pack (landing copy,
3–5 posts, a launch email, a launch video with a vertical cut) and a Stripe test-mode
checkout come out. Every action that deploys, charges or sends passes through one Action
Gate, is approved by a human where it matters, and is proved in the world before it is
called done.

EPYHIA is the product; any client is one row of input data. Anything that varies by client
lives in the brief or the brand doc — never in code, prompts, constants or fixtures.
`DESIGN.md` is the architecture of record; the feature's spec, plan and tasks live in
[specs/001-epyhia-agency/](specs/001-epyhia-agency/).

## From clone to running

| | |
|---|---|
| Required | Docker, [`uv`](https://docs.astral.sh/uv/), Node 22 |
| Not required to start | Stripe keys, Vercel token, an Anthropic key, any account signup |

The last row is the point: **the app starts with no credentials configured.** An absent
credential is a stored `None`, never a start-time failure — the system runs, accepts briefs
and queues work, and fails only at the specific gate action that needed the missing
provider, with `credential not configured: <provider>` rather than a stack trace.

```bash
git clone <repo> && cd epyhia
cp .env.example .env          # names and safe local defaults only — no real keys
docker compose up             # Postgres + Mailpit + web + worker
```

`docker compose up` is the whole setup. Migrations run via `alembic upgrade head`, the same
ones that run on deploy.

To exercise the paths that reach the world, add to `.env`:

- `ANTHROPIC_API_KEY` — the crew's inference
- `VERCEL_TOKEN` — the deploy
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` — the checkout, test mode only

The launch email needs no credential — it goes to the bundled Mailpit, and the gate reads it
back out of Mailpit's API to prove it arrived.

## Development

```bash
uv run ruff check             # lint
uv run pytest                 # must pass with no API key and no credentials set
uv run alembic upgrade head   # migrations against DATABASE_URL
```

Tests run offline and free: agents are exercised through PydanticAI's `TestModel` and
`FunctionModel`, the gate through a fake adapter, and CI needs no API key. The genericity
lint (`tests/genericity/`) harvests client tokens from every brief fixture and fails the
build if any appears in a prompt, in source or in a rendered template.

## Validating the system

[specs/001-epyhia-agency/quickstart.md](specs/001-epyhia-agency/quickstart.md) walks every
user story against a running system — gate assertions with no credentials (S0) through the
two-brief agency proof (S6) — naming the evidence each step must leave behind.

## Deploy

Fly.io, one image, `web` + `worker` processes, `release_command = "alembic upgrade head"` —
see [fly.toml](fly.toml). Secrets go in `fly secrets`; the console authenticates through
Auth0 with no bypass path.

In production, console access is approval-gated: signing up only *requests* access, and an
Auth0 post-login Action denies a token until an operator approves the account, so signup
grants nothing by itself. Spend is capped twice over — `DAILY_CEILING_USD` is armed in
`fly secrets`, refusing new runs once the day's spend reaches it, and the Anthropic
workspace behind the deployed key carries its own monthly limit as a provider-side backstop
that holds even if the app's own ledger is wrong.
