import type { UseQueryResult } from "@tanstack/react-query";
import type {
  ResearchDashboardEvidenceStatus,
  ResearchDashboardMarketStatus,
  ResearchDashboardResearchSummary,
  ResearchDashboardResponse,
  ResearchRunResponse,
} from "../../../api/types";

export interface BuildDashboardOptions {
  readonly marketStatus?: ResearchDashboardMarketStatus;
  readonly researchSummary?: ResearchDashboardResearchSummary;
  readonly evidenceStatus?: ResearchDashboardEvidenceStatus;
  readonly recentRuns?: ReadonlyArray<ResearchRunResponse>;
  readonly asOfDate?: string | null;
  readonly dataQuality?: ResearchDashboardResponse["data_quality"];
  readonly freshness?: ResearchDashboardResponse["freshness"];
  readonly generatedAt?: string;
}

export function buildDashboardResponse(
  options: BuildDashboardOptions = {},
): ResearchDashboardResponse {
  return {
    schema_version: "1.0.0",
    generated_at: options.generatedAt ?? "2026-08-09T01:15:00Z",
    as_of_date: options.asOfDate ?? null,
    data_quality: options.dataQuality ?? "empty",
    freshness: options.freshness ?? "unknown",
    market_status: options.marketStatus ?? {
      state: "unavailable",
      reason: "no market dashboard source registered",
    },
    research_summary: options.researchSummary ?? {
      case_count: 0,
      run_count: 0,
      latest_case: null,
    },
    evidence_status: options.evidenceStatus ?? {
      state: "empty",
      case_id: null,
      pack_id: null,
      schema_version: null,
      factor_set_key: null,
      factor_set_version: null,
      quality_status: null,
      freshness_status: null,
    },
    recent_runs: options.recentRuns ? [...options.recentRuns] : [],
  };
}

export function buildRun(
  overrides: Partial<ResearchRunResponse> = {},
): ResearchRunResponse {
  return {
    attempt: 1,
    case_id: "11111111-1111-1111-1111-111111111111",
    error_summary: null,
    evidence_pack_id: "22222222-2222-2222-2222-222222222222",
    finished_at: "2026-08-09T00:30:00Z",
    playbook_key: "playbook.default",
    run_id: "33333333-3333-3333-3333-333333333333",
    runner_key: "runner.default",
    started_at: "2026-08-09T00:00:00Z",
    status: "succeeded",
    ...overrides,
  };
}

export function pendingQuery<TData>(): UseQueryResult<TData, Error> {
  return {
    data: undefined,
    error: null,
    isPending: true,
    isError: false,
    isLoading: true,
    isLoadingError: false,
    isRefetchError: false,
    isSuccess: false,
    status: "pending",
    refetch: () => Promise.resolve({} as never),
  } as unknown as UseQueryResult<TData, Error>;
}

export function errorQuery<TData>(error: Error): UseQueryResult<TData, Error> {
  return {
    data: undefined,
    error,
    isPending: false,
    isError: true,
    isLoading: false,
    isLoadingError: true,
    isRefetchError: false,
    isSuccess: false,
    status: "error",
    refetch: () => Promise.resolve({} as never),
  } as unknown as UseQueryResult<TData, Error>;
}

export function successQuery<TData>(data: TData): UseQueryResult<TData, Error> {
  return {
    data,
    error: null,
    isPending: false,
    isError: false,
    isLoading: false,
    isLoadingError: false,
    isRefetchError: false,
    isSuccess: true,
    status: "success",
    refetch: () => Promise.resolve({} as never),
  } as unknown as UseQueryResult<TData, Error>;
}
