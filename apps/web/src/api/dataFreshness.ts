import { apiGet, queryKeys } from "./client";
import type { DataFreshnessResponse } from "./types";

export function fetchDataFreshness(
  signal?: AbortSignal,
): Promise<DataFreshnessResponse> {
  return apiGet<DataFreshnessResponse>("/api/v1/data-freshness", signal);
}

export const freshnessQueryKey = queryKeys.freshness;