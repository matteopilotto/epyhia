import { API_BASE, authHeaders } from "./auth";

export type ApiError = { error: string; detail: unknown };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(await authHeaders()), ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    throw (await response.json().catch(() => ({
      error: "request_failed",
      detail: response.statusText,
    }))) as ApiError;
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: body === undefined ? {} : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
};

export type RunEvent = { kind: string; data: Record<string, unknown> };

/**
 * The run timeline, over `fetch` + `ReadableStream` rather than `EventSource`.
 *
 * `EventSource` cannot send an `Authorization` header, and the alternatives are a JWT in the
 * query string — which leaks into access and proxy logs — or a parallel cookie session,
 * which would be the second way in that FR-057 forbids (DESIGN.md §10).
 */
export async function* streamRunEvents(
  runId: string,
  signal?: AbortSignal,
): AsyncGenerator<RunEvent> {
  const response = await fetch(`${API_BASE}/runs/${runId}/events`, {
    headers: { ...(await authHeaders()), accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`event stream: ${response.status}`);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;

    // Frames are separated by a blank line; a chunk boundary can fall anywhere, so the
    // remainder stays in the buffer until its terminator arrives.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let kind = "message";
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) kind = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (data.length) yield { kind, data: JSON.parse(data.join("\n")) };
    }
  }
}
