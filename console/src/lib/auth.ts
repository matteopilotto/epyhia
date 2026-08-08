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
 * Empty in production, where FastAPI serves this bundle from the same origin as the API.
 * Under `vite dev` the console is on its own port, so requests carry the `/api` prefix the
 * dev proxy strips again before forwarding (vite.config.ts) — still one origin, still no
 * CORS.
 *
 * Keyed on Vite's own dev flag rather than on `.env` alone, because Vite inlines env at
 * *build* time: a dev value left in a local `.env` would otherwise be baked into the image
 * and point the deployed console at a prefix nothing serves. `||` rather than `??` for a
 * related reason — `VITE_API_BASE_URL=` is an empty string, not absent, so `??` would hand
 * back the empty override instead of falling through to the default.
 */
export const API_BASE =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "/api" : "");
