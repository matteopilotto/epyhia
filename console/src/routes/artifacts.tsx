import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Violation = { kind?: string; quote?: string; why?: string; [key: string]: unknown };

type Artifact = {
  id: string;
  kind: string;
  path: string;
  content_type: string;
  sha256: string;
  size_bytes: number;
  grounding_status: string;
  violations: Violation[] | null;
  revision: number;
  created_at: string;
};

type ArtifactDetail = Artifact & { content: string | null };

/**
 * A flagged artifact is rendered *with* what is wrong with it, never hidden and never
 * quietly dropped (FR-024). The remedy is to correct the brief or the brand doc and re-run,
 * so everything here is read-only — there is no edit control, deliberately.
 */
function Violations({ violations }: { violations: Violation[] }) {
  return (
    <ul className="mt-3 space-y-2">
      {violations.map((violation, index) => (
        <li key={index} className="rounded-md border border-red-800 bg-red-950 p-3 text-xs">
          <div className="flex items-center gap-2">
            <Badge variant="bad">{violation.kind ?? "violation"}</Badge>
            {violation.quote !== undefined && (
              <span className="font-mono text-red-200 break-all">{violation.quote}</span>
            )}
          </div>
          {violation.why && <p className="mt-1 text-red-300">{violation.why}</p>}
          {violation.kind === undefined && violation.why === undefined && (
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-red-200">
              {JSON.stringify(violation, null, 2)}
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const [open, setOpen] = useState(false);
  const flagged = artifact.grounding_status !== "clean";

  const detail = useQuery({
    queryKey: ["artifact", artifact.id],
    queryFn: () => api.get<ArtifactDetail>(`/artifacts/${artifact.id}`),
    enabled: open,
  });

  return (
    <li
      className={`rounded-lg border p-4 ${flagged ? "border-red-800" : "border-line"}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={flagged ? "bad" : "good"}>{artifact.grounding_status}</Badge>
        <span className="text-sm font-medium">{artifact.kind}</span>
        <span className="font-mono text-xs text-ink-muted">{artifact.path}</span>
        <span className="text-xs text-ink-muted">rev {artifact.revision}</span>
        <span className="ml-auto text-xs text-ink-muted">
          {artifact.content_type} · {artifact.size_bytes} bytes
        </span>
      </div>

      {artifact.violations?.length ? <Violations violations={artifact.violations} /> : null}

      <div className="mt-3">
        <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide contents" : "Read contents"}
        </Button>
      </div>

      {open && (
        <div className="mt-3">
          {detail.isLoading && <p className="text-xs text-ink-muted">Loading…</p>}
          {detail.data &&
            (detail.data.content === null ? (
              <p className="text-xs text-ink-muted">
                Binary artifact — {artifact.size_bytes} bytes, sha256 {artifact.sha256}.
              </p>
            ) : (
              <pre className="max-h-96 overflow-auto rounded-md border border-line bg-surface-raised p-3 font-mono text-[11px] whitespace-pre-wrap">
                {detail.data.content}
              </pre>
            ))}
        </div>
      )}
    </li>
  );
}

export function ArtifactsRoute() {
  const { runId } = useParams({ from: "/runs/$runId/artifacts" });
  const artifacts = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => api.get<Artifact[]>(`/runs/${runId}/artifacts`),
    refetchInterval: 5000,
  });

  const flagged = (artifacts.data ?? []).filter((a) => a.grounding_status !== "clean").length;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/runs/$runId" params={{ runId }} className="text-sm text-ink-muted hover:text-ink">
          ← Timeline
        </Link>
        <h1 className="text-sm font-semibold">Artifacts</h1>
        {flagged > 0 && <Badge variant="bad">{flagged} held</Badge>}
      </header>

      {artifacts.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}

      <ul className="space-y-3">
        {artifacts.data?.map((artifact) => (
          <ArtifactCard key={artifact.id} artifact={artifact} />
        ))}
        {artifacts.data?.length === 0 && (
          <li className="text-sm text-ink-muted">This run has produced nothing yet.</li>
        )}
      </ul>
    </div>
  );
}
