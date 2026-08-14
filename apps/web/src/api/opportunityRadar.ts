import { apiGet, queryKeys } from "./client";
import type { ExternalObservationResponse } from "./types";

export type OpportunityRadarStatus =
  | "pending"
  | "corroborated"
  | "admitted"
  | "rejected"
  | "conflict";

export function fetchOpportunityRadar(
  filters: { admissionStatus?: OpportunityRadarStatus; limit: number; offset: number },
  signal?: AbortSignal,
): Promise<ExternalObservationResponse[]> {
  const params = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.admissionStatus) params.set("admission_status", filters.admissionStatus);
  return apiGet<ExternalObservationResponse[]>(
    `/api/v1/opportunity-radar?${params.toString()}`,
    signal,
  );
}

export const opportunityRadarQueryKey = (filters: {
  admissionStatus?: OpportunityRadarStatus;
  limit: number;
  offset: number;
}) => queryKeys.opportunityRadar(filters);
