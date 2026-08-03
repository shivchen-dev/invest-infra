import type { MetricTone } from "../../components/MetricCard";

export function pipelineStatusTone(
  status: string | null | undefined,
): MetricTone {
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

export function statusPillClass(tone: MetricTone): string {
  switch (tone) {
    case "success":
      return "statusPill statusPillSuccess";
    case "warning":
      return "statusPill statusPillWarning";
    case "danger":
      return "statusPill statusPillDanger";
    default:
      return "statusPill statusPillNeutral";
  }
}

export function RunStatusBadge({
  status,
}: {
  status: string | null | undefined;
}) {
  const tone = pipelineStatusTone(status);
  return <span className={statusPillClass(tone)}>{status}</span>;
}
