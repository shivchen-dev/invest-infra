import type { ReactElement } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { WidgetFrame } from "../../../research-workspace/runtime";
import type { ResearchWidgetState } from "../../../research-workspace/runtime";
import type {
  ResearchDashboardResponse,
  ResearchRunResponse,
} from "../../../api/types";
import { formatDateTime } from "../../../utils/format";
import { RunStatusBadge } from "../../operations/RunStatusBadge";

export interface ResearchRunTimelineWidgetProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

const WIDGET_ID = "research-run-timeline";
const WIDGET_TITLE = "Research Run Timeline";
const WIDGET_DESCRIPTION =
  "最近 Research Run 列表 · 状态使用 API 返回字符串原样展示";
const WIDGET_PROVENANCE = "Read API · /api/v1/research-dashboard";

export function ResearchRunTimelineWidget({
  query,
}: ResearchRunTimelineWidgetProps) {
  const state = deriveState(query);
  const meta = {
    id: WIDGET_ID,
    title: WIDGET_TITLE,
    description: WIDGET_DESCRIPTION,
    page: "dashboard" as const,
    size: "wide" as const,
    state,
    provenance: WIDGET_PROVENANCE,
    generatedAt: query.data?.generated_at ?? null,
    asOf: query.data?.as_of_date ?? null,
  };

  let body: ReactElement;
  if (query.isPending) {
    body = <p>正在等待 Research Run Timeline 响应…</p>;
  } else if (query.isError) {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>无法读取 Research Run Timeline</strong>
        <span>{query.error.message}</span>
      </div>
    );
  } else {
    body = <RecentRunsTable runs={query.data.recent_runs ?? []} />;
  }

  return <WidgetFrame meta={meta}>{body}</WidgetFrame>;
}

function RecentRunsTable({ runs }: { runs: ReadonlyArray<ResearchRunResponse> }) {
  if (runs.length === 0) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>Recent Runs · 空</strong>
        <span>暂无 Research Run 记录。</span>
      </div>
    );
  }
  return (
    <div className="cockpitScrollTable">
      <table className="cockpitHistoryTable">
        <thead>
          <tr>
            <th scope="col">Run ID</th>
            <th scope="col">状态</th>
            <th scope="col">Runner</th>
            <th scope="col">Playbook</th>
            <th scope="col">Attempt</th>
            <th scope="col">开始时间</th>
            <th scope="col">结束时间</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td>{run.run_id}</td>
              <td>
                <RunStatusBadge status={run.status} />
              </td>
              <td>{run.runner_key}</td>
              <td>{run.playbook_key}</td>
              <td>{run.attempt}</td>
              <td>{formatDateTime(run.started_at)}</td>
              <td>{formatDateTime(run.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function deriveState(
  query: UseQueryResult<ResearchDashboardResponse, Error>,
): ResearchWidgetState {
  if (query.isPending) return "loading";
  if (query.isError) return "failed";
  if (!query.data) return "empty";
  const runs = query.data.recent_runs ?? [];
  return runs.length === 0 ? "empty" : "ready";
}
