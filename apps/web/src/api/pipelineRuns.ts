import { apiGet, queryKeys } from "./client";
import type {
  PipelineRunListResponse,
  PipelineRunResponse,
} from "./types";

export function fetchLatestPipelineRun(
  signal?: AbortSignal,
): Promise<PipelineRunResponse> {
  return apiGet<PipelineRunResponse>("/api/v1/pipeline-runs/latest", signal);
}

export function fetchPipelineRuns(
  filters: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<PipelineRunListResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return apiGet<PipelineRunListResponse>(
    `/api/v1/pipeline-runs?${params.toString()}`,
    signal,
  );
}

export const latestPipelineRunQueryKey = queryKeys.latestPipelineRun;
export const pipelineRunsQueryKey = queryKeys.pipelineRuns;