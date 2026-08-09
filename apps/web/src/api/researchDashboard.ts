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
