/** Types mirroring backend/app/api/schemas.py */

export type JobStatus = "pending" | "processing" | "completed" | "failed" | string;

export type UploadConfirm = "replace" | "as_new";

export interface UploadAccepted {
  job_id: string;
  status: JobStatus;
  filename: string;
}

export interface FilenameConflictDetail {
  message?: string;
  code?: string;
  filename: string;
  existing_document_id: string;
  existing_version: number;
  existing_content_hash?: string;
  content_hash?: string;
}

export interface DocumentDeleted {
  document_id: string;
  filename: string;
  deleted: boolean;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  filename: string | null;
  document_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  tenant_id: string;
}

export interface Citation {
  document_id: string;
  filename: string;
  page_number: number;
  chunk_id: string;
  excerpt: string;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  confidence: number;
}

export interface ApiErrorBody {
  error?: string;
  code?: string;
  detail?: string | FilenameConflictDetail | { msg?: string }[];
}
