import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type {
  CandidatePoolDiffResponse,
  CandidatePoolItem,
  CandidatePoolLatestResponse,
  PipelineRunResponse,
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
  ResearchDashboardResponse,
  ResearchRunResponse,
} from "../api/types";
import { Router } from "../router";

vi.mock("../api/candidatePool", () => ({
  fetchCandidatePoolLatest: vi.fn(),
  fetchCandidatePoolLatestDiff: vi.fn(),
  latestCandidatePoolQueryKey: ["candidate-pool", "latest"],
  latestCandidateDiffQueryKey: ["candidate-pool", "latest", "diff"],
}));

vi.mock("../api/pipelineRuns", () => ({
  fetchLatestPipelineRun: vi.fn(),
  fetchPipelineRuns: vi.fn(),
  latestPipelineRunQueryKey: ["pipeline-runs", "latest"],
  pipelineRunsQueryKey: vi.fn(),
}));

vi.mock("../api/researchDashboard", () => ({
  fetchResearchDashboard: vi.fn(),
  useResearchDashboard: vi.fn(),
  researchDashboardQueryKey: ["research-dashboard"],
  RESEARCH_DASHBOARD_REFETCH_INTERVAL: 60_000,
}));

vi.mock("../api/researchCenter", () => ({
  fetchResearchCenter: vi.fn(),
  useResearchCenter: vi.fn(),
  researchCenterQueryKey: ["research-center"],
  RESEARCH_CENTER_REFETCH_INTERVAL: 60_000,
}));

vi.mock("../api/integrationHealth", () => ({
  fetchIntegrationHealth: vi.fn(),
  integrationHealthQueryKey: ["integration", "health"],
}));

import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { fetchIntegrationHealth } from "../api/integrationHealth";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import {
  useResearchDashboard,
} from "../api/researchDashboard";
import {
  useResearchCenter,
} from "../api/researchCenter";
import {
  errorQuery,
  pendingQuery,
  successQuery,
} from "../features/research/dashboard/test-helpers";
import { DashboardPage } from "./DashboardPage";

const mockFetchLatestPool = vi.mocked(fetchCandidatePoolLatest);
const mockFetchLatestDiff = vi.mocked(fetchCandidatePoolLatestDiff);
const mockFetchLatestRun = vi.mocked(fetchLatestPipelineRun);
const mockFetchIntegrationHealth = vi.mocked(fetchIntegrationHealth);
const mockUseResearchDashboard = vi.mocked(useResearchDashboard);
const mockUseResearchCenter = vi.mocked(useResearchCenter);

function neverResolvingPromise<T>(): Promise<T> {
  return new Promise<T>(() => {
    /* intentionally never resolves */
  });
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
    algorithm_version: "2.0.0",
    observations: [],
    scope_key: "ashare_active_universe_v1",
    scope_type: "ashare_universe",
    snapshot_id: "55555555-5555-5555-5555-555555555555",
    ...overrides,
    state: "available",
  };
}

function makeFreshness(
  overrides: Partial<ResearchCenterDataFreshness> = {},
): ResearchCenterDataFreshness {
  return {
    checked_at: "2026-08-03T12:00:00Z",
    daily_bar_count: 45,
    latest_published_trade_date: "2026-08-02",
    missing_count: 1,
    state: "available",
    status: "fresh",
    universe_count: 50,
    ...overrides,
  };
}

function makeMarket(
  overrides: Partial<ResearchCenterMarket> = {},
): ResearchCenterMarket {
  return {
    as_of_date: "2026-08-02",
    breadth: null,
    data_freshness: makeFreshness(),
    freshness_status: "fresh",
    quality_status: "complete",
    state: "available",
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

function makeResearchCenter(
  overrides: Partial<ResearchCenterResponse> = {},
): ResearchCenterResponse {
  return {
    schema_version: "1.0.0",
    generated_at: "2026-08-03T12:00:00Z",
    state: "available",
    market: makeMarket(),
    capabilities: makeCapabilities(),
    candidate_pool: makeCandidatePoolSummary(),
    opportunities: makeOpportunitySummary(),
    research: makeResearchSummary(),
    delivery: makeDelivery(),
    ...overrides,
  };
}

function makePoolItem(
  rank: number,
  symbol: string,
  options: Partial<CandidatePoolItem> = {},
): CandidatePoolItem {
  return {
    exchange: "SH",
    exclusion_reasons: [],
    included: true,
    instrument_id: `${rank.toString().padStart(3, "0")}-${symbol}`,
    metrics: { turnover: "1234567.89" },
    name: `名称 ${symbol}`,
    rank,
    rule_results: [],
    symbol,
    total_score: "0.85",
    ...options,
  };
}

function makePoolResponse(
  itemCount: number,
  options: { includedCount?: number; rowCount?: number } = {},
): CandidatePoolLatestResponse {
  const items: CandidatePoolItem[] = [];
  for (let i = 1; i <= itemCount; i += 1) {
    items.push(makePoolItem(i, `E${i.toString().padStart(3, "0")}`));
  }
  return {
    algorithm_key: "personal-etf-default",
    algorithm_version: "1.0.0",
    content_hash: "deadbeef",
    excluded_count: 0,
    included_count: options.includedCount ?? itemCount,
    items,
    parameter_set_key: "default-params",
    published_at: "2026-08-03T12:00:00Z",
    row_count: options.rowCount ?? itemCount,
    run_id: "33333333-3333-3333-3333-333333333333",
    snapshot_id: "44444444-4444-4444-4444-444444444444",
    trade_date: "2026-08-02",
  };
}

function makeDiffResponse(
  overrides: Partial<CandidatePoolDiffResponse> = {},
): CandidatePoolDiffResponse {
  return {
    added: [],
    previous_trade_date: "2026-08-01",
    removed: [],
    retained: [],
    trade_date: "2026-08-02",
    ...overrides,
  };
}

function makeRunResponse(
  overrides: Partial<PipelineRunResponse> = {},
): PipelineRunResponse {
  return {
    error_code: null,
    error_summary: null,
    finished_at: "2026-08-03T12:30:00Z",
    id: "55555555-5555-5555-5555-555555555555",
    job_key: "personal_etf_daily_job",
    partition_key: "2026-08-02",
    started_at: "2026-08-03T12:00:00Z",
    status: "success",
    trigger_type: "manual",
    ...overrides,
  };
}

function makeResearchDashboard(
  overrides: Partial<ResearchDashboardResponse> = {},
): ResearchDashboardResponse {
  return {
    schema_version: "1.0.0",
    generated_at: "2026-08-03T12:00:00Z",
    as_of_date: null,
    data_quality: "empty",
    freshness: "unknown",
    market_status: {
      state: "unavailable",
      reason: "no market dashboard source registered",
    },
    research_summary: {
      case_count: 0,
      run_count: 0,
      latest_case: null,
    },
    evidence_status: {
      state: "empty",
      case_id: null,
      pack_id: null,
      schema_version: null,
      factor_set_key: null,
      factor_set_version: null,
      quality_status: null,
      freshness_status: null,
    },
    recent_runs: [],
    ...overrides,
  };
}

function makeResearchRun(
  overrides: Partial<ResearchRunResponse> = {},
): ResearchRunResponse {
  return {
    attempt: 1,
    case_id: "case-001",
    error_summary: null,
    evidence_pack_id: "pack-001",
    finished_at: "2026-08-03T12:30:00Z",
    playbook_key: "playbook.default",
    run_id: "run-001",
    runner_key: "runner.default",
    started_at: "2026-08-03T12:00:00Z",
    status: "succeeded",
    ...overrides,
  };
}

function renderWithClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <Router routes={[{ path: "/dashboard", element: null }]}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Router>
    );
  }
  return render(<DashboardPage />, { wrapper: Wrapper });
}

function configureResearchDashboard(
  result: ReturnType<typeof successQuery<ResearchDashboardResponse>>,
) {
  mockUseResearchDashboard.mockReturnValue(result);
}

function configureResearchCenter(
  result: ReturnType<typeof successQuery<ResearchCenterResponse>>,
) {
  mockUseResearchCenter.mockReturnValue(result);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DashboardPage", () => {
  describe("initial loading", () => {
    it("renders the loading state when all queries are pending", () => {
      mockFetchLatestPool.mockReturnValue(neverResolvingPromise());
      mockFetchLatestDiff.mockReturnValue(neverResolvingPromise());
      mockFetchLatestRun.mockReturnValue(neverResolvingPromise());
      mockUseResearchDashboard.mockReturnValue(pendingQuery());
      mockUseResearchCenter.mockReturnValue(pendingQuery());

      renderWithClient();

      expect(
        screen.getByText("正在加载 Dashboard 数据"),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "个人 ETF 数据工作台" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("successful render", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(15));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchDashboard(successQuery(makeResearchDashboard()));
      configureResearchCenter(successQuery(makeResearchCenter()));
    });

    it("renders the page header and every preserved section once data resolves", async () => {
      renderWithClient();

      expect(
        await screen.findByRole("heading", { name: "个人 ETF 数据工作台" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Research Center 市场状态" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Research Center 子视图" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Research Center 交付链" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "候选池变化" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "最新候选" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "最新运行" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Research Cockpit" }),
      ).toBeInTheDocument();

      // The duplicate sections must be gone now that the center panel takes over.
      expect(
        screen.queryByRole("region", { name: "数据状态" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "关键指标" }),
      ).not.toBeInTheDocument();
    });

    it("renders the Research Center market-status panel with dates and provenance", async () => {
      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });

      expect(
        within(region).getByText(
          "Read API · /api/v1/research-center · schema 1.0.0",
        ),
      ).toBeInTheDocument();
      const stateLine = within(region).getByRole("status", { name: "市场状态 available" });
      expect(stateLine.textContent ?? "").toContain("市场广度与数据新鲜度均可展示");
      expect(within(region).getAllByText("2026-08-02").length).toBeGreaterThanOrEqual(1);
    });

    it("only displays the top 10 included candidates sorted by rank", async () => {
      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新候选" });

      await waitFor(() => {
        const rows = within(region).getAllByRole("row");
        expect(rows).toHaveLength(11);
      });

      const table = within(region).getByRole("table");

      for (let i = 1; i <= 10; i += 1) {
        expect(within(table).getByText(String(i))).toBeInTheDocument();
      }
      for (let i = 11; i <= 15; i += 1) {
        expect(within(table).queryByText(String(i))).not.toBeInTheDocument();
      }

      expect(
        within(region).getByText(/共\s*15\s*只\s*·\s*入选\s*15/),
      ).toBeInTheDocument();
    });

    it("displays the pipeline run with its status pill and metadata", async () => {
      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新运行" });

      await waitFor(() => {
        expect(within(region).getByText("success")).toBeInTheDocument();
      });
      expect(within(region).getByText("manual")).toBeInTheDocument();
    });
  });

  describe("research-center section", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchDashboard(successQuery(makeResearchDashboard()));
    });

    it("renders the loading placeholder while the Research Center query is pending", async () => {
      configureResearchCenter(pendingQuery());

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });
      expect(
        within(region).getByText("正在加载 Research Center 市场状态"),
      ).toBeInTheDocument();
    });

    it("renders the HTTP error state when the Research Center query fails", async () => {
      configureResearchCenter(
        errorQuery(new ApiError("research-center 503", 503)),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });
      const alert = await within(region).findByRole("alert");
      expect(alert).toHaveTextContent("无法读取 Research Center 市场状态");
      expect(within(region).getByText("research-center 503")).toBeInTheDocument();
    });

    it("renders the empty unavailable state when both sub-sources are missing", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            state: "unavailable",
            market: makeMarket({
              state: "unavailable",
              data_freshness: null,
            }),
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });
      expect(within(region).getByLabelText("市场广度")).toHaveTextContent(
        "市场广度 · unavailable",
      );
      expect(within(region).getByLabelText("数据新鲜度")).toHaveTextContent(
        "数据新鲜度 · unavailable",
      );
    });

    it("renders explicit text for the controlled failed state when both sources failed", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            state: "failed",
            market: makeMarket({
              state: "failed",
              breadth: null,
              data_freshness: null,
              quality_status: null,
              freshness_status: null,
            }),
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });
      expect(within(region).getByText("failed")).toBeInTheDocument();
      expect(
        within(region).getByText(/failed · 受控查询失败/),
      ).toBeInTheDocument();
    });

    it("renders the backend-valid unavailable wire shape with sentinel counts without surfacing them as metrics", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            state: "unavailable",
            market: {
              as_of_date: null,
              breadth: null,
              data_freshness: {
                checked_at: "2026-08-12T01:30:00Z",
                daily_bar_count: 0,
                latest_published_trade_date: null,
                missing_count: 0,
                state: "unavailable",
                status: "missing",
                universe_count: 0,
              },
              freshness_status: "missing",
              quality_status: null,
              state: "unavailable",
            },
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 市场状态",
      });
      const panel = within(region).getByLabelText(
        "Research Center 市场状态",
      );
      expect(panel).toHaveAttribute("data-state", "unavailable");
      expect(
        within(region).getByText(/unavailable · 两个市场来源均无可展示结果/),
      ).toBeInTheDocument();

      const freshness = screen.getByLabelText("数据新鲜度");
      expect(within(freshness).getByText("missing")).toBeInTheDocument();
      expect(within(freshness).getByText("unavailable")).toBeInTheDocument();
      expect(
        within(freshness).getByText(/missing · 尚无发布结果/),
      ).toBeInTheDocument();
      expect(
        within(freshness).getByText("数据新鲜度 · unavailable / missing"),
      ).toBeInTheDocument();
      expect(
        within(freshness).queryByText("0 只"),
      ).not.toBeInTheDocument();

      expect(screen.getByLabelText("候选池变化")).toBeInTheDocument();
      expect(screen.getByLabelText("最新候选")).toBeInTheDocument();
      expect(screen.getByLabelText("最新运行")).toBeInTheDocument();
      expect(screen.getByLabelText("Research Cockpit")).toBeInTheDocument();
    });
  });

  describe("research-center subviews section", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchDashboard(successQuery(makeResearchDashboard()));
    });

    it("mounts the subviews section that consumes the shared Research Center query", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            candidate_pool: makeCandidatePoolSummary({
              state: "available",
              trade_date: "2026-08-02",
              input_row_count: 100,
              included_count: 80,
              excluded_count: 20,
            }),
            opportunities: makeOpportunitySummary({
              state: "available",
              observation_count: 7,
              latest_as_of: "2026-08-02",
              admission_status_counts: { admitted: 7 },
            }),
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 子视图",
      });
      const pool = within(region).getByLabelText("Candidate Pool 只读摘要");
      expect(pool).toHaveAttribute("data-state", "available");
      const radar = within(region).getByLabelText("Opportunity Radar 只读摘要");
      expect(radar).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByRole("link", { name: "查看 Candidate Pool 详情" }),
      ).toHaveAttribute("href", "/candidate-pool");
      expect(
        within(region).getByRole("link", {
          name: "查看 Opportunity Radar 详情",
        }),
      ).toHaveAttribute("href", "/opportunity-radar");
    });

    it("renders the shared loading placeholder while the Research Center query is pending", async () => {
      configureResearchCenter(pendingQuery());

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 子视图",
      });
      expect(
        within(region).getByText("正在加载 Research Center 子视图"),
      ).toBeInTheDocument();
    });
  });

  describe("research-center delivery section", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchDashboard(successQuery(makeResearchDashboard()));
    });

    it("mounts the delivery section that consumes the shared Research Center query", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            delivery: makeDelivery({
              pipeline: {
                state: "available",
                status: "succeeded",
                started_at: "2026-08-02T01:00:00Z",
                finished_at: "2026-08-02T01:30:00Z",
                business_completion_date: "2026-08-02",
                reason: null,
              },
              integration: {
                state: "available",
                status: "healthy",
                sample_size: 5,
                producer_status_counts: { ok: 5 },
                intake_status_counts: { imported: 5 },
                latest_as_of: "2026-08-02",
                reason: null,
              },
              archive: {
                state: "available",
                artifact_count: 12,
                latest_run_status: "succeeded",
                latest_as_of: "2026-08-02",
                reason: null,
              },
              research_runs: {
                state: "available",
                run_count: 3,
                status_counts: { succeeded: 3 },
                latest_status: "succeeded",
                latest_started_at: "2026-08-02T00:00:00Z",
                latest_finished_at: "2026-08-02T00:30:00Z",
                reason: null,
              },
            }),
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 交付链",
      });
      expect(
        within(region).getByLabelText("Pipeline 只读摘要"),
      ).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByLabelText("Integration Health 只读摘要"),
      ).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByLabelText("Archive 只读摘要"),
      ).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByLabelText("Research Runs 只读摘要"),
      ).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByRole("link", { name: "查看 Pipeline 运行详情" }),
      ).toHaveAttribute("href", "/operations");
      expect(
        within(region).getByRole("link", {
          name: "查看 Integration Health 详情",
        }),
      ).toHaveAttribute("href", "/automation");
      expect(
        within(region).getByRole("link", { name: "查看 Archive 详情" }),
      ).toHaveAttribute("href", "/automation");
      expect(
        within(region).getByRole("link", { name: "查看 Research Run 历史" }),
      ).toHaveAttribute("href", "/research/history");
    });

    it("renders the shared loading placeholder while the Research Center query is pending", async () => {
      configureResearchCenter(pendingQuery());

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 交付链",
      });
      expect(
        within(region).getByText("正在加载 Research Center 交付链"),
      ).toBeInTheDocument();
    });

    it("renders the HTTP error state when the Research Center query fails", async () => {
      configureResearchCenter(
        errorQuery(new ApiError("research-center 503", 503)),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 交付链",
      });
      const alert = await within(region).findByRole("alert");
      expect(alert).toHaveTextContent("无法读取 Research Center 交付链");
      expect(
        within(region).getByText("research-center 503"),
      ).toBeInTheDocument();
    });

    it("does not introduce additional fetches or browser writes when rendering the delivery section", async () => {
      const fetchSpy = vi.fn();
      const originalFetch = globalThis.fetch;
      globalThis.fetch = fetchSpy as unknown as typeof fetch;
      mockFetchIntegrationHealth.mockReturnValue(neverResolvingPromise());

      try {
        configureResearchCenter(
          successQuery(
            makeResearchCenter({
              delivery: makeDelivery({
                pipeline: {
                  state: "available",
                  status: "succeeded",
                  started_at: "2026-08-02T01:00:00Z",
                  finished_at: "2026-08-02T01:30:00Z",
                  business_completion_date: "2026-08-02",
                  reason: null,
                },
              }),
            }),
          ),
        );

        renderWithClient();

        const region = await screen.findByRole("region", {
          name: "Research Center 交付链",
        });
        expect(
          within(region).getByLabelText("Pipeline 只读摘要"),
        ).toHaveAttribute("data-state", "available");
        expect(fetchSpy).not.toHaveBeenCalled();
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  describe("other panels", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchDashboard(successQuery(makeResearchDashboard()));
      configureResearchCenter(successQuery(makeResearchCenter()));
    });

    it("renders the empty state in TopCandidatesPanel when the candidate pool returns 404", async () => {
      mockFetchLatestPool.mockRejectedValue(
        new ApiError("Candidate pool not found", 404),
      );

      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新候选" });

      await waitFor(() => {
        expect(within(region).getByText("尚无候选结果")).toBeInTheDocument();
      });
      expect(within(region).queryByRole("alert")).not.toBeInTheDocument();
    });

    it("renders the error state in LatestRunPanel when the pipeline run fails with a non-404 status", async () => {
      mockFetchLatestRun.mockRejectedValue(
        new ApiError("Pipeline service unavailable", 503),
      );

      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新运行" });

      await waitFor(() => {
        const alert = within(region).getByRole("alert");
        expect(alert).toHaveTextContent("无法读取最新运行");
      });
      expect(
        within(region).getByText("Pipeline service unavailable"),
      ).toBeInTheDocument();
    });
  });

  describe("research cockpit section", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
      configureResearchCenter(successQuery(makeResearchCenter()));
    });

    it("renders six research cockpit widgets with empty default state", async () => {
      configureResearchDashboard(successQuery(makeResearchDashboard()));

      renderWithClient();

      const section = await screen.findByRole("region", {
        name: "Research Cockpit",
      });

      expect(within(section).getByText("Market Status")).toBeInTheDocument();
      expect(
        within(section).getByText("Research Summary"),
      ).toBeInTheDocument();
      expect(within(section).getByText("Evidence Pack")).toBeInTheDocument();
      expect(
        within(section).getByText("Factor Snapshot"),
      ).toBeInTheDocument();
      expect(
        within(section).getByText("Research Run Timeline"),
      ).toBeInTheDocument();
      expect(within(section).getByText("Risk Monitor")).toBeInTheDocument();

      const market = await within(section).findByText(
        "reason: no market dashboard source registered",
      );
      expect(market).toBeInTheDocument();
      const factor = section.querySelector(
        '[data-widget-id="factor-snapshot"]',
      ) as HTMLElement;
      const risk = section.querySelector(
        '[data-widget-id="risk-monitor"]',
      ) as HTMLElement;
      expect(factor).toHaveTextContent("Factor Snapshot · unavailable");
      expect(risk).toHaveTextContent("Risk Monitor · unavailable");
      expect(factor.textContent ?? "").not.toMatch(/buy|sell|position/i);
      expect(risk.textContent ?? "").not.toMatch(/buy|sell|position/i);
    });

    it("renders available summary, evidence and recent runs when the dashboard is populated", async () => {
      configureResearchDashboard(
        successQuery(
          makeResearchDashboard({
            as_of_date: "2026-08-08",
            data_quality: "partial",
            freshness: "current",
            research_summary: {
              case_count: 2,
              run_count: 4,
              latest_case: {
                case_id: "case-1",
                instrument_id: "inst-1",
                as_of_date: "2026-08-08",
                question: "趋势通道判断",
                horizon: "30d",
                status: "open",
                created_at: "2026-08-09T00:00:00Z",
                candidate_pool_run_id: null,
                closed_at: null,
              },
            },
            evidence_status: {
              state: "available",
              case_id: "case-1",
              pack_id: "pack-1",
              schema_version: "1.0.0",
              factor_set_key: "factor.basic",
              factor_set_version: "1",
              quality_status: "ok",
              freshness_status: "current",
            },
            recent_runs: [
              makeResearchRun({
                run_id: "run-1",
                status: "succeeded",
              }),
              makeResearchRun({
                run_id: "run-2",
                status: "failed",
              }),
            ],
          }),
        ),
      );

      renderWithClient();

      const section = await screen.findByRole("region", {
        name: "Research Cockpit",
      });

      const caseId = await within(section).findByText("case-1");
      expect(caseId).toBeInTheDocument();
      expect(
        within(section).getByText("趋势通道判断"),
      ).toBeInTheDocument();
      expect(within(section).getByText("pack-1")).toBeInTheDocument();
      const table = within(section).getByRole("table");
      expect(within(table).getByText("run-1")).toBeInTheDocument();
      expect(within(table).getByText("run-2")).toBeInTheDocument();
      expect(within(table).getByText("succeeded")).toBeInTheDocument();
      expect(within(table).getByText("failed")).toBeInTheDocument();
      expect(within(section).queryByText("Stance")).not.toBeInTheDocument();
      expect(
        within(section).queryByText("Confidence"),
      ).not.toBeInTheDocument();
    });

    it("renders explicit unavailable states for factor-snapshot and risk-monitor widgets regardless of payload", async () => {
      configureResearchDashboard(
        successQuery(
          makeResearchDashboard({
            data_quality: "complete",
            freshness: "current",
            research_summary: {
              case_count: 5,
              run_count: 9,
              latest_case: null,
            },
          }),
        ),
      );

      renderWithClient();

      const section = await screen.findByRole("region", {
        name: "Research Cockpit",
      });
      await waitFor(() => {
        const factor = section.querySelector(
          '[data-widget-id="factor-snapshot"]',
        ) as HTMLElement;
        expect(factor).toHaveTextContent("Factor Snapshot · unavailable");
      });
      const risk = section.querySelector(
        '[data-widget-id="risk-monitor"]',
      ) as HTMLElement;
      expect(risk).toHaveTextContent("Risk Monitor · unavailable");
    });

    it("renders an empty recent-runs placeholder when the dashboard returns no runs", async () => {
      configureResearchDashboard(successQuery(makeResearchDashboard()));

      renderWithClient();

      const section = await screen.findByRole("region", {
        name: "Research Cockpit",
      });
      expect(
        await within(section).findByText("Recent Runs · 空"),
      ).toBeInTheDocument();
    });

    it("renders a failed state in every research widget when the dashboard query fails with a non-404 status", async () => {
      configureResearchDashboard(
        errorQuery(new Error("Research query failed")),
      );

      renderWithClient();

      const section = await screen.findByRole("region", {
        name: "Research Cockpit",
      });
      await waitFor(() => {
        expect(
          within(section).getAllByText("Research query failed").length,
        ).toBeGreaterThan(0);
      });
      const widgetIds = [
        "market-status",
        "research-summary",
        "evidence-pack",
        "factor-snapshot",
        "research-run-timeline",
        "risk-monitor",
      ];
      for (const id of widgetIds) {
        const widget = section.querySelector(
          `[data-widget-id="${id}"]`,
        ) as HTMLElement;
        expect(widget).toHaveAttribute("data-widget-state", "failed");
      }
    });
  });
});
