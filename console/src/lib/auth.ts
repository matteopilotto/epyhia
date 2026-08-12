// One place holds the access token getter, so every request goes out the same way and
// there is no second path in (FR-057).
type TokenGetter = () => Promise<string>;

let getToken: TokenGetter | null = null;

export function setTokenGetter(fn: TokenGetter) {
  getToken = fn;
}

export async function authHeaders(): Promise<HeadersInit> {
  if (!getToken) throw new Error("no access token available");
  return { Authorization: `Bearer ${await getToken()}` };
}

/**
 * The API's own namespace, in every environment. FastAPI serves this bundle from the same
 * origin, so the request is relative and there is no CORS either way — but the two cannot
 * share one path namespace, because this console's client-side routes (`/runs`,
 * `/runs/:id/cost`) are the same strings as the API's. The prefix is what keeps a reload of
 * `/runs` a page rather than JSON (epyhia/api/app.py `API_PREFIX`).
 *
 * `||` rather than `??` because `VITE_API_BASE_URL=` is an empty string, not absent, so
 * `??` would hand back the empty override instead of falling through to the default.
 */
export const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
