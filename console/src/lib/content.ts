import { API_BASE, authHeaders } from "./auth";

/**
 * Artifact bytes for the elements that cannot ask for them themselves.
 *
 * `<video src>` and `<iframe src>` send no `Authorization` header, and the alternatives —
 * a token in the query string, a signed URL, a cookie session — are each the second way in
 * that FR-057 forbids (the same reasoning as `streamRunEvents` in `api.ts`). So the bytes
 * come down `fetch` with the one Bearer header, and the elements are handed a blob URL.
 */
export async function fetchArtifactBlob(artifactId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/artifacts/${artifactId}/content`, {
    headers: await authHeaders(),
  });
  if (!response.ok) throw new Error(`artifact content: ${response.status}`);
  return response.blob();
}

/** The blob URL for an artifact's bytes. Every caller owns its revoke (see `revoke`). */
export async function artifactObjectUrl(artifactId: string): Promise<string> {
  return URL.createObjectURL(await fetchArtifactBlob(artifactId));
}

/**
 * Release a blob URL. A view that unmounts without this holds the bytes in memory for the
 * life of the document — which for a video is the whole file.
 */
export function revoke(url: string | null | undefined): void {
  if (url) URL.revokeObjectURL(url);
}

/** Save a blob to disk under `filename`, the only way to name a download from script. */
export function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick rather than inline: the browser reads the URL after `click()`
  // returns, and pulling it out from under the download cancels it.
  window.setTimeout(() => revoke(url), 0);
}

/** One artifact to disk, named from its own `path` — the sensible filename of FR-006. */
export async function downloadArtifact(artifactId: string, path: string): Promise<void> {
  save(await fetchArtifactBlob(artifactId), path);
}
