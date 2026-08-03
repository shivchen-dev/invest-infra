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
import {
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
} from "../utils/format";

const HISTORY_LIMIT = 20;
const HISTORY_OFFSET = 0;
const REFETCH_INTERVAL = 60_000;
const ERROR_SUMMARY_MAX_LEN = 240;
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
        <LatestRunSection query={latestRunQuery} />
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
        <RecentRunsSection query={historyQuery} />
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
        <RerunHint />
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

type RunQuery = UseQueryResult<PipelineRunResponse, Error>;

function LatestRunSection({ query }: { query: RunQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载最新运行" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="尚无 Pipeline Run"
          description="系统暂未执行过任何 Pipeline。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取最新运行"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const run = query.data;
  if (!run) {
    return <EmptyState title="暂无最新运行" />;
  }
  const tone = pipelineStatusTone(run.status);
  return (
    <dl className="runSummary">
      <div>
        <dt>状态</dt>
        <dd>
          <span className={statusPillClass(tone)}>{run.status}</span>
        </dd>
      </div>
      <div>
        <dt>业务/分区日期</dt>
        <dd>{formatDate(run.partition_key)}</dd>
      </div>
      <div>
        <dt>触发方式</dt>
        <dd>{run.trigger_type}</dd>
      </div>
      <div>
        <dt>开始时间</dt>
        <dd>{formatDateTime(run.started_at)}</dd>
      </div>
      <div>
        <dt>结束时间</dt>
        <dd>{formatDateTime(run.finished_at)}</dd>
      </div>
      <div>
        <dt>耗时</dt>
        <dd>{formatDuration(run.started_at, run.finished_at)}</dd>
      </div>
      <div className="runSummaryFull">
        <dt>错误摘要</dt>
        <dd className="operationsErrorSummary">
          {sanitizeErrorSummary(run.error_summary)}
        </dd>
      </div>
    </dl>
  );
}

type HistoryQuery = UseQueryResult<PipelineRunListResponse, Error>;

function RecentRunsSection({ query }: { query: HistoryQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载最近运行" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="暂无运行历史"
          description="Pipeline Run 历史为空。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取运行历史"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data || data.items.length === 0) {
    return (
      <EmptyState
        title="暂无运行历史"
        description={`limit ${HISTORY_LIMIT} / offset ${HISTORY_OFFSET} 内没有结果。`}
      />
    );
  }

  const sorted = sortRunsByDateDesc(data.items);

  return (
    <div className="dataTableWrapper">
      <table
        className="dataTable operationsHistoryTable"
        aria-label="最近运行"
      >
        <thead>
          <tr>
            <th scope="col">日期</th>
            <th scope="col">状态</th>
            <th scope="col">触发</th>
            <th scope="col">开始</th>
            <th scope="col">结束</th>
            <th scope="col">耗时</th>
            <th scope="col">错误码</th>
            <th scope="col">Run ID</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => {
            const tone = pipelineStatusTone(run.status);
            return (
              <tr key={run.id}>
                <td>{formatDate(run.partition_key)}</td>
                <td>
                  <span className={statusPillClass(tone)}>{run.status}</span>
                </td>
                <td>{run.trigger_type}</td>
                <td>{formatDateTime(run.started_at)}</td>
                <td>{formatDateTime(run.finished_at)}</td>
                <td>{formatDuration(run.started_at, run.finished_at)}</td>
                <td>{run.error_code ?? "—"}</td>
                <td>
                  <code className="inlineCode">{run.id}</code>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="operationsHistoryFooter">
        共 {formatCount(data.total)} 条 · 显示 {formatCount(sorted.length)} 条
      </p>
    </div>
  );
}

function RerunHint() {
  return (
    <div className="operationsRerunHint">
      <p className="operationsRerunNote">
        仅作命令提示，不会触发任何写操作；请在确认网络影响后由运维执行。
      </p>
      <pre className="operationsRerunCode" aria-label="重跑命令">
        <code>{`make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1`}</code>
      </pre>
    </div>
  );
}

type PipelineTone = "neutral" | "success" | "warning" | "danger";

function pipelineStatusTone(status: string | null | undefined): PipelineTone {
  if (!status) return "neutral";
  const normalized = status.toLowerCase();
  if (
    normalized === "success" ||
    normalized === "succeeded" ||
    normalized === "completed"
  ) {
    return "success";
  }
  if (normalized === "failed" || normalized === "error") return "danger";
  if (
    normalized === "running" ||
    normalized === "pending" ||
    normalized === "started" ||
    normalized === "queued"
  ) {
    return "warning";
  }
  return "neutral";
}

function statusPillClass(tone: PipelineTone): string {
  switch (tone) {
    case "success":
      return "statusPill statusPillSuccess";
    case "warning":
      return "statusPill statusPillWarning";
    case "danger":
      return "statusPill statusPillDanger";
    default:
      return "statusPill statusPillNeutral";
  }
}

function sortRunsByDateDesc(runs: PipelineRunResponse[]): PipelineRunResponse[] {
  return runs.slice().sort((a, b) => {
    const ad = a.started_at ?? a.partition_key ?? "";
    const bd = b.started_at ?? b.partition_key ?? "";
    if (ad === bd) return a.id.localeCompare(b.id);
    return bd.localeCompare(ad);
  });
}

function sanitizeErrorSummary(raw: string | null | undefined): string {
  if (!raw) return "—";
  const cleaned = raw
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned.length === 0) return "—";
  if (cleaned.length <= ERROR_SUMMARY_MAX_LEN) return cleaned;
  return `${cleaned.slice(0, ERROR_SUMMARY_MAX_LEN)}…`;
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
