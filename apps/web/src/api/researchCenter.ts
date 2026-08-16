import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet, queryKeys } from "./client";
import type { ResearchCenterResponse } from "./types";

export function fetchResearchCenter(
  signal?: AbortSignal,
): Promise<ResearchCenterResponse> {
  return apiGet<ResearchCenterResponse>("/api/v1/research-center", signal);
}

export const researchCenterQueryKey = queryKeys.researchCenter;

export const RESEARCH_CENTER_REFETCH_INTERVAL = 60_000;

export function useResearchCenter(): UseQueryResult<
  ResearchCenterResponse,
  Error
> {
  return useQuery<ResearchCenterResponse, Error>({
    queryKey: researchCenterQueryKey,
    queryFn: ({ signal }) => fetchResearchCenter(signal),
    refetchInterval: RESEARCH_CENTER_REFETCH_INTERVAL,
  });
}