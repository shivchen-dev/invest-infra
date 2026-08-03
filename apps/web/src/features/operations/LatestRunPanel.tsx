import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type { PipelineRunResponse } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import {
  formatDate,
  formatDateTime,
  formatDuration,
} from "../../utils/format";
import { RunStatusBadge } from "./RunStatusBadge";

type RunQuery = UseQueryResult<PipelineRunResponse, Error>;

const ERROR_SUMMARY_MAX_LEN = 240;

export function LatestRunPanel({ query }: { query: RunQuery }) {
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
  return (
    <dl className="runSummary">
      <div>
        <dt>状态</dt>
        <dd>
          <RunStatusBadge status={run.status} />
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