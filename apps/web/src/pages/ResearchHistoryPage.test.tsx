import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { useResearchCases } from "../api/researchCases";
import { useResearchRuns } from "../api/researchRuns";
import type {
  ResearchCaseListResponse,
  ResearchCaseResponse,
  ResearchRunListResponse,
  ResearchRunResponse,
} from "../api/types";
import { Router } from "../router";
import {
  computeCombinedOffsetMax,
  ResearchHistoryPage,
  sortHistoryRowsByUpdatedAt,
} from "./ResearchHistoryPage";

vi.mock("../api/researchCases", () => ({
  useResearchCases: vi.fn(),
  fetchResearchCases: vi.fn(),
  researchCasesQueryKey: vi.fn(),
}));
vi.mock("../api/researchRuns", () => ({
  useResearchRuns: vi.fn(),
  fetchResearchRuns: vi.fn(),
  researchRunsQueryKey: vi.fn(),
}));

const mockUseResearchCases = vi.mocked(useResearchCases);
const mockUseResearchRuns = vi.mocked(useResearchRuns);

interface CaseOverrides extends Partial<ResearchCaseResponse> {}

interface RunOverrides extends Partial<ResearchRunResponse> {}

function makeCase(overrides: CaseOverrides = {}): ResearchCaseResponse {
  return {
    case_id: "11111111-1111-1111-1111-111111111111",
    instrument_id: "22222222-2222-2222-2222-222222222222",
    as_of_date: "2026-08-08",
    question: "趋势通道判断",
    horizon: "30d",
    status: "open",
    created_at: "2026-08-09T00:00:00Z",
    candidate_pool_run_id: null,
    closed_at: null,
    ...overrides,
  };
}

function makeRun(overrides: RunOverrides = {}): ResearchRunResponse {
  return {
    run_id: "33333333-3333-3333-3333-333333333333",
    case_id: "11111111-1111-1111-1111-111111111111",
    evidence_pack_id: "44444444-4444-4444-4444-444444444444",
    playbook_key: "playbook.default",
    runner_key: "runner.default",
    attempt: 1,
    started_at: "2026-08-09T00:00:00Z",
    finished_at: "2026-08-09T00:30:00Z",
    status: "succeeded",
    error_summary: null,
    ...overrides,
  };
}

function makeCaseList(
  items: ResearchCaseResponse[],
  overrides: Partial<ResearchCaseListResponse> = {},
): ResearchCaseListResponse {
  return {
    items,
    limit: 20,
    offset: 0,
    total: items.length,
    ...overrides,
  };
}

function makeRunList(
  items: ResearchRunResponse[],
  overrides: Partial<ResearchRunListResponse> = {},
): ResearchRunListResponse {
  return {
    items,
    limit: 20,
    offset: 0,
    total: items.length,
    ...overrides,
  };
}

function defaultRefetch(): Promise<unknown> {
  return Promise.resolve(null);
}

interface StoryState {
  data?: ResearchCaseListResponse | ResearchRunListResponse;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  isFetching: boolean;
  dataUpdatedAt: number;
  refetch: () => Promise<unknown>;
}

interface StoriesOptions {
  cases?: ResearchCaseListResponse;
  runs?: ResearchRunListResponse;
  casesPending?: boolean;
  runsPending?: boolean;
  casesError?: Error;
  runsError?: Error;
  casesUpdatedAt?: number;
  runsUpdatedAt?: number;
}

function installStories({
  cases,
  runs,
  casesPending = false,
  runsPending = false,
  casesError,
  runsError,
  casesUpdatedAt,
  runsUpdatedAt,
}: StoriesOptions = {}) {
  const casesState: StoryState = {
    data: cases,
    isPending: casesPending,
    isError: Boolean(casesError),
    error: casesError ?? null,
    isFetching: casesPending,
    dataUpdatedAt:
      typeof casesUpdatedAt === "number" ? casesUpdatedAt : Date.now(),
    refetch: defaultRefetch,
  };
  const runsState: StoryState = {
    data: runs,
    isPending: runsPending,
    isError: Boolean(runsError),
    error: runsError ?? null,
    isFetching: runsPending,
    dataUpdatedAt:
      typeof runsUpdatedAt === "number" ? runsUpdatedAt : Date.now(),
    refetch: defaultRefetch,
  };

  mockUseResearchCases.mockImplementation(() => casesState as never);
  mockUseResearchRuns.mockImplementation(() => runsState as never);

  return { casesState, runsState };
}

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

function renderHistory(initialPath = "/research/history") {
  setPathname(initialPath);
  const client = makeQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <Router routes={[{ path: "/research/history", element: <ResearchHistoryPage /> }]} />
    </QueryClientProvider>,
  );
}

function renderHistoryWith(options: StoriesOptions, initialPath = "/research/history") {
  installStories(options);
  return renderHistory(initialPath);
}

beforeEach(() => {
  mockUseResearchCases.mockReset();
  mockUseResearchRuns.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResearchHistoryPage header + scope tabs", () => {
  it("renders the page header, scope tabs, read-only badge and provenance callout", () => {
    renderHistoryWith({
      cases: makeCaseList([]),
      runs: makeRunList([]),
    });

    expect(
      screen.getByRole("heading", { name: "Research Case 与 Run 历史" }),
    ).toBeInTheDocument();

    const breadcrumb = screen.getByLabelText("Research History 路径");
    expect(within(breadcrumb).getByText("Dashboard")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("Research History")).toBeInTheDocument();

    const tablist = screen.getByRole("tablist", { name: "History 视图" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["全部", "Case", "Run"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    expect(
      screen.getByText("只读模式 · 浏览器不写入 Research 数据"),
    ).toBeInTheDocument();

    const grid = screen.getByLabelText("Research History widgets");
    expect(within(grid).getByText("Research Case 与 Run 列表")).toBeInTheDocument();
    expect(within(grid).getByText("Research 摘要")).toBeInTheDocument();
    expect(within(grid).getByText("数据来源")).toBeInTheDocument();
  });

  it("switches the active scope when a tab is clicked", async () => {
    renderHistoryWith({
      cases: makeCaseList([makeCase()], { total: 40 }),
      runs: makeRunList([makeRun()], { total: 40 }),
    });

    const tablist = screen.getByRole("tablist", { name: "History 视图" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    const user = userEvent.setup();
    await user.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");

    await user.click(tabs[2]);
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  });
});

describe("ResearchHistoryPage table states", () => {
  it("shows the loading state when the primary query is pending", () => {
    renderHistoryWith({
      casesPending: true,
      runsPending: true,
    });
    expect(screen.getAllByText(/正在加载/).length).toBeGreaterThan(0);
  });

  it("shows the error state when the primary query fails", () => {
    renderHistoryWith({
      casesError: new ApiError("Research query failed", 500),
      runs: makeRunList([makeRun()]),
    });
    expect(screen.getByText("无法读取 Research History")).toBeInTheDocument();
    expect(screen.getByText("Research query failed")).toBeInTheDocument();
  });

  it("shows the empty state when the page has no items", () => {
    renderHistoryWith({
      cases: makeCaseList([]),
      runs: makeRunList([]),
    });
    expect(screen.getByText("尚无 全部 History 数据")).toBeInTheDocument();
  });

  it("renders combined Case + Run rows for the all scope", () => {
    renderHistoryWith({
      cases: makeCaseList([makeCase({ case_id: "case-AAA", status: "open" })]),
      runs: makeRunList([makeRun({ run_id: "run-BBB", status: "succeeded" })]),
    });
    const table = screen.getByRole("region", { name: /History 列表/ });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(table).getByText("Case")).toBeInTheDocument();
    expect(within(table).getByText("Run")).toBeInTheDocument();
    expect(within(table).getByText("case-AAA")).toBeInTheDocument();
    expect(within(table).getByText("run-BBB")).toBeInTheDocument();
  });

  it("interleaves Case and Run rows by updatedAt desc in the all scope", () => {
    const laterCase = makeCase({
      case_id: "case-later",
      created_at: "2026-08-09T02:00:00Z",
    });
    const earlierCase = makeCase({
      case_id: "case-earlier",
      created_at: "2026-08-09T01:00:00Z",
    });
    const laterRun = makeRun({
      run_id: "run-later",
      finished_at: "2026-08-09T03:00:00Z",
    });
    const earlierRun = makeRun({
      run_id: "run-earlier",
      finished_at: "2026-08-09T00:30:00Z",
    });

    renderHistoryWith({
      cases: makeCaseList([earlierCase, laterCase]),
      runs: makeRunList([laterRun, earlierRun]),
    });

    const table = screen.getByRole("region", { name: /History 列表/ });
    const dataRows = within(table)
      .getAllByRole("row")
      .slice(1);
    const ids = dataRows.map(
      (row) => row.querySelector("td:nth-child(2)")?.textContent ?? "",
    );
    expect(ids).toEqual([
      "run-later",
      "case-later",
      "case-earlier",
      "run-earlier",
    ]);
  });
});

describe("ResearchHistoryPage pagination", () => {
  function installTrackingMock() {
    const casesCalls: Array<{ limit: number; offset: number }> = [];
    const runsCalls: Array<{ limit: number; offset: number }> = [];
    mockUseResearchCases.mockImplementation((filters) => {
      casesCalls.push({ limit: filters.limit, offset: filters.offset });
      return {
        data: makeCaseList([makeCase({ case_id: "case-AAA" })], {
          total: 60,
          offset: filters.offset,
        }),
        isPending: false,
        isError: false,
        error: null,
        isFetching: false,
        dataUpdatedAt: Date.now(),
        refetch: defaultRefetch,
      } as never;
    });
    mockUseResearchRuns.mockImplementation((filters) => {
      runsCalls.push({ limit: filters.limit, offset: filters.offset });
      return {
        data: makeRunList([makeRun({ run_id: "run-AAA" })], {
          total: 60,
          offset: filters.offset,
        }),
        isPending: false,
        isError: false,
        error: null,
        isFetching: false,
        dataUpdatedAt: Date.now(),
        refetch: defaultRefetch,
      } as never;
    });
    return { casesCalls, runsCalls };
  }

  it("shows enabled previous/next controls with offset meta when more data exists", () => {
    renderHistoryWith({
      cases: makeCaseList([makeCase()], { total: 60 }),
      runs: makeRunList([makeRun()], { total: 60 }),
    });
    const pager = screen.getByLabelText("Research History 分页");
    const previous = within(pager).getByRole("button", { name: "上一页" });
    const next = within(pager).getByRole("button", { name: "下一页" });
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();
    expect(within(pager).getByText(/offset 0/)).toBeInTheDocument();
  });

  it("advances offset when next is clicked and re-queries both endpoints", async () => {
    const tracker = installTrackingMock();
    renderHistory();

    const user = userEvent.setup();
    const next = screen.getByRole("button", { name: "下一页" });
    await user.click(next);

    await waitFor(() => {
      expect(tracker.casesCalls.some((c) => c.offset === 20)).toBe(true);
      expect(tracker.runsCalls.some((c) => c.offset === 20)).toBe(true);
    });
    expect(screen.getByText(/offset 20/)).toBeInTheDocument();
  });

  it("returns to the previous page when previous is clicked", async () => {
    const tracker = installTrackingMock();
    renderHistory();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => {
      expect(screen.getByText(/offset 20/)).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "上一页" }));
    await waitFor(() => {
      expect(tracker.casesCalls.some((c) => c.offset === 0)).toBe(true);
      expect(tracker.runsCalls.some((c) => c.offset === 0)).toBe(true);
    });
    expect(screen.getByText(/offset 0/)).toBeInTheDocument();
  });

  it("disables both buttons when only the current page of data exists", () => {
    renderHistoryWith({
      cases: makeCaseList([makeCase()], { total: 1 }),
      runs: makeRunList([makeRun()], { total: 1 }),
    });
    const pager = screen.getByLabelText("Research History 分页");
    expect(within(pager).getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(within(pager).getByRole("button", { name: "下一页" })).toBeDisabled();
  });
});

describe("ResearchHistoryPage summary widget", () => {
  it("reports server totals once data is available", () => {
    renderHistoryWith({
      cases: makeCaseList([makeCase()], { total: 42 }),
      runs: makeRunList([makeRun()], { total: 17 }),
    });

    const grid = screen.getByLabelText("Research History widgets");
    const summary = within(grid).getByText("Research 摘要").closest("article");
    expect(summary).not.toBeNull();
    if (!summary) return;
    expect(within(summary).getByText("Case 总数")).toBeInTheDocument();
    expect(within(summary).getByText("Run 总数")).toBeInTheDocument();
    expect(within(summary).getByText("42")).toBeInTheDocument();
    expect(within(summary).getByText("17")).toBeInTheDocument();
  });

  it("renders placeholder dashes when neither query has returned data", () => {
    renderHistoryWith({
      casesPending: true,
      runsPending: true,
    });
    const grid = screen.getByLabelText("Research History widgets");
    const summary = within(grid).getByText("Research 摘要").closest("article");
    expect(summary).not.toBeNull();
    if (!summary) return;
    expect(within(summary).getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});

describe("computeCombinedOffsetMax", () => {
  it("clamps to a PAGE_SIZE-aligned last valid offset", () => {
    expect(computeCombinedOffsetMax("case", 0, 1, 0)).toBe(0);
    expect(computeCombinedOffsetMax("case", 0, 21, 0)).toBe(20);
    expect(computeCombinedOffsetMax("case", 0, 60, 0)).toBe(40);
    expect(computeCombinedOffsetMax("run", 0, 42, 0)).toBe(40);
  });

  it("uses the larger of the two aligned last offsets for the all scope", () => {
    expect(computeCombinedOffsetMax("all", 0, 30, 70)).toBe(60);
    expect(computeCombinedOffsetMax("all", 0, 70, 30)).toBe(60);
  });

  it("never moves the max offset backwards", () => {
    expect(computeCombinedOffsetMax("all", 100, 30, 70)).toBe(100);
    expect(computeCombinedOffsetMax("case", 30, 12, 0)).toBe(30);
  });
});

describe("sortHistoryRowsByUpdatedAt", () => {
  function makeRow(input: {
    kind: "case" | "run";
    id: string;
    updatedAt: string;
  }) {
    return {
      kind: input.kind,
      kindLabel: input.kind === "case" ? "Case" : "Run",
      id: input.id,
      subject: "—",
      status: "unknown",
      updatedAt: input.updatedAt,
    };
  }

  it("orders rows by updatedAt descending across Case and Run", () => {
    const rows = [
      makeRow({ kind: "case", id: "case-old", updatedAt: "2026-08-09T00:00:00Z" }),
      makeRow({ kind: "run", id: "run-new", updatedAt: "2026-08-09T02:00:00Z" }),
      makeRow({ kind: "case", id: "case-mid", updatedAt: "2026-08-09T01:00:00Z" }),
      makeRow({ kind: "run", id: "run-old", updatedAt: "2026-08-09T00:30:00Z" }),
    ];

    const sorted = sortHistoryRowsByUpdatedAt(rows);
    expect(sorted.map((row) => row.id)).toEqual([
      "run-new",
      "case-mid",
      "run-old",
      "case-old",
    ]);
  });

  it("uses kind then id as a deterministic tie-breaker when updatedAt matches", () => {
    const rows = [
      makeRow({ kind: "run", id: "run-zzz", updatedAt: "2026-08-09T00:00:00Z" }),
      makeRow({ kind: "case", id: "case-zzz", updatedAt: "2026-08-09T00:00:00Z" }),
      makeRow({ kind: "case", id: "case-aaa", updatedAt: "2026-08-09T00:00:00Z" }),
      makeRow({ kind: "run", id: "run-aaa", updatedAt: "2026-08-09T00:00:00Z" }),
    ];

    const sorted = sortHistoryRowsByUpdatedAt(rows);
    expect(sorted.map((row) => `${row.kind}-${row.id}`)).toEqual([
      "case-case-aaa",
      "case-case-zzz",
      "run-run-aaa",
      "run-run-zzz",
    ]);
  });

  it("is stable across calls and never mutates the input array", () => {
    const rows = [
      makeRow({ kind: "run", id: "run-b", updatedAt: "2026-08-09T00:30:00Z" }),
      makeRow({ kind: "case", id: "case-a", updatedAt: "2026-08-09T00:00:00Z" }),
    ];
    const before = rows.map((row) => row.id);

    const first = sortHistoryRowsByUpdatedAt(rows);
    const second = sortHistoryRowsByUpdatedAt(rows);

    expect(rows.map((row) => row.id)).toEqual(before);
    expect(first.map((row) => row.id)).toEqual(["run-b", "case-a"]);
    expect(second.map((row) => row.id)).toEqual(["run-b", "case-a"]);
  });

  it("sends rows whose updatedAt cannot be parsed to the end, then sorts by kind/id", () => {
    const rows = [
      makeRow({ kind: "run", id: "run-missing", updatedAt: "—" }),
      makeRow({ kind: "case", id: "case-mid", updatedAt: "2026-08-09T01:00:00Z" }),
      makeRow({ kind: "run", id: "run-new", updatedAt: "2026-08-09T02:00:00Z" }),
      makeRow({ kind: "case", id: "case-missing-a", updatedAt: "—" }),
      makeRow({ kind: "case", id: "case-missing-b", updatedAt: "—" }),
    ];

    const sorted = sortHistoryRowsByUpdatedAt(rows);
    expect(sorted.map((row) => row.id)).toEqual([
      "run-new",
      "case-mid",
      "case-missing-a",
      "case-missing-b",
      "run-missing",
    ]);
  });
});
