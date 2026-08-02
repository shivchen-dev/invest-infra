import { useMemo, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
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
  formatAmount,
  formatCount,
  formatDate,
  formatDateTime,
  formatDecimal,
} from "../utils/format";

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
        <InstrumentMetadata instrument={instrument} />
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
        <LatestBarSection query={barsQuery} rangeDays={rangeDays} onRangeChange={setRangeDays} />
      </section>

      <section className="pageSection" aria-labelledby="etf-bars-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="etf-bars-title">
            日行情明细
          </h3>
        </header>
        <DailyBarsTable query={barsQuery} />
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

function InstrumentMetadata({ instrument }: { instrument: InstrumentResponse }) {
  return (
    <dl className="runSummary etfDetailMetadata">
      <div>
        <dt>代码</dt>
        <dd>{instrument.symbol ?? "—"}</dd>
      </div>
      <div>
        <dt>名称</dt>
        <dd>{instrument.name ?? "—"}</dd>
      </div>
      <div>
        <dt>交易所</dt>
        <dd>{instrument.exchange ?? "—"}</dd>
      </div>
      <div>
        <dt>类型</dt>
        <dd>{instrument.instrument_type ?? "—"}</dd>
      </div>
      <div>
        <dt>货币</dt>
        <dd>{instrument.currency ?? "—"}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>
          <span
            className={`statusPill ${
              instrument.is_active ? "statusPillSuccess" : "statusPillNeutral"
            }`}
          >
            {instrument.status || (instrument.is_active ? "active" : "inactive")}
          </span>
        </dd>
      </div>
      <div>
        <dt>上市日</dt>
        <dd>{formatDate(instrument.list_date)}</dd>
      </div>
      <div>
        <dt>退市日</dt>
        <dd>{formatDate(instrument.delist_date)}</dd>
      </div>
      <div>
        <dt>跟踪指数</dt>
        <dd>{instrument.underlying_index ?? "—"}</dd>
      </div>
      <div>
        <dt>分类</dt>
        <dd>{instrument.category ?? "—"}</dd>
      </div>
    </dl>
  );
}

type BarsQuery = UseQueryResult<DailyBarListResponse, Error>;

function LatestBarSection({
  query,
  rangeDays,
  onRangeChange,
}: {
  query: BarsQuery;
  rangeDays: number;
  onRangeChange: (days: number) => void;
}) {
  if (query.isPending) {
    return <LoadingState label="正在加载日行情" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="暂无日行情"
          description="该 ETF 在所选区间内没有可用行情。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取日行情"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }

  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无日行情" />;
  }

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="所选区间内暂无行情"
        description="请尝试更长的区间。"
      />
    );
  }

  const sortedBars = sortBarsByDate(data.items);
  const latest = sortedBars[sortedBars.length - 1];
  const previous = sortedBars.length >= 2 ? sortedBars[sortedBars.length - 2] : null;
  const change = computeChange(latest, previous);

  return (
    <>
      <div className="etfDetailRangeRow" role="group" aria-label="行情区间">
        {RANGE_OPTIONS.map((days) => {
          const selected = days === rangeDays;
          return (
            <button
              key={days}
              type="button"
              className={`etfDetailRangeButton${
                selected ? " etfDetailRangeButtonActive" : ""
              }`}
              aria-pressed={selected}
              onClick={() => onRangeChange(days)}
            >
              {days} 日
            </button>
          );
        })}
      </div>

      <div className="etfDetailLatestGrid">
        <LatestCard
          label="收盘价"
          value={formatDecimal(latest.close, 4)}
          tone="neutral"
        />
        <LatestCard
          label="涨跌"
          value={change.display}
          tone={change.tone}
          suffix={change.suffix}
        />
        <LatestCard
          label="涨跌幅"
          value={change.percentDisplay}
          tone={change.tone}
          suffix="%"
        />
        <LatestCard
          label="成交量"
          value={formatCount(latest.volume)}
          tone="neutral"
        />
        <LatestCard
          label="成交额"
          value={formatAmount(latest.amount)}
          tone="neutral"
        />
        <LatestCard
          label="数据源"
          value={latest.source_provider ?? "—"}
          tone="neutral"
        />
        <LatestCard
          label="修订"
          value={
            latest.revision !== null && latest.revision !== undefined
              ? String(latest.revision)
              : "—"
          }
          tone={
            latest.revision !== null && latest.revision > 1
              ? "warning"
              : "neutral"
          }
        />
        <LatestCard
          label="交易日"
          value={formatDate(latest.trade_date)}
          tone="neutral"
        />
      </div>

      <ClosePriceChart bars={sortedBars} />
    </>
  );
}

function LatestCard({
  label,
  value,
  tone,
  suffix,
}: {
  label: string;
  value: string;
  tone: "neutral" | "success" | "danger" | "warning";
  suffix?: string;
}) {
  return (
    <article className={`etfDetailLatestCard etfDetailLatestCard-${tone}`}>
      <p className="etfDetailLatestLabel">{label}</p>
      <p className="etfDetailLatestValue">
        <span>{value}</span>
        {suffix && <span className="etfDetailLatestSuffix">{suffix}</span>}
      </p>
    </article>
  );
}

function DailyBarsTable({ query }: { query: BarsQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载日行情明细" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="暂无日行情明细"
          description="该 ETF 在所选区间内没有可用行情。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取日行情明细"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无日行情明细" />;
  }
  if (data.items.length === 0) {
    return (
      <EmptyState
        title="所选区间内无日行情"
        description="尝试切换更长的区间。"
      />
    );
  }

  const sortedBars = sortBarsByDate(data.items);

  return (
    <div className="dataTableWrapper">
      <table className="dataTable etfDetailBarsTable" aria-label="日行情明细">
        <thead>
          <tr>
            <th scope="col">交易日</th>
            <th scope="col">开盘</th>
            <th scope="col">最高</th>
            <th scope="col">最低</th>
            <th scope="col">收盘</th>
            <th scope="col">涨跌</th>
            <th scope="col">涨跌幅</th>
            <th scope="col">成交量</th>
            <th scope="col">成交额</th>
            <th scope="col">数据源</th>
            <th scope="col">修订</th>
          </tr>
        </thead>
        <tbody>
          {sortedBars.map((bar) => {
            const previous = findPreviousBar(sortedBars, bar.trade_date);
            const change = computeChange(bar, previous);
            const revised = bar.revision !== null && bar.revision > 1;
            return (
              <tr key={`${bar.trade_date}-${bar.revision ?? 0}`}>
                <td>{formatDate(bar.trade_date)}</td>
                <td>{formatDecimal(bar.open, 4)}</td>
                <td>{formatDecimal(bar.high, 4)}</td>
                <td>{formatDecimal(bar.low, 4)}</td>
                <td>{formatDecimal(bar.close, 4)}</td>
                <td className={`etfDetailChangeCell etfDetailChangeCell-${change.tone}`}>
                  {change.display}
                </td>
                <td className={`etfDetailChangeCell etfDetailChangeCell-${change.tone}`}>
                  {change.percentDisplay}%
                </td>
                <td>{formatCount(bar.volume)}</td>
                <td>{formatAmount(bar.amount)}</td>
                <td>{bar.source_provider ?? "—"}</td>
                <td>
                  {revised ? (
                    <span className="statusPill statusPillWarning">已修订</span>
                  ) : (
                    <span className="statusPill statusPillNeutral">
                      {bar.revision ?? "—"}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="etfDetailBarsFooter">
        共 {formatCount(sortedBars.length)} 条 · 抓取时间{" "}
        {formatDateTime(data.items[data.items.length - 1]?.observed_at)}
      </p>
    </div>
  );
}

function ClosePriceChart({ bars }: { bars: DailyBarResponse[] }) {
  const closePrices = bars
    .map((bar) => toNumber(bar.close))
    .filter((value): value is number => value !== null);

  if (closePrices.length < 2) {
    return (
      <EmptyState
        title="无法绘制走势图"
        description="可用收盘价不足两条。"
      />
    );
  }

  const width = 720;
  const height = 200;
  const paddingX = 36;
  const paddingY = 24;
  const innerWidth = width - paddingX * 2;
  const innerHeight = height - paddingY * 2;

  const min = Math.min(...closePrices);
  const max = Math.max(...closePrices);
  const range = max - min || 1;

  const points = closePrices.map((value, index) => {
    const x =
      paddingX + (innerWidth * index) / Math.max(closePrices.length - 1, 1);
    const y =
      paddingY + innerHeight - ((value - min) / range) * innerHeight;
    return { x, y, value };
  });

  const linePath = points
    .map((point, index) =>
      index === 0 ? `M ${point.x} ${point.y}` : `L ${point.x} ${point.y}`,
    )
    .join(" ");

  const fillPath = `${linePath} L ${points[points.length - 1].x} ${
    paddingY + innerHeight
  } L ${points[0].x} ${paddingY + innerHeight} Z`;

  const firstDate = bars[0]?.trade_date ?? "";
  const lastDate = bars[bars.length - 1]?.trade_date ?? "";
  const middleDate =
    bars[Math.floor(bars.length / 2)]?.trade_date ?? "";

  return (
    <figure className="etfDetailChart" aria-label="收盘价走势图">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        preserveAspectRatio="xMidYMid meet"
        className="etfDetailChartSvg"
      >
        <title>收盘价走势图</title>
        <desc>
          {firstDate} 至 {lastDate}，共 {bars.length} 个交易日，最高 {formatDecimal(max)}，
          最低 {formatDecimal(min)}。
        </desc>
        <g className="etfDetailChartGrid">
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const y = paddingY + innerHeight * (1 - tick);
            return (
              <line
                key={tick}
                x1={paddingX}
                x2={width - paddingX}
                y1={y}
                y2={y}
              />
            );
          })}
        </g>
        <path d={fillPath} className="etfDetailChartArea" />
        <path d={linePath} className="etfDetailChartLine" />
        {points.map((point, index) => (
          <circle
            key={index}
            cx={point.x}
            cy={point.y}
            r={2.5}
            className="etfDetailChartPoint"
          />
        ))}
        <g className="etfDetailChartAxis">
          <text x={paddingX} y={paddingY - 6} textAnchor="start">
            {formatDecimal(max, 4)}
          </text>
          <text
            x={paddingX}
            y={paddingY + innerHeight + 14}
            textAnchor="start"
          >
            {formatDecimal(min, 4)}
          </text>
          <text x={paddingX} y={height - 4} textAnchor="start">
            {formatDate(firstDate)}
          </text>
          {middleDate && (
            <text
              x={paddingX + innerWidth / 2}
              y={height - 4}
              textAnchor="middle"
            >
              {formatDate(middleDate)}
            </text>
          )}
          <text
            x={width - paddingX}
            y={height - 4}
            textAnchor="end"
          >
            {formatDate(lastDate)}
          </text>
        </g>
      </svg>
    </figure>
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