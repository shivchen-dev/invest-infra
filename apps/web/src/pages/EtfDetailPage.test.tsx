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
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  DailyBarListResponse,
  DailyBarResponse,
  InstrumentListResponse,
  InstrumentResponse,
} from "../api/types";
import { Router } from "../router";
import { EtfDetailPage } from "./EtfDetailPage";

vi.mock("../api/instruments", () => ({
  fetchEtfInstruments: vi.fn(),
}));

vi.mock("../api/dailyBars", () => ({
  fetchEtfDailyBars: vi.fn(),
}));

import { fetchEtfInstruments } from "../api/instruments";
import { fetchEtfDailyBars } from "../api/dailyBars";

const mockFetchEtfInstruments = vi.mocked(fetchEtfInstruments);
const mockFetchEtfDailyBars = vi.mocked(fetchEtfDailyBars);

const INSTRUMENT_LOOKUP_LIMIT = 1000;
const DAILY_BARS_PAGE_LIMIT = 1000;

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function makeInstrument(
  overrides: Partial<InstrumentResponse> = {},
): InstrumentResponse {
  return {
    category: "股票指数",
    currency: "CNY",
    delist_date: null,
    exchange: "SH",
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    instrument_type: "ETF",
    is_active: true,
    list_date: "2012-05-28",
    name: "沪深300ETF",
    status: "active",
    symbol: "510300",
    underlying_index: "沪深300指数",
    ...overrides,
  };
}

function makeInstrumentList(
  items: InstrumentResponse[],
): InstrumentListResponse {
  return {
    items,
    limit: INSTRUMENT_LOOKUP_LIMIT,
    offset: 0,
    total: items.length,
  };
}

function makeBar(
  tradeDate: string,
  overrides: Partial<DailyBarResponse> = {},
): DailyBarResponse {
  return {
    adjustment: "none",
    amount: "123456789.0",
    close: "4.0000",
    high: "4.0500",
    instrument_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    low: "3.9800",
    observed_at: `${tradeDate}T15:00:00+08:00`,
    open: "4.0100",
    prev_close: "3.9900",
    revision: 1,
    source_batch_id: "batch-1",
    source_provider: "wind",
    trade_date: tradeDate,
    trading_status: "closed",
    volume: "100000",
    ...overrides,
  };
}

function makeBarsList(
  items: DailyBarResponse[],
): DailyBarListResponse {
  return {
    items,
    limit: DAILY_BARS_PAGE_LIMIT,
    offset: 0,
    total: items.length,
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
  return render(
    <QueryClientProvider client={client}>
      <Router
        routes={[{ path: "/etf/:instrumentId", element: <EtfDetailPage /> }]}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("EtfDetailPage", () => {
  describe("route parameter handling", () => {
    it("decodes a percent-encoded instrumentId and surfaces it in the page header", async () => {
      const decodedId = "a0e1d2c3-b4a5-4687-8901-23456789abcd";
      const path = "/etf/%61" + decodedId.slice(1);
      const instrument = makeInstrument({
        id: decodedId,
        symbol: "TEST",
        name: "测试ETF",
      });
      mockFetchEtfInstruments.mockResolvedValue(
        makeInstrumentList([instrument]),
      );
      mockFetchEtfDailyBars.mockResolvedValue(
        makeBarsList([
          makeBar("2026-08-03", {
            instrument_id: decodedId,
            revision: 1,
          }),
        ]),
      );

      setPathname(path);
      renderWithClient();

      const code = await screen.findByText(decodedId, { selector: "code" });
      expect(code.tagName).toBe("CODE");

      await waitFor(() => {
        expect(mockFetchEtfDailyBars).toHaveBeenCalled();
      });
      const lastCall =
        mockFetchEtfDailyBars.mock.calls[
          mockFetchEtfDailyBars.mock.calls.length - 1
        ];
      expect(lastCall[0]).toMatchObject({ instrument_id: decodedId });
    });
  });

  describe("missing instrument", () => {
    it("renders the empty state when the instrument id is not in the master data", async () => {
      mockFetchEtfInstruments.mockResolvedValue(
        makeInstrumentList([
          makeInstrument({ id: "other-instrument", symbol: "000000" }),
        ]),
      );
      mockFetchEtfDailyBars.mockResolvedValue(makeBarsList([]));

      setPathname("/etf/missing-instrument");
      renderWithClient();

      expect(await screen.findByText("未找到该 ETF")).toBeInTheDocument();
      expect(
        await screen.findByText(
          /未在主数据中找到 instrumentId = missing-instrument/,
        ),
      ).toBeInTheDocument();
    });
  });

  describe("empty daily bars", () => {
    it("renders the empty state in both the latest metrics and bars table when the list is empty", async () => {
      const instrument = makeInstrument();
      mockFetchEtfInstruments.mockResolvedValue(makeInstrumentList([instrument]));
      mockFetchEtfDailyBars.mockResolvedValue(makeBarsList([]));

      setPathname(`/etf/${instrument.id}`);
      renderWithClient();

      const latestRegion = await screen.findByRole("region", {
        name: "最新行情",
      });
      await waitFor(() => {
        expect(
          within(latestRegion).getByText("所选区间内暂无行情"),
        ).toBeInTheDocument();
      });

      const barsRegion = await screen.findByRole("region", {
        name: "日行情明细",
      });
      expect(
        within(barsRegion).getByText("所选区间内无日行情"),
      ).toBeInTheDocument();
    });
  });

  describe("date range switching", () => {
    it("issues a new daily-bars request with the expected start_date/end_date/limit/offset when the user changes the range", async () => {
      const instrument = makeInstrument();
      mockFetchEtfInstruments.mockResolvedValue(makeInstrumentList([instrument]));

      const baseBars: DailyBarResponse[] = [];
      for (let i = 0; i < 5; i += 1) {
        const d = new Date(2026, 7, 3 - i);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        baseBars.push(
          makeBar(`${yyyy}-${mm}-${dd}`, {
            instrument_id: instrument.id,
            revision: 1,
          }),
        );
      }
      mockFetchEtfDailyBars.mockResolvedValue(makeBarsList(baseBars));

      setPathname(`/etf/${instrument.id}`);
      const user = userEvent.setup();

      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date("2026-08-03T12:00:00"));
      try {
        renderWithClient();

        await waitFor(() => {
          expect(mockFetchEtfDailyBars).toHaveBeenCalledTimes(1);
        });
        expect(mockFetchEtfDailyBars.mock.calls[0][0]).toEqual({
          instrument_id: instrument.id,
          start_date: "2026-06-05",
          end_date: "2026-08-03",
          limit: DAILY_BARS_PAGE_LIMIT,
          offset: 0,
        });
        expect(mockFetchEtfInstruments).toHaveBeenCalledWith(
          { limit: INSTRUMENT_LOOKUP_LIMIT, offset: 0 },
          expect.anything(),
        );

        await user.click(await screen.findByRole("button", { name: "30 日" }));
        await waitFor(() => {
          expect(mockFetchEtfDailyBars).toHaveBeenCalledTimes(2);
        });
        expect(mockFetchEtfDailyBars.mock.calls[1][0]).toEqual({
          instrument_id: instrument.id,
          start_date: "2026-07-05",
          end_date: "2026-08-03",
          limit: DAILY_BARS_PAGE_LIMIT,
          offset: 0,
        });

        await user.click(screen.getByRole("button", { name: "120 日" }));
        await waitFor(() => {
          expect(mockFetchEtfDailyBars).toHaveBeenCalledTimes(3);
        });
        expect(mockFetchEtfDailyBars.mock.calls[2][0]).toEqual({
          instrument_id: instrument.id,
          start_date: "2026-04-06",
          end_date: "2026-08-03",
          limit: DAILY_BARS_PAGE_LIMIT,
          offset: 0,
        });
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe("revision display", () => {
    it("surfaces the warning tone in the latest metric and the 已修订 pill in the table when revision > 1", async () => {
      const instrument = makeInstrument();
      const revisedBar = makeBar("2026-08-03", {
        instrument_id: instrument.id,
        revision: 2,
      });
      const normalBar = makeBar("2026-08-02", {
        instrument_id: instrument.id,
        revision: 1,
      });
      mockFetchEtfInstruments.mockResolvedValue(makeInstrumentList([instrument]));
      mockFetchEtfDailyBars.mockResolvedValue(
        makeBarsList([normalBar, revisedBar]),
      );

      setPathname(`/etf/${instrument.id}`);
      renderWithClient();

      const latestRegion = await screen.findByRole("region", {
        name: "最新行情",
      });
      await waitFor(() => {
        expect(within(latestRegion).getByText("2")).toBeInTheDocument();
      });
      const revisedCard = within(latestRegion)
        .getByText("修订")
        .closest("article")!;
      expect(revisedCard).toHaveClass("etfDetailLatestCard-warning");

      const barsRegion = await screen.findByRole("region", {
        name: "日行情明细",
      });
      await waitFor(() => {
        expect(
          within(barsRegion).getAllByText("已修订").length,
        ).toBeGreaterThanOrEqual(1);
      });
      const pills = within(barsRegion).getAllByText("已修订");
      expect(pills.length).toBe(1);
      for (const pill of pills) {
        expect(pill).toHaveClass("statusPillWarning");
      }

      expect(within(barsRegion).getByText("1")).toBeInTheDocument();
    });
  });
});
