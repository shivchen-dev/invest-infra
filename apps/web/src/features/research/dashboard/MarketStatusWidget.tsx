import type { ReactElement } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { WidgetFrame } from "../../../research-workspace/runtime";
import type { ResearchWidgetState } from "../../../research-workspace/runtime";
import type { ResearchDashboardResponse } from "../../../api/types";

export interface MarketStatusWidgetProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

const WIDGET_ID = "market-status";
const WIDGET_TITLE = "Market Status";
const WIDGET_DESCRIPTION =
  "市场状态观察 · 显式 unavailable 时不展示任何衍生指标";
const WIDGET_PROVENANCE = "Read API · /api/v1/research-dashboard";

export function MarketStatusWidget({ query }: MarketStatusWidgetProps) {
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
    body = <p>正在等待 Market Status 响应…</p>;
  } else if (query.isError) {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>无法读取 Market Status</strong>
        <span>{query.error.message}</span>
      </div>
    );
  } else {
    const marketStatus = query.data.market_status;
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>Market Status · unavailable</strong>
        <span>reason: {marketStatus.reason}</span>
        <span>PR-W03 显式不渲染任何市场/因子衍生数据。</span>
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
  if (!query.data) return "empty";
  return "empty";
}
