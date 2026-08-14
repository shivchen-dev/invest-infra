import { apiGet, queryKeys } from "./client";
import type { IntegrationHealthResponse } from "./types";

export function fetchIntegrationHealth(
  signal?: AbortSignal,
): Promise<IntegrationHealthResponse> {
  return apiGet<IntegrationHealthResponse>("/api/v1/integration/health", signal);
}

export const integrationHealthQueryKey = queryKeys.integrationHealth;
