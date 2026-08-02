# Contract: Agent inputs, outputs and boundaries

Five PydanticAI agents. Each row of the table below is enforced by **construction** — what the
agent is handed and what its toolset contains — not by an instruction in a prompt. A prompt
instruction is not an architecture (§3.3).

Transcripts are never passed down the crew. Each agent receives the brand doc and its own
scoped inputs, which is both a cost control and the reason the Reviewer stays independent (§8).

---

## The table

| Agent | Model | Reads | Writes | Gate handles | May never |
|---|---|---|---|---|---|
| **Strategist** | `claude-opus-5` | brief (typed object) | brand doc v1, task rows | **none** | Make any external call. Write copy or markup |
| **Web Builder** | `claude-sonnet-5` | brand doc + **reviewed `copy` artifact** | `site` artifact | `deploy` | Author a price, feature or claim not in the copy artifact or the brief |
| **Marketer** | `claude-sonnet-5` | brand doc | `copy`, `posts`, `email`, `video_props` artifacts | `send_email`, `publish` | Invent a fact not in the brief. Deploy |
| **Reviewer** | `claude-haiku-4-5` | draft + brand doc + **raw brief** | violations | none | Approve silently. Rewrite the draft |
| **Ops** | `claude-haiku-4-5` | brand doc + `brief.products[]` | catalogue rows | `stripe_*`, `arm_charge_path` | Deploy. Publish. Touch markup |
| *(guardrail)* | `claude-haiku-4-5` | raw brief | a logged decision | none | — |

**The Reviewer is the only agent that reads the raw brief** (FR-011, §3.2). It needs the brief
for facts and the brand doc for voice. Everyone else reading only the brand doc is what makes
the "edit the brand doc, re-run, watch the output change" demo mean something — and it is also
a containment boundary, because a fixed schema of hex values, font names and word lists has
nowhere to put an injected instruction (§9.6).

---

## Per-agent I/O

### Strategist — `brief → brand doc + task list`

**In**: the brief as a **typed object with named fields**, never as prose spliced into a system
prompt (FR-008, §9.6).
**Out**: a document conforming to [brand-doc.schema.json](./brand-doc.schema.json), plus the
fixed task set.

**The task set is fixed in code**: `copy` → `site`, with `demand` and `money` in parallel. The
Strategist parameterises those stages through the brand doc; it does not compose a graph of its
own devising (FR-013, §3.3). Orchestration a model invents per run means idempotency keys
computed over work whose existence is itself uncertain.

Its toolset is `write_brand_doc` and `enqueue_tasks`. That is the entirety of its reach.

### Marketer — `brand doc → copy, posts, email, video props`

`copy` runs first as its own task and **blocks `site`** (§3.4, FR-021). The landing copy is a
pack deliverable, so it carries the same review as the rest of the pack rather than being
generated twice by two agents in two voices.

`video_props` conforms to [video-props.schema.json](./video-props.schema.json) — props JSON
only, never TSX (FR-026). The `content`/`style` split means every on-screen value lands where
the grounding check looks.

### Reviewer — `draft + brand doc + brief → violations`

**Out**: a structured list, never a rewrite and never a bare approval (FR-023).

```json
{"approved": false, "violations": [{"kind": "voice" | "unsupported_claim", "quote": "...", "why": "..."}]}
```

Its inputs are scoped to the draft, the brand doc and the brief — **not the run transcript**. A
reviewer that can see the author's reasoning tends to be persuaded by it (§3.2).

The numeric check does **not** run here. It is an artifact-boundary function that has already
run, deterministically, before the Reviewer is called at all (§3.4, Principle VI).

### Web Builder — `brand doc + copy artifact → site artifact`

**Streamed**, ~64K `max_tokens`. Non-streaming exceeds the ceiling and yields SDK timeouts with
truncated HTML — which is syntactically plausible and would then be deployed (§8.1).

Receives a section-level composition plan, not a page request (§6.3). Its prompt describes the
mechanism and the anti-slop bar and contains **no aesthetic direction for any client** — "dark
clinical surfaces" is something the Strategist writes into a brand doc, not something anyone
writes into a prompt (§1.2).

### Ops — `brand doc + brief.products[] → catalogue`

Near-mechanical translation. Products, prices, currencies and billing types come entirely from
the brief; none may exist in EPYHIA's code, config or fixtures (FR-027).

---

## Model settings

Applies to every agent (§8.1, Constitution "Stack & Provider Constraints"):

- **Never set `temperature`, `top_p` or `top_k`.** Removed on Opus 5 and Sonnet 5; a
  non-default value returns a 400. Steer through prompting.
- Extended thinking is on by default on Opus 5, and `max_tokens` caps thinking plus response
  text **together**.
- Prompt-cache minimums differ — 512 / 1024 / 4096. A brand doc that caches for the Strategist
  may silently not cache for the Reviewer, which shows up as a cost anomaly rather than an
  error.
- `UsageLimits` is token-denominated. There is no dollar ceiling; dollars are derived from
  `RunUsage` through `pricing.yaml` (§8, research.md R9).

## Prompts

Jinja2 templates under `prompts/<agent>/<version>.jinja`, rendered through `PromptService`.
Never string literals in source — that is what makes Principle I checkable rather than a wish
(§2.1, FR-060). The CI check that scans them is specified in [research.md R10](../research.md).

## Testing

`TestModel` / `FunctionModel` let the whole crew run offline and free. **CI must not need an
API key** (§2.1, Constitution).
