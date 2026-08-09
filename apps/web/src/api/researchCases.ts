import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet, queryKeys } from "./client";
import type { ResearchCaseListResponse } from "./types";

export interface ResearchCaseListFilters {
  limit: number;
  offset: number;
}

export function buildResearchCaseListQuery(filters: ResearchCaseListFilters): string {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return params.toString();
}

export function fetchResearchCases(
  filters: ResearchCaseListFilters,
  signal?: AbortSignal,
): Promise<ResearchCaseListResponse> {
  return apiGet<ResearchCaseListResponse>(
    `/api/v1/research-cases?${buildResearchCaseListQuery(filters)}`,
    signal,
  );
}

export function researchCasesQueryKey(filters: ResearchCaseListFilters) {
  return queryKeys.researchCases(filters);
}

export const RESEARCH_HISTORY_REFETCH_INTERVAL = 60_000;

export function useResearchCases(
  filters: ResearchCaseListFilters,
  options: {
    enabled?: boolean;
    retry?:
      | boolean
      | ((failureCount: number, error: unknown) => boolean);
  } = {},
): UseQueryResult<ResearchCaseListResponse, Error> {
  return useQuery<ResearchCaseListResponse, Error>({
    queryKey: researchCasesQueryKey(filters),
    queryFn: ({ signal }) => fetchResearchCases(filters, signal),
    refetchInterval: RESEARCH_HISTORY_REFETCH_INTERVAL,
    enabled: options.enabled ?? true,
    retry: options.retry ?? true,
  });
}
