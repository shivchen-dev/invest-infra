import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  DataFreshnessResponse,
  DataFreshnessStatus,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { StatusBanner } from "../../components/StatusBanner";
import { formatCount, formatDate, formatDateTime } from "../../utils/format";

const STATUS_LABELS: Record<DataFreshnessStatus, string> = {
  fresh: "数据已更新",
  partial: "数据部分缺失",
  stale: "数据未更新到预期日期",
  missing: "尚无发布结果",
  failed: "最新任务失败",
};

type FreshnessQuery = UseQueryResult<DataFreshnessResponse, Error>;

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

export function FreshnessPanel({ query }: { query: FreshnessQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在检查数据新鲜度" compact />;
  }
  if (query.isError) {
    return (
      <ErrorState
        title="无法读取数据新鲜度"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无数据新鲜度信息" />;
  }
  return (
    <StatusBanner
      status={data.status}
      title={STATUS_LABELS[data.status]}
      description={`最近发布 ${formatDate(data.latest_published_trade_date)} · 检查时间 ${formatDateTime(data.as_of)}`}
      details={[
        { label: "标的池数量", value: `${formatCount(data.universe_count)} 只` },
        {
          label: "行情覆盖",
          value: `${formatCount(data.daily_bar_count)} 只`,
        },
        {
          label: "缺失数量",
          value: `${formatCount(data.missing_count)} 只`,
        },
        {
          label: "候选数量",
          value: `${formatCount(data.candidate_count)} 只`,
        },
      ]}
    />
  );
}
