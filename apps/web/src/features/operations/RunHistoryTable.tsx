import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  PipelineRunListResponse,
  PipelineRunResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import {
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
} from "../../utils/format";
import { RunStatusBadge } from "./RunStatusBadge";

type HistoryQuery = UseQueryResult<PipelineRunListResponse, Error>;

export function RunHistoryTable({
  query,
  limit,
  offset,
}: {
  query: HistoryQuery;
  limit: number;
  offset: number;
}) {
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
        description={`limit ${limit} / offset ${offset} 内没有结果。`}
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
          {sorted.map((run) => (
            <tr key={run.id}>
              <td>{formatDate(run.partition_key)}</td>
              <td>
                <RunStatusBadge status={run.status} />
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
          ))}
        </tbody>
      </table>
      <p className="operationsHistoryFooter">
        共 {formatCount(data.total)} 条 · 显示 {formatCount(sorted.length)} 条
      </p>
    </div>
  );
}

function sortRunsByDateDesc(runs: PipelineRunResponse[]): PipelineRunResponse[] {
  return runs.slice().sort((a, b) => {
    const ad = a.started_at ?? a.partition_key ?? "";
    const bd = b.started_at ?? b.partition_key ?? "";
    if (ad === bd) return a.id.localeCompare(b.id);
    return bd.localeCompare(ad);
  });
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