import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ApiError } from "@/lib/api";
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
        <span className="ml-auto text-xs text-ink-muted">
          {action.projected_cost_usd === null
            ? "no projected cost"
            : `${Number(action.projected_cost_usd).toFixed(2)} USD projected`}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
        <dt className="text-ink-muted">Target</dt>
        <dd className="font-mono text-xs break-all">{describeTarget(action, run)}</dd>

        {/* Showing the key is the cheapest way to make idempotency legible: on a re-run the
            same key appears and the action short-circuits (§4.4, FR-039, SC-005). */}
        <dt className="text-ink-muted">Idempotency key</dt>
        <dd className="font-mono text-xs break-all">{action.idempotency_key}</dd>
      </dl>

      <div className="mt-4 flex gap-2">
        <Button disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
          Approve
        </Button>
        <Button
          variant="destructive"
          disabled={decide.isPending}
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

      {!runs.isLoading && pending.length === 0 && (
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
