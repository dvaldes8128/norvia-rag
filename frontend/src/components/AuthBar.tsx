import { FormEvent, useState } from "react";
import { clearAuth, type AuthState } from "../api/client";
import { exchangeToken } from "../api/endpoints";

interface Props {
  auth: AuthState | null;
  onAuth: (auth: AuthState) => void;
  onLogout: () => void;
}

export function AuthBar({ auth, onAuth, onLogout }: Props) {
  const [apiKey, setApiKey] = useState(auth?.apiKey ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const key = apiKey.trim();
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      onAuth(await exchangeToken(key));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  function handleLogout() {
    clearAuth();
    setApiKey("");
    onLogout();
  }

  if (auth) {
    return (
      <div className="auth-bar auth-bar--signed">
        <span className="tenant-pill" title="Authenticated tenant">
          tenant · {auth.tenantId}
        </span>
        <button type="button" className="btn btn-ghost" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    );
  }

  return (
    <form className="auth-bar" onSubmit={(e) => void handleSubmit(e)}>
      <label className="sr-only" htmlFor="api-key">
        Tenant API key
      </label>
      <input
        id="api-key"
        type="password"
        autoComplete="off"
        placeholder="Tenant API key (e.g. devkey-acme)"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        disabled={busy}
      />
      <button type="submit" className="btn btn-primary" disabled={busy || !apiKey.trim()}>
        {busy ? "Signing in…" : "Connect"}
      </button>
      {error ? <p className="form-error">{error}</p> : null}
    </form>
  );
}
