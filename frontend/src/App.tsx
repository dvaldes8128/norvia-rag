import { useState } from "react";
import { loadAuth, type AuthState } from "./api/client";
import { AuthBar } from "./components/AuthBar";
import { Chat } from "./components/Chat";
import { DocumentList } from "./components/DocumentList";
import { UploadPanel } from "./components/UploadPanel";
import { useJobPolling } from "./hooks/useJobPolling";

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(() => loadAuth());
  const signedIn = Boolean(auth);
  const { jobs, error, loading, refresh, upsertLocal } = useJobPolling(signedIn);

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
        </div>
        <AuthBar
          auth={auth}
          onAuth={setAuth}
          onLogout={() => setAuth(null)}
        />
      </header>

      {signedIn ? (
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
            <code>devkey-acme</code>) to upload documents and chat.
          </p>
        </section>
      )}
    </div>
  );
}
