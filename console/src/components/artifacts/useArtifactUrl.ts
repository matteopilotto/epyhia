import { useEffect, useState } from "react";
import { artifactObjectUrl, revoke } from "@/lib/content";

/**
 * The blob URL for one artifact's bytes, fetched asynchronously so a large video never
 * freezes the view while it transfers (US2 edge case), and revoked on unmount so the bytes
 * do not outlive the component that asked for them.
 */
export function useArtifactUrl(artifactId: string): { url: string | null; error: string | null } {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let created: string | null = null;

    setUrl(null);
    setError(null);
    artifactObjectUrl(artifactId)
      .then((value) => {
        created = value;
        // Unmounted (or re-keyed) while the bytes were in flight: nobody will revoke this
        // one but us.
        if (live) setUrl(value);
        else revoke(value);
      })
      .catch((cause) => {
        if (live) setError(cause instanceof Error ? cause.message : String(cause));
      });

    return () => {
      live = false;
      revoke(created);
    };
  }, [artifactId]);

  return { url, error };
}
