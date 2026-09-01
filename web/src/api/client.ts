/**
 * Single API client. The token lives in localStorage on the browser side only; it is sent
 * as an Authorization header and NEVER as a query parameter, because URLs land in server
 * logs, proxies and browser history. The SSE stream uses a single-use ticket instead.
 */

const TOKEN_KEY = "dgxctl.token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(value: string): void {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private windows and blocked site data both land here; the app still works */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  const type = resp.headers.get("content-type") ?? "";
  return (type.includes("json") ? await resp.json() : await resp.text()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  /** Obtain a short-lived single-use ticket for EventSource, which cannot set headers. */
  streamUrl: async (): Promise<string> => {
    const { ticket } = await request<{ ticket: string }>("/api/stream-ticket", {
      method: "POST",
    });
    return `/api/stream?ticket=${encodeURIComponent(ticket)}`;
  },
};
