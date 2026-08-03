import type { UseQueryResult } from "@tanstack/react-query";
import type {
  DailyBarListResponse,
  DailyBarResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { formatAmount, formatCount, formatDate, formatDecimal } from "../../utils/format";
import { ClosePriceChart } from "./ClosePriceChart";
import { DateRangeSelector } from "./DateRangeSelector";

type BarsQuery = UseQueryResult<DailyBarListResponse, Error>;
type ChangeTone = "success" | "danger" | "neutral";

interface ChangeSummary {
  display: string;
  percentDisplay: string;
  tone: ChangeTone;
  suffix?: string;
}

interface MarketMetricsProps {
  query: BarsQuery;
  rangeOptions: ReadonlyArray<number>;
  rangeDays: number;
  onRangeChange: (days: number) => void;
  isNotFound: (error: unknown) => boolean;
  describeError: (error: unknown) => string;
  sortBarsByDate: (bars: DailyBarResponse[]) => DailyBarResponse[];
  computeChange: (
    current: DailyBarResponse,
    previous: DailyBarResponse | null,
  ) => ChangeSummary;
  toNumber: (value: string | number | null | undefined) => number | null;
}

export function MarketMetrics({
  query,
  rangeOptions,
  rangeDays,
  onRangeChange,
  isNotFound,
  describeError,
  sortBarsByDate,
  computeChange,
  toNumber,
}: MarketMetricsProps) {
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
      <DateRangeSelector
        options={rangeOptions}
        rangeDays={rangeDays}
        onRangeChange={onRangeChange}
      />

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

      <ClosePriceChart bars={sortedBars} toNumber={toNumber} />
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
