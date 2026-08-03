import { apiGet } from "./client";
import type { InstrumentListResponse } from "./types";

export type EtfInstrumentFilters = {
  limit: number;
  offset: number;
  exchange?: string;
  status?: string;
};

export function buildEtfInstrumentsQuery(filters: EtfInstrumentFilters): string {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  if (filters.exchange) params.set("exchange", filters.exchange);
  if (filters.status) params.set("status", filters.status);
  return params.toString();
}

export function fetchEtfInstruments(
  filters: EtfInstrumentFilters,
  signal?: AbortSignal,
): Promise<InstrumentListResponse> {
  return apiGet<InstrumentListResponse>(
    `/api/v1/etf/instruments?${buildEtfInstrumentsQuery(filters)}`,
    signal,
  );
}
