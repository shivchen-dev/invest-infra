import type { UseQueryResult } from "@tanstack/react-query";
import type { ResearchDashboardResponse } from "../../../api/types";
import { MarketStatusWidget } from "./MarketStatusWidget";
import { ResearchSummaryWidget } from "./ResearchSummaryWidget";
import { EvidencePackWidget } from "./EvidencePackWidget";
import { ResearchRunTimelineWidget } from "./ResearchRunTimelineWidget";
import { FactorSnapshotWidget } from "./FactorSnapshotWidget";
import { RiskMonitorWidget } from "./RiskMonitorWidget";

export interface ResearchCockpitSectionProps {
  readonly query: UseQueryResult<ResearchDashboardResponse, Error>;
}

export function ResearchCockpitSection({ query }: ResearchCockpitSectionProps) {
  return (
    <div
      className="cockpitWorkspaceGrid"
      data-section="research-cockpit"
      aria-label="Research Cockpit 仪表板组件"
    >
      <MarketStatusWidget query={query} />
      <ResearchSummaryWidget query={query} />
      <EvidencePackWidget query={query} />
      <FactorSnapshotWidget query={query} />
      <RiskMonitorWidget query={query} />
      <ResearchRunTimelineWidget query={query} />
    </div>
  );
}
