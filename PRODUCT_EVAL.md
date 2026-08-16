# PRODUCT_EVAL.md

Read at 2026-08-16T11:56:21+00:00 from the stored records of the deployed agency at `https://epyhia.fly.dev`. The runs were driven by an operator; this evaluation graded what they left behind.

## Failed required checks

None — every required check passed.

## How to read this

Two kinds of row, and the difference between them is the point.

- **Mechanically checked** rows were asserted by `eval/eval.py` against the records those
  runs left behind. They carry pass/fail and the evidence they read.
- **Left to judgement** rows are human judgements. They carry what to look at and **no
  score**: a script that awards itself points for aesthetics is worth nothing to a reader.
  Their points are this area's budget for a judgement, not points this evaluation earned.
  A reference that resolves to nothing reads `missing` — a gap in the evidence rather than
  a failure, and it does not move this run's exit status.

Per-area budgets come from `eval/rubric.json`, whose areas and totals reconcile to the
tracked grading table in `specs/001-epyhia-agency/contracts/grading-rubric.md` — asserted by
`tests/eval/test_rubric_contract.py` rather than by reading.

## Areas

| Area | Budget | Mechanically checked | Of those, passing | Left to judgement |
|---|---|---|---|---|
| `deliverables-real` | 30 | 30 | 30 | 0 |
| `not-slop` | 15 | 0 | 0 | 15 |
| `crew-orchestration` | 15 | 15 | 15 | 0 |
| `action-gate` | 20 | 20 | 20 | 0 |
| `design-failure-catalogue` | 10 | 0 | 0 | 10 |
| `ships-clean-clone` | 10 | 0 | 0 | 10 |

## `deliverables-real`

### Mechanically checked

| Check | Points | Result | Evidence read |
|---|---|---|---|
| The site is published and was proved live | 8 | pass | one: 1 succeeded deploy(s), latest evidence {"matched_build_marker": "1dab77bd.1.v4", "matched_name": "Meridian Coffee Roasters", "status": 200, "url": "https://epyhia-1dab77bd201d.vercel.app"}; two: 1 succeeded deploy(s), latest evidence {"matched_build_marker": "55e582d7.1.v4", "matched_name": "Hollowfield Cycle Workshop", "status": 200, "url": "https://epyhia-55e582d723e3.vercel.app"} |
| The marketing pack exists and is grounded | 7 | pass | one: missing [], flagged []; two: missing [], flagged [] |
| The test purchase persisted a real order | 9 | pass | one: 1 orders, 1 paid, 1 matching; two: 1 orders, 1 paid, 1 matching |
| The launch video rendered, including the vertical cut | 6 | pass | one: cuts stored: ['video', 'video_vertical']; two: cuts stored: ['video', 'video_vertical'] |

## `not-slop`

### Left to judgement — no score awarded

| Check | Budget | What to look at | Resolves to |
|---|---|---|---|
| The site reads like a real brand's, not an AI template | 7 | Open each published site and judge whether it reads as work a studio was paid for: a committed palette, a chosen type pairing, sections that say something. | `one`: https://epyhia-1dab77bd201d.vercel.app<br>`two`: https://epyhia-55e582d723e3.vercel.app |
| Two unrelated briefs do not look like the same template | 5 | Compare the visual identity each run was given. Two businesses with nothing in common should not have arrived at the same look. | `one`: {"accent": "#C2521E", "bg": "#F4EDE1", "fg": "#201814", "muted": "#6F6156"}<br>`two`: {"accent": "#A8401C", "bg": "#F0EADD", "fg": "#191614", "muted": "#6A6154"} |
| The pack sounds like the business, not like a content mill | 3 | Read the posts against the brand doc's voice: adjectives honoured, the do-not list obeyed, no claim the brief never made. | `one`: ba9c298c-23d6-405c-b848-8705ff4c4513<br>`two`: 5ff61364-7286-4474-9d4f-bdd1a4f83f21 |

## `crew-orchestration`

### Mechanically checked

| Check | Points | Result | Evidence read |
|---|---|---|---|
| The orchestrator delegates and never acts | 5 | pass | one: 13 actions, 0 the orchestrator's; two: 13 actions, 0 the orchestrator's |
| Every call carries a tier, and the top tier is the orchestrator's | 4 | pass | one: 24 calls, 0 without a model id or tier, 1 at tier 'planning' of which 0 not the orchestrator's; two: 18 calls, 0 without a model id or tier, 1 at tier 'planning' of which 0 not the orchestrator's |
| Cost is logged for every call and every action | 3 | pass | one: one total of 1.398065999999999999480956858 covering 24 calls and 13 actions; 0 calls uncosted, 0 actions with no projected cost, 0 succeeded actions with no actual cost; two: one total of 1.211601000000000000027255975 covering 18 calls and 13 actions; 0 calls uncosted, 0 actions with no projected cost, 0 succeeded actions with no actual cost |
| An unrelated brief produced an unrelated run | 3 | pass | 2 distinct palettes and 2 distinct aliases across 2 runs, 0 shared artifact hashes, each deploy probe read its own brand doc name: True |

## `action-gate`

### Mechanically checked

| Check | Points | Result | Evidence read |
|---|---|---|---|
| Irreversible actions waited for a human | 5 | pass | one: 7 approval-gated actions, 0 executed with no recorded decision, approver and time; two: 8 approval-gated actions, 0 executed with no recorded decision, approver and time |
| A re-run produces no second site and no second charge | 6 | pass | one: resubmission 200 deduplicated=True; publications 1 → 1 at 1 alias(es), orders 1 → 1; two: resubmission 200 deduplicated=True; publications 1 → 1 at 1 alias(es), orders 1 → 1 |
| The evaluation approved nothing | 3 | pass | one: 7 approval decisions, 0 attributed to 1b81QLW9JKFboGE8ER0nGNfkGyGGeRpt@clients; two: 8 approval decisions, 0 attributed to 1b81QLW9JKFboGE8ER0nGNfkGyGGeRpt@clients |
| Every action left an auditable row | 3 | pass | one: 13 action rows, 0 missing a key, a state, a projected cost, or — where succeeded — an actual cost or the evidence a verification stored; two: 13 action rows, 0 missing a key, a state, a projected cost, or — where succeeded — an actual cost or the evidence a verification stored |
| The gate refused what it was built to refuse | 3 | pass | one: site artifact clean, charge path armed, 1 order(s) from 2 session(s); two: site artifact clean, charge path armed, 1 order(s) from 1 session(s) |

## `design-failure-catalogue`

### Left to judgement — no score awarded

| Check | Budget | What to look at | Resolves to |
|---|---|---|---|
| The design document argues its choices | 6 | Read the architecture of record and judge whether each significant choice is argued against the alternative it beat, rather than asserted. | DESIGN.md |
| Five real failure modes, each with a control | 4 | Read the failure catalogue and judge whether each mode is one this system could actually suffer and whether the named control is in the code. | DESIGN.md |

## `ships-clean-clone`

### Left to judgement — no score awarded

| Check | Budget | What to look at | Resolves to |
|---|---|---|---|
| The agency itself is deployed and reachable | 3 | The deployed agency this evaluation authenticated against and read every record from — open it and sign in. | https://epyhia.fly.dev |
| Every credential the system takes is declared | 2 | Read the example environment file and judge whether a clean clone can be configured from it, and whether the system starts without the credentials it leaves blank. | .env.example |
| A clean clone comes up with one command | 2 | Read the compose file and judge whether one command brings up the database, the mail catcher, the API and the worker with no account signup. | docker-compose.yml |
| The demo recording | 3 | Watch the recording of a brief going in and the three deliverables coming out. | missing |

