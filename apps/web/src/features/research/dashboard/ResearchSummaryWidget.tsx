import type { ReactElement } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { WidgetFrame } from "../../../research-workspace/runtime";
import type { ResearchWidgetState } from "../../../research-workspace/runtime";
import type {
  ResearchDashboardResponse,
  ResearchCaseResponse,
} from "../../../api/types";
import { formatCount, formatDate } from "../../../utils/format";

export interface ResearchSummaryWidgetProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

const WIDGET_ID = "research-summary";
const WIDGET_TITLE = "Research Summary";
const WIDGET_DESCRIPTION =
  "已发布研究案例的统计与最新案例元数据 · 不展示 stance/confidence";
const WIDGET_PROVENANCE = "Read API · /api/v1/research-dashboard";

export function ResearchSummaryWidget({ query }: ResearchSummaryWidgetProps) {
  const state = deriveState(query);
  const meta = {
    id: WIDGET_ID,
    title: WIDGET_TITLE,
    description: WIDGET_DESCRIPTION,
    page: "dashboard" as const,
    size: "medium" as const,
    state,
    provenance: WIDGET_PROVENANCE,
    generatedAt: query.data?.generated_at ?? null,
    asOf: query.data?.as_of_date ?? null,
  };

  let body: ReactElement;
  if (query.isPending) {
    body = <p>正在等待 Research Summary 响应…</p>;
  } else if (query.isError) {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>无法读取 Research Summary</strong>
        <span>{query.error.message}</span>
      </div>
    );
  } else {
    const summary = query.data.research_summary;
    body = (
      <>
        <dl className="cockpitKeyValueList">
          <div>
            <dt>已发布案例数</dt>
            <dd>{formatCount(summary.case_count)}</dd>
          </div>
          <div>
            <dt>累计 Run 数</dt>
            <dd>{formatCount(summary.run_count)}</dd>
          </div>
        </dl>
        <LatestCaseBlock latestCase={summary.latest_case} />
      </>
    );
  }

  return <WidgetFrame meta={meta}>{body}</WidgetFrame>;
}

function LatestCaseBlock({ latestCase }: { latestCase: ResearchCaseResponse | null }) {
  if (latestCase === null) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>Latest Case · 无可展示案例</strong>
        <span>暂无已发布 Research Case。</span>
      </div>
    );
  }
  return (
    <dl className="cockpitKeyValueList">
      <div>
        <dt>Case ID</dt>
        <dd>{latestCase.case_id}</dd>
      </div>
      <div>
        <dt>观测日期</dt>
        <dd>{formatDate(latestCase.as_of_date)}</dd>
      </div>
      <div>
        <dt>创建时间</dt>
        <dd>{latestCase.created_at}</dd>
      </div>
      <div>
        <dt>研究问题</dt>
        <dd>{latestCase.question}</dd>
      </div>
      <div>
        <dt>Horizon</dt>
        <dd>{latestCase.horizon}</dd>
      </div>
      <div>
        <dt>Case 状态</dt>
        <dd>{latestCase.status}</dd>
      </div>
    </dl>
  );
}

function deriveState(
  query: UseQueryResult<ResearchDashboardResponse, Error>,
): ResearchWidgetState {
  if (query.isPending) return "loading";
  if (query.isError) return "failed";
  if (!query.data) return "empty";
  const summary = query.data.research_summary;
  if (summary.case_count === 0 && summary.run_count === 0 && summary.latest_case === null) {
    return "empty";
  }
  return "ready";
}
