import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet, queryKeys } from "./client";
import type { ResearchCaseWorkspaceResponse } from "./types";

export function fetchResearchCaseWorkspace(
  caseId: string,
  signal?: AbortSignal,
): Promise<ResearchCaseWorkspaceResponse> {
  return apiGet<ResearchCaseWorkspaceResponse>(
    `/api/v1/research-cases/${encodeURIComponent(caseId)}/workspace`,
    signal,
  );
}

export function researchCaseWorkspaceQueryKey(caseId: string) {
  return queryKeys.researchCaseWorkspace(caseId);
}

export const RESEARCH_CASE_WORKSPACE_REFETCH_INTERVAL = 60_000;

export function useResearchCaseWorkspace(
  caseId: string | null | undefined,
): UseQueryResult<ResearchCaseWorkspaceResponse, Error> {
  return useQuery<ResearchCaseWorkspaceResponse, Error>({
    queryKey: researchCaseWorkspaceQueryKey(caseId ?? ""),
    queryFn: ({ signal }) => {
      if (!caseId) {
        return Promise.reject(
          new Error("Research Case ID is required to load workspace"),
        );
      }
      return fetchResearchCaseWorkspace(caseId, signal);
    },
    enabled: Boolean(caseId),
    refetchInterval: RESEARCH_CASE_WORKSPACE_REFETCH_INTERVAL,
  });
}
