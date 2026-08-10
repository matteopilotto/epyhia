# Feature Specification: EPYHIA — An Agency Staffed by Agents

**Feature Branch**: `docs/epyhia-agency-spec`

**Created**: 2026-08-02

**Status**: Draft

**Input**: User description: "based on the information described in DESIGN.md"

## Overview

EPYHIA is an agency staffed by autonomous agents. An operator hands it one plain-language
brief describing any business; EPYHIA hands back three real things for that business:

1. A **website** on a live, publicly reachable URL.
2. A **marketing pack** — landing copy, 3–5 social posts, a launch email, and a launch video
   with a vertical cut.
3. A **working test-mode checkout** whose completed purchase writes a real order record.

Every action that deploys, charges, sends, or publishes stops at a single approval-and-audit
boundary before it reaches the outside world.

**The product is the agency, not any one client.** Submitting a different business must be a
different brief, never a different codebase.

## Clarifications

### Session 2026-08-10

- Q: When the evaluation runs, who approves the actions that halt for approval — the eval
  script itself, a person while the script waits, or nobody because the run already happened?
  → A: Nobody at eval time. An operator drives both runs through the console, approvals and the
  one test purchase included; the evaluation asserts over the stored records afterwards. The
  only thing it may itself initiate is a byte-identical resubmission, which is side-effect-free
  by construction.
- Q: How does the evaluation know which two runs to assert over? → A: It is given the two brief
  files as arguments and resolves each run by hashing the brief exactly as ingest does. Run
  identity is brief identity, so no run identifier is ever written into the repository, and the
  re-run assertion falls out of resubmitting the same file.
- Q: Where should the six scored areas and their point values live as a tracked source of truth?
  → A: As an external contract alongside the others, `contracts/grading-rubric.md`, reproduced
  verbatim and not edited for convenience. The rubric schema constrains `area` to its six ids,
  and a test asserts every area is covered and the point totals reconcile.
- Q: What must the evaluation do with a human-judgement row — print a link, or resolve one and
  confirm it points at something real? → A: Resolve, never re-probe. Each row names what is to
  be shown; system output resolves from stored records, human-produced material from a tracked
  repository path or a URL in a tracked file, and an unresolvable row renders as missing.
- Q: What happens when a rubric check marked `required` fails? → A: The report is always
  written, with required failures summarised at the top, and the evaluation exits non-zero only
  for a failed required *automated* check. A missing human-judgement item is reported as missing
  and never affects exit status.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Brief to a verified live website (Priority: P1)

An operator writes a plain-language brief about a business — its name, positioning, products,
prices, voice — and submits it. EPYHIA reads the brief, decides a visual and verbal identity
for that business, writes and fact-checks the page copy, composes the site around it, and
pauses to ask the operator for permission before putting anything on the public internet. The
operator sees exactly what is about to go live, approves, and receives a URL. The system does
not report the site as live until it has independently fetched that URL and confirmed the
client's own name is on the page.

**Why this priority**: This is the smallest slice that delivers the headline value and proves
the two things everything else rests on — that a business is described by data rather than by
code, and that "done" means proved in the world rather than self-reported. Without it there is
no product.

**Independent Test**: Submit a brief for a business the system has never seen, approve go-live,
open the returned URL in a browser, and confirm the page presents that business. Then read the
audit record and confirm it stores the evidence (response status and the matched business name)
that the check actually ran.

**Acceptance Scenarios**:

1. **Given** a valid brief for a previously unseen business, **When** the operator submits it,
   **Then** the system opens a run, records an immutable copy of the brief, and shows a live
   timeline of the work as it progresses.
2. **Given** a run whose site is ready to publish, **When** the go-live action is requested,
   **Then** the action halts in an awaiting-approval state and the console shows the target
   URL, the projected cost, and the deduplication key, with approve and deny controls.
3. **Given** a pending go-live action, **When** the operator approves it, **Then** the site is
   published and the action is only marked successful after an independent fetch of the public
   URL returns success and contains the business name taken from that run's own identity
   record.
4. **Given** a pending go-live action, **When** the operator denies it, **Then** nothing is
   published and the action is permanently recorded as denied with the deciding identity.
5. **Given** a published site, **When** the operator later edits the run's brand identity and
   re-runs, **Then** the same stable URL serves the new version, the previous version remains
   reachable at its own immutable address, and the difference between the two identity versions
   is viewable in the console.
6. **Given** a site whose published version does not match the version just built, **When**
   verification runs, **Then** the action fails rather than succeeding, because the check
   asserts the build marker of the version being published — not merely that some page exists.

---

### User Story 2 - A marketing pack that cannot state a fact the business did not give it (Priority: P2)

The same brief produces landing copy, 3–5 social posts, a launch email, and a launch video with
a vertical cut, all in a voice chosen for that business. Before any of it can leave the system,
every number in it is checked mechanically against the numbers in the brief, and a separate
reviewer checks voice and unsupported claims. Anything that fails is held back and shown to the
operator instead of being sent.

**Why this priority**: A wrong price in an email cannot be unsent, and a wrong price in a video
is invisible until someone watches it. This is the failure most likely to damage a real
customer, and the pack is the second of the three deliverables.

**Independent Test**: Submit a brief, let the pack generate, and confirm every numeral in every
delivered piece traces to a number in the brief or to an enumerated derivation of one. Then
inject a fabricated price into a draft and confirm the piece is held back rather than sent.

**Acceptance Scenarios**:

1. **Given** a brief containing prices, product counts, and a founding year, **When** any
   artifact containing words or on-screen values is produced, **Then** every numeral in it is
   normalised and compared against the numbers extracted from that brief plus a fixed,
   code-defined set of legitimate derivations, before any model is asked an opinion about it.
2. **Given** an artifact containing a numeral outside both sets, **When** the check runs,
   **Then** the artifact is sent back for one revision, and if it still fails it is stored as
   flagged and surfaced in the console rather than delivered.
3. **Given** a draft that is numerically correct but off-voice for the business, **When** the
   review pass runs, **Then** it returns structured, itemised violations rather than a silent
   approval, and it does not rewrite the draft itself.
4. **Given** a launch email ready to send, **When** the send is requested, **Then** it halts
   for operator approval showing the recipient and content, and after sending it is confirmed
   by reading the message back from the receiving mailbox.
5. **Given** the same brief, **When** the launch video renders, **Then** the vertical cut is
   produced from the same on-screen values as the primary cut, and those values are subject to
   the same numeric check as the written copy.
6. **Given** the landing copy the pack produced, **When** the site is composed, **Then** the
   site uses that reviewed copy rather than authoring its own claims, so the site and the pack
   speak in one voice about the same facts.

---

### User Story 3 - A checkout that takes a real test payment and records the order (Priority: P3)

The products and prices in the brief become a live catalogue. Before that catalogue can take
money, the operator approves it once, on a screen showing every product, amount, currency, and
billing type exactly as it will be charged. After that, a visitor to the published site can
click a buy button, complete a card payment on the processor's hosted form, and the completed
purchase is recorded as an order without the buyer ever waiting on a human.

**Why this priority**: It is the third deliverable and the one that proves the pipeline reaches
money, but it depends on a published site existing first.

**Independent Test**: Submit a brief with both a recurring and a one-time product, approve the
catalogue, open the live site, complete a test purchase, and confirm an order record exists
matching a product in that brief.

**Acceptance Scenarios**:

1. **Given** a brief listing products with prices, currencies, and per-product billing types,
   **When** the catalogue is created, **Then** it is created entirely from those brief fields,
   with no product, price, or currency defined anywhere in the system's own configuration.
2. **Given** a catalogue ready to take money, **When** arming it is requested, **Then** it halts
   for approval on a screen showing the fully resolved catalogue, and after approval every price
   is re-read from the processor and confirmed active with a matching amount and currency.
3. **Given** an armed run, **When** a buyer clicks a buy button, **Then** a checkout session is
   created without any operator interaction, still recorded and deduplicated like every other
   consequential action.
4. **Given** a run whose catalogue has not been armed, **When** a buyer clicks buy, **Then** the
   request is refused with a clear unavailable state on the page — not an error page, and not a
   session against a price that does not exist.
5. **Given** a completed test purchase, **When** the payment notification arrives, **Then** an
   order record is written, and a repeated notification for the same event writes no second
   order.
6. **Given** a brief that prices in one unit and charges in another, **When** checkout runs,
   **Then** the displayed and charged currencies both come from the brief and neither is
   assumed by the system.

---

### User Story 4 - Re-runs and crashes never duplicate anything (Priority: P4)

An operator resubmits the exact same brief, or the system crashes halfway through a run and
restarts. Neither produces a second website, a second set of products, a second charge, or a
second order.

**Why this priority**: Duplicate work and duplicate charges are the fastest way to lose a
customer's trust, and this is the property most often claimed and least often proved. It is
separated from P1–P3 because it is only demonstrable once real actions exist to be repeated.

**Independent Test**: Run a brief to completion, then submit the byte-identical brief again and
confirm one live site, one catalogue, one order, and a set of short-circuited actions carrying
the same deduplication keys as the first run.

**Acceptance Scenarios**:

1. **Given** a brief identical to one already submitted, **When** it is resubmitted, **Then**
   it resolves to the existing brief record and every consequential action short-circuits to its
   existing result instead of executing again.
2. **Given** a re-run, **When** the underlying generated content differs slightly because
   generation is not deterministic, **Then** the site still does not deploy a second time,
   because the deduplication identity is the target being published, not the bytes produced
   for it.
3. **Given** an edited brand identity for the same brief, **When** the run repeats, **Then** a
   genuine second publication occurs — this case is supposed to fire, and is distinguishable in
   the audit trail from a duplicate.
4. **Given** a crash after an action reached the outside world but before its result was
   recorded, **When** the work resumes, **Then** the outcome is determined by independently
   probing the world, not by trusting a stored status.
5. **Given** a crash while an action is waiting for operator approval, **When** the system
   restarts, **Then** the pending action is still there on reload and the operator's approval
   resumes that same action rather than starting a new one.
6. **Given** a resumed run, **When** work that already produced expensive generated content is
   re-executed, **Then** the previous result is reused where possible so the customer is not
   billed twice for identical work — while correctness never depends on that reuse succeeding.

---

### User Story 5 - Every run answers "what did it do and what did it cost" (Priority: P5)

An operator opens a finished run and sees, without leaving the console: the timeline of what
each agent did, every consequential action with its target and its evidence, the cost of every
individual model call including which tier of model made it, the total spend for the run, and
whether it stayed inside budget.

**Why this priority**: Cost that is only visible after the fact is the same category of failure
as a status field that lies. It is P5 because it is observability over work that must exist
first.

**Independent Test**: Complete a run, then answer from the console alone: which model tier
planned the run, what each stage cost, what the run cost in total, and what evidence proves the
site is live.

**Acceptance Scenarios**:

1. **Given** any completed run, **When** the operator opens it, **Then** every model call is
   listed with its agent, model identity, tier, token counts, derived cost, and latency.
2. **Given** any completed run, **When** the operator opens it, **Then** model spend and
   external-action spend appear in one combined total against one budget, not two separate
   views.
3. **Given** a run that exceeds its configured spend budget, **When** the limit is reached,
   **Then** the run stops rather than continuing to spend.
4. **Given** a system-wide daily spend ceiling, **When** it is reached, **Then** new runs do not
   start.
5. **Given** a completed run, **When** costs are computed, **Then** they use rates that are
   dated, so a rate change on a known date does not silently misreport historical or future
   runs.
6. **Given** two runs of the same brief that differ only because the underlying instructions
   were edited, **When** they are compared, **Then** the recorded instruction version
   distinguishes them, so a cost or quality difference is attributable rather than noise.

---

### User Story 6 - A second, unrelated business proves it is an agency (Priority: P6)

The operator submits a brief for a completely different kind of business — a bakery rather than
a clinic — and the system produces a genuinely different site, a different identity, and a
different pack, with no change to any source file, prompt, or fixture.

**Why this priority**: It is the strongest available evidence that the system is an agency
rather than a one-client script, and it is much harder to fake than any single-client demo. It
is last because it is a property proved *over* the other stories rather than a slice of
functionality.

**Independent Test**: Run two unrelated briefs end to end without touching a source file, then
confirm the two runs share no artifact content, no visual identity, and no published address.

**Acceptance Scenarios**:

1. **Given** two unrelated briefs, **When** both run to completion, **Then** they produce
   different visual identities, different published addresses, and no shared artifact content.
2. **Given** any run, **When** the site's liveness is verified, **Then** the expected business
   name is read from that run's own identity record rather than from any value written into the
   system.
3. **Given** any run, **When** the automated evaluation inspects the record, **Then** it finds
   zero consequential actions attributed to the orchestrating agent, proving the orchestrator
   delegates rather than acts.
4. **Given** the delivered evaluation report, **When** a reader opens it, **Then** mechanically
   checkable results carry pass/fail and stored evidence, while human-judgement items carry
   links and no self-awarded score, with the difference stated plainly.

---

### Edge Cases

- **A price is fabricated into the website rather than into an email.** The site is copy too.
  Publication is refused for any run whose site content failed the numeric check — the check
  does not care which agent produced the string.
- **Legitimate copy computes a number the brief never stated** (an annual total from a monthly
  price, a plan count, an age from a founding year). A fixed, code-defined derivation set covers
  these. Anything outside it is held and shown to the operator rather than published — the
  system deliberately over-holds rather than under-checks.
- **The same number written four different ways** (with separators, with a currency symbol,
  spelled out in words, in a different display currency). Values are compared after
  normalisation, so spelling a number out is not a way around the check.
- **The brief itself contains instructions aimed at the system** rather than facts about the
  business — for example a request to add an endorsement from an authority that never gave one.
  The brief is screened at intake, the screening decision is logged whether it passes or fails,
  and the brief is thereafter handled as structured data rather than as instructions. Even if
  screening misses it, the resulting action still stops for human approval with its concrete
  target on screen and still cannot reach the outside world without a credential it does not
  hold.
- **Publication succeeds but the stable address still serves the previous version.** Verified
  against, by asserting the specific build's marker rather than merely that a page exists.
- **A publication returns success but serves a parked page or an error page.** Verified against,
  by asserting the business's own name appears in the response body.
- **Verification never passes.** The action retries with backoff, caps at a small number of
  attempts, then lands as failed. It never lands as succeeded.
- **A buyer clicks buy before the catalogue is armed.** The purchase is refused with a legible
  unavailable state, not an error page.
- **Payment credentials are not configured** (a fresh clone). The system still starts, the
  console still works, and the failure appears only at the point of the action, naming the
  missing credential explicitly.
- **The review pass is wrong about voice.** Two revision passes maximum, then the piece is held
  as flagged and surfaced — never an unbounded revision loop.
- **Two workers pick up the same action simultaneously.** Exactly one executes it; the other
  reads the existing result.
- **A repeated payment notification for the same event.** Recorded once.

## Requirements *(mandatory)*

### Input and grounding

- **FR-001**: The system MUST accept a client brief as its only channel for client-specific
  facts, carrying at minimum: business name, tagline, one-liner, positioning, a product list
  (name, description, price in minor units, display currency, charge currency, billing type,
  features, exclusions), voice guidance (adjectives, do list, don't list), locale, founding
  year, and contact details.
- **FR-002**: The system MUST persist every submitted brief verbatim with a content hash, and
  MUST treat two briefs with the same hash as the same run.
- **FR-003**: The system MUST support per-product billing type (recurring or one-time) within a
  single brief, and MUST support a display currency that differs from the charge currency.
- **FR-004**: At intake, the system MUST extract every numeral in the brief into a per-run
  grounding record before any expensive work begins.
- **FR-005**: The system MUST expand the grounding record with a closed, code-defined set of
  derivations (annualisations, sums and differences of stated prices, collection counts,
  elapsed time from a stated year, and the same minor-unit amount restated under the product's
  other stated currency label — with no exchange-rate conversion, since inventing a rate would
  be exactly the fabrication the check exists to prevent). This set MUST NOT be extendable at
  runtime by any model output.
- **FR-006**: The system MUST compare numerals after normalisation — separators and currency
  symbols removed, amounts reduced to minor units in a named currency, and number words mapped
  to digits.
- **FR-007**: The system MUST screen each incoming brief for instructions directed at the
  system rather than facts about the business, MUST log every screening decision whether it
  passes or fails, and MUST stop a rejected brief before expensive work begins.
- **FR-008**: The system MUST pass the brief to agents as structured, named fields rather than
  as free prose inserted into their instructions.

### Planning and parameterisation

- **FR-009**: The system MUST derive, per run, a versioned brand identity record containing at
  minimum: business name, descriptor, positioning, a colour palette as concrete values, a type
  pairing, a named motion language, a selected composition archetype, and voice do/don't lists.
- **FR-010**: The brand identity record MUST have a fixed schema with per-client contents; the
  schema MUST NOT change to accommodate a particular client.
- **FR-011**: The planning stage that derives the brand identity record is the only work that
  reads the raw brief in order to write it. Every agent downstream MUST read the brand
  identity record and MUST NOT read the raw brief, with two bounded exceptions: the review
  pass MUST read both, because it checks facts as well as voice; and the money stage MUST
  receive product facts through the run's resolved catalogue — structured product fields
  extracted from the brief at intake — never by reading the raw brief itself.
- **FR-012**: The brand identity record MUST be readable, editable, and diffable from the
  operator console, and editing it MUST produce a new version that a subsequent run treats as
  genuinely different work.
- **FR-013**: The sequence of work stages MUST be fixed by the system — copy, then site, with
  demand and money proceeding in parallel — and MUST NOT be composed at runtime by a model.

### The website

- **FR-014**: The system MUST produce a single-page website consisting of static content only,
  containing no credentials and requiring no build step to publish.
- **FR-015**: The website MUST be composed around the reviewed landing copy produced by the
  marketing stage; the site-building agent MUST NOT author a price, feature, or claim that is
  not in that copy or in the brief.
- **FR-016**: The rendered website MUST pass the same numeric grounding check as every written
  artifact, and publication MUST be refused for any run whose site content is flagged.
- **FR-017**: Each brief MUST own one stable public address; every successful publication for
  that brief MUST point that address at the newest version, while prior versions remain
  reachable at their own immutable addresses.
- **FR-018**: Publication MUST be verified by fetching the stable address and asserting both a
  success response and the presence of that run's own business name in the response body.
- **FR-019**: Publication MUST additionally assert a build marker identifying the specific
  brief, brand identity version, and instruction version being published, so a failed switch to
  the new version is detected rather than reported as success.

### The marketing pack

- **FR-020**: The system MUST produce landing copy, 3–5 social posts, a launch email, and
  launch video content for each run.
- **FR-021**: Landing copy MUST be produced by the marketing stage and MUST complete before the
  site is composed.
- **FR-022**: Every artifact containing words or on-screen values MUST be numerically checked
  against the grounding record before any model is asked to evaluate it.
- **FR-023**: A distinct review pass MUST evaluate each draft against the brand identity record
  and the brief, MUST return itemised violations rather than a silent approval, and MUST NOT
  rewrite the draft itself.
- **FR-024**: A failing draft MUST get at most two revision passes; if it still fails it MUST
  be stored as flagged and surfaced in the console rather than delivered.
- **FR-025**: The system MUST produce a launch video from a set of parameterised composition
  archetypes selected per client, plus a vertical cut of the same archetype consuming the same
  on-screen values.
- **FR-026**: Video on-screen values MUST be supplied as structured data, never as executable
  code authored by a model, so that they are subject to the same numeric check as written copy.

### Money

- **FR-027**: The system MUST create the payment catalogue at run time from the brief's product
  list; no product, price, currency, or billing type may be defined in the system's own code,
  configuration, or fixtures.
- **FR-028**: Arming a run's charge path MUST be a single approval-gated action whose approval
  screen shows the fully resolved catalogue — every product, amount, currency, and billing type
  as it will be charged.
- **FR-029**: Arming MUST be verified by re-reading every price from the payment processor and
  asserting each is active with a matching amount and currency.
- **FR-030**: Buy buttons on the published site MUST reference a product identifier derived from
  the brief; payment-processor identifiers MUST NOT appear in the published site content.
- **FR-031**: A purchase request MUST resolve its product identifier to a live price at click
  time, and MUST be refused with a legible unavailable state if the run's charge path is not
  armed.
- **FR-032**: A completed purchase MUST write an order record, deduplicated on the payment
  notification's event identifier such that a repeated notification can never produce a second
  order, even if the repeat arrives while the first is still being recorded.

### The action boundary

- **FR-033**: Every action that deploys, charges, sends, or publishes MUST pass through one
  boundary that is the sole holder of external credentials. Agents MUST receive only named,
  typed capability functions with no key material reachable through them.
- **FR-034**: Model inference MUST NOT route through that boundary; it MUST instead be metered
  against per-run token limits, a per-run spend budget, and a system-wide daily ceiling.
- **FR-035**: Every consequential action MUST progress through the states pending →
  (awaiting approval) → executing → verifying → succeeded or failed, with denied as a terminal
  state reachable only from awaiting approval. There MUST be no path from executing directly to
  succeeded.
- **FR-036**: Every action type MUST register both an execution behaviour and an independent
  verification behaviour. Approval policy, deduplication, retry, and audit MUST live in the
  boundary itself, not be duplicated per action type.
- **FR-037**: Approval MUST be required for going live, for arming the charge path, and for
  anything outbound to a person. Approval MUST NOT be required for individual buyer checkout
  sessions, for draft artifacts, for local video rendering, or for writing a brand identity
  record.
- **FR-038**: A pending approval MUST survive a restart of the system: it MUST be durably
  recorded, MUST reappear in the console on reload, and the operator's eventual decision MUST
  resume that same action rather than starting a second one.
- **FR-039**: The approval screen MUST show what is about to happen, the concrete target (URL,
  amount and currency, or recipient), the projected cost, the deduplication key, and approve and
  deny controls.
- **FR-040**: Verification evidence — response status, matched strings, resolved record
  identifiers — MUST be stored on the action record and MUST be the basis on which success is
  claimed anywhere in the system.
- **FR-041**: Verification MUST retry with backoff up to a small fixed cap and then record
  failure. An action whose verification never passes MUST NOT be recorded as succeeded. Where the
  proof of an effect can only arrive on a later external event, the action MUST hold in the
  verifying state — consuming no attempt and recording no failure — until that event supplies it.
  Holding at verifying is never reported as success.
- **FR-042**: The orchestrating agent MUST be constructed with no capability functions at all,
  and the system MUST be able to demonstrate zero consequential actions attributed to it across
  a full run.
- **FR-043**: Channels that are not connected to a live third party (published social posts,
  outbound email) MUST still be implemented as real action types with real approval, real
  deduplication, real audit records, and real verification against a stand-in destination.

### Deduplication and recovery

- **FR-044**: Every consequential action MUST carry a deduplication key derived from the brief
  hash, and two simultaneous attempts on the same key MUST resolve to exactly one execution —
  the second reading the first's result — without either attempt needing to coordinate with the
  other.
- **FR-045**: The publication key MUST identify the target being published — brief, brand
  identity version, instruction version — and MUST NOT include a hash of the generated content.
- **FR-046**: The video key MUST include the pinned rendering-tool version, so that a version
  upgrade does not serve stale output as a cache hit.
- **FR-047**: Work items MUST be claimed with a lease so that a crashed worker's item becomes
  re-claimable. Delivery MUST be at-least-once at the work layer and exactly-once in effect at
  the action boundary.
- **FR-048**: Expensive model results MUST be reusable across a resumed run, keyed on everything
  that determines the output including instruction version and brand identity version. This
  reuse MUST be a cache that is permitted to miss, and no correctness guarantee may depend on it
  hitting.

### Cost, audit, and observability

- **FR-049**: The system MUST record one row per model call carrying agent, model identity,
  tier, instruction version, token counts by kind, derived cost, latency, and the run it belongs
  to.
- **FR-050**: The system MUST record one row per consequential action carrying the run, the
  requesting agent, the action type, the deduplication key, the request payload, the approval
  decision and decider, the verification evidence, the cost, and timestamps.
- **FR-051**: Cost rates MUST be dated and MUST distinguish input, output, cache-write, and
  cache-read pricing per model.
- **FR-052**: Model spend and external-action spend MUST roll up into one total against one
  per-run budget.
- **FR-053**: The system MUST enforce per-run token limits, a per-run spend budget, and a
  system-wide daily kill switch.
- **FR-054**: Every model call and every action MUST be attributable to a single run identifier
  that threads from brief to delivery.
- **FR-055**: The system MUST record the instruction version used for each run alongside the
  brand identity version.

### Operator console

- **FR-056**: The console MUST let an operator submit a brief, watch a run's timeline update
  live, approve or deny pending actions, read and edit the brand identity record and diff its
  versions, view produced artifacts including flagged ones, and view cost.
- **FR-057**: The console MUST authenticate operators against a real identity provider, and the
  same authenticated path MUST be the only way in — no separate bypass credential may exist.
- **FR-058**: Automated evaluation MUST authenticate through the same identity provider using
  machine-to-machine credentials rather than through any alternative authentication path. That
  credential MUST NOT carry approval authority — the evaluation reads records and may resubmit a
  byte-identical brief, but no approval decision may ever be attributed to it.

### Genericity and evaluation

- **FR-059**: No client-specific value may appear in source code, instruction templates,
  constants, or test fixtures. Every such value MUST be read from the run's brief or brand
  identity record at the moment it is used.
- **FR-060**: Instruction templates MUST live in versioned files rather than embedded in source
  code, so that an automated check can scan the rendered templates for client-specific data and
  fail the build.
- **FR-061**: Automated evaluation MUST assert, against the deployed system and from the stored
  records of a brief already driven end to end by an operator: that publication succeeded with
  its stored evidence; that an order exists matching a product in that brief; that re-running
  the same brief produces one publication and one order; that every action and every model call
  carries a cost and a tier with exactly one top-tier call; that nothing flagged reached
  publication; that no purchase exists for an unarmed run; and that zero actions are attributed
  to the orchestrator. It MUST NOT re-probe the outside world for anything a verification step
  already proved and stored. Resubmitting the brief byte-identically is the one action the
  evaluation may itself initiate, because deduplication makes it free of external effect.
  The evaluation MUST locate each run by hashing a brief it is given as input, using the same
  canonicalisation as ingest — never by a run identifier recorded anywhere in the repository,
  and never by an implicit "most recent run" rule.
- **FR-062**: Automated evaluation MUST additionally assert, from the stored records of a
  second, unrelated brief driven end to end, that the two runs differ in visual identity and
  published address and share no artifact content.
- **FR-063**: The evaluation report MUST separate mechanically checked results, which carry
  pass/fail and the evidence read, from human-judgement items, which carry links and no
  self-awarded score, and MUST state that distinction plainly. Each human-judgement item MUST
  name what is to be shown rather than carry a literal link: references to system output MUST
  resolve from stored records, references to human-produced material MUST resolve to a tracked
  repository path or a URL held in a tracked file, and an item that resolves to nothing MUST
  render as missing — never as a pass, and never as a score.
- **FR-067**: The scored areas and their point values MUST exist as a tracked contract in the
  repository, reproduced from the external grading table rather than restated inside the
  evaluation script. Every rubric entry MUST name one of those areas, every area MUST carry at
  least one entry, and the per-area point totals MUST reconcile to the contract — checked
  mechanically, not by reading.
- **FR-068**: The evaluation MUST produce its report on every run, including a failing one, and
  MUST summarise any failed required check at the top of it. It MUST signal failure to whatever
  invoked it, in a form an automated check can act on, when and only when a required
  mechanically-checked result fails — a human-judgement item that resolved to nothing MUST NOT
  change that signal.

### Operability

- **FR-064**: The system MUST start successfully without payment or hosting credentials
  configured, and MUST fail only at the point of the specific action, naming the missing
  credential explicitly rather than surfacing an internal error.
- **FR-065**: A clean clone MUST reach a fully running local system — including a local mail
  catcher requiring no account signup — with a single command and default configuration.
- **FR-066**: No credential, generated artifact, or local-only file may be tracked in version
  control; the artifacts of record MUST live in the system's own storage.

### Key Entities

- **Brief**: The verbatim client input and its content hash. The sole boundary through which
  client facts enter the system.
- **Run**: One execution against one brief. Carries the brand identity version, the instruction
  version, the grounding record, the resolved catalogue derived from the brief's product list,
  the budget, and status. Its identifier threads through every model call and every action.
- **Brand identity record**: The versioned, structured parameterisation of a run — palette, type
  pairing, motion language, composition archetype, voice, business name. Read by every agent
  downstream.
- **Grounding record**: The per-run set of literal numerals extracted from the brief plus their
  enumerated derivations. The reference against which every artifact is checked.
- **Work item**: A unit of the fixed pipeline, claimed under lease, carrying its own state. Also
  the source of the run timeline.
- **Artifact**: A produced deliverable — copy, posts, email, video content, site — with its
  content, hash, grounding status (clean or flagged), and any violations found.
- **Action**: One consequential external effect. Simultaneously the audit record and the
  deduplication ledger entry: unique deduplication key, request, approval decision and decider,
  verification evidence, cost.
- **Model call**: One invocation of one agent, with its model, tier, token counts, derived cost,
  and latency. The per-call half of the cost record.
- **Order**: One recorded test purchase, deduplicated on the payment notification's event
  identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can go from submitting a brief for a business the system has never
  seen to a publicly reachable website for that business, with zero source-file changes.
- **SC-002**: 100% of actions recorded as successful carry independently gathered evidence that
  they took effect in the world; zero actions can reach a successful state on self-report.
- **SC-003**: Re-submitting a byte-identical brief produces zero additional live sites, zero
  additional catalogue entries, zero additional charges, and zero additional orders.
- **SC-004**: Zero numerals that trace neither to the brief nor to an enumerated derivation of
  it appear in any delivered artifact — including the published website.
- **SC-005**: An operator can decide on a pending irreversible action in under one minute from a
  single screen, without consulting any other system, because the target, cost, and
  deduplication key are all present on it.
- **SC-006**: Two unrelated briefs run without any intervening source change produce zero shared
  artifact content, distinct visual identities, and distinct published addresses.
- **SC-007**: 100% of model calls carry a recorded model tier and cost, and exactly one top-tier
  call occurs per run.
- **SC-008**: A forced crash at any point in a run results in zero duplicated external effects
  after resume, and any pending approval is still actionable after restart.
- **SC-009**: A buyer completes a test purchase on the published site with zero operator
  interaction between the buy button and the payment form.
- **SC-010**: A fresh clone reaches a running system with one command, no account signups, and
  no credentials configured — and any action requiring an absent credential fails with a message
  naming that credential.
- **SC-011**: An operator can answer "what did this run do, and what did it cost" entirely from
  the console, with model spend and external-action spend in one total.
- **SC-012**: A brief containing instructions aimed at the system results in zero published
  artifacts carrying the injected content, and the screening decision is retrievable from the
  record whether it passed or failed.
- **SC-013**: A reader of the evaluation report can tell, for every line, whether the result was
  mechanically checked or left to human judgement.

## Assumptions

- **One operator, many briefs.** Multi-tenancy, tenant data isolation, role separation, and
  operator-editable approval policy are out of scope. There is one approval tier and one audit
  trail.
- **Everything outbound is simulated but real in shape.** Payments run in the processor's test
  mode; email goes to a local catcher; social posts go to a recording destination that stores
  and returns a readable permalink. Each is a genuine action with approval, deduplication, audit,
  and verification — swapping in a live destination is a change to one adapter, not to the
  system.
- **Custom domains are out of scope.** Each brief gets a stable address on the hosting
  provider's own domain.
- **Design effort goes into the generated client site, not the operator console.** The console
  is a working operator surface — submit, timeline, approve, artifacts, cost — polished only as
  far as the demonstration requires.
- **Flagged artifacts are surfaced read-only.** The operator's remedy is to correct the brief or
  the brand identity record and re-run, not to hand-edit a flagged artifact in place.
- **Two revision passes is the ceiling** for a draft failing review, chosen so the failure mode
  is a held artifact rather than an unbounded loop.
- **The numeric check deliberately over-holds.** Copy computing a value outside the enumerated
  derivation set is held and shown to the operator. This costs the operator a click; the opposite
  bias costs a customer a wrong price in public.
- **Run duration is deliberately unconstrained.** No success criterion bounds how long a run
  takes, because nothing in the architecture trades anything away for run latency — the video
  render is a queued work item rather than a request-path operation, so a slow render costs
  throughput, not correctness. The only latency that is user-facing is the buyer's, covered by
  SC-009.
- **A demonstration tenant exists purely as input data.** A fictional business is used to
  exercise the system once — recurring plus one-time products, split display and charge
  currencies, a distinctive voice — precisely because those properties stress the pipeline. It is
  a row in the brief store, never a code path.
- **The evaluation's second brief is an unrelated business** of the operator's choosing; its
  only requirement is that it shares no facts with the first.
