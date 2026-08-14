# Evidence: Distinctive Generated Sites

T041's record — what was observed against a running system, as opposed to what the offline
suite asserts. Each section names the criterion it settles and the run it settles it from.

## Offline gate (T040) — 2026-08-13

`uv run ruff check` clean; `uv run pytest` 422 passed; `uv run alembic upgrade head` a no-op
at `c4b7d21f5a08` and no migration file on the branch — this feature ships no schema change
(R11).

## Fixture one, end to end — run `31b3e4ac-38c8-4e9e-b633-50ae3297fa34`

`tests/fixtures/briefs/one.json`, local stack, real models, deploy approved by the operator.
The site stage was driven twice: the first attempt exposed two defects (below), and the
figures here are from the run after both fixes.

**Brand doc.** Archetype `editorial_stack`; pairing `zilla-slab` / `ibm-plex-sans`; palette
`#F3EBDF` / `#241C16` / `#B5451B` / `#6B5D50`; motion "slow bloom, settle". Its composition
plan selected `split_manifesto` and `numbered_process` — two of the four section layouts T034
added — so the grown library is reachable in practice and not merely rendered (FR-018).

**Artifacts.** `site` revision 0 (133,869 bytes, clean), `site` revision 1 (134,237 bytes,
clean), `design_report` (schema-valid against `contracts/design-report.schema.json`).

**The loop (FR-012 – FR-014).** Screenshots captured at both widths; the Site Critic returned
one finding; one revision pass ran and was **kept**, taking the lint count from 1 to 0 — the
`ignored_pairing` finding at `a, button` was fixed by the revision. `findings_before: 1`,
`findings_after: 0`.

**Cost (FR-016, SC-003).** All three calls metered against the run's one budget:

| agent | cost | latency |
|---|---|---|
| `web_builder` | $0.000 (memo hit) | 0 ms |
| `site_critic` | $0.016 | 27 s |
| `web_builder_revise` | $0.421 | 4 m 46 s |

**Self-containment (SC-004, FR-002).** Checked over the deployed bytes: no `href`, `src`,
`url()` or `@import` reaching anything but `data:` or `#` — **zero external references**. Four
`@font-face` rules, one per weight file of the resolved pairing, every one a
`data:font/woff2;base64` URI; both families (`Zilla Slab`, `IBM Plex Sans`) referenced in the
page's CSS.

**Size budget (FR-006).** 134,237 bytes — 13% of the 1 MiB ceiling.

**Deploy verified live.** The gate's own probe:

```json
{"url": "https://epyhia-1dab77bd201d.vercel.app", "status": 200,
 "matched_name": "Meridian Coffee Roasters", "matched_build_marker": "1dab77bd.1.v3"}
```

### Two defects this run found, both fixed

1. **The revision pass was handed the font-embedded page** — it spent the 64K output ceiling
   reproducing base64 woff2 and returned 53 bytes of markup. 26 minutes, $1.32, a white page.
   Fixed in `e0efbe9`; the same pass now costs $0.42 and 4m46s.
2. **The keep gate could not tell a page from a stub** — grounding clean (no text), under
   budget (fonts are not the page), lint tied, so the stub was recorded `kept` and reached the
   deploy request. Fixed in `8e900dc` with `discarded_empty`.

Neither was reachable from the offline suite: every revision test returns a complete page from
its `FunctionModel`, so the suite checked the loop's arithmetic and never that the thing being
counted was a document.

### Open observation — the critic may be judging a screenshot artifact

Its only finding on either run is a contrast complaint that reverses between widths ("nearly
illegible on phone, readable on desktop", then "nearly invisible on desktop, readable on
phone"). Contrast does not reverse with viewport width. The page reveals content with
`.reveal{opacity:0}` plus an `IntersectionObserver`, and the captures are static at
`--virtual-time-budget=5000`, so unrevealed or mid-transition elements photograph faint — and
which ones do depends on the viewport. If that is what is happening, the punch list is being
spent on the capture rather than the page. Candidate fix: capture with
`--force-prefers-reduced-motion`, a path the page is already required to support.

## SC-001, the two-fixture divergence check — **NOT MET**

Fixture two run 2026-08-14 against a scratch database with the fake deploy adapter
(`preview_site.py --real --stages site`, $0.66). Compared with fixture one's brand doc:

| | fixture one (coffee roastery) | fixture two (cycle workshop) | |
|---|---|---|---|
| page archetype | `editorial_stack` | `split_technical` | differ |
| pairing | `zilla-slab` / `ibm-plex-sans` | `zilla-slab` / `ibm-plex-sans` | **identical** |
| `bg` | `#F3EBDF` | `#f3eee3` | Δ 4 |
| `fg` | `#241C16` | `#1b1916` | Δ 9 |
| `accent` | `#B5451B` | `#b4571f` | Δ 18 |
| `muted` | `#6B5D50` | `#6a6154` | Δ 4 |

(Δ = maximum per-channel distance out of 255.) The literal check "no shared palette value"
passes because no hex string repeats; that is the check being generous rather than the output
being distinct. Both are a warm cream ground, a near-black brown, and a burnt-orange accent.

Not a shortage of options: the library offers six display-capable and seven body-capable faces,
roughly forty valid pairings.

### A third sample, and what it costs the reading above

Fixture two was run again on 2026-08-14 to verify the `numbered_process` fix (`60f71d0`). No
instruction the Strategist reads had changed except that layout's one-line description, and the
brand doc came back **differently**:

| | fixture two, first run | fixture two, second run |
|---|---|---|
| pairing | `zilla-slab` / `ibm-plex-sans` | **`archivo-black`** / `ibm-plex-sans` |
| `bg` | `#f3eee3` | `#F1EDE4` |
| `accent` | `#b4571f` | `#B23A16` |
| archetype | `split_technical` | `split_technical` |

So the display face is sampling variance, and "both fixtures converge on one pairing" was a
conclusion drawn from n=2 that a third sample does not support. What *does* repeat across all
three brand docs is the palette: a warm cream ground, a near-black brown, a burnt-orange
accent, every time. The body face has also been `ibm-plex-sans` three times out of three.

SC-001 as written still fails — the pairing shares its body face, and the palettes are close —
but the two candidate causes are now unequally supported:

1. **The palette instruction bans exactly one default** — near-black on near-white with a
   saturated blue accent — and every run so far has avoided it identically. Naming one banned
   default appears to relocate the default rather than remove it. **Three samples.**
2. **The display roster has one moderate face among five extremes.** Plausible, but the second
   fixture-two run chose `archivo-black` — one of the extremes — which weakens it. **Not
   supported by the current samples.**

The honest state: the palette is the convergent thing, the type may not be, and n=3 across two
briefs is still too thin to rewrite a prompt on.

SC-001 is also, structurally, a cross-run property that no single run can enforce: each run
sees one brief, one library, one prompt, and nothing makes the second aware of the first. It
should be restated as a tendency measured over a sample — which is what these three runs
already show it has to be — or the enforcement (library spread, prompt framing) named for what
it is.

**The measurement needs fixing before any of this can be judged.** "No shared palette value"
compares hex strings, and two palettes one digit apart pass it. A perceptual threshold is what
would have called the first two runs identical; per-channel distance would have done it.

### Diagnosis was blind, and turning tracing on did not fix it

The instruction this section used to carry — *turn tracing on before changing anything* — was
followed. Tracing landed in PR #33 and ran against a live `plan` stage: spans ship, `run_id` and
`task_kind` are on every worker span, prompts and tool-call arguments are all there. The drafted
directions are still unobservable, and not for want of instrumentation:

```text
ThinkingPart(content='')          gen_ai.usage.details.thinking_tokens = 662
```

662 tokens of thinking happened; none of it is readable. Opus 5 does not return its raw chain of
thought and `thinking.display` defaults to `"omitted"`, so the part arrives empty and the span
faithfully records an empty string. `include_content=True` governs whether PydanticAI *copies* a
`ThinkingPart`'s content into the span, not whether there is content to copy. The Strategist
sends no thinking configuration at all, so this is the provider's default and not a setting of
ours — no telemetry change reaches it.

FR-019 puts the drafted directions in extended thinking, and the `BrandDocument` shape
deliberately has no field for them. Those two facts together make the requirement unverifiable
by construction: not untested, not expensively tested — **unobservable**. The only test that
exists, `test_the_discarded_directions_have_nowhere_to_land`
(`tests/agents/test_brand_document.py:69`), asserts the shape has nowhere for them to leak,
which is the opposite claim. DESIGN.md §8's standard — "a requirement whose only evidence lives
in a SaaS dashboard is a requirement I cannot test" — is a step short of this one, whose
evidence lives nowhere at all.

So the *process* question is closed rather than answered, and SC-001 has to be settled on the
*outcome* the tables above already measure: do two briefs produce two directions? One lever
remains on the process side and is untried —
`anthropic_thinking={"type": "adaptive", "display": "summarized"}` on the Strategist's call,
which would make the drafts readable by a human reading a trace. It would not make them
assertable: a summary is prose, and no test should parse it. Whether the summary is granular
enough to separate "three distinct directions" from "three shades of one" is the open question;
until it is run, treat FR-019's drafting step as instructional only.

## SC-007, the pre/post regression guard — **NOT MET, for lack of headroom**

Fixture one built off `main` in a worktree against a second scratch database ($0.755), linted
with today's lint beside the post-feature page:

| | pre-feature (`main`) | post-feature |
|---|---|---|
| structural tells | 0 | 0 |
| `ignored_pairing` | 6 | 0 |

The five structural rules (`uniform_sections`, `gradient_hero`, `single_radius`,
`accent_overuse`, `weak_type_scale`) found nothing on either page, so "strictly fewer" cannot
be demonstrated — the baseline was already at zero. The old prompt's own anti-default section
was doing work the lint cannot see past.

What did change is the thing the lint's sixth rule measures. The pre-feature brand doc named
`GT Sectra Display` and `Atlas Grotesk` — commercial faces nobody licensed, loaded from
nowhere, rendered in whatever the visitor's device had. The post-feature page names library ids
and carries four embedded woff2 faces with zero external requests. That is the regression this
feature actually prevents, and it is not a count of tells.

## A defect this pass found: `numbered_process` writes ungrounded numerals

Fixture two's site artifact was **flagged**, on one violation: `{"value": "5"}`. Its source is
`<span class="step-number">5</span>` — the fifth step of a `numbered_process` section, one of
the four layouts T034 added. The run's grounding set contains 1, 2, 3, 4, 14, 15, 2011 and the
prices; it does not contain 5. Steps one through four passed by coincidence.

The consequence is not cosmetic. A flagged page is refused by the gate, and the site handler
skips the critique and the revision for exactly that reason
(`"the page is flagged for ungrounded numerals and will not be deployed"`), so the whole US3
loop was bypassed:

```json
"critique": {"status": "skipped", ...}, "revision": {"outcome": "skipped", "findings_before": 1}
```

A layout whose premise is "sequential steps, numbered" guarantees ordinals on the page, and
ordinals past whatever the brief happens to state are ungrounded by construction.

**Fixed in `60f71d0` and verified live.** The layout now asks for an ordered list and lets the
list supply the numbering; the builder's fact rule says the same thing where it explains what a
numeral is. Fixture two re-run 2026-08-14 ($0.98), with the Strategist selecting
`numbered_process` again — so the broken path was genuinely exercised:

| | before | after |
|---|---|---|
| site artifact | flagged on `{"value": "5"}` | **clean**, 94,446 bytes |
| the steps section | `<ol>` with six typed `step-number` spans | `<ol>`, zero numerals in the markup, `counter()` in the CSS |
| critique | skipped (flagged page) | ran — one `type_timid` finding |
| revision | skipped (flagged page) | **kept**, findings 1 → 0 |

The model had been writing the ordered list *and* typing the digits into it. The list was never
the problem; the hand-written numbers were.

### The critic's first substantive finding

This run is also the first where the Site Critic said something checkable: `type_timid` on
`.stat .num`, corroborating the lint's own `weak_type_scale` — a largest declared size of 2.40×
body against the 2.5 threshold. That is `contracts/site-critic.md`'s "corroborate or extend"
behaving as specified, and no `broken_render` complaint about invisible text. One sample, but
it is the first evidence the visual review adds signal rather than noise.

The same page also tripped `uniform_sections` — nine sections in one 1400px container — while
its brand doc named `split_technical`, whose spec sheet commits to a two-column split that
flips sides between sections. The spec sheets render; this page did not obey one.

## Still open

- **The money stage** of run `31b3e4ac` failed, and not for any reason belonging to this
  feature: `StripePriceAdapter` has no already-exists branch, while its sibling
  `StripeProductAdapter` deliberately retrieves the existing object, so the same brief run
  twice against one Stripe account fails every time. Filed against feature 001.
