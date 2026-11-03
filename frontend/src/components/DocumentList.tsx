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
  return (
    <section className="panel" aria-labelledby="docs-heading">
      <header className="panel__head">
        <h2 id="docs-heading">Documents</h2>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={loading}>
          Refresh
        </button>
      </header>

      {error ? <p className="form-error">{error}</p> : null}

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
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
