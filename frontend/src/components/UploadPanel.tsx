import { useRef, useState, type ChangeEvent } from "react";
import { ApiError } from "../api/client";
import { uploadPdf } from "../api/endpoints";
import type { FilenameConflictDetail, JobStatusResponse, UploadConfirm } from "../types/api";
import { rememberJobFilename } from "../hooks/useJobPolling";

interface Props {
  onUploaded: (job: JobStatusResponse) => void;
}

interface PendingConflict {
  file: File;
  detail: FilenameConflictDetail;
}

function conflictFromError(err: ApiError): FilenameConflictDetail | null {
  if (err.status !== 409 || err.code !== "filename_conflict") return null;
  const detail = err.detail;
  if (typeof detail === "object" && detail && "existing_document_id" in detail) {
    return detail as FilenameConflictDetail;
  }
  return null;
}

export function UploadPanel({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingConflict | null>(null);

  async function enqueue(
    file: File,
    opts?: { confirm?: UploadConfirm; replaceDocumentId?: string },
  ) {
    setBusy(true);
    setError(null);
    setHint(null);
    try {
      const accepted = await uploadPdf(file, opts);
      rememberJobFilename(accepted.job_id, accepted.filename);
      const now = new Date().toISOString();
      onUploaded({
        job_id: accepted.job_id,
        status: accepted.status,
        filename: accepted.filename,
        document_id: null,
        error: null,
        created_at: now,
        updated_at: now,
      });
      setHint(`Queued ${accepted.filename}`);
      setPending(null);
    } catch (err) {
      if (err instanceof ApiError) {
        const conflict = conflictFromError(err);
        if (conflict && !opts?.confirm) {
          setPending({ file, detail: conflict });
          return;
        }
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Upload failed");
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function handleFile(file: File | undefined) {
    if (!file) return;
    void enqueue(file);
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    handleFile(e.target.files?.[0]);
  }

  function resolveConflict(choice: UploadConfirm) {
    if (!pending) return;
    const { file, detail } = pending;
    void enqueue(file, {
      confirm: choice,
      replaceDocumentId: choice === "replace" ? detail.existing_document_id : undefined,
    });
  }

  return (
    <div className="upload-panel">
      <input
        ref={inputRef}
        id="pdf-upload"
        type="file"
        accept="application/pdf,.pdf"
        disabled={busy || Boolean(pending)}
        onChange={onChange}
        hidden
      />
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy || Boolean(pending)}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? "Uploading…" : "Upload PDF"}
      </button>
      {hint ? <p className="form-hint">{hint}</p> : null}
      {error ? <p className="form-error">{error}</p> : null}

      {pending ? (
        <div className="confirm-box" role="dialog" aria-labelledby="version-confirm-title">
          <p id="version-confirm-title" className="confirm-box__title">
            New version of <strong>{pending.detail.filename}</strong>?
          </p>
          <p className="confirm-box__body">
            A live document with this name already exists (v{pending.detail.existing_version})
            but the bytes differ. Replace soft-deletes old chunks and re-indexes; keep both
            creates a separate document.
          </p>
          <div className="confirm-box__actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy}
              onClick={() => resolveConflict("replace")}
            >
              Replace (new version)
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => resolveConflict("as_new")}
            >
              Keep both
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => setPending(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
