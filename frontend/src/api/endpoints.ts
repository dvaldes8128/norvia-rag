import { apiFetch, saveAuth, type AuthState } from "./client";
import type {
  AskResponse,
  DocumentDeleted,
  JobStatusResponse,
  TokenResponse,
  UploadAccepted,
  UploadConfirm,
} from "../types/api";

export async function exchangeToken(apiKey: string): Promise<AuthState> {
  const token = await apiFetch<TokenResponse>(
    "/auth/token",
    { method: "POST" },
    { auth: false, json: { api_key: apiKey } },
  );
  const state: AuthState = {
    apiKey,
    accessToken: token.access_token,
    tenantId: token.tenant_id,
  };
  saveAuth(state);
  return state;
}

export function uploadPdf(
  file: File,
  opts?: { confirm?: UploadConfirm; replaceDocumentId?: string },
): Promise<UploadAccepted> {
  const body = new FormData();
  body.append("file", file);
  const params = new URLSearchParams();
  if (opts?.confirm) params.set("confirm", opts.confirm);
  if (opts?.replaceDocumentId) params.set("replace_document_id", opts.replaceDocumentId);
  const qs = params.toString();
  return apiFetch<UploadAccepted>(`/upload${qs ? `?${qs}` : ""}`, { method: "POST", body });
}

export function listJobs(limit = 50): Promise<JobStatusResponse[]> {
  return apiFetch<JobStatusResponse[]>(`/jobs?limit=${limit}`);
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`);
}

export function deleteDocument(documentId: string): Promise<DocumentDeleted> {
  return apiFetch<DocumentDeleted>(`/documents/${documentId}`, { method: "DELETE" });
}

export function askQuestion(
  question: string,
  opts?: { citationTopN?: number; lexicalGrounding?: boolean },
): Promise<AskResponse> {
  return apiFetch<AskResponse>(
    "/ask",
    { method: "POST" },
    {
      json: {
        question,
        citation_top_n: opts?.citationTopN ?? 3,
        lexical_grounding: opts?.lexicalGrounding ?? false,
      },
    },
  );
}
