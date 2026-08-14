# Contract: The Site Critic

The fast visual reviewer inside the site stage (FR-013). A checking-tier model caller,
not a pipeline stage: it examines the rendered page and reports; it changes nothing.

## Identity

| | |
|---|---|
| Agent id | `site_critic` (ledger rows, prompt directory) |
| Model | `claude-haiku-4-5` (checking tier — it checks, it never writes; vision-capable) |
| Prompt | `prompts/site_critic/v1.jinja` (versioned tree; covered by the CI genericity scans automatically) |
| Module | `epyhia/agents/site_critic.py`, mirroring `reviewer.py`'s shape |

## Boundaries (each one structural, not instructional)

| May never | Enforced by |
|---|---|
| Edit the page or propose replacement markup/copy | Output shape has no field for it |
| Approve silently | Approval is derived from an empty `findings` list, never asserted by the model |
| Make any external call / hold a gate handle | Constructed with no toolset |
| Read the raw brief | Its inputs are the brand doc, the lint findings, and the screenshots — the call site has no brief parameter |
| Fail the run | Every failure of this call is caught by the site handler and recorded as a skip (FR-015) |

The constitution's Principle III agent table gains a matching row (MINOR amendment,
1.1.1 → 1.2.0), scheduled as the first implementation task.

## Input

One user message containing:

- The run's **brand doc** (JSON) — the standard against which the page is judged;
  each run's page is judged against its own brand doc, never another run's output.
- The **lint findings** already computed for the page (JSON, possibly empty) — so the
  critic corroborates or extends the mechanical findings rather than rediscovering
  them.
- **Two screenshots** as `BinaryContent(media_type="image/png")`: phone (390 px wide)
  and desktop (1440 px wide), captured by the worker's own Chromium (FR-012). A blank
  or partial capture is delivered as-is: a broken render is a finding
  (`kind="broken_render"`), not a crash.

## Output

`Critique{findings: list[CritiqueFinding]}`, via `PromptedOutput`, with
`findings` bounded at **8** items.

```python
class CritiqueFinding(BaseModel):
    kind: Literal[
        "palette_ignored", "rhythm_uniform", "type_timid",
        "accent_overused", "hierarchy_flat", "broken_render", "other",
    ]
    where: str   # region of the page, in words
    what: str    # the concrete observation
```

- A schema-valid `findings: []` is a **clean review** — recorded as
  `critique.status="clean"` in the design report.
- Output that fails to produce the typed shape after the standard retry, or any
  render/call failure, is a **skip** — `critique.status="skipped"` with a reason.
  The stage completes with the unrevised page either way (spec edge cases).

## Cost and limits

Every call is metered via `record_call` (agent `site_critic`, its prompt version) and
runs under the run's `limits_for_run` `UsageLimits`, so its spend rolls into the run's
one budget (FR-016). Explicit thinking budget and `max_tokens` headroom follow the
Reviewer's precedent (Haiku 4.5 predates adaptive thinking; budget ≥ 1024, headroom so
an overrun cannot swallow the answer). Never set `temperature`/`top_p`/`top_k`.

## Gating semantics

The critic's findings are unioned with the lint's to gate the single revision pass
(FR-014). They never refuse a deploy (FR-010), never fail the stage, and are recorded
in the `design_report` artifact whichever way the review falls.
