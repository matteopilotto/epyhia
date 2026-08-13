import { Component, useState, type ReactNode } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { parseCopy, parseEmail, parsePosts, parseVideoProps } from "@/components/artifacts/guards";
import { CopyDoc } from "@/components/artifacts/CopyDoc";
import { EmailPreview } from "@/components/artifacts/EmailPreview";
import { PostCards } from "@/components/artifacts/PostCards";
import { SitePreview } from "@/components/artifacts/SitePreview";
import { Storyboard } from "@/components/artifacts/Storyboard";
import { VideoPlayer } from "@/components/artifacts/VideoPlayer";
import { downloadArtifact, downloadRunPack } from "@/lib/content";

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

/** One entry per deliverable kind, its revisions oldest → newest (FR-013). The last member
 * is the latest revision — what the entry shows until an operator asks for an earlier one. */
type DeliverableGroup = { kind: string; revisions: Artifact[] };

/**
 * Grouping is a presentation concern over the list response the API already returns in
 * full — no second call, no grouped API shape (research R9). Entry order follows each
 * kind's first appearance, so the page keeps the server's ordering.
 */
function groupByKind(artifacts: Artifact[]): DeliverableGroup[] {
  const groups = new Map<string, Artifact[]>();
  for (const artifact of artifacts) {
    const revisions = groups.get(artifact.kind);
    if (revisions) revisions.push(artifact);
    else groups.set(artifact.kind, [artifact]);
  }
  return [...groups].map(([kind, revisions]) => ({
    kind,
    revisions: [...revisions].sort((a, b) => a.revision - b.revision),
  }));
}

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

/**
 * Dispatch keyed on the system's closed kind vocabulary. An unknown kind or a guard
 * failure returns null, meaning raw is the only view for that artifact (FR-014).
 * `quotes` are this artifact's own violation quotes, marked inline by the renderers.
 */
function renderDeliverable(kind: string, content: string, quotes: string[]): ReactNode | null {
  switch (kind) {
    case "copy": {
      const copy = parseCopy(content);
      return copy && <CopyDoc copy={copy} quotes={quotes} />;
    }
    case "posts": {
      const posts = parsePosts(content);
      return posts && <PostCards posts={posts} quotes={quotes} />;
    }
    case "email": {
      const email = parseEmail(content);
      return email && <EmailPreview email={email} quotes={quotes} />;
    }
    case "video_props": {
      const videoProps = parseVideoProps(content);
      return videoProps && <Storyboard videoProps={videoProps} quotes={quotes} />;
    }
    default:
      return null;
  }
}

/** The quoted strings of an artifact's own violations — the only thing that may drive its
 * inline marks. A violation without a quote marks nothing (FR-012). */
function violationQuotes(violations: Violation[] | null): string[] {
  return (violations ?? [])
    .map((violation) => violation.quote)
    .filter((quote): quote is string => typeof quote === "string");
}

/**
 * A render-time throw (content the guards accepted but a renderer chokes on) must stay
 * contained to the one artifact, like a guard failure — the fallback is the same raw view.
 */
class RenderFallback extends Component<{ raw: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.raw : this.props.children;
  }
}

function ArtifactContent({ artifact, content }: { artifact: Artifact; content: string }) {
  const [showRaw, setShowRaw] = useState(false);
  const rendered = renderDeliverable(artifact.kind, content, violationQuotes(artifact.violations));
  const raw = (
    <pre className="max-h-96 overflow-auto rounded-md border border-line bg-surface-raised p-3 font-mono text-[11px] whitespace-pre-wrap">
      {content}
    </pre>
  );

  if (rendered === null) return raw;

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => setShowRaw((value) => !value)}>
          {showRaw ? "Rendered" : "Raw"}
        </Button>
      </div>
      {showRaw ? raw : <RenderFallback raw={raw}>{rendered}</RenderFallback>}
    </div>
  );
}

/**
 * Download of one artifact, named from its own `path` (FR-006). A failure is said out loud
 * — a control that silently does nothing reads as a browser that swallowed the file.
 */
function DownloadButton({ artifact }: { artifact: Artifact }) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");

  const download = async () => {
    setState("busy");
    try {
      await downloadArtifact(artifact.id, artifact.path);
      setState("idle");
    } catch {
      setState("failed");
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={state === "busy"}
      onClick={download}
      className={state === "failed" ? "border-red-800 text-red-300" : undefined}
    >
      {state === "idle" ? "Download" : state === "busy" ? "Downloading…" : "Download failed"}
    </Button>
  );
}

/**
 * The whole run in one archive (FR-008). With nothing produced yet there is nothing to
 * pack, and the control says so rather than handing back an empty file or an opaque error.
 */
function PackDownloadButton({ runId, empty }: { runId: string; empty: boolean }) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");

  const download = async () => {
    setState("busy");
    try {
      await downloadRunPack(runId);
      setState("idle");
    } catch {
      setState("failed");
    }
  };

  return (
    <div className="ml-auto flex items-center gap-2">
      {empty && <span className="text-xs text-ink-muted">Nothing produced yet to pack</span>}
      <Button
        variant="outline"
        size="sm"
        disabled={empty || state === "busy"}
        onClick={download}
        className={state === "failed" ? "border-red-800 text-red-300" : undefined}
      >
        {state === "idle"
          ? "Download pack"
          : state === "busy"
            ? "Assembling…"
            : "Pack download failed"}
      </Button>
    </div>
  );
}

/** The kinds whose bytes are the deliverable itself, fetched from the content endpoint
 * rather than read as text out of the JSON detail route. */
const MEDIA_KINDS = new Set(["site", "video", "video_vertical"]);

/**
 * One deliverable, at one revision. Everything below the selector — badge, violations,
 * inline marks, contents, download — reads the *selected* revision's own row, never
 * another member of the group's (FR-013).
 */
function DeliverableCard({ group }: { group: DeliverableGroup }) {
  const [open, setOpen] = useState(false);
  // Null means "whatever is latest", so a revision arriving under the polling refetch is
  // shown by default; picking one explicitly pins it (and un-pins if it is superseded away).
  const [pinned, setPinned] = useState<string | null>(null);

  const latest = group.revisions[group.revisions.length - 1];
  const artifact = group.revisions.find((revision) => revision.id === pinned) ?? latest;

  const flagged = artifact.grounding_status !== "clean";
  const media = MEDIA_KINDS.has(artifact.kind);

  const detail = useQuery({
    queryKey: ["artifact", artifact.id],
    queryFn: () => api.get<ArtifactDetail>(`/artifacts/${artifact.id}`),
    enabled: open && !media,
  });

  return (
    <li
      className={`rounded-lg border p-4 ${flagged ? "border-red-800" : "border-line"}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={flagged ? "bad" : "good"}>{artifact.grounding_status}</Badge>
        <span className="text-sm font-medium">{artifact.kind}</span>
        <span className="font-mono text-xs text-ink-muted">{artifact.path}</span>
        {group.revisions.length > 1 ? (
          <div className="flex items-center gap-1">
            {group.revisions.map((revision) => (
              <Button
                key={revision.id}
                variant={revision.id === artifact.id ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => setPinned(revision.id)}
              >
                rev {revision.revision}
              </Button>
            ))}
          </div>
        ) : (
          <span className="text-xs text-ink-muted">rev {artifact.revision}</span>
        )}
        <span className="ml-auto text-xs text-ink-muted">
          {artifact.content_type} · {artifact.size_bytes} bytes
        </span>
      </div>

      {artifact.violations?.length ? <Violations violations={artifact.violations} /> : null}

      <div className="mt-3 flex gap-2">
        <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide contents" : "Read contents"}
        </Button>
        <DownloadButton artifact={artifact} />
      </div>

      {open && (
        <div className="mt-3">
          {media ? (
            artifact.kind === "site" ? (
              <SitePreview artifactId={artifact.id} />
            ) : (
              <VideoPlayer cut={artifact} />
            )
          ) : (
            <>
              {detail.isLoading && <p className="text-xs text-ink-muted">Loading…</p>}
              {detail.data &&
                (detail.data.content === null ? (
                  <p className="text-xs text-ink-muted">
                    Binary artifact — {artifact.size_bytes} bytes, sha256 {artifact.sha256}.
                  </p>
                ) : (
                  <ArtifactContent artifact={artifact} content={detail.data.content} />
                ))}
            </>
          )}
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

  const groups = groupByKind(artifacts.data ?? []);
  // Counted over deliverables, not rows: a revision that was flagged and has since been
  // superseded is not something still being held.
  const flagged = groups.filter(
    (group) => group.revisions[group.revisions.length - 1].grounding_status !== "clean",
  ).length;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/runs/$runId" params={{ runId }} className="text-sm text-ink-muted hover:text-ink">
          ← Timeline
        </Link>
        <h1 className="text-sm font-semibold">Artifacts</h1>
        {flagged > 0 && <Badge variant="bad">{flagged} held</Badge>}
        {artifacts.data && (
          <PackDownloadButton runId={runId} empty={artifacts.data.length === 0} />
        )}
      </header>

      {artifacts.isLoading && <p className="text-sm text-ink-muted">Loading…</p>}

      <ul className="space-y-3">
        {groups.map((group) => (
          <DeliverableCard key={group.kind} group={group} />
        ))}
        {artifacts.data?.length === 0 && (
          <li className="text-sm text-ink-muted">This run has produced nothing yet.</li>
        )}
      </ul>
    </div>
  );
}
