import { useQuery } from "@tanstack/react-query";
import {
  fetchExternalWorkflowArtifacts,
  fetchExternalWorkflows,
  externalWorkflowsQueryKey,
} from "../api/externalWorkflows";
import type { ExternalWorkflowRunResponse } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatDateTime } from "../utils/format";

const LIMIT = 20;

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
  const artifacts = useQuery({
    queryKey: ["external-workflow", run.run_id, "artifacts"],
    queryFn: ({ signal }) => fetchExternalWorkflowArtifacts(run.run_id, signal),
    staleTime: 60_000,
  });
  return (
    <article className="automationRunCard">
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
        <div><dt>Artifacts</dt><dd>{artifacts.data?.length ?? "—"}</dd></div>
      </dl>
    </article>
  );
}
