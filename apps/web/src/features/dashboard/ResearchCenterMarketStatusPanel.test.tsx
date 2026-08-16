import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  render as renderWithTestingLibrary,
  screen,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  ResearchCenterBreadth,
  ResearchCenterCandidatePoolSummary,
  ResearchCenterCapabilities,
  ResearchCenterCapability,
  ResearchCenterDataFreshness,
  ResearchCenterMarket,
  ResearchCenterObservation,
  ResearchCenterOpportunitySummary,
  ResearchCenterResearchSummary,
  ResearchCenterResponse,
} from "../../api/types";
import { ResearchCenterMarketStatusPanel } from "./ResearchCenterMarketStatusPanel";
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

function makeObservation(
  overrides: Partial<ResearchCenterObservation> = {},
): ResearchCenterObservation {
  return {
    key: "advancing_ratio",
    value: "0.60000000",
    unit: "ratio",
    observed_date: "2026-08-15",
    source_kind: "analytics",
    source_ref: "market_breadth:2.0.0",
    quality_status: "complete",
    ...overrides,
  };
}

function makeBreadth(
  overrides: Partial<Extract<ResearchCenterBreadth, { state: "available" }>> = {},
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

function makeCandidatePoolSummary(
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

function makeOpportunitySummary(
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

function makeResearchSummary(
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

function makeResponse(
  overrides: Partial<ResearchCenterResponse> = {},
): ResearchCenterResponse {
  return {
    schema_version: "1.0.0",
    generated_at: "2026-08-15T13:00:00Z",
    state: "unavailable",
    market: makeMarket(),
    capabilities: makeCapabilities(),
    candidate_pool: makeCandidatePoolSummary(),
    opportunities: makeOpportunitySummary(),
    research: makeResearchSummary(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("ResearchCenterMarketStatusPanel", () => {
  it("renders a loading state when the query is pending", () => {
    render(<ResearchCenterMarketStatusPanel query={pendingQuery()} />);

    expect(screen.getByText("正在加载 Research Center 市场状态")).toBeInTheDocument();
    expect(screen.queryByText("Research Center 市场状态")).not.toBeInTheDocument();
  });

  it("renders a generic error state when the HTTP request fails", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={errorQuery(new ApiError("research-center 503", 503))}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("无法读取 Research Center 市场状态");
    expect(alert).toHaveTextContent("research-center 503");
  });

  it("renders unavailable sub-sections and their detail links when both sources are null", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "unavailable",
            market: makeMarket({ state: "unavailable" }),
          }),
        )}
      />,
    );

    expect(screen.getByLabelText("市场广度")).toHaveTextContent("unavailable");
    expect(screen.getByLabelText("数据新鲜度")).toHaveTextContent("unavailable");
    expect(screen.getByRole("link", { name: "查看 Market Breadth 详情" })).toHaveAttribute(
      "href",
      "/api/v1/market-breadth/latest",
    );
    expect(screen.getByRole("link", { name: "查看 Data Freshness 详情" })).toHaveAttribute(
      "href",
      "/operations",
    );
  });

  it("renders the available state with dates, quality and provenance", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({
              state: "available",
              as_of_date: "2026-08-15",
              freshness_status: "fresh",
              quality_status: "complete",
              breadth: makeBreadth({
                observations: [
                  makeObservation({
                    key: "advancing_ratio",
                    value: "0.60000000",
                  }),
                  makeObservation({
                    key: "declining_ratio",
                    value: "0.40000000",
                    observed_date: "2026-08-15",
                  }),
                ],
              }),
              data_freshness: makeFreshness(),
            }),
          }),
        )}
      />,
    );

    const root = screen.getByLabelText("Research Center 市场状态");
    expect(root).toHaveAttribute("data-state", "available");
    const stateLine = within(root).getByRole("status", { name: "市场状态 available" });
    expect(stateLine.textContent ?? "").toContain("市场广度与数据新鲜度均可展示");
    expect(
      within(root).getByText("Read API · /api/v1/research-center · schema 1.0.0"),
    ).toBeInTheDocument();

    const datesSection = screen.getByLabelText("市场日期与质量");
    expect(within(datesSection).getAllByText("2026-08-15").length).toBeGreaterThanOrEqual(1);
    expect(within(datesSection).getByText("2026-08-15 21:00:00")).toBeInTheDocument();
    expect(within(datesSection).getByText("complete")).toBeInTheDocument();
    expect(within(datesSection).getByText("fresh")).toBeInTheDocument();

    const breadth = screen.getByLabelText("市场广度");
    expect(within(breadth).getByText("snapshot_id 55555555-5555-5555-5555-555555555555 · algorithm 2.0.0")).toBeInTheDocument();
    expect(within(breadth).getByText("ashare_universe")).toBeInTheDocument();
    expect(within(breadth).getByText("ashare_active_universe_v1")).toBeInTheDocument();

    const table = within(breadth).getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows.length).toBe(3);
    expect(within(table).getByText("advancing_ratio")).toBeInTheDocument();
    expect(within(table).getByText("declining_ratio")).toBeInTheDocument();
    expect(within(table).getByText("0.60000000")).toBeInTheDocument();
    expect(within(table).getAllByText("market_breadth:2.0.0").length).toBeGreaterThanOrEqual(1);

    const freshness = screen.getByLabelText("数据新鲜度");
    expect(within(freshness).getByText("fresh · 数据已更新")).toBeInTheDocument();
    expect(within(freshness).getAllByText("fresh").length).toBeGreaterThanOrEqual(1);
    expect(within(freshness).getByText("available")).toBeInTheDocument();
    expect(within(freshness).getAllByText("100 只").length).toBeGreaterThanOrEqual(1);
    expect(within(breadth).getByRole("link", { name: "查看 Market Breadth 详情" })).toHaveAttribute("href", "/api/v1/market-breadth/latest");
    expect(within(freshness).getByRole("link", { name: "查看 Data Freshness 详情" })).toHaveAttribute("href", "/operations");
  });

  it("renders the partial state when breadth is missing but freshness is present", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "partial",
            market: makeMarket({
              state: "partial",
              as_of_date: "2026-08-15",
              freshness_status: "stale",
              quality_status: null,
              breadth: null,
              data_freshness: makeFreshness({
                status: "stale",
                state: "partial",
                latest_published_trade_date: "2026-08-13",
              }),
            }),
          }),
        )}
      />,
    );

    const root = screen.getByLabelText("Research Center 市场状态");
    expect(root).toHaveAttribute("data-state", "partial");
    const stateLine = within(root).getByRole("status", { name: "市场状态 partial" });
    expect(stateLine.textContent ?? "").toContain("仅部分来源可展示");

    const breadth = screen.getByLabelText("市场广度");
    expect(
      within(breadth).getByText("市场广度 · unavailable"),
    ).toBeInTheDocument();

    const freshness = screen.getByLabelText("数据新鲜度");
    expect(
      within(freshness).getByText("stale · 数据未更新到预期日期"),
    ).toBeInTheDocument();
    expect(within(freshness).getByText("stale")).toBeInTheDocument();
    expect(within(freshness).getByText("2026-08-13")).toBeInTheDocument();
  });

  it("renders the failed state with explicit text when both sources failed but response is delivered", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "failed",
            market: makeMarket({
              state: "failed",
              as_of_date: null,
              breadth: {
                state: "failed",
                snapshot_id: null,
                algorithm_version: null,
                scope_type: null,
                scope_key: null,
                observations: null,
              },
              data_freshness: makeFreshness({
                state: "failed",
                status: "failed",
                latest_published_trade_date: null,
                universe_count: null,
                daily_bar_count: null,
                missing_count: null,
              }),
            }),
          }),
        )}
      />,
    );

    const root = screen.getByLabelText("Research Center 市场状态");
    expect(root).toHaveAttribute("data-state", "failed");
    const stateLine = within(root).getByRole("status", { name: "市场状态 failed" });
    expect(stateLine.textContent ?? "").toContain("受控查询失败");
    expect(
      within(root).getByText(/failed · 受控查询失败/),
    ).toBeInTheDocument();

    const dates = screen.getByLabelText("市场日期与质量");
    expect(within(dates).getAllByText("—").length).toBeGreaterThanOrEqual(3);

    const breadth = screen.getByLabelText("市场广度");
    const freshness = screen.getByLabelText("数据新鲜度");
    expect(breadth).toHaveTextContent("市场广度 · failed");
    expect(freshness).toHaveTextContent("数据新鲜度 · failed");
    expect(breadth).not.toHaveTextContent("unavailable");
    expect(freshness).not.toHaveTextContent("unavailable");
    expect(freshness).not.toHaveTextContent("0 只");
    expect(within(breadth).getByRole("link", { name: "查看 Market Breadth 详情" })).toHaveAttribute("href", "/api/v1/market-breadth/latest");
    expect(within(freshness).getByRole("link", { name: "查看 Data Freshness 详情" })).toHaveAttribute("href", "/operations");
  });

  it("renders null observation values as em-dashes without fabricating zeros", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({
              state: "available",
              breadth: makeBreadth({
                observations: [
                  makeObservation({
                    key: "above_ma20_ratio",
                    value: null,
                  }),
                ],
              }),
            }),
          }),
        )}
      />,
    );

    const table = within(
      screen.getByLabelText("市场广度"),
    ).getByRole("table");
    const valueCells = within(table).getAllByRole("cell");
    const valueCell = valueCells.find(
      (cell) => cell.textContent === "—",
    );
    expect(valueCell).toBeDefined();
    expect(within(table).queryByText("0")).not.toBeInTheDocument();
  });

  it("does not render a stale freshness pill when the freshness is fresh", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({
              state: "available",
              data_freshness: makeFreshness(),
            }),
          }),
        )}
      />,
    );

    const freshness = screen.getByLabelText("数据新鲜度");
    expect(within(freshness).queryByText("stale")).not.toBeInTheDocument();
  });

  it("shows an explicit unavailable note for the breadth sub-section when only freshness is available", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "partial",
            market: makeMarket({
              state: "partial",
              breadth: null,
              data_freshness: makeFreshness(),
            }),
          }),
        )}
      />,
    );

    const breadth = screen.getByLabelText("市场广度");
    expect(
      within(breadth).getByText("市场广度 · unavailable"),
    ).toBeInTheDocument();
    expect(
      within(breadth).getByText(/Market Breadth 快照缺失/),
    ).toBeInTheDocument();
  });

  it("renders the backend-valid unavailable wire shape with sentinel counts without surfacing them as metrics", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "unavailable",
            market: makeMarket({
              state: "unavailable",
              as_of_date: null,
              quality_status: null,
              freshness_status: "missing",
              breadth: null,
              data_freshness: makeFreshness({
                checked_at: "2026-08-12T01:30:00Z",
                state: "unavailable",
                status: "missing",
                latest_published_trade_date: null,
                universe_count: 0,
                daily_bar_count: 0,
                missing_count: 0,
              }),
            }),
          }),
        )}
      />,
    );

    const freshness = screen.getByLabelText("数据新鲜度");
    expect(within(freshness).getByText("missing")).toBeInTheDocument();
    expect(within(freshness).getByText("unavailable")).toBeInTheDocument();
    expect(
      within(freshness).getByText(/missing · 尚无发布结果/),
    ).toBeInTheDocument();
    expect(
      within(freshness).getByText("数据新鲜度 · unavailable / missing"),
    ).toBeInTheDocument();
    expect(within(freshness).getByText("2026-08-12 09:30:00")).toBeInTheDocument();
    expect(
      within(freshness).queryByText("0 只"),
    ).not.toBeInTheDocument();
    expect(
      within(freshness).queryByText("latest_published_trade_date"),
    ).not.toBeInTheDocument();

    const root = screen.getByLabelText("Research Center 市场状态");
    expect(root).toHaveAttribute("data-state", "unavailable");
    expect(within(root).queryAllByText("0 只").length).toBe(0);

    const dates = screen.getByLabelText("市场日期与质量");
    expect(within(dates).getByText("missing")).toBeInTheDocument();
    expect(
      within(dates).queryByText("2026-08-12 09:30:00"),
    ).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable branch when only status=missing without state=unavailable", () => {
    render(
      <ResearchCenterMarketStatusPanel
        query={successQuery(
          makeResponse({
            state: "unavailable",
            market: makeMarket({
              state: "unavailable",
              breadth: null,
              data_freshness: makeFreshness({
                state: "available",
                status: "missing",
                latest_published_trade_date: null,
                universe_count: 0,
                daily_bar_count: 0,
                missing_count: 0,
              }),
            }),
          }),
        )}
      />,
    );

    const freshness = screen.getByLabelText("数据新鲜度");
    expect(within(freshness).getByText("missing")).toBeInTheDocument();
    expect(
      within(freshness).getByText("数据新鲜度 · available / missing"),
    ).toBeInTheDocument();
    expect(
      within(freshness).queryByText("0 只"),
    ).not.toBeInTheDocument();
  });
});
