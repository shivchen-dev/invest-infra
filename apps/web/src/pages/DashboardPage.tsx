import { useQuery } from "@tanstack/react-query";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import { fetchIntegrationHealth } from "../api/integrationHealth";
import { useResearchCenter } from "../api/researchCenter";
import { useResearchDashboard } from "../api/researchDashboard";
import type {
  CandidatePoolDiffResponse,
  CandidatePoolLatestResponse,
  PipelineRunResponse,
} from "../api/types";
import { CandidateDiffPanel } from "../features/dashboard/CandidateDiffPanel";
import { TopCandidatesPanel } from "../features/dashboard/TopCandidatesPanel";
import { LatestRunPanel } from "../features/dashboard/LatestRunPanel";
import { ResearchCenterMarketStatusPanel } from "../features/dashboard/ResearchCenterMarketStatusPanel";
import { ResearchCenterSubviewsPanel } from "../features/dashboard/ResearchCenterSubviewsPanel";
import { ResearchCockpitSection } from "../features/research/dashboard/ResearchCockpitSection";
import { LoadingState } from "../components/LoadingState";
import { formatCount, formatDate } from "../utils/format";
import { IntegrationHealthPanel } from "../features/dashboard/IntegrationHealthPanel";

const TOP_N = 10;

const REFETCH_INTERVAL = {
  candidatePool: 5 * 60_000,
  pipelineRun: 60_000,
  integrationHealth: 60_000,
} as const;

export function DashboardPage() {
  const latestPool = useQuery<CandidatePoolLatestResponse>({
    queryKey: ["candidate-pool", "latest"],
    queryFn: ({ signal }) => fetchCandidatePoolLatest(signal),
    refetchInterval: REFETCH_INTERVAL.candidatePool,
  });

  const latestDiff = useQuery<CandidatePoolDiffResponse>({
    queryKey: ["candidate-pool", "latest", "diff"],
    queryFn: ({ signal }) => fetchCandidatePoolLatestDiff(signal),
    refetchInterval: REFETCH_INTERVAL.candidatePool,
  });

  const latestRun = useQuery<PipelineRunResponse>({
    queryKey: ["pipeline-runs", "latest"],
    queryFn: ({ signal }) => fetchLatestPipelineRun(signal),
    refetchInterval: REFETCH_INTERVAL.pipelineRun,
  });

  const integrationHealth = useQuery({
    queryKey: ["integration", "health"],
    queryFn: ({ signal }) => fetchIntegrationHealth(signal),
    refetchInterval: REFETCH_INTERVAL.integrationHealth,
  });

  const researchCenter = useResearchCenter();
  const researchDashboard = useResearchDashboard();

  const initialLoading =
    latestPool.isPending &&
    latestDiff.isPending &&
    latestRun.isPending &&
    integrationHealth.isPending &&
    researchCenter.isPending;

  if (initialLoading) {
    return <LoadingState label="正在加载 Dashboard 数据" />;
  }

  return (
    <div className="dashboardPage">
      <header className="pageHeader">
        <p className="pageEyebrow">Dashboard</p>
        <h2 className="pageTitle">个人 ETF 数据工作台</h2>
        <p className="pageSubtitle">
          一屏判断数据是否最新、今天选了什么、有哪些变化。
        </p>
      </header>

      <section className="pageSection" aria-label="Research Center 市场状态">
        <ResearchCenterMarketStatusPanel query={researchCenter} />
      </section>

      <section className="pageSection" aria-label="Research Center 子视图">
        <header className="sectionHeader">
          <h3 className="sectionTitle">Research Center 子视图</h3>
          <span className="sectionMeta">
            Candidate Pool · Opportunity Radar · 来自同一份 Research Center 响应
          </span>
        </header>
        <ResearchCenterSubviewsPanel query={researchCenter} />
      </section>

      <section className="pageSection" aria-label="候选池变化">
        <header className="sectionHeader">
          <h3 className="sectionTitle">候选池变化</h3>
          {latestDiff.data && (
            <span className="sectionMeta">
              对比 {formatDate(latestDiff.data.previous_trade_date)} →{" "}
              {formatDate(latestDiff.data.trade_date)}
            </span>
          )}
        </header>
        <CandidateDiffPanel query={latestDiff} />
      </section>

      <section className="pageSection" aria-label="最新候选">
        <header className="sectionHeader">
          <h3 className="sectionTitle">最新入选候选（前 {TOP_N}）</h3>
          {latestPool.data && (
            <span className="sectionMeta">
              共 {formatCount(latestPool.data.row_count)} 只 · 入选{" "}
              {formatCount(latestPool.data.included_count)}
            </span>
          )}
        </header>
        <TopCandidatesPanel query={latestPool} />
      </section>

      <section className="pageSection" aria-label="最新运行">
        <h3 className="sectionTitle">最新运行</h3>
        <LatestRunPanel query={latestRun} />
      </section>

      <section className="pageSection" aria-label="外部集成状态">
        <header className="sectionHeader">
          <h3 className="sectionTitle">外部集成状态</h3>
          <span className="sectionMeta">WorkBuddy / Artifact Bridge</span>
        </header>
        <IntegrationHealthPanel query={integrationHealth} />
      </section>

      <section className="pageSection researchCockpitSection" aria-label="Research Cockpit">
        <header className="sectionHeader">
          <h3 className="sectionTitle">Research Cockpit</h3>
          <span className="cockpitReadOnlyHint" role="note">
            只读模式 · 浏览器不写入 Research 数据
          </span>
        </header>
        <p className="cockpitCaption">
          来自 <code className="inlineCode">GET /api/v1/research-dashboard</code>
          的只读聚合 · 仅消费 PR-7 已有资源
        </p>
        <ResearchCockpitSection query={researchDashboard} />
      </section>
    </div>
  );
}