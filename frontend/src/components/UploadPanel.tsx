import { useRef, useState, type ChangeEvent } from "react";
import { uploadPdf } from "../api/endpoints";
import type { JobStatusResponse } from "../types/api";
import { rememberJobFilename } from "../hooks/useJobPolling";

interface Props {
  onUploaded: (job: JobStatusResponse) => void;
}

export function UploadPanel({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setHint(null);
    try {
      const accepted = await uploadPdf(file);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    void handleFile(e.target.files?.[0]);
  }

  return (
    <div className="upload-panel">
      <input
        ref={inputRef}
        id="pdf-upload"
        type="file"
        accept="application/pdf,.pdf"
        disabled={busy}
        onChange={onChange}
        hidden
      />
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? "Uploading…" : "Upload PDF"}
      </button>
      {hint ? <p className="form-hint">{hint}</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
    </div>
  );
}
