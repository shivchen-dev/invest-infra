import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  render as renderWithTestingLibrary,
  screen,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  ResearchCenterBreadth,
  ResearchCenterCandidatePoolSummary,
  ResearchCenterCapabilities,
  ResearchCenterCapability,
  ResearchCenterDataFreshness,
  ResearchCenterDelivery,
  ResearchCenterMarket,
  ResearchCenterOpportunitySummary,
  ResearchCenterResearchSummary,
  ResearchCenterResponse,
} from "../../api/types";
import { ResearchCenterSubviewsPanel } from "./ResearchCenterSubviewsPanel";
import { Router } from "../../router";

function render(ui: ReactNode) {
  return renderWithTestingLibrary(
    <Router routes={[{ path: "/dashboard", element: null }]}>{ui}</Router>,
  );
}

function pendingQuery<TData>(): UseQueryResult<TData, Error> {
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

function errorQuery<TData>(error: Error): UseQueryResult<TData, Error> {
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

function successQuery<TData>(data: TData): UseQueryResult<TData, Error> {
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

function makeCapability(
  overrides: Partial<ResearchCenterCapability> = {},
): ResearchCenterCapability {
  return {
    reason: "slice_2_not_implemented",
    state: "deferred",
    ...overrides,
  };
}

function makeCapabilities(
  overrides: Partial<ResearchCenterCapabilities> = {},
): ResearchCenterCapabilities {
  return {
    opportunities: makeCapability({ reason: "slice_2_not_implemented" }),
    research: makeCapability({ reason: "slice_2_not_implemented" }),
    delivery: makeCapability({ reason: "slice_3_not_implemented" }),
    strategy: makeCapability({
      reason: "strategy_iteration_contract_not_frozen",
      state: "unavailable",
    }),
    discipline: makeCapability({
      reason: "position_discipline_contract_not_frozen",
      state: "unavailable",
    }),
    ...overrides,
  };
}

function makeBreadth(
  overrides: Partial<ResearchCenterBreadth> = {},
): ResearchCenterBreadth {
  return {
    state: "available",
    algorithm_version: "2.0.0",
    observations: [],
    scope_key: "ashare_active_universe_v1",
    scope_type: "ashare_universe",
    snapshot_id: "55555555-5555-5555-5555-555555555555",
    ...overrides,
  };
}

function makeFreshness(
  overrides: Partial<ResearchCenterDataFreshness> = {},
): ResearchCenterDataFreshness {
  return {
    checked_at: "2026-08-15T13:00:00Z",
    daily_bar_count: 100,
    latest_published_trade_date: "2026-08-15",
    missing_count: 0,
    state: "available",
    status: "fresh",
    universe_count: 100,
    ...overrides,
  };
}

function makeMarket(
  overrides: Partial<ResearchCenterMarket> = {},
): ResearchCenterMarket {
  return {
    as_of_date: "2026-08-15",
    breadth: null,
    data_freshness: null,
    freshness_status: null,
    quality_status: null,
    state: "unavailable",
    ...overrides,
  };
}

function makeCandidatePool(
  overrides: Partial<ResearchCenterCandidatePoolSummary> = {},
): ResearchCenterCandidatePoolSummary {
  return {
    state: "empty",
    run_id: null,
    trade_date: null,
    input_row_count: null,
    included_count: null,
    excluded_count: null,
    reason: null,
    ...overrides,
  };
}

function makeOpportunity(
  overrides: Partial<ResearchCenterOpportunitySummary> = {},
): ResearchCenterOpportunitySummary {
  return {
    state: "empty",
    observation_count: null,
    latest_as_of: null,
    admission_status_counts: null,
    reason: null,
    ...overrides,
  };
}

function makeResearch(
  overrides: Partial<ResearchCenterResearchSummary> = {},
): ResearchCenterResearchSummary {
  return {
    schema_version: "1.0.0",
    state: "empty",
    case_count: 0,
    run_count: 0,
    latest_case: null,
    evidence: {
      state: "empty",
      pack_id: null,
      quality_status: null,
      freshness_status: null,
    },
    ...overrides,
  };
}

function makeDelivery(
  overrides: Partial<ResearchCenterDelivery> = {},
): ResearchCenterDelivery {
  return {
    schema_version: "1.0.0",
    pipeline: {
      state: "empty",
      status: null,
      started_at: null,
      finished_at: null,
      business_completion_date: null,
      reason: null,
    },
    integration: {
      state: "empty",
      status: null,
      sample_size: null,
      producer_status_counts: null,
      intake_status_counts: null,
      latest_as_of: null,
      reason: null,
    },
    archive: {
      state: "empty",
      artifact_count: null,
      latest_run_status: null,
      latest_as_of: null,
      reason: null,
    },
    research_runs: {
      state: "empty",
      run_count: null,
      status_counts: null,
      latest_status: null,
      latest_started_at: null,
      latest_finished_at: null,
      reason: null,
    },
    ...overrides,
  };
}

function makeResponse(
  overrides: Partial<ResearchCenterResponse> = {},
): ResearchCenterResponse {
  return {
    schema_version: "1.0.0",
    generated_at: "2026-08-15T13:00:00Z",
    state: "unavailable",
    market: makeMarket(),
    capabilities: makeCapabilities(),
    candidate_pool: makeCandidatePool(),
    opportunities: makeOpportunity(),
    research: makeResearch(),
    delivery: makeDelivery(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("ResearchCenterSubviewsPanel", () => {
  it("renders a loading state when the source query is pending", () => {
    render(<ResearchCenterSubviewsPanel query={pendingQuery()} />);

    expect(
      screen.getByText("正在加载 Research Center 子视图"),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Candidate Pool 只读摘要"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Opportunity Radar 只读摘要"),
    ).not.toBeInTheDocument();
  });

  it("renders an HTTP error state when the source query fails", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={errorQuery(new ApiError("research-center 503", 503))}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("无法读取 Research Center 子视图");
    expect(alert).toHaveTextContent("research-center 503");
  });

  it("renders available subviews with bounded counts and distinct labels", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({ state: "available" }),
            candidate_pool: makeCandidatePool({
              state: "available",
              run_id: "11111111-1111-1111-1111-111111111111",
              trade_date: "2026-08-15",
              input_row_count: 320,
              included_count: 240,
              excluded_count: 80,
            }),
            opportunities: makeOpportunity({
              state: "available",
              observation_count: 12,
              latest_as_of: "2026-08-15",
              admission_status_counts: {
                pending: 4,
                corroborated: 3,
                admitted: 2,
                rejected: 1,
                conflict: 0,
              },
            }),
          }),
        )}
      />,
    );

    const pool = screen.getByLabelText("Candidate Pool 只读摘要");
    expect(pool).toHaveAttribute("data-state", "available");
    const poolState = within(pool).getByRole("status", {
      name: "Candidate Pool 状态 available",
    });
    expect(poolState.textContent ?? "").toContain("已发布最新候选池");
    expect(within(pool).getByText("trade_date")).toBeInTheDocument();
    expect(within(pool).getByText("2026-08-15")).toBeInTheDocument();
    expect(within(pool).getByText("input_row_count")).toBeInTheDocument();
    expect(within(pool).getByText("320")).toBeInTheDocument();
    expect(within(pool).getByText("included_count")).toBeInTheDocument();
    expect(within(pool).getByText("240")).toBeInTheDocument();
    expect(within(pool).getByText("excluded_count")).toBeInTheDocument();
    expect(within(pool).getByText("80")).toBeInTheDocument();
    expect(
      within(pool).queryByText("11111111-1111-1111-1111-111111111111"),
    ).not.toBeInTheDocument();
    expect(within(pool).getByRole("link", { name: "查看 Candidate Pool 详情" })).toHaveAttribute(
      "href",
      "/candidate-pool",
    );

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    expect(radar).toHaveAttribute("data-state", "available");
    const radarState = within(radar).getByRole("status", {
      name: "Opportunity Radar 状态 available",
    });
    expect(radarState.textContent ?? "").toContain("已拉取外部观察");
    expect(within(radar).getByText("ExternalObservation count")).toBeInTheDocument();
    expect(within(radar).getByText("12")).toBeInTheDocument();
    expect(within(radar).getByText("latest_as_of")).toBeInTheDocument();
    expect(within(radar).getByText("Admission status counts")).toBeInTheDocument();
    expect(within(radar).getByText("待验证")).toBeInTheDocument();
    expect(within(radar).getByText("已交叉验证")).toBeInTheDocument();
    expect(within(radar).getByText("已准入")).toBeInTheDocument();
    expect(within(radar).getByText("已拒绝")).toBeInTheDocument();
    expect(within(radar).getByText("冲突")).toBeInTheDocument();
    expect(within(radar).getByRole("link", { name: "查看 Opportunity Radar 详情" })).toHaveAttribute(
      "href",
      "/opportunity-radar",
    );
  });

  it("renders empty subviews with the no-published-run / no-observations wording", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "unavailable",
            candidate_pool: makeCandidatePool({ state: "empty" }),
            opportunities: makeOpportunity({ state: "empty" }),
          }),
        )}
      />,
    );

    const pool = screen.getByLabelText("Candidate Pool 只读摘要");
    expect(pool).toHaveAttribute("data-state", "empty");
    expect(
      within(pool).getByRole("status", { name: "Candidate Pool 状态 empty" }),
    ).toHaveTextContent("暂无已发布的候选池");
    expect(
      within(pool).getByText("Candidate Pool · empty"),
    ).toBeInTheDocument();
    expect(within(pool).queryByText("0")).not.toBeInTheDocument();
    expect(within(pool).getByRole("link", { name: "查看 Candidate Pool 详情" })).toHaveAttribute(
      "href",
      "/candidate-pool",
    );

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    expect(radar).toHaveAttribute("data-state", "empty");
    expect(
      within(radar).getByRole("status", { name: "Opportunity Radar 状态 empty" }),
    ).toHaveTextContent("暂无外部观察");
    expect(
      within(radar).getByText("Opportunity Radar · empty"),
    ).toBeInTheDocument();
    expect(within(radar).getByRole("link", { name: "查看 Opportunity Radar 详情" })).toHaveAttribute(
      "href",
      "/opportunity-radar",
    );
  });

  it("renders failed subviews with the sanitized reason, never the run_id", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "failed",
            candidate_pool: makeCandidatePool({
              state: "failed",
              reason: "candidate_pool_query_timeout",
              run_id: "11111111-1111-1111-1111-111111111111",
            }),
            opportunities: makeOpportunity({
              state: "failed",
              reason: "external_workflow_timeout",
            }),
          }),
        )}
      />,
    );

    const pool = screen.getByLabelText("Candidate Pool 只读摘要");
    expect(pool).toHaveAttribute("data-state", "failed");
    expect(
      within(pool).getByText("Candidate Pool · failed"),
    ).toBeInTheDocument();
    expect(
      within(pool).getByText("内部原因：candidate_pool_query_timeout"),
    ).toBeInTheDocument();
    expect(
      within(pool).queryByText("11111111-1111-1111-1111-111111111111"),
    ).not.toBeInTheDocument();
    expect(
      within(pool).queryByText("input_row_count"),
    ).not.toBeInTheDocument();
    expect(within(pool).getByRole("link", { name: "查看 Candidate Pool 详情" })).toHaveAttribute(
      "href",
      "/candidate-pool",
    );

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    expect(radar).toHaveAttribute("data-state", "failed");
    expect(
      within(radar).getByText("Opportunity Radar · failed"),
    ).toBeInTheDocument();
    expect(
      within(radar).getByText("内部原因：external_workflow_timeout"),
    ).toBeInTheDocument();
    expect(within(radar).getByRole("link", { name: "查看 Opportunity Radar 详情" })).toHaveAttribute(
      "href",
      "/opportunity-radar",
    );
  });

  it("does not render 0 counts as a fabricated available value when state is empty", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "unavailable",
            candidate_pool: makeCandidatePool({
              state: "empty",
              input_row_count: 0,
              included_count: 0,
              excluded_count: 0,
            }),
            opportunities: makeOpportunity({
              state: "empty",
              observation_count: 0,
            }),
          }),
        )}
      />,
    );

    const pool = screen.getByLabelText("Candidate Pool 只读摘要");
    expect(within(pool).queryByText("0")).not.toBeInTheDocument();

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    expect(within(radar).queryByText("0")).not.toBeInTheDocument();
  });

  it("renders unknown admission keys with the raw value while keeping known labels", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({ state: "available" }),
            opportunities: makeOpportunity({
              state: "available",
              observation_count: 4,
              latest_as_of: "2026-08-15",
              admission_status_counts: {
                pending: 2,
                unknown_status: 1,
              },
            }),
          }),
        )}
      />,
    );

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    const admissionSection = within(radar).getByLabelText(
      "Admission status counts",
    );
    const items = within(admissionSection).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("待验证");
    expect(items[0]).toHaveTextContent("2");
    expect(items[1]).toHaveTextContent("unknown_status");
    expect(items[1]).toHaveTextContent("1");
  });

  it("renders an empty admission-status placeholder when counts are missing", () => {
    render(
      <ResearchCenterSubviewsPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({ state: "available" }),
            opportunities: makeOpportunity({
              state: "available",
              observation_count: 0,
              latest_as_of: null,
              admission_status_counts: {},
            }),
          }),
        )}
      />,
    );

    const radar = screen.getByLabelText("Opportunity Radar 只读摘要");
    expect(
      within(radar).getByText("Admission status counts 无条目"),
    ).toBeInTheDocument();
  });

  it("uses the same query source for both cards and does not fetch radar data separately", () => {
    const response = makeResponse({
      state: "available",
      market: makeMarket({ state: "available" }),
      candidate_pool: makeCandidatePool({
        state: "available",
        trade_date: "2026-08-15",
        input_row_count: 10,
        included_count: 8,
        excluded_count: 2,
      }),
      opportunities: makeOpportunity({
        state: "available",
        observation_count: 5,
        latest_as_of: "2026-08-15",
        admission_status_counts: { admitted: 5 },
      }),
    });
    const refetch = vi.fn(() => Promise.resolve({} as never));
    const query = {
      ...successQuery(response),
      refetch,
    } as UseQueryResult<ResearchCenterResponse, Error>;

    render(<ResearchCenterSubviewsPanel query={query} />);

    expect(screen.getByLabelText("Candidate Pool 只读摘要")).toBeInTheDocument();
    expect(screen.getByLabelText("Opportunity Radar 只读摘要")).toBeInTheDocument();
    expect(refetch).not.toHaveBeenCalled();
  });
});
