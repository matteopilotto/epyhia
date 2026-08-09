import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

type AgentCall = {
  id: string;
  agent: string;
  model_id: string;
  tier: string;
  input_tokens: number;
  output_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  latency_ms: number;
  cache_hit: boolean;
  created_at: string;
};

type RunCost = {
  run_id: string;
  status: string;
  budget_usd: number;
  total_usd: number;
  calls: AgentCall[];
};

const usd = (value: number) => Number(value).toFixed(4);

/**
 * The per-call table and the one combined total, and nothing else.
 *
 * `total_usd` covers model spend and gate-action spend together, so it deliberately does not
 * add up to the rows below it: two totals would be the two separate views FR-052 exists to
 * prevent. Design effort belongs in the generated client site, not here.
 */
export function CostRoute() {
  const { runId } = useParams({ from: "/runs/$runId/cost" });
  const cost = useQuery({
    queryKey: ["cost", runId],
    queryFn: () => api.get<RunCost>(`/runs/${runId}/cost`),
    refetchInterval: 5000,
  });

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/runs/$runId" params={{ runId }} className="text-sm text-ink-muted hover:text-ink">
          ← Timeline
        </Link>
        <h1 className="text-sm font-semibold">Cost</h1>
        {cost.data && (
          <>
            {cost.data.status === "halted_budget" && <Badge variant="bad">halted</Badge>}
            <span className="ml-auto text-xs text-ink-muted">
              {usd(cost.data.total_usd)} / {Number(cost.data.budget_usd).toFixed(2)} USD —
              model and action spend, one total against one budget
            </span>
          </>
        )}
      </header>

      {cost.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <thead className="text-ink-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-medium">Agent</th>
              <th className="px-3 py-2 font-medium">Model</th>
              <th className="px-3 py-2 font-medium">Tier</th>
              <th className="px-3 py-2 text-right font-medium">In</th>
              <th className="px-3 py-2 text-right font-medium">Out</th>
              <th className="px-3 py-2 text-right font-medium">Cache w</th>
              <th className="px-3 py-2 text-right font-medium">Cache r</th>
              <th className="px-3 py-2 text-right font-medium">USD</th>
              <th className="px-3 py-2 text-right font-medium">ms</th>
            </tr>
          </thead>
          <tbody>
            {cost.data?.calls.map((call) => (
              <tr key={call.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2">{call.agent}</td>
                <td className="px-3 py-2 font-mono">{call.model_id}</td>
                <td className="px-3 py-2">
                  <Badge variant="muted">{call.tier}</Badge>
                </td>
                <td className="px-3 py-2 text-right font-mono">{call.input_tokens}</td>
                <td className="px-3 py-2 text-right font-mono">{call.output_tokens}</td>
                <td className="px-3 py-2 text-right font-mono">{call.cache_write_tokens}</td>
                <td className="px-3 py-2 text-right font-mono">{call.cache_read_tokens}</td>
                <td className="px-3 py-2 text-right font-mono">{usd(call.cost_usd)}</td>
                <td className="px-3 py-2 text-right font-mono">{call.latency_ms}</td>
              </tr>
            ))}
            {cost.data?.calls.length === 0 && (
              <tr>
                <td className="px-3 py-3 text-ink-muted" colSpan={9}>
                  No model calls yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
