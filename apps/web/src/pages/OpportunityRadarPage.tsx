import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchOpportunityRadar,
  opportunityRadarQueryKey,
  type OpportunityRadarStatus,
} from "../api/opportunityRadar";
import type { ExternalObservationResponse } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatDate, formatDateTime } from "../utils/format";

const LIMIT = 50;
const STATUS_OPTIONS: { value: OpportunityRadarStatus | undefined; label: string }[] = [
  { value: undefined, label: "全部状态" },
  { value: "pending", label: "待验证" },
  { value: "corroborated", label: "已交叉验证" },
  { value: "admitted", label: "已准入" },
  { value: "rejected", label: "已拒绝" },
  { value: "conflict", label: "冲突" },
];

export function OpportunityRadarPage() {
  const [status, setStatus] = useState<OpportunityRadarStatus | undefined>(undefined);
  const query = useQuery<ExternalObservationResponse[]>({
    queryKey: opportunityRadarQueryKey({ admissionStatus: status, limit: LIMIT, offset: 0 }),
    queryFn: ({ signal }) => fetchOpportunityRadar({ admissionStatus: status, limit: LIMIT, offset: 0 }, signal),
    refetchInterval: 60_000,
  });

  return (
    <div className="opportunityRadarPage">
      <header className="pageHeader">
        <p className="pageEyebrow">Opportunity Radar</p>
        <h2 className="pageTitle">外部候选雷达</h2>
        <p className="pageSubtitle">查看 WorkBuddy 外部观察及准入状态；所有候选仍需正式数据验证。</p>
      </header>
      <section className="pageSection" aria-label="候选筛选">
        <label className="radarFilterLabel" htmlFor="radar-status">准入状态</label>
        <select
          id="radar-status"
          className="radarFilter"
          value={status ?? ""}
          onChange={(event) => setStatus((event.target.value || undefined) as OpportunityRadarStatus | undefined)}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.label} value={option.value ?? ""}>{option.label}</option>
          ))}
        </select>
      </section>
      <section className="pageSection" aria-label="候选列表">
        {query.isPending && <LoadingState label="正在加载外部候选" />}
        {query.isError && <ErrorState title="无法读取外部候选" message={query.error.message} onRetry={() => void query.refetch()} />}
        {query.data && query.data.length === 0 && <EmptyState title="暂无外部候选" description="当前筛选条件下没有候选观察。" />}
        {query.data && query.data.length > 0 && <RadarTable items={query.data} />}
      </section>
    </div>
  );
}

function RadarTable({ items }: { items: ExternalObservationResponse[] }) {
  return (
    <div className="radarTableWrap">
      <table className="radarTable">
        <thead><tr><th>标的</th><th>状态</th><th>观察日期</th><th>来源</th><th>观察时间</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.observation_id}>
              <td><strong>{item.symbol ?? "待解析"}</strong></td>
              <td><span className="statusPill statusPillNeutral">{statusLabel(item.admission_status)}</span></td>
              <td>{formatDate(item.as_of)}</td>
              <td className="radarSource">{item.producer}</td>
              <td>{formatDateTime(item.observed_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusLabel(status: string): string {
  return { pending: "待验证", corroborated: "已交叉验证", admitted: "已准入", rejected: "已拒绝", conflict: "冲突" }[status] ?? status;
}
