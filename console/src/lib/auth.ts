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

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
