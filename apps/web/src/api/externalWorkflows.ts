import { apiGet, queryKeys } from "./client";
import type {
  ExternalArtifactResponse,
  ExternalWorkflowRunListResponse,
  ExternalWorkflowRunResponse,
} from "./types";

export function fetchExternalWorkflows(
  filters: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<ExternalWorkflowRunListResponse> {
  return apiGet<ExternalWorkflowRunListResponse>(
    `/api/v1/external-workflows?limit=${filters.limit}&offset=${filters.offset}`,
    signal,
  );
}

export function fetchExternalWorkflowArtifacts(
  runId: string,
  signal?: AbortSignal,
): Promise<ExternalArtifactResponse[]> {
  return apiGet<ExternalArtifactResponse[]>(
    `/api/v1/external-workflows/${encodeURIComponent(runId)}/artifacts`,
    signal,
  );
}

export function fetchExternalWorkflow(
  runId: string,
  signal?: AbortSignal,
): Promise<ExternalWorkflowRunResponse> {
  return apiGet<ExternalWorkflowRunResponse>(
    `/api/v1/external-workflows/${encodeURIComponent(runId)}`,
    signal,
  );
}

export const externalWorkflowsQueryKey = (filters: { limit: number; offset: number }) =>
  queryKeys.externalWorkflows(filters);
