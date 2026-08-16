import { Fragment, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type Run = { id: string; alias: string; status: string };

type Action = {
  id: string;
  action_type: string;
  state: string;
  requested_by: string;
  idempotency_key: string;
  request: Record<string, unknown>;
  projected_cost_usd: number | null;
  created_at: string;
  approval_decision: "approved" | "denied" | null;
  approved_by: string | null;
  approved_at: string | null;
  evidence: Record<string, unknown> | null;
  error: string | null;
};

// Mirrors the gate's TERMINAL_STATES (epyhia/gate/gate.py).
const TERMINAL = ["succeeded", "failed", "denied"];

/**
 * A card is an open decision only while the row is undecided. The gate deliberately leaves
 * an approved row in `awaiting_approval` for a worker to resume, so state alone cannot tell
 * "waiting on the operator" from "waiting on a worker" — the decision column can.
 */
function isOpen(action: Action): boolean {
  return action.state === "awaiting_approval" && action.approval_decision === null;
}

/**
 * What the operator is actually authorising, in the concrete (contracts/action-gate.md §6).
 *
 * Deliberately not a dump of `request`: a deploy carries the whole page in it, and an
 * approval screen that makes the reviewer scroll past 40kB of markup is one that gets
 * clicked through. Everything here is read from the run and the action, never from a
 * literal, so it stays correct for any client (FR-059).
 */
function describeTarget(action: Action, run: Run | undefined): string {
  const request = action.request;
  switch (action.action_type) {
    case "deploy":
      return run ? `https://${run.alias}` : "the run's alias";
    case "send_email":
      return String(request.to ?? request.recipient ?? "—");
    case "publish":
      return String(request.permalink ?? request.channel ?? "the recording sink");
    case "arm_charge_path":
      return "this run's catalogue goes live for charging";
    default:
      return Object.entries(request)
        .filter(([key]) => key !== "files")
        .map(([key, value]) => `${key}=${String(value)}`)
        .join(" · ");
  }
}

/**
 * What approving actually does, in one sentence — the badge names the action type, but
 * FR-039 asks the screen to say what is about to happen, and "deploy" is a verb only to
 * someone who already knows the system. Generic by construction: the concrete target — the
 * URL, the recipient, the prices — is the run's own data, rendered beside it.
 */
function describeConsequence(action: Action): string {
  switch (action.action_type) {
    case "deploy":
      return "Publishes this run's site at its alias — the page goes live for anyone to open.";
    case "send_email":
      return "Sends the launch email to the recipient below.";
    case "publish":
      return "Publishes the post through the recording sink, permalink and all.";
    case "arm_charge_path":
      return "Arms the charge path — buyers can complete checkout against every price below.";
    default:
      return "Executes an external action through the gate.";
  }
}

type CatalogueRow = {
  slug: string;
  name: string;
  price_minor: number;
  currency_display: string;
  currency_charge: string;
  billing: string;
  billing_interval?: string;
  billing_interval_count?: number;
};

function describeBilling(row: CatalogueRow): string {
  if (row.billing !== "subscription") return row.billing;
  const count = row.billing_interval_count;
  return count && count > 1
    ? `${row.billing} · every ${count} ${row.billing_interval}s`
    : `${row.billing} · every ${row.billing_interval}`;
}

/**
 * The resolved catalogue, as it will be charged (FR-028, DESIGN.md §4.4).
 *
 * The unit of the decision is these prices going live, once — so every row has to be on the
 * screen, with the currency the charge is actually made in. Where the brief displays one
 * currency and charges another, both are shown and neither is converted: the difference is
 * the business's own and it is not this screen's to reconcile (research.md R6).
 */
function Catalogue({ rows }: { rows: CatalogueRow[] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-ink-muted">
          <tr>
            <th className="py-1 pr-4 font-normal">Product</th>
            <th className="py-1 pr-4 font-normal">Charged</th>
            <th className="py-1 pr-4 font-normal">Displayed</th>
            <th className="py-1 font-normal">Billing</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.slug} className="border-t border-line">
              <td className="py-1 pr-4">{row.name}</td>
              <td className="py-1 pr-4 font-mono text-xs">
                {formatAmount(row.price_minor, row.currency_charge)} {row.currency_charge}
              </td>
              <td className="py-1 pr-4 font-mono text-xs text-ink-muted">
                {row.currency_display === row.currency_charge
                  ? "—"
                  : `${formatAmount(row.price_minor, row.currency_display)} ${row.currency_display}`}
              </td>
              <td className="py-1">{describeBilling(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ApprovalCard({ action, run }: { action: Action; run: Run | undefined }) {
  const queryClient = useQueryClient();

  const decide = useMutation({
    mutationFn: (decision: "approve" | "deny") =>
      api.post<{ state: string }>(`/actions/${action.id}/${decision}`),
    // Flip the cached row on click so the card moves to Decided instantly instead of after
    // the 5s poll. `run` can be undefined (its query not yet landed) — then there is no
    // per-run cache entry to write, and the invalidation below carries the update alone.
    onMutate: async (decision) => {
      if (!run) return {};
      await queryClient.cancelQueries({ queryKey: ["actions", run.id] });
      const snapshot = queryClient.getQueryData<Action[]>(["actions", run.id]);
      queryClient.setQueryData<Action[]>(["actions", run.id], (rows) =>
        rows?.map((row) =>
          row.id === action.id
            ? {
                ...row,
                approval_decision: decision === "approve" ? "approved" : "denied",
                approved_by: "you",
                approved_at: new Date().toISOString(),
              }
            : row,
        ),
      );
      return { snapshot };
    },
    onError: (mutationError, _decision, context) => {
      // A 409 is not an error but stale state — the row was already decided, so the flip
      // is correct; the refetch replaces the guesses with the true decision.
      if ((mutationError as unknown as ApiError).error === "not_awaiting_approval") return;
      if (run && context?.snapshot) {
        queryClient.setQueryData(["actions", run.id], context.snapshot);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["actions"] }),
  });

  const error = decide.error as ApiError | null;

  return (
    <li className="rounded-lg border border-line p-4">
      <div className="flex items-center gap-3">
        <Badge variant="warn">{action.action_type}</Badge>
        <span className="text-xs text-ink-muted">requested by {action.requested_by}</span>
        {/* Which run this decision belongs to — with two briefs pending at once, a card
            without its run is a decision made from memory (FR-039). */}
        {run && <span className="font-mono text-xs text-ink-muted">{run.alias}</span>}
        <span className="ml-auto text-xs text-ink-muted">
          {action.projected_cost_usd === null
            ? "no projected cost"
            : `${Number(action.projected_cost_usd).toFixed(2)} USD projected`}
        </span>
      </div>

      <p className="mt-3 text-sm">{describeConsequence(action)}</p>

      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
        <dt className="text-ink-muted">Target</dt>
        <dd className="font-mono text-xs break-all">{describeTarget(action, run)}</dd>

        {/* Showing the key is the cheapest way to make idempotency legible: on a re-run the
            same key appears and the action short-circuits (§4.4, FR-039, SC-005). */}
        <dt className="text-ink-muted">Idempotency key</dt>
        <dd className="font-mono text-xs break-all">{action.idempotency_key}</dd>
      </dl>

      {action.action_type === "arm_charge_path" && (
        <Catalogue rows={(action.request.catalogue ?? []) as CatalogueRow[]} />
      )}

      {/* Disabled from the click until the refetch removes the card: the server refuses a
          second decision anyway (409), but a button that stays live in that window invites
          one. */}
      <div className="mt-4 flex gap-2">
        <Button
          disabled={decide.isPending || decide.isSuccess}
          onClick={() => decide.mutate("approve")}
        >
          Approve
        </Button>
        <Button
          variant="destructive"
          disabled={decide.isPending || decide.isSuccess}
          onClick={() => decide.mutate("deny")}
        >
          Deny
        </Button>
      </div>

      {error && (
        <p className="mt-2 text-xs text-red-400">
          {error.error === "not_awaiting_approval"
            ? "Already decided — a second click is not a second action."
            : error.error}
        </p>
      )}
    </li>
  );
}

/**
 * The gate's own sequence — approved → executing → verifying → succeeded|failed — with the
 * current step read from `state`. No path from `executing` straight to `succeeded` is the
 * gate's central claim; this strip is that claim made visible where the operator is looking.
 * An approved row still in `awaiting_approval` renders as the `approved` step: the decision
 * has landed but no worker has picked it up — exactly what "did my approval reach a worker?"
 * needs answered when the worker is down.
 */
function LifecycleStrip({ state }: { state: string }) {
  const current = state === "awaiting_approval" ? "approved" : state;
  const steps = ["approved", "executing", "verifying", state === "failed" ? "failed" : "succeeded"];
  const variant = (step: string): "muted" | "good" | "bad" | "warn" => {
    if (step !== current) return "muted";
    if (step === "succeeded") return "good";
    if (step === "failed") return "bad";
    return "warn";
  };
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      {steps.map((step, index) => (
        <Fragment key={step}>
          {index > 0 && <span>→</span>}
          <Badge variant={variant(step)}>{step}</Badge>
        </Fragment>
      ))}
      {current === "approved" && <span>waiting for a worker</span>}
    </div>
  );
}

/**
 * A card that has been decided: the decision line replaces the buttons, and everything on
 * it is the row's own data — so a decision made in a previous session (or by another
 * operator) presents the same as one made a moment ago.
 */
function DecidedCard({
  action,
  run,
  onDismiss,
}: {
  action: Action;
  run: Run | undefined;
  onDismiss?: () => void;
}) {
  const queryClient = useQueryClient();
  const denied = action.approval_decision === "denied";

  // T146: re-open verification only — the server refuses (409) unless the action is failed
  // with execute()'s result recorded, so this can never re-execute an effect. The refetch
  // walks the card's strip back to `verifying` and the resume's probe decides from there.
  const reverify = useMutation({
    mutationFn: () => api.post<{ state: string }>(`/actions/${action.id}/reverify`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["actions"] }),
  });
  const reverifyError = reverify.error as ApiError | null;
  return (
    <li className="rounded-lg border border-line p-4">
      <div className="flex items-center gap-3">
        <Badge variant={denied ? "bad" : "muted"}>{action.action_type}</Badge>
        <span className="text-xs text-ink-muted">requested by {action.requested_by}</span>
        {run && <span className="font-mono text-xs text-ink-muted">{run.alias}</span>}
        {/* Only a settled card can be cleared — an in-flight one is still becoming
            something. Session-local: leaving the route brings it back from server truth. */}
        {onDismiss && (
          <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={onDismiss}>
            clear
          </Button>
        )}
      </div>

      <p className="mt-3 text-sm">
        {denied ? "Denied" : "Approved"} by {action.approved_by ?? "—"} ·{" "}
        {action.approved_at ?? "—"}
      </p>

      {denied ? (
        // Deny is terminal — nothing will ever execute for that key. That deserves a
        // visible tombstone more than an approval does.
        <p className="mt-2 text-xs text-ink-muted">
          Nothing will execute for this key — deny is terminal.
        </p>
      ) : (
        <LifecycleStrip state={action.state} />
      )}

      {/* What verify() proved in the world — "deployed" is never self-reported (FR-040). */}
      {!denied && action.state === "succeeded" && action.evidence && (
        <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
          {Object.entries(action.evidence).map(([key, value]) => (
            <Fragment key={key}>
              <dt className="text-ink-muted">{key}</dt>
              <dd className="font-mono text-xs break-all">
                {typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}
              </dd>
            </Fragment>
          ))}
        </dl>
      )}

      {!denied && action.state === "failed" && action.error && (
        <p className="mt-2 text-xs break-all text-red-400">{action.error}</p>
      )}

      {!denied && action.state === "failed" && (
        <div className="mt-3">
          <Button
            size="sm"
            disabled={reverify.isPending || reverify.isSuccess}
            onClick={() => reverify.mutate()}
          >
            Re-verify
          </Button>
          {reverifyError && (
            <p className="mt-2 text-xs text-red-400">
              {reverifyError.error === "not_reverifiable"
                ? "Nothing recorded to prove — this action holds no execute() result to verify from."
                : reverifyError.error}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function ApprovalsRoute() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/runs") });

  // Settled cards stay until dismissed — auto-clearing would hide the succeeded +
  // evidence moment, which is the payoff of the verify step. Session-local by design.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // No cross-run actions endpoint exists, so the queue is assembled from the per-run ones
  // (contracts/rest-api.md). One query per run keeps each cache entry independently
  // invalidated by a decision.
  const actionQueries = useQueries({
    queries: (runs.data ?? []).map((run) => ({
      queryKey: ["actions", run.id],
      queryFn: () => api.get<Action[]>(`/runs/${run.id}/actions`),
      refetchInterval: 5000,
    })),
  });

  const all = actionQueries.flatMap((query, index) =>
    (query.data ?? []).map((action) => ({ action, run: runs.data?.[index] })),
  );

  const open = all
    .filter(({ action }) => isOpen(action))
    .sort((a, b) => a.action.created_at.localeCompare(b.action.created_at));

  // Everything that carries a decision: still in flight (approved → executing → verifying)
  // or settled. Actions that never paused for approval don't belong on this page.
  const decided = all
    .filter(({ action }) => action.approval_decision !== null && !dismissed.has(action.id))
    .sort((a, b) => a.action.created_at.localeCompare(b.action.created_at));

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-4 text-lg font-semibold">Awaiting approval</h1>

      {runs.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}

      {/* A failed load and an empty queue must not read the same: "nothing is waiting" on
          a screen that could not ask is an approval queue silently invisible. */}
      {runs.isError && (
        <p className="text-sm text-red-400">
          The runs could not be loaded — the queue may not be empty.
        </p>
      )}

      {!runs.isLoading && !runs.isError && open.length === 0 && (
        <p className="text-sm text-ink-muted">Nothing is waiting on a decision.</p>
      )}

      <ul className="space-y-3">
        {open.map(({ action, run }) => (
          <ApprovalCard key={action.id} action={action} run={run} />
        ))}
      </ul>

      {decided.length > 0 && (
        <>
          <h2 className="mt-8 mb-4 text-lg font-semibold">Decided</h2>
          <ul className="space-y-3">
            {decided.map(({ action, run }) => (
              <DecidedCard
                key={action.id}
                action={action}
                run={run}
                onDismiss={
                  TERMINAL.includes(action.state)
                    ? () => setDismissed((prev) => new Set(prev).add(action.id))
                    : undefined
                }
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
