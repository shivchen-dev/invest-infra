import type { UseQueryResult } from "@tanstack/react-query";
import type {
  DailyBarListResponse,
  DailyBarResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import {
  formatAmount,
  formatCount,
  formatDate,
  formatDateTime,
  formatDecimal,
} from "../../utils/format";

type BarsQuery = UseQueryResult<DailyBarListResponse, Error>;

interface ChangeSummary {
  display: string;
  percentDisplay: string;
  tone: "success" | "danger" | "neutral";
  suffix?: string;
}

interface DailyBarsTableProps {
  query: BarsQuery;
  isNotFound: (error: unknown) => boolean;
  describeError: (error: unknown) => string;
  sortBarsByDate: (bars: DailyBarResponse[]) => DailyBarResponse[];
  findPreviousBar: (
    bars: DailyBarResponse[],
    tradeDate: string,
  ) => DailyBarResponse | null;
  computeChange: (
    current: DailyBarResponse,
    previous: DailyBarResponse | null,
  ) => ChangeSummary;
}

export function DailyBarsTable({
  query,
  isNotFound,
  describeError,
  sortBarsByDate,
  findPreviousBar,
  computeChange,
}: DailyBarsTableProps) {
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
