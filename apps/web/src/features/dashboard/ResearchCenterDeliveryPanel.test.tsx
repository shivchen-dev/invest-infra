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
  ResearchCenterDeliveryArchive,
  ResearchCenterDeliveryIntegration,
  ResearchCenterDeliveryPipeline,
  ResearchCenterDeliveryResearchRuns,
  ResearchCenterMarket,
  ResearchCenterOpportunitySummary,
  ResearchCenterResearchSummary,
  ResearchCenterResponse,
} from "../../api/types";
import { ResearchCenterDeliveryPanel } from "./ResearchCenterDeliveryPanel";
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

function makePipeline(
  overrides: Partial<ResearchCenterDeliveryPipeline> = {},
): ResearchCenterDeliveryPipeline {
  return {
    state: "empty",
    status: null,
    started_at: null,
    finished_at: null,
    business_completion_date: null,
    freshness_at: null,
    source: null,
    reason: null,
    ...overrides,
  };
}

function makeIntegration(
  overrides: Partial<ResearchCenterDeliveryIntegration> = {},
): ResearchCenterDeliveryIntegration {
  return {
    state: "empty",
    status: null,
    sample_size: null,
    producer_status_counts: null,
    intake_status_counts: null,
    latest_as_of: null,
    freshness_at: null,
    source: null,
    reason: null,
    ...overrides,
  };
}

function makeArchive(
  overrides: Partial<ResearchCenterDeliveryArchive> = {},
): ResearchCenterDeliveryArchive {
  return {
    state: "empty",
    artifact_count: null,
    latest_run_status: null,
    latest_as_of: null,
    freshness_at: null,
    source: null,
    reason: null,
    ...overrides,
  };
}

function makeResearchRuns(
  overrides: Partial<ResearchCenterDeliveryResearchRuns> = {},
): ResearchCenterDeliveryResearchRuns {
  return {
    state: "empty",
    run_count: null,
    status_counts: null,
    latest_status: null,
    latest_started_at: null,
    latest_finished_at: null,
    freshness_at: null,
    source: null,
    reason: null,
    ...overrides,
  };
}

function makeDelivery(
  overrides: Partial<ResearchCenterDelivery> = {},
): ResearchCenterDelivery {
  return {
    schema_version: "1.0.0",
    pipeline: makePipeline(),
    integration: makeIntegration(),
    archive: makeArchive(),
    research_runs: makeResearchRuns(),
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

describe("ResearchCenterDeliveryPanel", () => {
  it("renders the loading state when the source query is pending", () => {
    render(<ResearchCenterDeliveryPanel query={pendingQuery()} />);

    expect(
      screen.getByText("正在加载 Research Center 交付链"),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Pipeline 只读摘要"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Integration Health 只读摘要"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Archive 只读摘要"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Research Runs 只读摘要"),
    ).not.toBeInTheDocument();
  });

  it("renders an HTTP error state when the source query fails", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={errorQuery(new ApiError("research-center 503", 503))}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("无法读取 Research Center 交付链");
    expect(alert).toHaveTextContent("research-center 503");
  });

  it("renders every sub-card with bounded fields and existing detail links", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            state: "available",
            market: makeMarket({ state: "available" }),
            delivery: makeDelivery({
              pipeline: {
                state: "available",
                status: "succeeded",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: "2026-08-15T01:30:00Z",
                business_completion_date: "2026-08-15",
                freshness_at: null,
                source: null,
                reason: null,
              },
              integration: {
                state: "available",
                status: "healthy",
                sample_size: 5,
                producer_status_counts: { ok: 5 },
                intake_status_counts: { imported: 5 },
                latest_as_of: "2026-08-15",
                freshness_at: null,
                source: null,
                reason: null,
              },
              archive: {
                state: "available",
                artifact_count: 12,
                latest_run_status: "succeeded",
                latest_as_of: "2026-08-15",
                freshness_at: null,
                source: null,
                reason: null,
              },
              research_runs: {
                state: "available",
                run_count: 3,
                status_counts: { succeeded: 3 },
                latest_status: "succeeded",
                latest_started_at: "2026-08-15T00:00:00Z",
                latest_finished_at: "2026-08-15T00:30:00Z",
                freshness_at: null,
                source: null,
                reason: null,
              },
            }),
          }),
        )}
      />,
    );

    const pipeline = screen.getByLabelText("Pipeline 只读摘要");
    expect(pipeline).toHaveAttribute("data-state", "available");
    expect(
      within(pipeline).getByRole("status", { name: "Pipeline 状态 available" }),
    ).toHaveTextContent("已完成最新一次 Pipeline");
    expect(within(pipeline).getByText("succeeded")).toBeInTheDocument();
    expect(within(pipeline).getByText("business_completion_date")).toBeInTheDocument();
    expect(within(pipeline).getByText("2026-08-15")).toBeInTheDocument();
    expect(
      within(pipeline).getByRole("link", { name: "查看 Pipeline 运行详情" }),
    ).toHaveAttribute("href", "/operations");

    const integration = screen.getByLabelText("Integration Health 只读摘要");
    expect(integration).toHaveAttribute("data-state", "available");
    expect(
      within(integration).getByRole("status", {
        name: "Integration Health 状态 available",
      }),
    ).toHaveTextContent("外部工作流健康度可展示");
    expect(within(integration).getByText("sample_size")).toBeInTheDocument();
    expect(within(integration).getByText("5")).toBeInTheDocument();
    expect(within(integration).getByText("latest_as_of")).toBeInTheDocument();
    expect(within(integration).getByText("healthy · 外部工作流整体健康")).toBeInTheDocument();
    expect(
      within(integration).getByRole("link", {
        name: "查看 Integration Health 详情",
      }),
    ).toHaveAttribute("href", "/automation");

    const archive = screen.getByLabelText("Archive 只读摘要");
    expect(archive).toHaveAttribute("data-state", "available");
    expect(
      within(archive).getByRole("status", { name: "Archive 状态 available" }),
    ).toHaveTextContent("已记录最新归档");
    expect(within(archive).getByText("artifact_count")).toBeInTheDocument();
    expect(within(archive).getByText("12")).toBeInTheDocument();
    expect(
      within(archive).getByRole("link", { name: "查看 Archive 详情" }),
    ).toHaveAttribute("href", "/automation");

    const runs = screen.getByLabelText("Research Runs 只读摘要");
    expect(runs).toHaveAttribute("data-state", "available");
    expect(
      within(runs).getByRole("status", {
        name: "Research Runs 状态 available",
      }),
    ).toHaveTextContent("已观测 Research Run");
    expect(within(runs).getByText("run_count")).toBeInTheDocument();
    expect(within(runs).getByText("latest_status")).toBeInTheDocument();
    expect(
      within(runs).getByRole("link", { name: "查看 Research Run 历史" }),
    ).toHaveAttribute("href", "/research/history");
  });

  it("renders the empty state for each sub-card with stable wording", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({ state: "empty" }),
              integration: makeIntegration({ state: "empty" }),
              archive: makeArchive({ state: "empty" }),
              research_runs: makeResearchRuns({ state: "empty" }),
            }),
          }),
        )}
      />,
    );

    const pipeline = screen.getByLabelText("Pipeline 只读摘要");
    expect(pipeline).toHaveAttribute("data-state", "empty");
    expect(
      within(pipeline).getByRole("status", { name: "Pipeline 状态 empty" }),
    ).toHaveTextContent("尚无 Pipeline 运行");
    expect(
      within(pipeline).getByRole("link", { name: "查看 Pipeline 运行详情" }),
    ).toHaveAttribute("href", "/operations");

    const integration = screen.getByLabelText("Integration Health 只读摘要");
    expect(integration).toHaveAttribute("data-state", "empty");
    expect(
      within(integration).getByRole("status", {
        name: "Integration Health 状态 empty",
      }),
    ).toHaveTextContent("尚无外部运行");
    expect(
      within(integration).getByRole("link", {
        name: "查看 Integration Health 详情",
      }),
    ).toHaveAttribute("href", "/automation");

    const archive = screen.getByLabelText("Archive 只读摘要");
    expect(archive).toHaveAttribute("data-state", "empty");
    expect(
      within(archive).getByRole("status", { name: "Archive 状态 empty" }),
    ).toHaveTextContent("尚无归档产物");
    expect(
      within(archive).getByRole("link", { name: "查看 Archive 详情" }),
    ).toHaveAttribute("href", "/automation");

    const runs = screen.getByLabelText("Research Runs 只读摘要");
    expect(runs).toHaveAttribute("data-state", "empty");
    expect(
      within(runs).getByRole("status", { name: "Research Runs 状态 empty" }),
    ).toHaveTextContent("尚无 Research Run");
    expect(
      within(runs).getByRole("link", { name: "查看 Research Run 历史" }),
    ).toHaveAttribute("href", "/research/history");
  });

  it("renders running and partial pipeline states with bounded timestamps only", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "running",
                status: "running",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: null,
                business_completion_date: null,
              }),
            }),
          }),
        )}
      />,
    );

    const pipeline = screen.getByLabelText("Pipeline 只读摘要");
    expect(pipeline).toHaveAttribute("data-state", "running");
    expect(
      within(pipeline).getByRole("status", { name: "Pipeline 状态 running" }),
    ).toHaveTextContent("在飞");
    expect(within(pipeline).getAllByText("running").length).toBeGreaterThanOrEqual(2);
    const emdashes = within(pipeline).getAllByText("—");
    expect(emdashes.length).toBeGreaterThanOrEqual(2);

    cleanup();

    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "partial",
                status: "partial",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: "2026-08-15T01:30:00Z",
                business_completion_date: "2026-08-15",
              }),
            }),
          }),
        )}
      />,
    );

    const partial = screen.getByLabelText("Pipeline 只读摘要");
    expect(partial).toHaveAttribute("data-state", "partial");
    expect(
      within(partial).getByRole("status", { name: "Pipeline 状态 partial" }),
    ).toHaveTextContent("部分结果已落地");
    expect(within(partial).getAllByText("partial").length).toBeGreaterThanOrEqual(2);
    expect(within(partial).getByText("2026-08-15")).toBeInTheDocument();
  });

  it("renders failed sub-cards with sanitized reason and no run_id, URI or raw error text", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "failed",
                status: "failed",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: "2026-08-15T01:30:00Z",
                business_completion_date: null,
                reason: "pipeline_query_failed",
              }),
              integration: makeIntegration({
                state: "failed",
                reason: "integration_health_query_failed",
              }),
              archive: makeArchive({
                state: "failed",
                reason: "archive_query_failed",
                artifact_count: 999,
              }),
              research_runs: makeResearchRuns({
                state: "failed",
                reason: "research_runs_query_failed",
                run_count: 999,
              }),
            }),
          }),
        )}
      />,
    );

    const pipeline = screen.getByLabelText("Pipeline 只读摘要");
    expect(pipeline).toHaveAttribute("data-state", "failed");
    expect(
      within(pipeline).getByRole("status", { name: "Pipeline 状态 failed" }),
    ).toHaveTextContent("受控查询失败");
    expect(
      within(pipeline).getByText("Pipeline · failed"),
    ).toBeInTheDocument();
    expect(
      within(pipeline).getByText("内部原因：pipeline_query_failed"),
    ).toBeInTheDocument();
    expect(
      within(pipeline).queryByText(/DatabaseError|SQLAlchemy|Traceback/),
    ).not.toBeInTheDocument();

    const integration = screen.getByLabelText("Integration Health 只读摘要");
    expect(integration).toHaveAttribute("data-state", "failed");
    expect(
      within(integration).getByText(
        "内部原因：integration_health_query_failed",
      ),
    ).toBeInTheDocument();
    expect(within(integration).queryByText("sample_size")).not.toBeInTheDocument();
    expect(within(integration).queryByText("999")).not.toBeInTheDocument();

    const archive = screen.getByLabelText("Archive 只读摘要");
    expect(archive).toHaveAttribute("data-state", "failed");
    expect(
      within(archive).getByText("内部原因：archive_query_failed"),
    ).toBeInTheDocument();
    expect(within(archive).queryByText("artifact_count")).not.toBeInTheDocument();
    expect(within(archive).queryByText("999")).not.toBeInTheDocument();

    const runs = screen.getByLabelText("Research Runs 只读摘要");
    expect(runs).toHaveAttribute("data-state", "failed");
    expect(
      within(runs).getByText("内部原因：research_runs_query_failed"),
    ).toBeInTheDocument();
    expect(within(runs).queryByText("run_count")).not.toBeInTheDocument();
    expect(within(runs).queryByText("999")).not.toBeInTheDocument();
  });

  it("never surfaces run_id, URI, payload, metadata or host-path style strings on success", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "available",
                status: "succeeded",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: "2026-08-15T01:30:00Z",
                business_completion_date: "2026-08-15",
                reason: null,
              }),
              integration: makeIntegration({
                state: "available",
                status: "healthy",
                sample_size: 2,
                producer_status_counts: { ok: 2 },
                intake_status_counts: { imported: 2 },
                latest_as_of: "2026-08-15",
                reason: null,
              }),
              archive: makeArchive({
                state: "available",
                artifact_count: 3,
                latest_run_status: "succeeded",
                latest_as_of: "2026-08-15",
                reason: null,
              }),
              research_runs: makeResearchRuns({
                state: "available",
                run_count: 1,
                status_counts: { succeeded: 1 },
                latest_status: "succeeded",
                latest_started_at: "2026-08-15T00:00:00Z",
                latest_finished_at: "2026-08-15T00:30:00Z",
                reason: null,
              }),
            }),
          }),
        )}
      />,
    );

    const forbidden = [
      "run_id",
      "artifact",
      "uri",
      "payload",
      "metadata",
      "host",
      "credential",
      "/var/run/workbuddy",
      "/tmp/jiuwen",
      "Bearer ",
      "11111111-1111-1111-1111-111111111111",
      "pack-001",
      "case-001",
    ];
    const panel = screen.getByLabelText("Research Center 交付链摘要");
    for (const token of forbidden) {
      expect(within(panel).queryByText(token)).not.toBeInTheDocument();
    }
  });

  it("keeps the other sub-cards renderable when one delivery sub-segment fails", () => {
    render(
      <ResearchCenterDeliveryPanel
        query={successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "failed",
                reason: "pipeline_query_failed",
              }),
              integration: makeIntegration({
                state: "available",
                status: "healthy",
                sample_size: 4,
                latest_as_of: "2026-08-15",
              }),
              archive: makeArchive({
                state: "available",
                artifact_count: 2,
                latest_run_status: "succeeded",
                latest_as_of: "2026-08-15",
              }),
              research_runs: makeResearchRuns({
                state: "empty",
              }),
            }),
          }),
        )}
      />,
    );

    expect(
      screen.getByLabelText("Pipeline 只读摘要"),
    ).toHaveAttribute("data-state", "failed");
    expect(
      screen.getByLabelText("Integration Health 只读摘要"),
    ).toHaveAttribute("data-state", "available");
    expect(
      screen.getByLabelText("Archive 只读摘要"),
    ).toHaveAttribute("data-state", "available");
    expect(
      screen.getByLabelText("Research Runs 只读摘要"),
    ).toHaveAttribute("data-state", "empty");
  });

  it("does not refetch or write anything when the panel renders", () => {
    const fetchSpy = vi.fn();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    try {
      const refetch = vi.fn(() => Promise.resolve({} as never));
      const query = {
        ...successQuery(
          makeResponse({
            delivery: makeDelivery({
              pipeline: makePipeline({
                state: "available",
                status: "succeeded",
                started_at: "2026-08-15T01:00:00Z",
                finished_at: "2026-08-15T01:30:00Z",
                business_completion_date: "2026-08-15",
                reason: null,
              }),
            }),
          }),
        ),
        refetch,
      } as UseQueryResult<ResearchCenterResponse, Error>;

      render(<ResearchCenterDeliveryPanel query={query} />);

      expect(
        screen.getByLabelText("Pipeline 只读摘要"),
      ).toHaveAttribute("data-state", "available");
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(refetch).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});