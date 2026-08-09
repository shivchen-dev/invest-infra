import { useQuery } from "@tanstack/react-query";
import { fetchDataFreshness } from "../api/dataFreshness";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
} from "../api/candidatePool";
import { fetchLatestPipelineRun } from "../api/pipelineRuns";
import { useResearchDashboard } from "../api/researchDashboard";
import type {
  CandidatePoolDiffResponse,
  CandidatePoolLatestResponse,
  DataFreshnessResponse,
  PipelineRunResponse,
} from "../api/types";
import { FreshnessPanel } from "../features/dashboard/FreshnessPanel";
import { MetricsPanel } from "../features/dashboard/MetricsPanel";
import { CandidateDiffPanel } from "../features/dashboard/CandidateDiffPanel";
import { TopCandidatesPanel } from "../features/dashboard/TopCandidatesPanel";
import { LatestRunPanel } from "../features/dashboard/LatestRunPanel";
import { ResearchCockpitSection } from "../features/research/dashboard/ResearchCockpitSection";
import { LoadingState } from "../components/LoadingState";
import { formatCount, formatDate } from "../utils/format";

const TOP_N = 10;

const REFETCH_INTERVAL = {
  freshness: 60_000,
  candidatePool: 5 * 60_000,
  pipelineRun: 60_000,
} as const;

export function DashboardPage() {
  const freshness = useQuery<DataFreshnessResponse>({
    queryKey: ["data-freshness"],
    queryFn: ({ signal }) => fetchDataFreshness(signal),
    refetchInterval: REFETCH_INTERVAL.freshness,
  });

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

  const researchDashboard = useResearchDashboard();

  const initialLoading =
    freshness.isPending &&
    latestPool.isPending &&
    latestDiff.isPending &&
    latestRun.isPending;

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

      <section className="pageSection" aria-label="数据状态">
        <FreshnessPanel query={freshness} />
      </section>

      <section className="pageSection" aria-label="关键指标">
        <h3 className="sectionTitle">关键指标</h3>
        <MetricsPanel query={freshness} />
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