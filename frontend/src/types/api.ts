/** Types mirroring backend/app/api/schemas.py */

export type JobStatus = "pending" | "processing" | "completed" | "failed" | string;

export interface UploadAccepted {
  job_id: string;
  status: JobStatus;
  filename: string;
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
  detail?: string | { msg?: string }[];
}
