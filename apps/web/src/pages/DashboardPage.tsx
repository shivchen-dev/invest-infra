import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { fetchDataFreshness } from "../api/dataFreshness";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import type {
  CandidatePoolDiffEntry,
  CandidatePoolDiffResponse,
  CandidatePoolItem,
  CandidatePoolLatestResponse,
  DataFreshnessResponse,
  DataFreshnessStatus,
  PipelineRunResponse,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { MetricCard, type MetricTone } from "../components/MetricCard";
import { StatusBanner } from "../components/StatusBanner";
import {
  formatAmount,
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
} from "../utils/format";

const TOP_N = 10;

const STATUS_LABELS: Record<DataFreshnessStatus, string> = {
  fresh: "数据已更新",
  partial: "数据部分缺失",
  stale: "数据未更新到预期日期",
  missing: "尚无发布结果",
  failed: "最新任务失败",
};

const REFETCH_INTERVAL = {
  freshness: 60_000,
  candidatePool: 5 * 60_000,
  pipelineRun: 60_000,
} as const;

export function DashboardPage() {
  const freshness = useQuery<DataFreshnessResponse>({
    queryKey: ["data-freshness"],
    queryFn: ({ signal }) => fetchDataFreshness(signal),
    refetchInterval: REFETCH_INTERVAL.freshness,
  });

  const latestPool = useQuery<CandidatePoolLatestResponse>({
    queryKey: ["candidate-pool", "latest"],
    queryFn: ({ signal }) => fetchCandidatePoolLatest(signal),
    refetchInterval: REFETCH_INTERVAL.candidatePool,
  });

  const latestDiff = useQuery<CandidatePoolDiffResponse>({
    queryKey: ["candidate-pool", "latest", "diff"],
    queryFn: ({ signal }) => fetchCandidatePoolLatestDiff(signal),
    refetchInterval: REFETCH_INTERVAL.candidatePool,
  });

  const latestRun = useQuery<PipelineRunResponse>({
    queryKey: ["pipeline-runs", "latest"],
    queryFn: ({ signal }) => fetchLatestPipelineRun(signal),
    refetchInterval: REFETCH_INTERVAL.pipelineRun,
  });

  const initialLoading =
    freshness.isPending &&
    latestPool.isPending &&
    latestDiff.isPending &&
    latestRun.isPending;

  if (initialLoading) {
    return <LoadingState label="正在加载 Dashboard 数据" />;
  }

  return (
    <div className="dashboardPage">
      <header className="pageHeader">
        <p className="pageEyebrow">Dashboard</p>
        <h2 className="pageTitle">个人 ETF 数据工作台</h2>
        <p className="pageSubtitle">
          一屏判断数据是否最新、今天选了什么、有哪些变化。
        </p>
      </header>

      <section className="pageSection" aria-label="数据状态">
        <FreshnessSection query={freshness} />
      </section>

      <section className="pageSection" aria-label="关键指标">
        <h3 className="sectionTitle">关键指标</h3>
        <div className="metricGrid">
          <MetricCard
            label="个人 ETF 数"
            value={freshness.data ? formatCount(freshness.data.universe_count) : null}
          />
          <MetricCard
            label="当日行情覆盖"
            value={freshness.data ? formatCount(freshness.data.daily_bar_count) : null}
          />
          <MetricCard
            label="候选数"
            value={freshness.data ? formatCount(freshness.data.candidate_count) : null}
          />
          <MetricCard
            label="最新 Run 状态"
            value={freshness.data?.pipeline_status ?? null}
            valueAsText
            tone={pipelineStatusTone(freshness.data?.pipeline_status ?? null)}
          />
        </div>
      </section>

      <section className="pageSection" aria-label="候选池变化">
        <header className="sectionHeader">
          <h3 className="sectionTitle">候选池变化</h3>
          {latestDiff.data && (
            <span className="sectionMeta">
              对比 {formatDate(latestDiff.data.previous_trade_date)} →{" "}
              {formatDate(latestDiff.data.trade_date)}
            </span>
          )}
        </header>
        <DiffSection query={latestDiff} />
      </section>

      <section className="pageSection" aria-label="最新候选">
        <header className="sectionHeader">
          <h3 className="sectionTitle">最新入选候选（前 {TOP_N}）</h3>
          {latestPool.data && (
            <span className="sectionMeta">
              共 {formatCount(latestPool.data.row_count)} 只 · 入选{" "}
              {formatCount(latestPool.data.included_count)}
            </span>
          )}
        </header>
        <TopCandidatesSection query={latestPool} />
      </section>

      <section className="pageSection" aria-label="最新运行">
        <h3 className="sectionTitle">最新运行</h3>
        <LatestRunSection query={latestRun} />
      </section>
    </div>
  );
}

function pipelineStatusTone(status: string | null | undefined): MetricTone {
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

function statusPillClass(tone: MetricTone): string {
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

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
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

type DiffQuery = UseQueryResult<CandidatePoolDiffResponse, Error>;

function DiffSection({ query }: { query: DiffQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载候选池变化" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="尚无候选池差异"
          description="还没有可比较的发布结果。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取候选池变化"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const diff = query.data;
  if (!diff) {
    return <EmptyState title="暂无候选池差异数据" />;
  }
  return (
    <div className="diffGrid">
      <DiffColumn
        title="新增"
        tone="success"
        entries={diff.added}
        emptyText="本期无新增"
      />
      <DiffColumn
        title="保留"
        tone="neutral"
        entries={diff.retained}
        emptyText="本期无保留"
      />
      <DiffColumn
        title="移出"
        tone="danger"
        entries={diff.removed}
        emptyText="本期无移出"
      />
    </div>
  );
}

type DiffColumnTone = "success" | "danger" | "neutral";

function DiffColumn({
  title,
  tone,
  entries,
  emptyText,
}: {
  title: string;
  tone: DiffColumnTone;
  entries: CandidatePoolDiffEntry[];
  emptyText: string;
}) {
  const columnClass = `diffColumn diffColumn-${tone}`;
  return (
    <div className={columnClass}>
      <header className="diffColumnHeader">
        <h4>{title}</h4>
        <span className="diffColumnCount">{entries.length}</span>
      </header>
      {entries.length === 0 ? (
        <p className="diffEmpty">{emptyText}</p>
      ) : (
        <ul className="diffList">
          {entries.map((entry) => (
            <li key={entry.instrument_id} className="diffItem">
              <span className="diffSymbol">{entry.symbol ?? "—"}</span>
              <span className="diffName">{entry.name ?? "未命名"}</span>
              {entry.exchange && (
                <span className="diffExchange">{entry.exchange}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type PoolQuery = UseQueryResult<CandidatePoolLatestResponse, Error>;

function TopCandidatesSection({ query }: { query: PoolQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载最新候选" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="尚无候选结果"
          description="还没有发布的候选池。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取最新候选"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无候选结果" />;
  }
  const included = data.items
    .filter((item: CandidatePoolItem) => item.included)
    .slice()
    .sort((a, b) => {
      const rankA = a.rank ?? Number.POSITIVE_INFINITY;
      const rankB = b.rank ?? Number.POSITIVE_INFINITY;
      return rankA - rankB;
    })
    .slice(0, TOP_N);

  if (included.length === 0) {
    return (
      <EmptyState
        title="本期暂无入选候选"
        description={`本期共 ${formatCount(data.row_count)} 只标的，0 只入选。`}
      />
    );
  }

  return (
    <div className="dataTableWrapper">
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">排名</th>
            <th scope="col">代码</th>
            <th scope="col">名称</th>
            <th scope="col">交易所</th>
            <th scope="col">成交额</th>
            <th scope="col">状态</th>
          </tr>
        </thead>
        <tbody>
          {included.map((item) => (
            <tr key={item.instrument_id}>
              <td>{item.rank ?? "—"}</td>
              <td>{item.symbol ?? "—"}</td>
              <td>{item.name ?? "—"}</td>
              <td>{item.exchange ?? "—"}</td>
              <td>{formatAmount(item.metrics.turnover ?? null)}</td>
              <td>
                <span className="statusPill statusPillSuccess">入选</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
          description="系统暂未执行过 personal_etf_daily_job。"
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
        <dt>业务日期</dt>
        <dd>{formatDate(run.partition_key)}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>
          <span className={statusPillClass(tone)}>{run.status}</span>
        </dd>
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
        <dd>{run.error_summary ?? "—"}</dd>
      </div>
    </dl>
  );
}