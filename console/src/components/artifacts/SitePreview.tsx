import { useState } from "react";
import { Button } from "@/components/ui/button";
import { revoke } from "@/lib/content";
import { useArtifactUrl } from "./useArtifactUrl";

// A container width, not a device: what the operator is checking is how the generated
// layout reflows, so the two ends of the range are enough.
const WIDTHS = { desktop: "100%", mobile: "390px" } as const;

type Width = keyof typeof WIDTHS;

/**
 * The wrapper document behind open-in-new-tab.
 *
 * Static, console-authored, and the reason this is not simply the site's own blob URL: a
 * blob document opened top-level inherits the console's origin, so the generated site's
 * script would run where the operator's session lives. Embedding it in a sandboxed frame
 * here keeps the opaque origin identical in both viewing modes (FR-004, research R2).
 */
function wrapper(siteUrl: string): string {
  return `<!doctype html>
<meta charset="utf-8">
<title>Site preview</title>
<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>
<iframe sandbox="allow-scripts" src="${siteUrl}"></iframe>`;
}

/**
 * The `site` artifact rendered in place. `sandbox="allow-scripts"` deliberately WITHOUT
 * `allow-same-origin`: the site's one vanilla JS file runs, but the document has an opaque
 * origin and can reach neither the console's origin nor its storage (FR-004).
 */
export function SitePreview({ artifactId }: { artifactId: string }) {
  const { url, error } = useArtifactUrl(artifactId);
  const [width, setWidth] = useState<Width>("desktop");

  const openInNewTab = () => {
    if (!url) return;
    const wrapperUrl = URL.createObjectURL(new Blob([wrapper(url)], { type: "text/html" }));
    window.open(wrapperUrl, "_blank", "noopener");
    // The new tab reads the URL after `open` returns; revoking inline would leave it blank.
    window.setTimeout(() => revoke(wrapperUrl), 10_000);
  };

  if (error) return <p className="text-xs text-red-300">Could not load the site: {error}</p>;
  if (!url) return <p className="text-xs text-ink-muted">Loading site…</p>;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {(Object.keys(WIDTHS) as Width[]).map((option) => (
          <Button
            key={option}
            variant={option === width ? "default" : "outline"}
            size="sm"
            onClick={() => setWidth(option)}
          >
            {option}
          </Button>
        ))}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={openInNewTab}>
          Open in new tab
        </Button>
      </div>
      <div className="mx-auto" style={{ maxWidth: WIDTHS[width] }}>
        <iframe
          title="Site preview"
          src={url}
          sandbox="allow-scripts"
          className="h-[600px] w-full rounded-md border border-line bg-white"
        />
      </div>
    </div>
  );
}
