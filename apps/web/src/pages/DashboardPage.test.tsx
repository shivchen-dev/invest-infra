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
  DataFreshnessResponse,
  PipelineRunResponse,
} from "../api/types";

vi.mock("../api/dataFreshness", () => ({
  fetchDataFreshness: vi.fn(),
  freshnessQueryKey: ["data-freshness"],
}));

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

import { fetchDataFreshness } from "../api/dataFreshness";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import { DashboardPage } from "./DashboardPage";

const mockFetchFreshness = vi.mocked(fetchDataFreshness);
const mockFetchLatestPool = vi.mocked(fetchCandidatePoolLatest);
const mockFetchLatestDiff = vi.mocked(fetchCandidatePoolLatestDiff);
const mockFetchLatestRun = vi.mocked(fetchLatestPipelineRun);

function neverResolvingPromise<T>(): Promise<T> {
  return new Promise<T>(() => {
    /* intentionally never resolves */
  });
}

function makeFreshness(
  overrides: Partial<DataFreshnessResponse> = {},
): DataFreshnessResponse {
  return {
    as_of: "2026-08-03T12:00:00Z",
    candidate_count: 12,
    daily_bar_count: 45,
    latest_published_trade_date: "2026-08-02",
    missing_count: 1,
    pipeline_run_id: "11111111-1111-1111-1111-111111111111",
    pipeline_status: "success",
    snapshot_id: "22222222-2222-2222-2222-222222222222",
    status: "fresh",
    universe_count: 50,
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
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return render(<DashboardPage />, { wrapper: Wrapper });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DashboardPage", () => {
  describe("initial loading", () => {
    it("renders the loading state when all four queries are pending", () => {
      mockFetchFreshness.mockReturnValue(neverResolvingPromise());
      mockFetchLatestPool.mockReturnValue(neverResolvingPromise());
      mockFetchLatestDiff.mockReturnValue(neverResolvingPromise());
      mockFetchLatestRun.mockReturnValue(neverResolvingPromise());

      renderWithClient();

      // LoadingState renders a role="status" live region with the dashboard
      // copy; the accessible name comes from the visible label text.
      expect(
        screen.getByText("正在加载 Dashboard 数据"),
      ).toBeInTheDocument();
      // Page sections should not yet be visible.
      expect(
        screen.queryByRole("heading", { name: "个人 ETF 数据工作台" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("successful render", () => {
    beforeEach(() => {
      mockFetchFreshness.mockResolvedValue(makeFreshness());
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(15));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());
    });

    it("renders the page header and all sections once data resolves", async () => {
      renderWithClient();

      expect(
        await screen.findByRole("heading", { name: "个人 ETF 数据工作台" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "数据状态" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "关键指标" }),
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

      // Freshness banner is rendered with the "fresh" status copy.
      expect(
        await screen.findByRole("status", { name: "数据已更新" }),
      ).toBeInTheDocument();
    });

    it("only displays the top 10 included candidates sorted by rank", async () => {
      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新候选" });

      // Wait for the table to render with exactly 10 data rows + 1 header row.
      await waitFor(() => {
        const rows = within(region).getAllByRole("row");
        expect(rows).toHaveLength(11);
      });

      const table = within(region).getByRole("table");

      // Ranks 1..10 should be present; ranks 11..15 should be truncated.
      for (let i = 1; i <= 10; i += 1) {
        expect(within(table).getByText(String(i))).toBeInTheDocument();
      }
      for (let i = 11; i <= 15; i += 1) {
        expect(within(table).queryByText(String(i))).not.toBeInTheDocument();
      }

      // Header meta should reflect the full row count and included count.
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
      // Pipeline status also surfaces in the metrics card.
      expect(screen.getAllByText("success").length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("error states", () => {
    it("renders the freshness error state when the freshness query fails", async () => {
      const message = "数据服务异常";
      mockFetchFreshness.mockRejectedValue(new ApiError(message, 500));
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());

      renderWithClient();

      const region = await screen.findByRole("region", { name: "数据状态" });

      await waitFor(() => {
        const alert = within(region).getByRole("alert");
        expect(alert).toHaveTextContent("无法读取数据新鲜度");
      });
      // The raw ApiError message is forwarded as the user-facing error text.
      expect(within(region).getByText(message)).toBeInTheDocument();
    });

    it("renders the empty state in TopCandidatesPanel when the candidate pool returns 404", async () => {
      mockFetchFreshness.mockResolvedValue(makeFreshness());
      mockFetchLatestPool.mockRejectedValue(
        new ApiError("Candidate pool not found", 404),
      );
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(makeRunResponse());

      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新候选" });

      await waitFor(() => {
        expect(within(region).getByText("尚无候选结果")).toBeInTheDocument();
      });
      // 404 is treated as empty state, not as an error alert.
      expect(within(region).queryByRole("alert")).not.toBeInTheDocument();
    });

    it("renders the error state in LatestRunPanel when the pipeline run fails with a non-404 status", async () => {
      mockFetchFreshness.mockResolvedValue(makeFreshness());
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
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

    it("shows a failed pipeline run status pill and surfaces its error summary", async () => {
      // The FreshnessPanel banner status comes from `data.status`, so set
      // it to "failed" to mirror a backend-reported pipeline failure.
      mockFetchFreshness.mockResolvedValue(
        makeFreshness({ pipeline_status: "failed", status: "failed" }),
      );
      mockFetchLatestPool.mockResolvedValue(makePoolResponse(5));
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      mockFetchLatestRun.mockResolvedValue(
        makeRunResponse({
          status: "failed",
          error_summary: "data source timeout",
        }),
      );

      renderWithClient();

      const region = await screen.findByRole("region", { name: "最新运行" });

      await waitFor(() => {
        expect(within(region).getByText("failed")).toBeInTheDocument();
      });
      expect(
        within(region).getByText("data source timeout"),
      ).toBeInTheDocument();
      // Freshness banner reflects the failed pipeline state.
      expect(
        await screen.findByRole("status", { name: "最新任务失败" }),
      ).toBeInTheDocument();
    });
  });
});