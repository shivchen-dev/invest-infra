import { useQuery } from "@tanstack/react-query";
import {
  fetchExternalWorkflowArtifacts,
  fetchExternalWorkflowObservations,
  fetchExternalWorkflows,
  externalWorkflowsQueryKey,
} from "../api/externalWorkflows";
import type {
  ExternalObservationResponse,
  ExternalWorkflowRunResponse,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatDateTime } from "../utils/format";

const LIMIT = 20;
const OBSERVATION_PREVIEW_LIMIT = 5;
const DETAIL_STALE_TIME_MS = 60_000;
const RUN_ANCHOR_PREFIX = "automation-run-";

const ADMISSION_STATUS_LABELS: Record<string, string> = {
  pending: "待验证",
  corroborated: "已交叉验证",
  admitted: "已准入",
  rejected: "已拒绝",
  conflict: "冲突",
};

const CANDIDATE_STATUS_LABELS: Record<string, string> = {
  pending_validation: "候选待校验",
  needs_symbol_resolution: "需解析代码",
};

function admissionLabel(status: string): string {
  return ADMISSION_STATUS_LABELS[status] ?? status;
}

function candidateLabel(status: string | null): string {
  if (!status) return "—";
  return CANDIDATE_STATUS_LABELS[status] ?? status;
}

function runDetailAnchor(runId: string): string {
  return `${RUN_ANCHOR_PREFIX}${runId}`;
}

export function AutomationCenterPage() {
  const query = useQuery({
    queryKey: externalWorkflowsQueryKey({ limit: LIMIT, offset: 0 }),
    queryFn: ({ signal }) => fetchExternalWorkflows({ limit: LIMIT, offset: 0 }, signal),
    refetchInterval: 60_000,
  });

  return (
    <div className="automationCenterPage">
      <header className="pageHeader">
        <p className="pageEyebrow">Automation Center</p>
        <h2 className="pageTitle">外部工作流中心</h2>
        <p className="pageSubtitle">观测 WorkBuddy 等外部工作流的运行状态、Intake 状态与产物，不在浏览器发起任务。</p>
      </header>
      <section className="pageSection" aria-label="外部工作流列表">
        {query.isPending && <LoadingState label="正在加载外部工作流" />}
        {query.isError && <ErrorState title="无法读取外部工作流" message={query.error.message} onRetry={() => void query.refetch()} />}
        {query.data && query.data.items.length === 0 && <EmptyState title="暂无外部工作流" description="等待 WorkBuddy 产生可导入的运行结果。" />}
        {query.data && query.data.items.length > 0 && <WorkflowList runs={query.data.items} />}
      </section>
    </div>
  );
}

function WorkflowList({ runs }: { runs: ExternalWorkflowRunResponse[] }) {
  return (
    <div className="automationRunList">
      {runs.map((run) => <WorkflowCard key={run.run_id} run={run} />)}
    </div>
  );
}

function WorkflowCard({ run }: { run: ExternalWorkflowRunResponse }) {
  const observationsQuery = useQuery({
    queryKey: ["external-workflow", run.run_id, "observations"],
    queryFn: ({ signal }) => fetchExternalWorkflowObservations(run.run_id, signal),
    staleTime: DETAIL_STALE_TIME_MS,
  });
  const artifactsQuery = useQuery({
    queryKey: ["external-workflow", run.run_id, "artifacts"],
    queryFn: ({ signal }) => fetchExternalWorkflowArtifacts(run.run_id, signal),
    staleTime: DETAIL_STALE_TIME_MS,
  });

  const observations = observationsQuery.data ?? [];
  const artifacts = artifactsQuery.data ?? [];
  const previewObservations = observations.slice(0, OBSERVATION_PREVIEW_LIMIT);
  const remainingObservations = observations.length - previewObservations.length;

  return (
    <article
      className="automationRunCard"
      id={runDetailAnchor(run.run_id)}
      data-run-id={run.run_id}
    >
      <div className="automationRunHeader">
        <div>
          <h3 className="automationRunTitle">{run.producer}</h3>
          <code className="automationRunId">{run.run_id}</code>
        </div>
        <span className="statusPill statusPillNeutral">{run.intake_status}</span>
      </div>
      <dl className="automationRunDetails">
        <div><dt>Producer 状态</dt><dd>{run.producer_status}</dd></div>
        <div><dt>Schema</dt><dd>{run.schema_version}</dd></div>
        <div><dt>开始时间</dt><dd>{formatDateTime(run.started_at)}</dd></div>
        <div><dt>Artifacts</dt><dd>{artifactsQuery.data?.length ?? "—"}</dd></div>
      </dl>
      <section className="automationRunDrill" aria-label="观测与产物预览">
        <div className="automationRunDrillBlock">
          <h4 className="automationRunDrillTitle">
            Observations
            <span className="automationRunDrillCount">{observationsQuery.data?.length ?? "—"}</span>
          </h4>
          {observationsQuery.isError && (
            <ErrorState
              title="无法读取观测"
              message={observationsQuery.error.message}
            />
          )}
          {observationsQuery.data && observations.length === 0 && (
            <p className="automationRunDrillEmpty">该运行暂无观测。</p>
          )}
          {observations.length > 0 && (
            <ul className="automationRunObservationList">
              {previewObservations.map((observation) => (
                <ObservationRow
                  key={observation.observation_id}
                  observation={observation}
                />
              ))}
              {remainingObservations > 0 && (
                <li className="automationRunObservationMore">
                  还有 {remainingObservations} 条观测未显示
                </li>
              )}
            </ul>
          )}
        </div>
        <div className="automationRunDrillBlock">
          <h4 className="automationRunDrillTitle">Artifacts</h4>
          {artifactsQuery.isError && (
            <ErrorState
              title="无法读取产物"
              message={artifactsQuery.error.message}
            />
          )}
          {artifactsQuery.data && artifacts.length === 0 && (
            <p className="automationRunDrillEmpty">该运行暂无产物。</p>
          )}
          {artifacts.length > 0 && (
            <ul className="automationRunArtifactList">
              {artifacts.map((artifact) => (
                <li key={artifact.artifact_id} className="automationRunArtifactItem">
                  <code className="automationRunArtifactUri">{artifact.logical_uri}</code>
                  <code className="automationRunArtifactHash">{artifact.content_hash}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </article>
  );
}

function ObservationRow({ observation }: { observation: ExternalObservationResponse }) {
  return (
    <li className="automationRunObservationItem">
      <strong className="automationRunObservationSymbol">{observation.symbol ?? "—"}</strong>
      <span className="automationRunObservationStatuses">
        {observation.candidate_status && (
          <span className="statusPill statusPillNeutral">{candidateLabel(observation.candidate_status)}</span>
        )}
        <span className="statusPill statusPillNeutral">{admissionLabel(observation.admission_status)}</span>
      </span>
      {observation.reason && (
        <span className="automationRunObservationReason">{observation.reason}</span>
      )}
    </li>
  );
}