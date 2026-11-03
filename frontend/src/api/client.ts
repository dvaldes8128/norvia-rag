import type { ApiErrorBody } from "../types/api";

const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: unknown;

  constructor(status: number, message: string, code: string | null = null, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
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

async function parseError(res: Response): Promise<{ message: string; code: string | null; detail: unknown }> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    const detail = body.detail ?? null;
    const code = body.code ?? (typeof detail === "object" && detail && "code" in detail
      ? String((detail as { code?: string }).code)
      : null);
    if (typeof body.error === "string" && body.error) {
      return { message: body.error, code, detail };
    }
    if (typeof body.detail === "string") return { message: body.detail, code, detail };
    if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      return {
        message: body.detail.map((d) => d.msg).filter(Boolean).join("; "),
        code,
        detail,
      };
    }
    if (typeof detail === "object" && detail && "message" in detail) {
      return { message: String((detail as { message: string }).message), code, detail };
    }
  } catch {
    /* ignore */
  }
  return { message: res.statusText || `HTTP ${res.status}`, code: null, detail: null };
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
    const parsed = await parseError(res);
    throw new ApiError(res.status, parsed.message, parsed.code, parsed.detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
