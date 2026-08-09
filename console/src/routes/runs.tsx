import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, streamRunEvents, type ApiError, type RunEvent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type Run = {
  id: string;
  brief_id: string;
  status: string;
  brand_doc_version: number | null;
  prompt_version: string;
  spend_usd: number;
  budget_usd: number;
  alias: string;
};

const statusVariant = (status: string) =>
  status === "succeeded" ? "good" : status === "running" ? "default" : "bad";

/**
 * The brief goes in as JSON rather than through a field-by-field form.
 *
 * Not laziness: a bespoke form would have to encode the brief's shape in the console, and
 * every field it left out would become a field no client could ever supply. The payload is
 * validated server-side and comes back as itemised violations (FR-001), so this stays a
 * transport for whatever the contract currently says — and holds no client value of its own.
 */
function SubmitBrief() {
  const queryClient = useQueryClient();
  const [payload, setPayload] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (brief: unknown) => api.post<{ run_id: string }>("/briefs", brief),
    onSuccess: () => {
      setPayload("");
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  const error = submit.error as ApiError | null;

  return (
    <section className="mb-8 rounded-lg border border-line p-4">
      <h2 className="mb-2 text-sm font-semibold">Submit a brief</h2>
      <textarea
        value={payload}
        onChange={(event) => setPayload(event.target.value)}
        rows={10}
        spellCheck={false}
        placeholder="Paste the brief JSON"
        className="w-full rounded-md border border-line bg-surface-raised p-3 font-mono text-xs text-ink"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button
          disabled={submit.isPending || payload.trim() === ""}
          onClick={() => {
            setParseError(null);
            try {
              submit.mutate(JSON.parse(payload));
            } catch (caught) {
              setParseError((caught as Error).message);
            }
          }}
        >
          {submit.isPending ? "Submitting…" : "Submit"}
        </Button>
        {parseError && <span className="text-xs text-red-400">{parseError}</span>}
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-red-800 bg-red-950 p-3 text-xs">
          <p className="font-medium text-red-300">{error.error}</p>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-red-200">
            {JSON.stringify(error.detail, null, 2)}
          </pre>
        </div>
      )}
    </section>
  );
}

export function RunsRoute() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/runs") });

  return (
    <div className="mx-auto max-w-4xl">
      <SubmitBrief />

      <h2 className="mb-2 text-sm font-semibold">Runs</h2>
      {runs.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}
      <ul className="divide-y divide-line rounded-lg border border-line">
        {runs.data?.map((run) => (
          <li key={run.id} className="flex items-center gap-3 px-4 py-3 text-sm">
            <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
            <Link to="/runs/$runId" params={{ runId: run.id }} className="font-mono text-xs">
              {run.alias}
            </Link>
            <span className="ml-auto text-xs text-ink-muted">
              brand doc v{run.brand_doc_version ?? "—"} · prompts {run.prompt_version} ·{" "}
              {Number(run.spend_usd).toFixed(2)} / {Number(run.budget_usd).toFixed(2)} USD
            </span>
          </li>
        ))}
        {runs.data?.length === 0 && (
          <li className="px-4 py-3 text-sm text-ink-muted">No runs yet.</li>
        )}
      </ul>
    </div>
  );
}

function eventVariant(event: RunEvent) {
  if (event.kind === "artifact") {
    return event.data.grounding_status === "clean" ? "good" : "bad";
  }
  if (event.kind === "action") {
    const state = event.data.state;
    if (state === "succeeded") return "good";
    if (state === "awaiting_approval") return "warn";
    if (state === "failed" || state === "denied") return "bad";
  }
  return "muted";
}

function summarise(event: RunEvent): string {
  const data = event.data;
  switch (event.kind) {
    case "task":
      return `${data.kind} → ${data.state}`;
    case "action":
      return `${data.action_type} → ${data.state}`;
    case "artifact":
      return `${data.kind} (${data.grounding_status})`;
    case "agent_call":
      return `${data.agent} · ${data.model_id} · ${Number(data.cost_usd).toFixed(4)} USD`;
    default:
      return JSON.stringify(data);
  }
}

export function RunDetailRoute() {
  const { runId } = useParams({ from: "/runs/$runId" });
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.get<Run>(`/runs/${runId}`),
  });
  const [events, setEvents] = useState<RunEvent[]>([]);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    const controller = new AbortController();
    seen.current = new Set();
    setEvents([]);

    void (async () => {
      try {
        for await (const event of streamRunEvents(runId, controller.signal)) {
          // The stream replays from the beginning on every connect, so a reconnect after a
          // redeploy must not double the timeline.
          const key = `${event.kind}:${event.data.id}:${event.data.at}`;
          if (seen.current.has(key)) continue;
          seen.current.add(key);
          setEvents((current) => [...current, event]);
        }
      } catch (caught) {
        if (!controller.signal.aborted) console.error(caught);
      }
    })();

    return () => controller.abort();
  }, [runId]);

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/runs" className="text-sm text-ink-muted hover:text-ink">
          ← Runs
        </Link>
        {run.data && (
          <>
            <Badge variant={statusVariant(run.data.status)}>{run.data.status}</Badge>
            <span className="font-mono text-xs">{run.data.alias}</span>
            <Link
              to="/runs/$runId/artifacts"
              params={{ runId }}
              className="text-sm text-ink-muted hover:text-ink"
            >
              Artifacts
            </Link>
            <Link
              to="/runs/$runId/brand-doc"
              params={{ runId }}
              className="text-sm text-ink-muted hover:text-ink"
            >
              Brand doc
            </Link>
            <span className="ml-auto text-xs text-ink-muted">
              brand doc v{run.data.brand_doc_version ?? "—"} · prompts {run.data.prompt_version}
            </span>
          </>
        )}
      </header>

      <h2 className="mb-2 text-sm font-semibold">Timeline</h2>
      <ol className="divide-y divide-line rounded-lg border border-line">
        {events.map((event, index) => (
          <li key={index} className="flex items-center gap-3 px-4 py-2 text-sm">
            <Badge variant={eventVariant(event)}>{event.kind}</Badge>
            <span>{summarise(event)}</span>
            <span className="ml-auto font-mono text-[11px] text-ink-muted">
              {String(event.data.at).slice(11, 19)}
            </span>
          </li>
        ))}
        {events.length === 0 && (
          <li className="px-4 py-3 text-sm text-ink-muted">Waiting for events…</li>
        )}
      </ol>
    </div>
  );
}
