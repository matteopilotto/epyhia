import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { useArtifactUrl } from "./useArtifactUrl";

export type Cut = { id: string; kind: string; path: string };

// Safari's prefixed spelling. Named rather than cast through `any` so the fallback is the
// only untyped thing here, not the element.
type FullscreenVideo = HTMLVideoElement & { webkitRequestFullscreen?: () => void };

// The cut rendered for a phone, from the vertical composition (`CUTS` in
// epyhia/queue/handlers/video.py). Framed at 9:16 so the operator sees it as it will appear.
const VERTICAL = "video_vertical";

/**
 * One rendered cut in the browser's own playback controls, framed at the aspect it was
 * rendered for. Each cut is its own artifact and so plays in its own entry — showing the
 * vertical cut again beside the horizontal one would be the same file in two places.
 */
export function VideoPlayer({ cut }: { cut: Cut }) {
  const { url, error } = useArtifactUrl(cut.id);
  const video = useRef<FullscreenVideo>(null);
  const vertical = cut.kind === VERTICAL;

  // The native control bar carries its own fullscreen button, but the browser hides it when
  // the player is narrow — which is exactly the vertical cut. An explicit control is the one
  // that is there at every size.
  const fullscreen = () => {
    const element = video.current;
    if (!element) return;
    if (element.requestFullscreen) void element.requestFullscreen();
    else element.webkitRequestFullscreen?.();
  };

  return (
    <figure className={vertical ? "w-80 max-w-full" : "w-full"}>
      <figcaption className="mb-1 flex items-center gap-2 font-mono text-xs text-ink-muted">
        {cut.path}
        {url && document.fullscreenEnabled && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={fullscreen}>
            Fullscreen
          </Button>
        )}
      </figcaption>
      <div
        className="flex items-center justify-center rounded-md border border-line bg-black"
        style={vertical ? { aspectRatio: "9 / 16" } : { aspectRatio: "16 / 9" }}
      >
        {error ? (
          <p className="p-2 text-xs text-red-300">Could not load: {error}</p>
        ) : url ? (
          <video ref={video} src={url} controls className="h-full w-full" />
        ) : (
          // Visible while the bytes transfer — the view stays usable rather than freezing
          // on a large file (US2 edge case).
          <p className="p-2 text-xs text-ink-muted">Loading…</p>
        )}
      </div>
    </figure>
  );
}
