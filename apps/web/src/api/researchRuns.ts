import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet, queryKeys } from "./client";
import type { ResearchRunListResponse } from "./types";

export interface ResearchRunListFilters {
  limit: number;
  offset: number;
}

export function buildResearchRunListQuery(filters: ResearchRunListFilters): string {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return params.toString();
}

export function fetchResearchRuns(
  filters: ResearchRunListFilters,
  signal?: AbortSignal,
): Promise<ResearchRunListResponse> {
  return apiGet<ResearchRunListResponse>(
    `/api/v1/research-runs?${buildResearchRunListQuery(filters)}`,
    signal,
  );
}

export function researchRunsQueryKey(filters: ResearchRunListFilters) {
  return queryKeys.researchRuns(filters);
}

export const RESEARCH_HISTORY_REFETCH_INTERVAL = 60_000;

export function useResearchRuns(
  filters: ResearchRunListFilters,
  options: {
    enabled?: boolean;
    retry?:
      | boolean
      | ((failureCount: number, error: unknown) => boolean);
  } = {},
): UseQueryResult<ResearchRunListResponse, Error> {
  return useQuery<ResearchRunListResponse, Error>({
    queryKey: researchRunsQueryKey(filters),
    queryFn: ({ signal }) => fetchResearchRuns(filters, signal),
    refetchInterval: RESEARCH_HISTORY_REFETCH_INTERVAL,
    enabled: options.enabled ?? true,
    retry: options.retry ?? true,
  });
}
