import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet, queryKeys } from "./client";
import type { ResearchDashboardResponse } from "./types";

export function fetchResearchDashboard(
  signal?: AbortSignal,
): Promise<ResearchDashboardResponse> {
  return apiGet<ResearchDashboardResponse>(
    "/api/v1/research-dashboard",
    signal,
  );
}

export const researchDashboardQueryKey = queryKeys.researchDashboard;

export const RESEARCH_DASHBOARD_REFETCH_INTERVAL = 60_000;

export function useResearchDashboard(): UseQueryResult<
  ResearchDashboardResponse,
  Error
> {
  return useQuery<ResearchDashboardResponse, Error>({
    queryKey: researchDashboardQueryKey,
    queryFn: ({ signal }) => fetchResearchDashboard(signal),
    refetchInterval: RESEARCH_DASHBOARD_REFETCH_INTERVAL,
  });
}
