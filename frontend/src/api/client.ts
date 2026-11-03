import type { ApiErrorBody } from "../types/api";

const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface AuthState {
  apiKey: string;
  accessToken: string;
  tenantId: string;
}

let auth: AuthState | null = null;

const STORAGE_KEY = "norvia.auth";

export function loadAuth(): AuthState | null {
  if (auth) return auth;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    auth = JSON.parse(raw) as AuthState;
    return auth;
  } catch {
    return null;
  }
}

export function saveAuth(next: AuthState): void {
  auth = next;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export function clearAuth(): void {
  auth = null;
  sessionStorage.removeItem(STORAGE_KEY);
}

function authHeaders(): HeadersInit {
  const current = loadAuth();
  if (!current) return {};
  // Prefer JWT; fall back to API key so requests still work mid-session.
  if (current.accessToken) {
    return { Authorization: `Bearer ${current.accessToken}` };
  }
  return { "X-API-Key": current.apiKey };
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      return body.detail.map((d) => d.msg).filter(Boolean).join("; ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  opts: { auth?: boolean; json?: unknown } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (opts.auth !== false) {
    const extra = authHeaders();
    for (const [k, v] of Object.entries(extra)) {
      headers.set(k, v);
    }
  }
  let body = init.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body });
  if (!res.ok) {
    throw new ApiError(res.status, await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
