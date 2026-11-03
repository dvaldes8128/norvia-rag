import { apiFetch, saveAuth, type AuthState } from "./client";
import type {
  AskResponse,
  JobStatusResponse,
  TokenResponse,
  UploadAccepted,
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

export function uploadPdf(file: File): Promise<UploadAccepted> {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<UploadAccepted>("/upload", { method: "POST", body });
}

export function listJobs(limit = 50): Promise<JobStatusResponse[]> {
  return apiFetch<JobStatusResponse[]>(`/jobs?limit=${limit}`);
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`);
}

export function askQuestion(question: string): Promise<AskResponse> {
  return apiFetch<AskResponse>("/ask", { method: "POST" }, { json: { question } });
}
