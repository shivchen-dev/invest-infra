import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { fetchDataFreshness } from "../api/dataFreshness";
import {
  fetchLatestPipelineRun,
  fetchPipelineRuns,
  latestPipelineRunQueryKey,
  pipelineRunsQueryKey,
} from "../api/pipelineRuns";
import { ApiError } from "../api/client";
import type {
  DataFreshnessResponse,
  DataFreshnessStatus,
  PipelineRunListResponse,
  PipelineRunResponse,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { StatusBanner } from "../components/StatusBanner";
import { LatestRunPanel } from "../features/operations/LatestRunPanel";
import { ReprocessHint } from "../features/operations/ReprocessHint";
import { RunHistoryTable } from "../features/operations/RunHistoryTable";
import {
  formatCount,
  formatDate,
  formatDateTime,
} from "../utils/format";

const HISTORY_LIMIT = 20;
const HISTORY_OFFSET = 0;
const REFETCH_INTERVAL = 60_000;
const MARKET_TIMEZONE = "Asia/Shanghai";

const STATUS_LABELS: Record<DataFreshnessStatus, string> = {
  fresh: "数据已更新",
  partial: "数据部分缺失",
  stale: "数据未更新到预期日期",
  missing: "尚无发布结果",
  failed: "最新任务失败",
};

export function OperationsPage() {
  const latestRunQuery = useQuery<PipelineRunResponse>({
    queryKey: latestPipelineRunQueryKey,
    queryFn: ({ signal }) => fetchLatestPipelineRun(signal),
    refetchInterval: REFETCH_INTERVAL,
    retry: shouldRetry,
  });

  const historyQuery = useQuery<PipelineRunListResponse>({
    queryKey: pipelineRunsQueryKey({
      limit: HISTORY_LIMIT,
      offset: HISTORY_OFFSET,
    }),
    queryFn: ({ signal }) =>
      fetchPipelineRuns(
        { limit: HISTORY_LIMIT, offset: HISTORY_OFFSET },
        signal,
      ),
    refetchInterval: REFETCH_INTERVAL,
    retry: shouldRetry,
  });

  const freshnessQuery = useQuery<DataFreshnessResponse>({
    queryKey: ["data-freshness"],
    queryFn: ({ signal }) => fetchDataFreshness(signal),
    refetchInterval: REFETCH_INTERVAL,
    retry: shouldRetry,
  });

  const initialLoading =
    latestRunQuery.isPending &&
    historyQuery.isPending &&
    freshnessQuery.isPending;

  if (initialLoading) {
    return (
      <div className="operationsPage">
        <PageHeader />
        <LoadingState label="正在加载 Operations 数据" />
      </div>
    );
  }

  return (
    <div className="operationsPage">
      <PageHeader />

      <section
        className="pageSection"
        aria-labelledby="operations-freshness-title"
      >
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="operations-freshness-title">
            数据新鲜度
          </h3>
        </header>
        <FreshnessSection query={freshnessQuery} />
      </section>

      <section
        className="pageSection"
        aria-labelledby="operations-latest-run-title"
      >
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="operations-latest-run-title">
            最新运行
          </h3>
        </header>
        <LatestRunPanel query={latestRunQuery} />
      </section>

      <section
        className="pageSection"
        aria-labelledby="operations-history-title"
      >
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="operations-history-title">
            最近运行
          </h3>
          <span className="sectionMeta">
            最近 {HISTORY_LIMIT} 条 · offset {HISTORY_OFFSET}
          </span>
        </header>
        <RunHistoryTable
          query={historyQuery}
          limit={HISTORY_LIMIT}
          offset={HISTORY_OFFSET}
        />
      </section>

      <section
        className="pageSection"
        aria-labelledby="operations-rerun-title"
      >
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="operations-rerun-title">
            重跑命令提示
          </h3>
        </header>
        <ReprocessHint />
      </section>
    </div>
  );
}

function PageHeader() {
  return (
    <header className="pageHeader">
      <p className="pageEyebrow">Operations</p>
      <h2 className="pageTitle">Pipeline 运行观测</h2>
      <p className="pageSubtitle">
        集中查看最新一次运行、最近 {HISTORY_LIMIT} 条历史与数据新鲜度，所有操作只读。
      </p>
    </header>
  );
}

type FreshnessQuery = UseQueryResult<DataFreshnessResponse, Error>;

function FreshnessSection({ query }: { query: FreshnessQuery }) {
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
  const expectedDate = computeExpectedTradeDate(data.as_of);
  return (
    <StatusBanner
      status={data.status}
      title={STATUS_LABELS[data.status]}
      description={`最近发布 ${formatDate(data.latest_published_trade_date)} · 检查时间 ${formatDateTime(data.as_of)}`}
      details={[
        { label: "预期发布日", value: formatDate(expectedDate) },
        { label: "实际发布日", value: formatDate(data.latest_published_trade_date) },
        {
          label: "标的池数量",
          value: `${formatCount(data.universe_count)} 只`,
        },
        {
          label: "日行情覆盖",
          value: `${formatCount(data.daily_bar_count)} 只`,
        },
        {
          label: "缺失数量",
          value: `${formatCount(data.missing_count)} 只`,
        },
      ]}
    />
  );
}

export function computeExpectedTradeDate(asOf: string | null | undefined): string {
  if (!asOf) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(asOf)) {
    return previousBusinessDay(asOf);
  }
  const date = new Date(asOf);
  if (Number.isNaN(date.getTime())) return asOf.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: MARKET_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((result, part) => {
      result[part.type] = part.value;
      return result;
    }, {});
  const marketDate = `${parts.year}-${parts.month}-${parts.day}`;
  return previousBusinessDay(marketDate);
}

function previousBusinessDay(value: string): string {
  const candidate = new Date(`${value}T00:00:00Z`);
  for (let i = 0; i < 7; i += 1) {
    const day = candidate.getUTCDay();
    if (day !== 0 && day !== 6) break;
    candidate.setUTCDate(candidate.getUTCDate() - 1);
  }
  return candidate.toISOString().slice(0, 10);
}

function shouldRetry(failureCount: number, error: Error): boolean {
  return !isNotFound(error) && failureCount < 3;
}

function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}