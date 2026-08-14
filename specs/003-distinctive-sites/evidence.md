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
roughly forty valid pairings, and both runs chose the same one.

Two structural causes are visible, neither of them "the divergence instruction is too weak":

1. **The display roster has one moderate face among five extremes** — `playfair-display`
   (hairline editorial), `bebas-neue` (poster-loud caps), `archivo-black` (signage),
   `space-grotesk` (technical), `jetbrains-mono` (terminal), and `zilla-slab` (sturdy,
   mid-century). Any small physical-goods business honestly lands on the sixth, twice.
2. **The palette instruction bans exactly one default** — near-black on near-white with a
   saturated blue accent — and both runs avoided it identically. Naming one banned default
   relocates the default rather than removing it.

SC-001 is also, structurally, a cross-run property that no single run can enforce: each run
sees one brief, one library, one prompt, and nothing makes the second aware of the first. It
should be restated as a tendency measured over a sample, or the enforcement (library spread,
prompt framing) named for what it is.

**Diagnosis is currently blind**: `LOGFIRE_TOKEN` is unset, and by FR-019's design the drafted
alternatives exist in no field of the brand doc. Whether the Strategist drafted three genuinely
distinct directions and chose the safe one, or drafted three variations of one, is not
observable from the output. Turn tracing on before changing anything.

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
ordinals past whatever the brief happens to state are ungrounded by construction. Either the
derivation set admits ordinals for a numbered layout, or the layout must not emit them, or the
Strategist must not select it. This needs a decision before the layout is used again.

The same page also tripped `uniform_sections` — nine sections in one 1400px container — while
its brand doc named `split_technical`, whose spec sheet commits to a two-column split that
flips sides between sections. The spec sheets render; this page did not obey one.

## Still open

- **The money stage** of run `31b3e4ac` failed, and not for any reason belonging to this
  feature: `StripePriceAdapter` has no already-exists branch, while its sibling
  `StripeProductAdapter` deliberately retrieves the existing object, so the same brief run
  twice against one Stripe account fails every time. Filed against feature 001.
