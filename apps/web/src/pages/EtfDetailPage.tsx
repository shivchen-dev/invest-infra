import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { fetchEtfInstruments } from "../api/instruments";
import { fetchEtfDailyBars } from "../api/dailyBars";
import type {
  DailyBarListResponse,
  DailyBarResponse,
  InstrumentListResponse,
  InstrumentResponse,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { useParams } from "../router";
import {
  formatCount,
  formatDate,
  formatDecimal,
} from "../utils/format";
import { DailyBarsTable } from "../features/instruments/DailyBarsTable";
import { InstrumentSummary } from "../features/instruments/InstrumentSummary";
import { MarketMetrics } from "../features/instruments/MarketMetrics";

const INSTRUMENT_LOOKUP_LIMIT = 1000;
const DAILY_BARS_PAGE_LIMIT = 1000;
const DEFAULT_RANGE_DAYS = 60;
const RANGE_OPTIONS: ReadonlyArray<number> = [30, 60, 120];

interface RangeMeta {
  days: number;
  startDate: string;
  endDate: string;
}

function isoDate(date: Date): string {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function buildRange(days: number): RangeMeta {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - (days - 1));
  return {
    days,
    startDate: isoDate(start),
    endDate: isoDate(end),
  };
}

export function EtfDetailPage() {
  const { instrumentId: rawInstrumentId } = useParams<{ instrumentId: string }>();
  const instrumentId = decodeInstrumentId(rawInstrumentId);

  const [rangeDays, setRangeDays] = useState<number>(DEFAULT_RANGE_DAYS);
  const range = useMemo(() => buildRange(rangeDays), [rangeDays]);

  const instrumentsQuery = useQuery<InstrumentListResponse>({
    queryKey: ["etf-instruments", { limit: INSTRUMENT_LOOKUP_LIMIT, offset: 0 }],
    queryFn: ({ signal }) =>
      fetchEtfInstruments(
        { limit: INSTRUMENT_LOOKUP_LIMIT, offset: 0 },
        signal,
      ),
  });

  const instrument = useMemo<InstrumentResponse | null>(() => {
    if (!instrumentsQuery.data || !instrumentId) return null;
    return (
      instrumentsQuery.data.items.find((item) => item.id === instrumentId) ??
      null
    );
  }, [instrumentsQuery.data, instrumentId]);

  const barsQuery = useQuery<DailyBarListResponse>({
    queryKey: [
      "etf-daily-bars",
      instrumentId ?? "",
      range.startDate,
      range.endDate,
    ],
    queryFn: ({ signal }) =>
      fetchEtfDailyBars(
        {
          instrument_id: instrumentId ?? "",
          start_date: range.startDate,
          end_date: range.endDate,
          limit: DAILY_BARS_PAGE_LIMIT,
          offset: 0,
        },
        signal,
      ),
    enabled: Boolean(instrumentId),
    retry: shouldRetry,
  });

  if (!instrumentId) {
    return (
      <div className="etfDetailPage">
        <PageHeader instrumentId="" />
        <ErrorState
          title="ETF ID 缺失"
          message="URL 中缺少 instrumentId，无法加载详情。"
        />
      </div>
    );
  }

  const initialLoading =
    instrumentsQuery.isPending || barsQuery.isPending;

  if (initialLoading) {
    return (
      <div className="etfDetailPage">
        <PageHeader instrumentId={instrumentId} />
        <LoadingState label="正在加载 ETF 详情" />
      </div>
    );
  }

  if (instrumentsQuery.isError) {
    return (
      <div className="etfDetailPage">
        <PageHeader instrumentId={instrumentId} />
        <ErrorState
          title="无法读取 ETF 主数据"
          message={describeError(instrumentsQuery.error)}
          onRetry={() => {
            void instrumentsQuery.refetch();
          }}
        />
      </div>
    );
  }

  if (!instrument) {
    return (
      <div className="etfDetailPage">
        <PageHeader instrumentId={instrumentId} />
        <EmptyState
          title="未找到该 ETF"
          description={`未在主数据中找到 instrumentId = ${instrumentId}。`}
        />
      </div>
    );
  }

  return (
    <div className="etfDetailPage">
      <PageHeader
        instrumentId={instrumentId}
        symbol={instrument.symbol}
        name={instrument.name}
      />

      <section className="pageSection" aria-labelledby="etf-metadata-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="etf-metadata-title">
            主数据
          </h3>
          {instrument.exchange && (
            <span className="sectionMeta">{instrument.exchange}</span>
          )}
        </header>
        <InstrumentSummary instrument={instrument} />
      </section>

      <section className="pageSection" aria-labelledby="etf-latest-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="etf-latest-title">
            最新行情
          </h3>
          <span className="sectionMeta">
            区间 {formatDate(range.startDate)} → {formatDate(range.endDate)} · 共{" "}
            {barsQuery.data ? formatCount(barsQuery.data.items.length) : "—"} 条
          </span>
        </header>
        <MarketMetrics
          query={barsQuery}
          rangeOptions={RANGE_OPTIONS}
          rangeDays={rangeDays}
          onRangeChange={setRangeDays}
          isNotFound={isNotFound}
          describeError={describeError}
          sortBarsByDate={sortBarsByDate}
          computeChange={computeChange}
          toNumber={toNumber}
        />
      </section>

      <section className="pageSection" aria-labelledby="etf-bars-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="etf-bars-title">
            日行情明细
          </h3>
        </header>
        <DailyBarsTable
          query={barsQuery}
          isNotFound={isNotFound}
          describeError={describeError}
          sortBarsByDate={sortBarsByDate}
          findPreviousBar={findPreviousBar}
          computeChange={computeChange}
        />
      </section>
    </div>
  );
}

function PageHeader({
  instrumentId,
  symbol,
  name,
}: {
  instrumentId: string;
  symbol?: string;
  name?: string;
}) {
  return (
    <header className="pageHeader">
      <p className="pageEyebrow">ETF Detail</p>
      <h2 className="pageTitle">
        {symbol ?? "ETF 详情"}
        {name && <span className="etfDetailSubtitle">· {name}</span>}
      </h2>
      <p className="pageSubtitle">
        instrument_id：<code className="inlineCode">{instrumentId}</code>
      </p>
    </header>
  );
}

interface ChangeSummary {
  display: string;
  percentDisplay: string;
  tone: "success" | "danger" | "neutral";
  suffix?: string;
}

function computeChange(
  current: DailyBarResponse,
  previous: DailyBarResponse | null,
): ChangeSummary {
  const currentClose = toNumber(current.close);
  if (currentClose === null) {
    return { display: "—", percentDisplay: "—", tone: "neutral" };
  }
  const prevClose = toNumber(current.prev_close) ?? toNumber(previous?.close);
  if (prevClose === null || prevClose === 0) {
    return { display: "—", percentDisplay: "—", tone: "neutral" };
  }
  const diff = currentClose - prevClose;
  const pct = (diff / prevClose) * 100;
  const tone: ChangeSummary["tone"] = diff > 0 ? "success" : diff < 0 ? "danger" : "neutral";
  const sign = diff > 0 ? "+" : "";
  return {
    display: `${sign}${formatDecimal(diff, 4)}`,
    percentDisplay: `${sign}${pct.toFixed(2)}`,
    tone,
  };
}

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(n) ? n : null;
}

function sortBarsByDate(bars: DailyBarResponse[]): DailyBarResponse[] {
  return bars
    .slice()
    .sort((a, b) => a.trade_date.localeCompare(b.trade_date));
}

function findPreviousBar(
  bars: DailyBarResponse[],
  tradeDate: string,
): DailyBarResponse | null {
  for (let i = bars.length - 1; i >= 0; i -= 1) {
    if (bars[i].trade_date < tradeDate) return bars[i];
  }
  return null;
}

function decodeInstrumentId(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function shouldRetry(failureCount: number, error: Error): boolean {
  return !isNotFound(error) && failureCount < 3;
}

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.message;
  if (error instanceof Error) return error.message;
  return "未知错误";
}