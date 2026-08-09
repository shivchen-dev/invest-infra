import type { ReactElement } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { WidgetFrame } from "../../../research-workspace/runtime";
import type { ResearchWidgetState } from "../../../research-workspace/runtime";
import type { ResearchDashboardResponse } from "../../../api/types";

export interface EvidencePackWidgetProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

const WIDGET_ID = "evidence-pack";
const WIDGET_TITLE = "Evidence Pack";
const WIDGET_DESCRIPTION =
  "只读展示的 Evidence Pack 标识与质量元数据 · 浏览器不重算";
const WIDGET_PROVENANCE = "Read API · /api/v1/research-dashboard";

export function EvidencePackWidget({ query }: EvidencePackWidgetProps) {
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
    body = <p>正在等待 Evidence Pack 响应…</p>;
  } else if (query.isError) {
    body = (
      <div className="cockpitWidgetPlaceholder">
        <strong>无法读取 Evidence Pack</strong>
        <span>{query.error.message}</span>
      </div>
    );
  } else {
    body = <EvidencePackBody status={query.data.evidence_status} />;
  }

  return <WidgetFrame meta={meta}>{body}</WidgetFrame>;
}

function EvidencePackBody({
  status,
}: {
  status: ResearchDashboardResponse["evidence_status"];
}) {
  if (status.state === "empty") {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>Evidence Pack · empty</strong>
        {status.case_id ? (
          <span>Case {status.case_id} 暂未绑定任何 Evidence Pack。</span>
        ) : (
          <span>暂无 Case，Evidence Pack 槽位保持 empty。</span>
        )}
      </div>
    );
  }
  return (
    <dl className="cockpitKeyValueList">
      <div>
        <dt>Evidence Pack ID</dt>
        <dd>{status.pack_id ?? "—"}</dd>
      </div>
      <div>
        <dt>Schema Version</dt>
        <dd>{status.schema_version ?? "—"}</dd>
      </div>
      <div>
        <dt>Factor Set</dt>
        <dd>
          {status.factor_set_key ?? "—"}
          {status.factor_set_version ? ` · ${status.factor_set_version}` : ""}
        </dd>
      </div>
      <div>
        <dt>Quality Status</dt>
        <dd>{status.quality_status ?? "—"}</dd>
      </div>
      <div>
        <dt>Freshness Status</dt>
        <dd>{status.freshness_status ?? "—"}</dd>
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
  return query.data.evidence_status.state === "available" ? "ready" : "empty";
}
