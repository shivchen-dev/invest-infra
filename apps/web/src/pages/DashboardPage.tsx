import { useQuery } from "@tanstack/react-query";
import { fetchCandidatePoolLatestDiff } from "../api/candidatePool";
import { useResearchCenter } from "../api/researchCenter";
import type { CandidatePoolDiffResponse } from "../api/types";
import { CandidateDiffPanel } from "../features/dashboard/CandidateDiffPanel";
import { ResearchCenterMarketStatusPanel } from "../features/dashboard/ResearchCenterMarketStatusPanel";
import { ResearchCenterSubviewsPanel } from "../features/dashboard/ResearchCenterSubviewsPanel";
import { ResearchCenterDeliveryPanel } from "../features/dashboard/ResearchCenterDeliveryPanel";
import { LoadingState } from "../components/LoadingState";
import { formatDate } from "../utils/format";

const REFETCH_INTERVAL = {
  candidatePool: 5 * 60_000,
} as const;

export function DashboardPage() {
  const latestDiff = useQuery<CandidatePoolDiffResponse>({
    queryKey: ["candidate-pool", "latest", "diff"],
    queryFn: ({ signal }) => fetchCandidatePoolLatestDiff(signal),
    refetchInterval: REFETCH_INTERVAL.candidatePool,
  });

  const researchCenter = useResearchCenter();

  const initialLoading = researchCenter.isPending;

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
            Research · Candidate Pool · Opportunity Radar · 来自同一份 Research Center 响应
          </span>
        </header>
        <ResearchCenterSubviewsPanel query={researchCenter} />
      </section>

      <section className="pageSection" aria-label="Research Center 交付链">
        <header className="sectionHeader">
          <h3 className="sectionTitle">Research Center 交付链</h3>
          <span className="sectionMeta">
            Pipeline · Integration Health · Archive · Research Runs · 来自同一份 Research Center 响应
          </span>
        </header>
        <ResearchCenterDeliveryPanel query={researchCenter} />
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
    </div>
  );
}
