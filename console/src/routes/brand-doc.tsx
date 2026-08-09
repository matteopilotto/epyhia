import { useEffect, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type BrandDoc = {
  id: string;
  brief_id: string;
  version: number;
  doc: Record<string, unknown>;
  authored_by: string;
  created_at: string;
};

type Change = { path: string; from: unknown; to: unknown };
type Diff = { brief_id: string; from: number; to: number; changes: Change[] };

/**
 * Rendered as raw JSON, and diffed by dotted path. Nothing here knows the name or meaning of
 * a single brand doc field, so no client value — a business name, a price, a palette entry —
 * can reach this file (Principle I). The document is the client data; this is the editor.
 */
function value(raw: unknown) {
  return raw === undefined ? "—" : JSON.stringify(raw);
}

function Changes({ diff }: { diff: Diff }) {
  if (diff.changes.length === 0) {
    return (
      <p className="text-xs text-ink-muted">
        v{diff.from} and v{diff.to} are identical.
      </p>
    );
  }
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-ink-muted">
        <tr>
          <th className="py-1 pr-3 font-normal">field</th>
          <th className="py-1 pr-3 font-normal">v{diff.from}</th>
          <th className="py-1 font-normal">v{diff.to}</th>
        </tr>
      </thead>
      <tbody className="font-mono">
        {diff.changes.map((change) => (
          <tr key={change.path} className="border-t border-line align-top">
            <td className="py-1 pr-3 break-all">{change.path}</td>
            <td className="py-1 pr-3 break-all text-ink-muted">{value(change.from)}</td>
            <td className="py-1 break-all">{value(change.to)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BrandDocRoute() {
  const { runId } = useParams({ from: "/runs/$runId/brand-doc" });
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = useQuery({
    queryKey: ["brand-doc", runId],
    queryFn: () => api.get<BrandDoc>(`/runs/${runId}/brand-doc`),
  });

  // The editor starts from whatever version the run is pointed at, and is left alone after
  // that so a background refetch cannot discard an operator's half-finished edit.
  useEffect(() => {
    if (current.data && draft === null) {
      setDraft(JSON.stringify(current.data.doc, null, 2));
    }
  }, [current.data, draft]);

  const versions = useQuery({
    queryKey: ["brand-docs", current.data?.brief_id],
    queryFn: () => api.get<BrandDoc[]>(`/briefs/${current.data!.brief_id}/brand-docs`),
    enabled: current.data !== undefined,
  });

  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const pair = versions.data ?? [];
  const fromVersion = from ?? pair.at(-2)?.version ?? null;
  const toVersion = to ?? pair.at(-1)?.version ?? null;

  const diff = useQuery({
    queryKey: ["brand-doc-diff", current.data?.brief_id, fromVersion, toVersion],
    queryFn: () =>
      api.get<Diff>(
        `/briefs/${current.data!.brief_id}/brand-docs/diff?from=${fromVersion}&to=${toVersion}`,
      ),
    enabled:
      current.data !== undefined &&
      fromVersion !== null &&
      toVersion !== null &&
      fromVersion !== toVersion,
  });

  /**
   * A save inserts version + 1 and never updates in place (FR-012), so the version the first
   * publication was built from stays readable beside the edit. Re-running the run against
   * the new version is a different deploy key, and therefore a genuine second publication.
   */
  const save = useMutation({
    mutationFn: (doc: unknown) => api.put<BrandDoc>(`/runs/${runId}/brand-doc`, doc),
    onSuccess: (saved) => {
      setError(null);
      setFrom(saved.version - 1);
      setTo(saved.version);
      queryClient.invalidateQueries({ queryKey: ["brand-doc", runId] });
      queryClient.invalidateQueries({ queryKey: ["brand-docs", saved.brief_id] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
    onError: (failure: ApiError) => setError(JSON.stringify(failure.detail, null, 2)),
  });

  function onSave() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft ?? "");
    } catch (failure) {
      setError(String(failure));
      return;
    }
    save.mutate(parsed);
  }

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <Link to="/runs/$runId" params={{ runId }} className="text-sm text-ink-muted hover:text-ink">
          ← Timeline
        </Link>
        <h1 className="text-sm font-semibold">Brand doc</h1>
        {current.data && <Badge variant="good">v{current.data.version}</Badge>}
        {current.data && (
          <span className="text-xs text-ink-muted">by {current.data.authored_by}</span>
        )}
      </header>

      {current.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}
      {current.isError && (
        <p className="text-sm text-ink-muted">This run has no brand doc yet.</p>
      )}

      {draft !== null && (
        <>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={false}
            className="h-96 w-full rounded-md border border-line bg-surface-raised p-3 font-mono text-[11px]"
          />
          <div className="mt-3 flex items-center gap-3">
            <Button size="sm" onClick={onSave} disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save as new version"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDraft(JSON.stringify(current.data?.doc, null, 2))}
            >
              Revert
            </Button>
            <span className="text-xs text-ink-muted">
              Saving inserts a new version; it never overwrites the one already published.
            </span>
          </div>
        </>
      )}

      {error && (
        <pre className="mt-3 overflow-x-auto rounded-md border border-red-800 bg-red-950 p-3 text-[11px] text-red-200 whitespace-pre-wrap">
          {error}
        </pre>
      )}

      {pair.length > 1 && (
        <section className="mt-8">
          <div className="mb-2 flex items-center gap-3">
            <h2 className="text-sm font-semibold">Diff</h2>
            <select
              value={fromVersion ?? ""}
              onChange={(event) => setFrom(Number(event.target.value))}
              className="rounded-md border border-line bg-surface-raised px-2 py-1 text-xs"
            >
              {pair.map((row) => (
                <option key={row.id} value={row.version}>
                  v{row.version}
                </option>
              ))}
            </select>
            <span className="text-xs text-ink-muted">→</span>
            <select
              value={toVersion ?? ""}
              onChange={(event) => setTo(Number(event.target.value))}
              className="rounded-md border border-line bg-surface-raised px-2 py-1 text-xs"
            >
              {pair.map((row) => (
                <option key={row.id} value={row.version}>
                  v{row.version}
                </option>
              ))}
            </select>
          </div>
          {diff.data && <Changes diff={diff.data} />}
        </section>
      )}
    </div>
  );
}
