import type {
  AdminQueueSnapshot,
  AdminTelemetrySnapshot,
  AdminTenantCreated,
  AdminTenantKeyIssued,
  AdminTenantOut,
} from "../types/api";

const API_BASE = "/api";
const STORAGE_KEY = "norvia.admin";

export function loadAdminKey(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function saveAdminKey(key: string): void {
  sessionStorage.setItem(STORAGE_KEY, key);
}

export function clearAdminKey(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

async function adminFetch<T>(path: string, init: RequestInit = {}, key?: string): Promise<T> {
  const adminKey = key ?? loadAdminKey();
  if (!adminKey) throw new Error("Admin key required");
  const headers = new Headers(init.headers);
  headers.set("X-Admin-Key", adminKey);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string; error?: string };
      if (typeof body.detail === "string") message = body.detail;
      else if (typeof body.error === "string") message = body.error;
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function listAdminTenants(): Promise<AdminTenantOut[]> {
  return adminFetch("/admin/tenants");
}

export function createAdminTenant(body: {
  id: string;
  name?: string;
  key_label?: string;
}): Promise<AdminTenantCreated> {
  return adminFetch("/admin/tenants", { method: "POST", body: JSON.stringify(body) });
}

export function issueAdminTenantKey(
  tenantId: string,
  label = "default",
): Promise<AdminTenantKeyIssued> {
  return adminFetch(`/admin/tenants/${encodeURIComponent(tenantId)}/keys`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function getAdminQueues(): Promise<AdminQueueSnapshot> {
  return adminFetch("/admin/queues");
}

export function getAdminTelemetry(): Promise<AdminTelemetrySnapshot> {
  return adminFetch("/admin/telemetry");
}

export async function verifyAdminKey(key: string): Promise<void> {
  await adminFetch("/admin/telemetry", {}, key);
  saveAdminKey(key);
}
