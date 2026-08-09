import type { ReactElement } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { WidgetFrame } from "../../../research-workspace/runtime";
import type { ResearchWidgetState } from "../../../research-workspace/runtime";
import type { ResearchDashboardResponse } from "../../../api/types";

export interface FactorSnapshotWidgetProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

const WIDGET_ID = "factor-snapshot";
const WIDGET_TITLE = "Factor Snapshot";
const WIDGET_DESCRIPTION =
  "来自 Analytics 的因子观测 · PR-W04 暂无因子负载，显式 unavailable";
const WIDGET_PROVENANCE = "Read API · /api/v1/research-dashboard";

export function FactorSnapshotWidget({ query }: FactorSnapshotWidgetProps) {
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
    body = <p>正在等待 Factor Snapshot 响应…</p>;
  } else if (query.isError) {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>无法读取 Factor Snapshot</strong>
        <span>{query.error.message}</span>
      </div>
    );
  } else {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>Factor Snapshot · unavailable</strong>
        <span>PR-W04 尚未接入因子负载，浏览器不计算任何投资结论。</span>
      </div>
    );
  }

  return <WidgetFrame meta={meta}>{body}</WidgetFrame>;
}

function deriveState(
  query: UseQueryResult<ResearchDashboardResponse, Error>,
): ResearchWidgetState {
  if (query.isPending) return "loading";
  if (query.isError) return "failed";
  return "empty";
}
