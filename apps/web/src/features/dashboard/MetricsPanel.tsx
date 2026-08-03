import type { UseQueryResult } from "@tanstack/react-query";
import type { DataFreshnessResponse } from "../../api/types";
import { MetricCard, type MetricTone } from "../../components/MetricCard";
import { formatCount } from "../../utils/format";

type MetricsQuery = UseQueryResult<DataFreshnessResponse, Error>;

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

export function MetricsPanel({ query }: { query: MetricsQuery }) {
  const data = query.data;
  return (
    <div className="metricGrid">
      <MetricCard
        label="个人 ETF 数"
        value={data ? formatCount(data.universe_count) : null}
      />
      <MetricCard
        label="当日行情覆盖"
        value={data ? formatCount(data.daily_bar_count) : null}
      />
      <MetricCard
        label="候选数"
        value={data ? formatCount(data.candidate_count) : null}
      />
      <MetricCard
        label="最新 Run 状态"
        value={data?.pipeline_status ?? null}
        valueAsText
        tone={pipelineStatusTone(data?.pipeline_status ?? null)}
      />
    </div>
  );
}
