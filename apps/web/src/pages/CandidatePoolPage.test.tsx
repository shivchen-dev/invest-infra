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
import { ApiError } from "../api/client";
import type {
  CandidatePoolDiffResponse,
  CandidatePoolItem,
  CandidatePoolLatestResponse,
} from "../api/types";
import { Router, useParams } from "../router";

vi.mock("../api/candidatePool", () => ({
  fetchCandidatePoolLatest: vi.fn(),
  fetchCandidatePoolLatestDiff: vi.fn(),
  latestCandidatePoolQueryKey: ["candidate-pool", "latest"],
  latestCandidateDiffQueryKey: ["candidate-pool", "latest", "diff"],
}));

import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { CandidatePoolPage } from "./CandidatePoolPage";

const mockFetchLatestPool = vi.mocked(fetchCandidatePoolLatest);
const mockFetchLatestDiff = vi.mocked(fetchCandidatePoolLatestDiff);

const INSTR_A = "11111111-1111-1111-1111-111111111111";
const INSTR_B = "22222222-2222-2222-2222-222222222222";
const INSTR_C = "33333333-3333-3333-3333-333333333333";
const INSTR_D = "44444444-4444-4444-4444-444444444444";
const DIFF_INSTR_ENCODED = encodeURIComponent(
  "55555555-5555-5555-5555-555555555555",
);

function neverResolvingPromise<T>(): Promise<T> {
  return new Promise<T>(() => {
    /* intentionally never resolves */
  });
}

function makeIncludedItem(
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

function makeExcludedItem(
  rank: number,
  symbol: string,
  options: Partial<CandidatePoolItem> = {},
): CandidatePoolItem {
  return {
    exchange: "SZ",
    exclusion_reasons: [
      {
        code: "low_volume",
        message: "成交量低于阈值",
      },
    ],
    included: false,
    instrument_id: `${rank.toString().padStart(3, "0")}-${symbol}`,
    metrics: { volume: "100" },
    name: `排除 ${symbol}`,
    rank: null,
    rule_results: [
      {
        message: "成交量过低",
        passed: false,
        rule_key: "liquidity.low_volume",
        severity: "error",
        threshold: "1000",
        value: "100",
      },
    ],
    symbol,
    total_score: null,
    ...options,
  };
}

function makePoolResponse(
  items: CandidatePoolItem[],
  overrides: Partial<CandidatePoolLatestResponse> = {},
): CandidatePoolLatestResponse {
  return {
    algorithm_key: "personal-etf-default",
    algorithm_version: "1.0.0",
    content_hash: "deadbeef",
    excluded_count: items.filter((item) => !item.included).length,
    included_count: items.filter((item) => item.included).length,
    items,
    parameter_set_key: "default-params",
    published_at: "2026-08-03T12:00:00Z",
    row_count: items.length,
    run_id: "33333333-3333-3333-3333-333333333333",
    snapshot_id: "44444444-4444-4444-4444-444444444444",
    trade_date: "2026-08-02",
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

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

interface RenderOptions {
  initialPath?: string;
}

function renderWithProviders(options: RenderOptions = {}) {
  const initialPath = options.initialPath ?? "/candidate-pool";
  setPathname(initialPath);
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryDelay: 0,
        gcTime: 0,
      },
    },
  });
  function EtfRoute() {
    const { instrumentId } = useParams<{ instrumentId: string }>();
    return <h1>ETF {instrumentId}</h1>;
  }

  function App() {
    return (
      <QueryClientProvider client={client}>
        <Router
          routes={[
            { path: "/candidate-pool", element: <CandidatePoolPage /> },
            { path: "/etf/:instrumentId", element: <EtfRoute /> },
          ]}
        />
      </QueryClientProvider>
    );
  }

  return {
    client,
    ...render(<App />),
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function buildFullPool(): CandidatePoolLatestResponse {
  const includedA = makeIncludedItem(1, "E001", {
    exchange: "SH",
    instrument_id: INSTR_A,
    metrics: { amount: "5000000", turnover: "5000000", volume: "10000" },
    name: "上证 50ETF",
    symbol: "510100",
  });
  const includedB = makeIncludedItem(2, "E002", {
    exchange: "SZ",
    instrument_id: INSTR_B,
    metrics: { amount: "2000000", turnover: "2000000", volume: "5000" },
    name: "深市 ETF",
    symbol: "159901",
  });
  const excludedLowVolume = makeExcludedItem(3, "E003", {
    exchange: "SH",
    exclusion_reasons: [
      { code: "low_volume", message: "成交量低于阈值" },
    ],
    instrument_id: INSTR_C,
    metrics: { volume: "100" },
    name: "低量 ETF",
    rule_results: [
      {
        message: "成交量过低",
        passed: false,
        rule_key: "liquidity.low_volume",
        severity: "error",
        threshold: "1000",
        value: "100",
      },
    ],
    symbol: "510300",
  });
  const excludedSuspended = makeExcludedItem(4, "E004", {
    exchange: "SZ",
    exclusion_reasons: [
      { code: "suspended", message: "当日停牌" },
    ],
    instrument_id: INSTR_D,
    metrics: { volume: "0" },
    name: "停牌 ETF",
    rule_results: [
      {
        message: "本日无成交",
        passed: false,
        rule_key: "trading.suspended",
        severity: "error",
        threshold: "1",
        value: "0",
      },
    ],
    symbol: "159905",
  });
  return makePoolResponse([
    includedA,
    includedB,
    excludedLowVolume,
    excludedSuspended,
  ]);
}

describe("CandidatePoolPage", () => {
  describe("loading", () => {
    it("renders the loading state while the latest pool query is pending", () => {
      mockFetchLatestPool.mockReturnValue(neverResolvingPromise());
      mockFetchLatestDiff.mockReturnValue(neverResolvingPromise());

      renderWithProviders();

      expect(
        screen.getByText("正在加载最新候选池"),
      ).toBeInTheDocument();
      // The candidate details section should not yet render.
      expect(
        screen.queryByRole("heading", { name: "候选明细" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("tabs", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(buildFullPool());
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
    });

    it("shows tab counts and the included tab by default", async () => {
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      const tablist = within(region).getByRole("tablist", {
        name: "候选池状态",
      });
      const tabs = within(tablist).getAllByRole("tab");
      // 3 tabs: 入选 / 排除 / 全部
      expect(tabs).toHaveLength(3);

      // The "入选" tab counts two items.
      const includedTab = within(tablist).getByRole("tab", { name: /^入选/ });
      expect(within(includedTab).getByText("2")).toBeInTheDocument();
      const excludedTab = within(tablist).getByRole("tab", { name: /^排除/ });
      expect(within(excludedTab).getByText("2")).toBeInTheDocument();
      const allTab = within(tablist).getByRole("tab", { name: /^全部/ });
      expect(within(allTab).getByText("4")).toBeInTheDocument();

      // Selected by default.
      expect(includedTab).toHaveAttribute("aria-selected", "true");

      // The default table shows the two included instruments.
      const includedTable = await within(region).findByRole("table", {
        name: "入选候选",
      });
      expect(
        within(includedTable).getByRole("row", { name: /510100/ }),
      ).toBeInTheDocument();
      expect(
        within(includedTable).getByRole("row", { name: /159901/ }),
      ).toBeInTheDocument();
    });

    it("switches to the excluded tab and shows excluded items", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      await user.click(within(region).getByRole("tab", { name: /^排除/ }));

      const excludedTable = await within(region).findByRole("table", {
        name: "排除候选",
      });
      expect(
        within(excludedTable).getByRole("row", { name: /510300/ }),
      ).toBeInTheDocument();
      expect(
        within(excludedTable).getByRole("row", { name: /159905/ }),
      ).toBeInTheDocument();
      // The included table should no longer be in the panel.
      expect(
        within(region).queryByRole("table", { name: "入选候选" }),
      ).not.toBeInTheDocument();
    });

    it("switches to the all tab and renders both groups", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      await user.click(within(region).getByRole("tab", { name: /^全部/ }));

      const includedGroup = await within(region).findByRole("region", {
        name: "入选候选",
      });
      const excludedGroup = within(region).getByRole("region", {
        name: "排除候选",
      });

      expect(
        within(includedGroup).getByRole("row", { name: /510100/ }),
      ).toBeInTheDocument();
      expect(
        within(excludedGroup).getByRole("row", { name: /510300/ }),
      ).toBeInTheDocument();

      // The result count in the section meta should reflect all 4 items.
      expect(
        within(region).getByText(/筛选后\s*4\s*\/\s*4/),
      ).toBeInTheDocument();
    });
  });

  describe("filters", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(buildFullPool());
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
    });

    it("filters by symbol or name search", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      const search = within(region).getByPlaceholderText("输入代码或名称");

      // Search by code on the included tab.
      await user.type(search, "510100");
      await waitFor(() => {
        expect(
          within(region).getByRole("row", { name: /510100/ }),
        ).toBeInTheDocument();
        expect(
          within(region).queryByRole("row", { name: /159901/ }),
        ).not.toBeInTheDocument();
      });

      // Search by Chinese name on the included tab.
      await user.clear(search);
      await user.type(search, "深市");
      await waitFor(() => {
        expect(
          within(region).getByRole("row", { name: /159901/ }),
        ).toBeInTheDocument();
        expect(
          within(region).queryByRole("row", { name: /510100/ }),
        ).not.toBeInTheDocument();
      });
    });

    it("filters by exchange", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      // Switch to the "全部" tab so both exchanges are represented.
      await user.click(within(region).getByRole("tab", { name: /^全部/ }));

      const exchangeSelect = within(region).getByRole("combobox", {
        name: "交易所",
      }) as HTMLSelectElement;
      await user.selectOptions(exchangeSelect, "SZ");

      await waitFor(() => {
        expect(
          within(region).getByRole("row", { name: /159901/ }),
        ).toBeInTheDocument();
        expect(
          within(region).queryByRole("row", { name: /510100/ }),
        ).not.toBeInTheDocument();
      });
    });

    it("filters excluded items by reason code and shows the human-readable label", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      await user.click(within(region).getByRole("tab", { name: /^排除/ }));

      const reasonSelect = within(region).getByRole("combobox", {
        name: "排除原因",
      }) as HTMLSelectElement;
      // Select the human-readable "成交量不足（low_volume）" option.
      expect(
        within(reasonSelect).getByRole("option", {
          name: "成交量不足（low_volume）",
        }),
      ).toBeInTheDocument();
      await user.selectOptions(reasonSelect, "low_volume");

      await waitFor(() => {
        expect(
          within(region).getByRole("row", { name: /510300/ }),
        ).toBeInTheDocument();
        expect(
          within(region).queryByRole("row", { name: /159905/ }),
        ).not.toBeInTheDocument();
      });

      // Switch to the suspended reason and only 159905 should remain.
      await user.selectOptions(reasonSelect, "suspended");
      await waitFor(() => {
        expect(
          within(region).getByRole("row", { name: /159905/ }),
        ).toBeInTheDocument();
        expect(
          within(region).queryByRole("row", { name: /510300/ }),
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("row expansion", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(buildFullPool());
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
    });

    it("expands and collapses the details panel for an included row", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      const includedTable = within(region).getByRole("table", {
        name: "入选候选",
      });
      const row = within(includedTable).getByRole("row", { name: /510100/ });
      const toggle = within(row).getByRole("button", { name: "展开 510100 详情" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      await user.click(toggle);

      const collapsed = await within(includedTable).findByRole("button", {
        name: "收起 510100 详情",
      });
      expect(collapsed).toHaveAttribute("aria-expanded", "true");

      // The detail row should render the "Metrics" section with the
      // instrument's metric values.
      const details = await screen.findByRole("region", { name: "Metrics" });
      expect(within(details).getByText("amount")).toBeInTheDocument();
      expect(within(details).getByText("volume")).toBeInTheDocument();
      expect(within(details).getByText("10000")).toBeInTheDocument();
      // The "Exclusion reasons" section renders an empty-state copy for
      // included items because they carry no exclusion reasons.
      const reasons = within(region).getByRole("region", {
        name: "Exclusion reasons",
      });
      expect(within(reasons).getByText("无排除原因")).toBeInTheDocument();

      await user.click(collapsed);
      await waitFor(() => {
        expect(
          within(includedTable).getByRole("button", {
            name: "展开 510100 详情",
          }),
        ).toHaveAttribute("aria-expanded", "false");
      });
    });

    it("shows rule results and exclusion reasons when an excluded row is expanded", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      await user.click(within(region).getByRole("tab", { name: /^排除/ }));

      const excludedTable = within(region).getByRole("table", {
        name: "排除候选",
      });
      const row = within(excludedTable).getByRole("row", { name: /510300/ });
      await user.click(
        within(row).getByRole("button", { name: "展开 510300 详情" }),
      );

      // The detail panel renders the Rule results and Exclusion reasons
      // sections.
      const rules = await screen.findByRole("region", { name: "Rule results" });
      expect(
        within(rules).getByText("liquidity.low_volume"),
      ).toBeInTheDocument();

      const reasons = within(region).getByRole("region", {
        name: "Exclusion reasons",
      });
      expect(within(reasons).getByText("low_volume")).toBeInTheDocument();
      expect(
        within(reasons).getByText("成交量低于阈值"),
      ).toBeInTheDocument();
    });
  });

  describe("navigation", () => {
    beforeEach(() => {
      mockFetchLatestPool.mockResolvedValue(buildFullPool());
      mockFetchLatestDiff.mockResolvedValue(
        makeDiffResponse({
          added: [
            {
              exchange: "SH",
              instrument_id: "55555555-5555-5555-5555-555555555555",
              name: "新增 ETF",
              symbol: "510500",
            },
          ],
        }),
      );
    });

    it("navigates to the encoded instrument path when an included row is clicked", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      const includedTable = within(region).getByRole("table", {
        name: "入选候选",
      });
      const row = within(includedTable).getByRole("row", { name: /510100/ });

      // The symbol link in the row should expose the encoded path as its
      // href so it remains a real anchor.
      const symbolLink = within(row).getByRole("link", { name: "510100" });
      expect(symbolLink).toHaveAttribute(
        "href",
        `/etf/${encodeURIComponent(INSTR_A)}`,
      );

      await user.click(row);
      expect(window.location.pathname).toBe(
        `/etf/${encodeURIComponent(INSTR_A)}`,
      );
      expect(
        await screen.findByRole("heading", { name: `ETF ${INSTR_A}` }),
      ).toBeInTheDocument();
    });

    it("navigates to the encoded instrument path when an excluded row is clicked", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      await user.click(within(region).getByRole("tab", { name: /^排除/ }));

      const excludedTable = within(region).getByRole("table", {
        name: "排除候选",
      });
      const row = within(excludedTable).getByRole("row", { name: /510300/ });

      const symbolLink = within(row).getByRole("link", { name: "510300" });
      expect(symbolLink).toHaveAttribute(
        "href",
        `/etf/${encodeURIComponent(INSTR_C)}`,
      );

      await user.click(row);
      expect(window.location.pathname).toBe(
        `/etf/${encodeURIComponent(INSTR_C)}`,
      );
      expect(
        await screen.findByRole("heading", { name: `ETF ${INSTR_C}` }),
      ).toBeInTheDocument();
    });

    it("navigates when a diff link is clicked", async () => {
      const user = userEvent.setup();
      renderWithProviders();

      // The diff section renders a "新增" column with a NavLink to the
      // encoded instrument id.
      const diffRegion = await screen.findByRole("region", { name: "候选池变化" });
      const diffLink = within(diffRegion).getByRole("link", {
        name: /510500/,
      });
      expect(diffLink).toHaveAttribute("href", `/etf/${DIFF_INSTR_ENCODED}`);

      await user.click(diffLink);
      expect(window.location.pathname).toBe(`/etf/${DIFF_INSTR_ENCODED}`);
      expect(
        await screen.findByRole("heading", {
          name: `ETF 55555555-5555-5555-5555-555555555555`,
        }),
      ).toBeInTheDocument();
    });
  });

  describe("empty and error states", () => {
    it("shows the empty state when no items match the active filters", async () => {
      mockFetchLatestPool.mockResolvedValue(buildFullPool());
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());
      const user = userEvent.setup();

      renderWithProviders();

      const region = await screen.findByRole("region", { name: "候选明细" });
      const search = within(region).getByPlaceholderText("输入代码或名称");
      await user.type(search, "不存在的代码");

      expect(
        await within(region).findByText("没有符合条件的候选"),
      ).toBeInTheDocument();
    });

    it("shows the empty state when the latest pool returns 404", async () => {
      mockFetchLatestPool.mockRejectedValue(
        new ApiError("Candidate pool not found", 404),
      );
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());

      renderWithProviders();

      expect(
        await screen.findByText("尚无候选池"),
      ).toBeInTheDocument();
      // The 404 is treated as an empty state — no error alert is rendered.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows the error state when the latest pool returns a non-404 error", async () => {
      mockFetchLatestPool.mockRejectedValue(
        new ApiError("服务暂时不可用", 503, "服务暂时不可用"),
      );
      mockFetchLatestDiff.mockResolvedValue(makeDiffResponse());

      renderWithProviders();

      const alert = await screen.findByRole("alert");
      await waitFor(() => {
        expect(alert).toHaveTextContent("无法读取最新候选池");
      });
      expect(within(alert).getByText("服务暂时不可用")).toBeInTheDocument();
    });
  });
});
