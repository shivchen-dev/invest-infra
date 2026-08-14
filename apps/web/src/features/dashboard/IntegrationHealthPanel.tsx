import type { UseQueryResult } from "@tanstack/react-query";
import type { IntegrationHealthResponse } from "../../api/types";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { MetricCard } from "../../components/MetricCard";
import { formatCount } from "../../utils/format";

type HealthQuery = UseQueryResult<IntegrationHealthResponse, Error>;

export function IntegrationHealthPanel({ query }: { query: HealthQuery }) {
  if (query.isPending) return <LoadingState label="正在检查外部集成状态" compact />;
  if (query.isError) {
    return <ErrorState title="无法读取外部集成状态" message={query.error.message} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) return null;

  const data = query.data;
  const tone = data.status === "healthy" ? "success" : "warning";
  return (
    <div className="integrationHealthPanel" data-status={data.status}>
      <div className="integrationHealthHeader">
        <div>
          <p className="integrationHealthStatus">{data.status === "healthy" ? "运行正常" : "需要关注"}</p>
          <p className="integrationHealthHint">最近 {formatCount(data.sample_size)} 次外部运行状态</p>
        </div>
        <span className={`statusPill statusPill${tone === "success" ? "Success" : "Warning"}`}>
          {data.status}
        </span>
      </div>
      <div className="metricGrid integrationHealthMetrics">
        <MetricCard label="成功运行" value={data.producer_statuses.succeeded ?? 0} tone={tone} />
        <MetricCard label="部分完成" value={data.producer_statuses.partial ?? 0} tone="warning" />
        <MetricCard label="失败运行" value={data.producer_statuses.failed ?? 0} tone="danger" />
        <MetricCard label="待验证 Intake" value={data.intake_statuses.accepted ?? 0} tone="neutral" />
      </div>
    </div>
  );
}
