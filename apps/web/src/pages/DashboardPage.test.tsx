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
} from "../api/types";
import { Router } from "../router";

vi.mock("../api/candidatePool", () => ({
  fetchCandidatePoolLatestDiff: vi.fn(),
  latestCandidateDiffQueryKey: ["candidate-pool", "latest", "diff"],
}));

vi.mock("../api/pipelineRuns", () => ({
  fetchLatestPipelineRun: vi.fn(),
  fetchPipelineRuns: vi.fn(),
  latestPipelineRunQueryKey: ["pipeline-runs", "latest"],
  pipelineRunsQueryKey: vi.fn(),
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

import { fetchCandidatePoolLatestDiff } from "../api/candidatePool";
import { fetchIntegrationHealth } from "../api/integrationHealth";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import { useResearchCenter } from "../api/researchCenter";
import {
  errorQuery,
  pendingQuery,
  successQuery,
} from "../features/research/dashboard/test-helpers";
import { DashboardPage } from "./DashboardPage";

const mockFetchLatestDiff = vi.mocked(fetchCandidatePoolLatestDiff);
const mockFetchLatestRun = vi.mocked(fetchLatestPipelineRun);
const mockFetchIntegrationHealth = vi.mocked(fetchIntegrationHealth);
const mockUseResearchCenter = vi.mocked(useResearchCenter);

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
    it("renders the loading state when the Research Center query is pending", () => {
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
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
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

      // The duplicate sections must be gone now that the center panel takes over.
      expect(
        screen.queryByRole("region", { name: "最新候选" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "最新运行" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "外部集成状态" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "Research Cockpit" }),
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

    it("preserves the candidate-pool diff panel that is not in the Research Center response", async () => {
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
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", { name: "候选池变化" });
      await waitFor(() => {
        expect(
          within(region).getByText("对比 2026-08-01 → 2026-08-02"),
        ).toBeInTheDocument();
      });
    });
  });

  describe("research-center section", () => {
    beforeEach(() => {
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
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
    });
  });

  describe("research-center subviews section", () => {
    beforeEach(() => {
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
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
            research: makeResearchSummary({
              state: "available",
              case_count: 2,
              run_count: 3,
              latest_case: {
                case_id: "case-001",
                as_of_date: "2026-08-02",
              },
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
      const research = within(region).getByLabelText("Research 只读摘要");
      expect(research).toHaveAttribute("data-state", "available");
      expect(
        within(region).getByRole("link", { name: "查看 Candidate Pool 详情" }),
      ).toHaveAttribute("href", "/candidate-pool");
      expect(
        within(region).getByRole("link", {
          name: "查看 Opportunity Radar 详情",
        }),
      ).toHaveAttribute("href", "/opportunity-radar");
      expect(
        within(region).getByRole("link", { name: "查看 Research 历史" }),
      ).toHaveAttribute("href", "/research/history");
    });

    it("isolates a failed Research summary from the Candidate Pool and Opportunity Radar summaries", async () => {
      configureResearchCenter(
        successQuery(
          makeResearchCenter({
            state: "partial",
            candidate_pool: makeCandidatePoolSummary({
              state: "available",
              trade_date: "2026-08-02",
              input_row_count: 12,
              included_count: 9,
              excluded_count: 3,
            }),
            opportunities: makeOpportunitySummary({
              state: "available",
              observation_count: 4,
              latest_as_of: "2026-08-02",
              admission_status_counts: { admitted: 4 },
            }),
            research: makeResearchSummary({
              state: "failed",
              case_count: null,
              run_count: null,
              latest_case: null,
            }),
          }),
        ),
      );

      renderWithClient();

      const region = await screen.findByRole("region", {
        name: "Research Center 子视图",
      });
      const research = within(region).getByLabelText("Research 只读摘要");
      expect(research).toHaveAttribute("data-state", "failed");
      expect(
        within(research).getByText("Research · failed"),
      ).toBeInTheDocument();
      const pool = within(region).getByLabelText("Candidate Pool 只读摘要");
      expect(pool).toHaveAttribute("data-state", "available");
      const radar = within(region).getByLabelText("Opportunity Radar 只读摘要");
      expect(radar).toHaveAttribute("data-state", "available");
    });
  });

  describe("research-center delivery section", () => {
    beforeEach(() => {
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
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
      mockFetchIntegrationHealth.mockReturnValue(new Promise(() => {}));

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
        expect(mockFetchIntegrationHealth).not.toHaveBeenCalled();
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  describe("legacy homepage fetches", () => {
    beforeEach(() => {
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      configureResearchCenter(successQuery(makeResearchCenter()));
      mockFetchLatestRun.mockReturnValue(new Promise(() => {}));
      mockFetchIntegrationHealth.mockReturnValue(new Promise(() => {}));
    });

    it("never invokes the legacy latest pipeline-run fetch", async () => {
      renderWithClient();

      await screen.findByRole("heading", { name: "个人 ETF 数据工作台" });

      expect(mockFetchLatestRun).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("region", { name: "最新运行" }),
      ).not.toBeInTheDocument();
    });

    it("never invokes the legacy integration-health fetch", async () => {
      renderWithClient();

      await screen.findByRole("heading", { name: "个人 ETF 数据工作台" });

      expect(mockFetchIntegrationHealth).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("region", { name: "外部集成状态" }),
      ).not.toBeInTheDocument();
    });

    it("only fetches the Research Center query and the candidate-pool diff", async () => {
      renderWithClient();

      await screen.findByRole("heading", { name: "个人 ETF 数据工作台" });

      expect(mockUseResearchCenter).toHaveBeenCalled();
      expect(mockFetchLatestDiff).toHaveBeenCalled();
    });
  });
});
