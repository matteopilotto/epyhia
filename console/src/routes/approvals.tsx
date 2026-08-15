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
};

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

export function ApprovalsRoute() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/runs") });

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

  const pending = actionQueries
    .flatMap((query, index) =>
      (query.data ?? []).map((action) => ({ action, run: runs.data?.[index] })),
    )
    .filter(({ action }) => action.state === "awaiting_approval")
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

      {!runs.isLoading && !runs.isError && pending.length === 0 && (
        <p className="text-sm text-ink-muted">Nothing is waiting on a decision.</p>
      )}

      <ul className="space-y-3">
        {pending.map(({ action, run }) => (
          <ApprovalCard key={action.id} action={action} run={run} />
        ))}
      </ul>
    </div>
  );
}
