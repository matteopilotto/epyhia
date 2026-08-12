import { useArtifactUrl } from "./useArtifactUrl";

export type Cut = { id: string; kind: string; path: string };

// The cut rendered for a phone, from the vertical composition (`CUTS` in
// epyhia/queue/handlers/video.py). Framed at 9:16 so the operator sees it as it will appear.
const VERTICAL = "video_vertical";

function VideoCut({ cut }: { cut: Cut }) {
  const { url, error } = useArtifactUrl(cut.id);
  const vertical = cut.kind === VERTICAL;

  return (
    <figure className={vertical ? "w-48 shrink-0" : "min-w-0 flex-1"}>
      <figcaption className="mb-1 font-mono text-xs text-ink-muted">{cut.path}</figcaption>
      <div
        className="flex items-center justify-center rounded-md border border-line bg-black"
        style={vertical ? { aspectRatio: "9 / 16" } : { aspectRatio: "16 / 9" }}
      >
        {error ? (
          <p className="p-2 text-xs text-red-300">Could not load: {error}</p>
        ) : url ? (
          <video src={url} controls className="h-full w-full" />
        ) : (
          // Visible while the bytes transfer — the view stays usable rather than freezing
          // on a large file (US2 edge case).
          <p className="p-2 text-xs text-ink-muted">Loading…</p>
        )}
      </div>
    </figure>
  );
}

/** Both cuts of the launch video, side by side, in the browser's own playback controls. */
export function VideoPlayers({ cuts }: { cuts: Cut[] }) {
  return (
    <div className="flex flex-wrap items-start gap-4">
      {cuts.map((cut) => (
        <VideoCut key={cut.id} cut={cut} />
      ))}
    </div>
  );
}
