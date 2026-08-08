import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

vi.mock("./api/dataFreshness", () => ({
  fetchDataFreshness: vi.fn(),
  freshnessQueryKey: ["data-freshness"],
}));

vi.mock("./api/candidatePool", () => ({
  fetchCandidatePoolLatest: vi.fn(),
  fetchCandidatePoolLatestDiff: vi.fn(),
  latestCandidatePoolQueryKey: ["candidate-pool", "latest"],
  latestCandidateDiffQueryKey: ["candidate-pool", "latest", "diff"],
}));

vi.mock("./api/pipelineRuns", () => ({
  fetchLatestPipelineRun: vi.fn(),
  fetchPipelineRuns: vi.fn(),
  latestPipelineRunQueryKey: ["pipeline-runs", "latest"],
  pipelineRunsQueryKey: vi.fn(),
}));

import { fetchDataFreshness } from "./api/dataFreshness";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "./api/candidatePool";
import { fetchLatestPipelineRun } from "./api/pipelineRuns";

const mockFetchFreshness = vi.mocked(fetchDataFreshness);
const mockFetchLatestPool = vi.mocked(fetchCandidatePoolLatest);
const mockFetchLatestDiff = vi.mocked(fetchCandidatePoolLatestDiff);
const mockFetchLatestRun = vi.mocked(fetchLatestPipelineRun);

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryDelay: 0,
        gcTime: 0,
      },
    },
  });
}

function renderApp(initialPath: string) {
  setPathname(initialPath);
  const client = makeQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetchFreshness.mockResolvedValue({
    as_of: "2026-08-03T12:00:00Z",
    candidate_count: 0,
    daily_bar_count: 0,
    latest_published_trade_date: "2026-08-02",
    missing_count: 0,
    pipeline_run_id: null,
    pipeline_status: null,
    snapshot_id: null,
    status: "fresh",
    universe_count: 0,
  });
  mockFetchLatestPool.mockResolvedValue({
    algorithm_key: "personal-etf-default",
    algorithm_version: "1.0.0",
    content_hash: "deadbeef",
    excluded_count: 0,
    included_count: 0,
    items: [],
    parameter_set_key: "default-params",
    published_at: "2026-08-03T12:00:00Z",
    row_count: 0,
    run_id: "33333333-3333-3333-3333-333333333333",
    snapshot_id: "44444444-4444-4444-4444-444444444444",
    trade_date: "2026-08-02",
  });
  mockFetchLatestDiff.mockResolvedValue({
    added: [],
    previous_trade_date: "2026-08-01",
    removed: [],
    retained: [],
    trade_date: "2026-08-02",
  });
  mockFetchLatestRun.mockResolvedValue({
    error_code: null,
    error_summary: null,
    finished_at: "2026-08-03T12:30:00Z",
    id: "55555555-5555-5555-5555-555555555555",
    job_key: "personal_etf_daily_job",
    partition_key: "2026-08-02",
    started_at: "2026-08-03T12:00:00Z",
    status: "success",
    trigger_type: "manual",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("App shell + router integration", () => {
  it("renders the AppShell sidebar with NavLinks inside Router context at /dashboard", () => {
    renderApp("/dashboard");

    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(sidebar).toBeInTheDocument();

    expect(within(sidebar).getByRole("link", { name: /Dashboard/ })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: /候选池/ })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: /Operations/ })).toBeInTheDocument();
  });

  it("renders the dashboard page at /dashboard without throwing", async () => {
    renderApp("/dashboard");

    expect(
      await screen.findByRole("heading", { name: "个人 ETF 数据工作台" }),
    ).toBeInTheDocument();
  });

  it("renders the research history page at /research/history without throwing", () => {
    renderApp("/research/history");

    expect(
      screen.getByRole("heading", { name: "Research Case 与 Run 历史" }),
    ).toBeInTheDocument();
  });

  it("renders the research case page at /research/:caseId without throwing", () => {
    renderApp("/research/case-2026-08-03");

    expect(
      screen.getByRole("heading", { name: /Research Case · case-2026-08-03/ }),
    ).toBeInTheDocument();

    const breadcrumb = screen.getByLabelText("Research Case 路径");
    expect(within(breadcrumb).getByText("Dashboard")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("Research History")).toBeInTheDocument();
  });

  it("drives navigation from the AppShell sidebar via NavLink context", async () => {
    const user = userEvent.setup();
    renderApp("/dashboard");

    const operationsLink = screen.getByRole("link", { name: /Operations/ });
    expect(operationsLink).toHaveAttribute("href", "/operations");

    await user.click(operationsLink);
    await waitFor(() => {
      expect(window.location.pathname).toBe("/operations");
    });
  });
});