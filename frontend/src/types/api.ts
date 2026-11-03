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

export interface AdminTenantOut {
  id: string;
  name: string;
  created_at: string;
  document_count: number;
  job_count: number;
  api_key_prefixes: string[];
  env_backed: boolean;
}

export interface AdminTenantCreated {
  id: string;
  name: string;
  api_key: string;
  api_key_id: string;
  api_key_prefix: string;
}

export interface AdminTenantKeyIssued {
  tenant_id: string;
  api_key: string;
  api_key_id: string;
  api_key_prefix: string;
  label: string;
}

export interface AdminQueueSnapshot {
  workers: string[];
  worker_count: number;
  broker_queue_depth: number | null;
  active_tasks: Record<string, unknown>[];
  reserved_tasks: Record<string, unknown>[];
  scheduled_tasks: Record<string, unknown>[];
  jobs_by_status: Record<string, number>;
}

export interface AdminTelemetrySnapshot {
  service_name: string;
  traces_exporter: string;
  otlp_endpoint_configured: boolean;
  llm_provider: string;
  embeddings_provider: string;
  tenant_count: number;
  document_count: number;
  chunk_count: number;
  jobs_by_status: Record<string, number>;
  worker_count: number;
  recent_failed_jobs: {
    job_id: string;
    tenant_id: string;
    error: string | null;
    updated_at: string | null;
  }[];
  note: string;
}
