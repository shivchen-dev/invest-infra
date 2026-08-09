import type { components } from "./generated";

type RequiredDefined<T> = T extends readonly (infer U)[]
  ? RequiredDefined<U>[]
  : T extends object
    ? { [K in keyof T]-?: RequiredDefined<T[K]> }
    : Exclude<T, undefined>;

export type DataFreshnessStatus = components["schemas"]["DataFreshnessResponse"]["status"];
export type DataFreshnessResponse = RequiredDefined<components["schemas"]["DataFreshnessResponse"]>;
export type RuleOutcome = RequiredDefined<components["schemas"]["RuleOutcomeResponse"]>;
export type ExclusionReason = RequiredDefined<components["schemas"]["ExclusionReasonResponse"]>;
export type CandidatePoolItem = Omit<
  RequiredDefined<components["schemas"]["CandidatePoolItemResponse"]>,
  "rule_results" | "exclusion_reasons"
> & {
  rule_results: RuleOutcome[];
  exclusion_reasons: ExclusionReason[];
};
export type CandidatePoolLatestResponse = Omit<
  RequiredDefined<components["schemas"]["CandidatePoolLatestResponse"]>,
  "items"
> & {
  items: CandidatePoolItem[];
};
export type CandidatePoolDiffEntry = RequiredDefined<components["schemas"]["CandidatePoolDiffEntry"]>;
export type CandidatePoolDiffResponse = Omit<
  RequiredDefined<components["schemas"]["CandidatePoolDiffResponse"]>,
  "added" | "retained" | "removed"
> & {
  added: CandidatePoolDiffEntry[];
  retained: CandidatePoolDiffEntry[];
  removed: CandidatePoolDiffEntry[];
};
export type PipelineRunResponse = RequiredDefined<components["schemas"]["PipelineRunResponse"]>;
export type PipelineRunListResponse = Omit<
  RequiredDefined<components["schemas"]["PipelineRunListResponse"]>,
  "items"
> & {
  items: PipelineRunResponse[];
};
export type InstrumentResponse = RequiredDefined<components["schemas"]["InstrumentResponse"]>;
export type InstrumentListResponse = Omit<
  RequiredDefined<components["schemas"]["InstrumentListResponse"]>,
  "items"
> & {
  items: InstrumentResponse[];
};
export type DailyBarResponse = RequiredDefined<components["schemas"]["DailyBarResponse"]>;
export type DailyBarListResponse = Omit<
  RequiredDefined<components["schemas"]["DailyBarListResponse"]>,
  "items"
> & {
  items: DailyBarResponse[];
};
export type ResearchCaseResponse = RequiredDefined<components["schemas"]["ResearchCaseResponse"]>;
export type ResearchRunResponse = RequiredDefined<components["schemas"]["ResearchRunResponse"]>;
export type ResearchResultResponse = RequiredDefined<
  components["schemas"]["ResearchResultResponse"]
>;
export type EvidencePackResponse = RequiredDefined<
  components["schemas"]["EvidencePackResponse"]
>;
export type EvidenceDataQualityResponse = RequiredDefined<
  components["schemas"]["EvidenceDataQualityResponse"]
>;
export type EvidenceFactorResponse = RequiredDefined<
  components["schemas"]["EvidenceFactorResponse"]
>;
export type EvidenceCaseResponse = RequiredDefined<
  components["schemas"]["EvidenceCaseResponse"]
>;
export type EvidenceInstrumentResponse = RequiredDefined<
  components["schemas"]["EvidenceInstrumentResponse"]
>;
export type EvidenceMarketSnapshotResponse = RequiredDefined<
  components["schemas"]["EvidenceMarketSnapshotResponse"]
>;
export type EvidenceSourceReferenceResponse = RequiredDefined<
  components["schemas"]["EvidenceSourceReferenceResponse"]
>;
export type ResearchCaseWorkspaceEvidencePack = EvidencePackResponse;
export type ResearchCaseWorkspaceRun = ResearchRunResponse;
export type ResearchCaseWorkspaceResult = ResearchResultResponse;
export type ResearchCaseWorkspaceResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchCaseWorkspaceResponse"]>,
  "evidence_packs" | "runs" | "results"
> & {
  evidence_packs: ResearchCaseWorkspaceEvidencePack[];
  runs: ResearchCaseWorkspaceRun[];
  results: (ResearchCaseWorkspaceResult | null)[];
};
export type ResearchDashboardDataQuality = components["schemas"]["ResearchDashboardResponse"]["data_quality"];
export type ResearchDashboardFreshness = components["schemas"]["ResearchDashboardResponse"]["freshness"];
export type ResearchDashboardMarketStatus = RequiredDefined<
  components["schemas"]["ResearchDashboardMarketStatus"]
>;
export type ResearchDashboardEvidenceStatus = RequiredDefined<
  components["schemas"]["ResearchDashboardEvidenceStatus"]
>;
export type ResearchDashboardResearchSummary = Omit<
  RequiredDefined<components["schemas"]["ResearchDashboardResearchSummary"]>,
  "latest_case"
> & {
  latest_case: ResearchCaseResponse | null;
};
export type ResearchDashboardResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchDashboardResponse"]>,
  "research_summary" | "recent_runs"
> & {
  research_summary: ResearchDashboardResearchSummary;
  recent_runs: ResearchRunResponse[];
};
