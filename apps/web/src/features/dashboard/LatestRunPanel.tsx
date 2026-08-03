import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type { PipelineRunResponse } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import type { MetricTone } from "../../components/MetricCard";
import { formatDate, formatDateTime, formatDuration } from "../../utils/format";

type RunQuery = UseQueryResult<PipelineRunResponse, Error>;

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

export function LatestRunPanel({ query }: { query: RunQuery }) {
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