import { useState } from "react";
import { loadAuth, type AuthState } from "./api/client";
import { AdminPanel } from "./components/AdminPanel";
import { AuthBar } from "./components/AuthBar";
import { Chat } from "./components/Chat";
import { DocumentList } from "./components/DocumentList";
import { UploadPanel } from "./components/UploadPanel";
import { useJobPolling } from "./hooks/useJobPolling";

type Mode = "tenant" | "admin";

export function App() {
  const [mode, setMode] = useState<Mode>("tenant");
  const [auth, setAuth] = useState<AuthState | null>(() => loadAuth());
  const signedIn = Boolean(auth);
  const { jobs, error, loading, refresh, upsertLocal } = useJobPolling(
    signedIn && mode === "tenant",
  );

  return (
    <div className="app">
      <header className="app__hero">
        <div>
          <h1 className="brand">
            Norvia <span>RAG</span>
          </h1>
          <p className="tagline">
            Multi-tenant policy assistant — upload PDFs, track ingestion, ask with
            verifiable citations.
          </p>
          <div className="mode-switch" role="tablist" aria-label="App mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "tenant"}
              className={`btn btn-sm ${mode === "tenant" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("tenant")}
            >
              Tenant
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "admin"}
              className={`btn btn-sm ${mode === "admin" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode("admin")}
            >
              Admin
            </button>
          </div>
        </div>
        {mode === "tenant" ? (
          <AuthBar
            auth={auth}
            onAuth={setAuth}
            onLogout={() => setAuth(null)}
          />
        ) : null}
      </header>

      {mode === "admin" ? (
        <AdminPanel />
      ) : signedIn ? (
        <div className="app__grid">
          <div className="docs-stack">
            <section className="panel" aria-labelledby="upload-heading">
              <header className="panel__head">
                <h2 id="upload-heading">Upload</h2>
              </header>
              <UploadPanel onUploaded={upsertLocal} />
            </section>
            <DocumentList
              jobs={jobs}
              loading={loading}
              error={error}
              onRefresh={() => void refresh()}
            />
          </div>
          <Chat enabled={signedIn} />
        </div>
      ) : (
        <section className="panel gate">
          <p>
            Connect with a tenant API key from <code>TENANT_API_KEYS</code> (e.g.{" "}
            <code>devkey-acme</code>) or one issued in Admin to upload documents and chat.
          </p>
        </section>
      )}
    </div>
  );
}
