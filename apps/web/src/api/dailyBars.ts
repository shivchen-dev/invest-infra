import { apiGet } from "./client";
import type { DailyBarListResponse } from "./types";

export type EtfDailyBarsFilters = {
  instrument_id: string;
  start_date: string;
  end_date: string;
  limit: number;
  offset: number;
};

export function buildEtfDailyBarsQuery(filters: EtfDailyBarsFilters): string {
  const params = new URLSearchParams();
  params.set("instrument_id", filters.instrument_id);
  params.set("start_date", filters.start_date);
  params.set("end_date", filters.end_date);
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return params.toString();
}

export function fetchEtfDailyBars(
  filters: EtfDailyBarsFilters,
  signal?: AbortSignal,
): Promise<DailyBarListResponse> {
  return apiGet<DailyBarListResponse>(
    `/api/v1/etf/daily-bars?${buildEtfDailyBarsQuery(filters)}`,
    signal,
  );
}
