import { useState } from "react";
import { deleteDocument } from "../api/endpoints";
import type { JobStatusResponse } from "../types/api";

interface Props {
  jobs: JobStatusResponse[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

function statusClass(status: string): string {
  switch (status) {
    case "completed":
      return "status status--ok";
    case "failed":
      return "status status--fail";
    case "processing":
      return "status status--busy";
    default:
      return "status status--pending";
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function DocumentList({ jobs, loading, error, onRefresh }: Props) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onDelete(job: JobStatusResponse) {
    if (!job.document_id) return;
    setBusyId(job.document_id);
    setActionError(null);
    try {
      await deleteDocument(job.document_id);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="docs-heading">
      <header className="panel__head">
        <h2 id="docs-heading">Documents</h2>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={loading}>
          Refresh
        </button>
      </header>

      {error ? <p className="form-error">{error}</p> : null}
      {actionError ? <p className="form-error">{actionError}</p> : null}

      {jobs.length === 0 && !loading ? (
        <p className="empty">No documents yet. Upload a PDF to start ingestion.</p>
      ) : (
        <ul className="job-list">
          {jobs.map((job) => (
            <li key={job.job_id} className="job-row">
              <div className="job-row__main">
                <span className="job-row__name" title={job.filename ?? job.job_id}>
                  {job.filename ?? `${job.job_id.slice(0, 8)}…`}
                </span>
                <span className={statusClass(job.status)}>{job.status}</span>
              </div>
              <div className="job-row__meta">
                <time dateTime={job.updated_at}>{formatTime(job.updated_at)}</time>
                {job.error ? <span className="job-row__err">{job.error}</span> : null}
                {job.status === "completed" && job.document_id ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busyId === job.document_id}
                    onClick={() => void onDelete(job)}
                  >
                    {busyId === job.document_id ? "Deleting…" : "Delete"}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
