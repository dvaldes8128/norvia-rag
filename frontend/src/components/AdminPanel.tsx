import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  clearAdminKey,
  createAdminTenant,
  getAdminQueues,
  getAdminTelemetry,
  issueAdminTenantKey,
  listAdminTenants,
  loadAdminKey,
  verifyAdminKey,
} from "../api/admin";
import type {
  AdminQueueSnapshot,
  AdminTelemetrySnapshot,
  AdminTenantOut,
} from "../types/api";

type Tab = "tenants" | "queues" | "telemetry";

export function AdminPanel() {
  const [adminKey, setAdminKey] = useState<string | null>(() => loadAdminKey());
  const [keyInput, setKeyInput] = useState("");
  const [tab, setTab] = useState<Tab>("tenants");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [tenants, setTenants] = useState<AdminTenantOut[]>([]);
  const [queues, setQueues] = useState<AdminQueueSnapshot | null>(null);
  const [telemetry, setTelemetry] = useState<AdminTelemetrySnapshot | null>(null);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [issuedKey, setIssuedKey] = useState<string | null>(null);

  const refresh = useCallback(async (active: Tab) => {
    setError(null);
    setBusy(true);
    try {
      if (active === "tenants") setTenants(await listAdminTenants());
      if (active === "queues") setQueues(await getAdminQueues());
      if (active === "telemetry") setTelemetry(await getAdminTelemetry());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (adminKey) void refresh(tab);
  }, [adminKey, tab, refresh]);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    const key = keyInput.trim();
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      await verifyAdminKey(key);
      setAdminKey(key);
      setKeyInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Admin auth failed");
    } finally {
      setBusy(false);
    }
  }

  function handleLogout() {
    clearAdminKey();
    setAdminKey(null);
    setTenants([]);
    setQueues(null);
    setTelemetry(null);
    setIssuedKey(null);
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newId.trim()) return;
    setBusy(true);
    setError(null);
    setIssuedKey(null);
    try {
      const created = await createAdminTenant({
        id: newId.trim(),
        name: newName.trim() || undefined,
      });
      setIssuedKey(created.api_key);
      setNewId("");
      setNewName("");
      setTenants(await listAdminTenants());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleIssueKey(tenantId: string) {
    setBusy(true);
    setError(null);
    try {
      const issued = await issueAdminTenantKey(tenantId);
      setIssuedKey(issued.api_key);
      setTenants(await listAdminTenants());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Issue key failed");
    } finally {
      setBusy(false);
    }
  }

  if (!adminKey) {
    return (
      <section className="panel gate admin-gate">
        <h2>Admin</h2>
        <p>
          Paste the platform <code>ADMIN_API_KEY</code> to manage tenants, queues, and
          operational telemetry.
        </p>
        <form className="auth-bar" onSubmit={(e) => void handleLogin(e)}>
          <label className="sr-only" htmlFor="admin-key">
            Admin API key
          </label>
          <input
            id="admin-key"
            type="password"
            autoComplete="off"
            placeholder="ADMIN_API_KEY"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            disabled={busy}
          />
          <button type="submit" className="btn btn-primary" disabled={busy || !keyInput.trim()}>
            {busy ? "Checking…" : "Enter admin"}
          </button>
        </form>
        {error ? <p className="form-error">{error}</p> : null}
      </section>
    );
  }

  return (
    <div className="admin">
      <div className="admin__toolbar">
        <nav className="admin__tabs" aria-label="Admin sections">
          {(["tenants", "queues", "telemetry"] as Tab[]).map((id) => (
            <button
              key={id}
              type="button"
              className={`btn btn-sm ${tab === id ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab(id)}
            >
              {id === "tenants" ? "Tenants" : id === "queues" ? "Queues" : "Telemetry"}
            </button>
          ))}
        </nav>
        <div className="admin__actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => void refresh(tab)}
            disabled={busy}
          >
            Refresh
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleLogout}>
            Exit admin
          </button>
        </div>
      </div>

      {error ? <p className="form-error">{error}</p> : null}

      {issuedKey ? (
        <div className="confirm-box" role="status">
          <p className="confirm-box__title">New API key (copy now — shown once)</p>
          <code className="admin__secret">{issuedKey}</code>
          <div className="confirm-box__actions">
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void navigator.clipboard.writeText(issuedKey)}
            >
              Copy
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setIssuedKey(null)}>
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {tab === "tenants" ? (
        <div className="admin__grid">
          <section className="panel" aria-labelledby="create-tenant-h">
            <header className="panel__head">
              <h2 id="create-tenant-h">Create tenant</h2>
            </header>
            <form className="admin__form" onSubmit={(e) => void handleCreate(e)}>
              <label>
                Tenant id
                <input
                  value={newId}
                  onChange={(e) => setNewId(e.target.value)}
                  placeholder="contoso"
                  pattern="[a-z0-9][a-z0-9_-]*"
                  required
                  disabled={busy}
                />
              </label>
              <label>
                Display name
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Contoso Corp"
                  disabled={busy}
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={busy || !newId.trim()}>
                Create + issue key
              </button>
            </form>
          </section>

          <section className="panel" aria-labelledby="tenant-list-h">
            <header className="panel__head">
              <h2 id="tenant-list-h">Tenants</h2>
              <p className="panel__sub">{tenants.length} total</p>
            </header>
            {tenants.length === 0 ? (
              <p className="empty">{busy ? "Loading…" : "No tenants in the database yet."}</p>
            ) : (
              <ul className="job-list">
                {tenants.map((t) => (
                  <li key={t.id} className="job-row">
                    <div className="job-row__main">
                      <span className="job-row__name">
                        {t.name} <span className="admin__muted">({t.id})</span>
                      </span>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => void handleIssueKey(t.id)}
                        disabled={busy}
                      >
                        New key
                      </button>
                    </div>
                    <div className="job-row__meta">
                      <span>{t.document_count} docs</span>
                      <span>{t.job_count} jobs</span>
                      {t.env_backed ? <span>env keys</span> : null}
                      <span>
                        prefixes:{" "}
                        {t.api_key_prefixes.length
                          ? t.api_key_prefixes.join(", ")
                          : "—"}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}

      {tab === "queues" && queues ? (
        <section className="panel">
          <header className="panel__head">
            <h2>Ingestion queues</h2>
            <p className="panel__sub">
              {queues.worker_count} worker{queues.worker_count === 1 ? "" : "s"} · broker depth{" "}
              {queues.broker_queue_depth ?? "n/a"}
            </p>
          </header>
          <dl className="admin__stats">
            {Object.entries(queues.jobs_by_status).map(([status, count]) => (
              <div key={status}>
                <dt>{status}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
          <p className="panel__sub">
            Active tasks: {queues.active_tasks.length} · reserved: {queues.reserved_tasks.length} ·
            scheduled: {queues.scheduled_tasks.length}
          </p>
          {queues.workers.length ? (
            <ul className="admin__workers">
              {queues.workers.map((w) => (
                <li key={w}>
                  <code>{w}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">No Celery workers responded to inspect (is the worker up?).</p>
          )}
        </section>
      ) : null}

      {tab === "telemetry" && telemetry ? (
        <section className="panel">
          <header className="panel__head">
            <h2>Operational telemetry</h2>
            <p className="panel__sub">{telemetry.service_name}</p>
          </header>
          <dl className="admin__stats">
            <div>
              <dt>Traces</dt>
              <dd>{telemetry.traces_exporter}</dd>
            </div>
            <div>
              <dt>OTLP</dt>
              <dd>{telemetry.otlp_endpoint_configured ? "configured" : "off"}</dd>
            </div>
            <div>
              <dt>LLM</dt>
              <dd>{telemetry.llm_provider}</dd>
            </div>
            <div>
              <dt>Embeddings</dt>
              <dd>{telemetry.embeddings_provider}</dd>
            </div>
            <div>
              <dt>Tenants</dt>
              <dd>{telemetry.tenant_count}</dd>
            </div>
            <div>
              <dt>Documents</dt>
              <dd>{telemetry.document_count}</dd>
            </div>
            <div>
              <dt>Chunks</dt>
              <dd>{telemetry.chunk_count}</dd>
            </div>
            <div>
              <dt>Workers</dt>
              <dd>{telemetry.worker_count}</dd>
            </div>
          </dl>
          <dl className="admin__stats">
            {Object.entries(telemetry.jobs_by_status).map(([status, count]) => (
              <div key={status}>
                <dt>jobs · {status}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
          <p className="form-hint">{telemetry.note}</p>
          {telemetry.recent_failed_jobs.length ? (
            <>
              <h3 className="admin__subh">Recent failures</h3>
              <ul className="job-list">
                {telemetry.recent_failed_jobs.map((j) => (
                  <li key={j.job_id} className="job-row">
                    <div className="job-row__main">
                      <span className="job-row__name">{j.tenant_id}</span>
                      <span className="status status--fail">failed</span>
                    </div>
                    <div className="job-row__meta">
                      <span>{j.job_id.slice(0, 8)}…</span>
                      {j.error ? <span className="job-row__err">{j.error}</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="empty">No recent failed jobs.</p>
          )}
        </section>
      ) : null}
    </div>
  );
}
