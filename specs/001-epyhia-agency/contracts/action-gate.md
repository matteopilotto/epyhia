# Contract: The Action Gate

**The first thing built** (`DESIGN.md` §12 step 2) — before any agent exists, because building
it afterwards means retrofitting every call site and discovering the ones that went around it.

This is the interface every consequential effect passes through. It has two faces: what an
**agent** sees (capability handles), and what an **adapter** must implement.

---

## 1 · What agents see

Agents never see the gate. They are constructed with a toolset of **capability handles**:
named, typed functions with no key material reachable through them (FR-033, §4.1).

| Handle | Held by | Action type |
|---|---|---|
| `deploy(files)` | Web Builder | `deploy` |
| `send_email(to, subject, body)` | Marketer | `send_email` |
| `publish(payload)` | Marketer | `publish` |
| `stripe_product(...)` / `stripe_price(...)` | Ops | `stripe_product`, `stripe_price` |
| `arm_charge_path()` | Ops | `arm_charge_path` |
| — | **Strategist: none at all** | — |

**The Strategist's toolset contains zero handles.** Not a handle that refuses — no function to
call (§3.3, FR-042). The eval asserts zero `actions` rows with `requested_by = 'strategist'`
across a full run, which is the mechanical half of the same claim.

`checkout_session` has no agent handle: it is requested by the `POST /checkout` route on a
buyer's click, still through the gate, still keyed, still audited (§4.4).

---

## 2 · What the gate does, in order

```text
gate.request(run_id, requested_by, action_type, request, key)
  │
  1. preconditions(action_type, run)        ── fail fast, before any row
  2. INSERT INTO actions ... ON CONFLICT DO NOTHING RETURNING id
  3. if no id returned  →  read the existing row
        terminal?  →  return its result. NOTHING EXECUTES.
        in-flight? →  return "in progress"
  4. if requires_approval(action_type)
        state = awaiting_approval  (durable, BEFORE anything is raised)
        raise ApprovalRequired
  5. state = executing   →  adapter.execute(request, credentials)
  6. state = verifying   →  adapter.verify(...) with backoff, cap 5
  7. evidence stored     →  state = succeeded
```

Steps 1–4 are the gate's, always. Steps 5–6 are the adapter's. **Approval policy, idempotency,
retry and audit live in the gate and are never duplicated into an adapter** (FR-036, §4.6).

**The ordering in step 4 is the contract, not an implementation detail.** The durable row
exists before `ApprovalRequired` is raised, so a redeploy during the pause cannot lose the
action or let the operator's eventual click create a second unkeyed attempt (§4.4, research.md
R7).

---

## 3 · The adapter interface

Every action type registers exactly one pair.

```python
class Adapter(Protocol):
    action_type: str
    requires_approval: bool

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        """Reach the world. Returns the raw provider result.
        Raises CredentialNotConfigured(provider) if its credential is absent."""

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Prove it happened, INDEPENDENTLY of `result`. Returns evidence.
        Raises VerificationFailed to trigger a retry."""
```

**`verify()` must not trust `result`.** For `deploy` this is concrete: the probe fetches the
alias it derives from `brief_hash`, not the deployment URL the API handed back (§4.5). An
adapter whose `verify()` only reads what `execute()` returned is the "status field is not
evidence" failure with extra steps.

`GateContext` carries `run_id`, the run's brand doc row, and the credential store. It does not
carry an agent, a transcript, or a model.

---

## 4 · Registered pairs

| Action | Approval | `execute()` | `verify()` — what "it happened" means |
|---|---|---|---|
| `deploy` | **yes** | `POST /v13/deployments` (inline files, `target: production`), poll `readyState`, `POST /v2/deployments/{id}/aliases` | `GET` **the alias**: assert `200`, that `brand_doc.name` for this run is in the body, **and** that the build marker is (§4.5) |
| `arm_charge_path` | **yes** | Mark the run's catalogue live | Re-read **every** price from Stripe: assert `active`, `unit_amount` and `currency` match the brief (FR-029) |
| `stripe_product` / `stripe_price` | no | Create from `brief.products[]` | Read back the object by id; assert it exists |
| `checkout_session` | **no** — deliberately (§4.4) | Create a hosted Checkout Session | `SELECT` the order by `stripe_session_id`; assert it exists and is paid |
| `send_email` | **yes** | SMTP to Mailpit | Assert the catcher's API shows the message |
| `publish` | **yes** | `POST` to the recording sink (research.md R4) | `GET` the returned permalink; assert the payload is stored and readable |

**Why `checkout_session` is not approval-gated** is a correctness argument, not a convenience
one: a buyer clicking buy would sit on a spinner until a human in another timezone noticed.
That is not an approval step, it is an outage with a review queue attached. The human decision
that *can* be made in advance — *may this run take money at these prices?* — is
`arm_charge_path`, and it is gated (§4.4, FR-037).

---

## 5 · Preconditions

Checked in step 1, before any row is written:

| Action | Precondition | On failure |
|---|---|---|
| `deploy` | The run's `site` artifact is `grounding_status = 'clean'` | Refuse. **FR-016, §3.4 — the gate refuses, not the agent** |
| `checkout_session` | The run's `arm_charge_path` action is `succeeded` | `409 {"error": "not_armed"}` (FR-031, research.md R11) |
| any | The required credential is configured | `CredentialNotConfigured` → `credential not configured: vercel` (FR-064, §11) |

The `deploy` precondition is the one that must live here rather than in the Web Builder. A
control that guards outbound copy while the same fabricated price sits in an `<h2>` on the live
site is not a control; it is a report (§9.2).

---

## 6 · Approval surface

What the console must render for an `awaiting_approval` row (FR-039, §4.4):

| Field | Source |
|---|---|
| What is about to happen | `action_type` |
| The concrete target | `request` — URL, or amount + currency, or recipient |
| Projected cost | `actions.projected_cost_usd` |
| **The idempotency key** | `actions.idempotency_key` |
| Approve / deny | `POST /actions/{id}/approve` \| `/deny` |

Showing the key is the cheapest way to make idempotency legible: on the re-run the same key
appears and the action short-circuits (§4.4).

Deny is terminal: `state = denied`, `approval_decision = denied`, `approved_by` = the Auth0
`sub`. Nothing executes, ever, for that key.

---

## 7 · Failure and retry

- `verify()` retries with backoff, caps at **5** attempts, then `failed` (FR-041, §4.5).
- **A verify that never passes must never leave a row at `succeeded`.** Enforced by a CHECK
  constraint that `succeeded ⇒ evidence IS NOT NULL`, so it is a schema guarantee rather than a
  code path anyone can forget.
- An adapter error in `execute()` → `failed` with `error` populated. No verification runs.
- Crash mid-`executing`: the keyed row already exists, so the retry short-circuits into
  `verifying` and the truth comes from the world, not from a status field (§7.4).

---

## 8 · Testability — the reason this is step 2

Every behaviour above is exercisable against a **fake adapter with zero agents, zero
credentials and zero network** (§4.6):

| Test | Needs |
|---|---|
| Approval pause and resume | fake adapter |
| Key collision under concurrency | fake adapter, two sessions |
| Verification failure → retry cap → `failed` | fake adapter that always raises |
| Crash mid-`executing` → probe decides | fake adapter, killed process |
| Denial is terminal | fake adapter |
| Missing credential names the provider | no adapter at all |

The highest-stakes component in the system is also the cheapest one to test, which is why it
has no excuse for being untested (Constitution Principle VII).
