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
export type IntegrationHealthResponse = RequiredDefined<components["schemas"]["IntegrationHealthResponse"]>;
export type ExternalObservationResponse = RequiredDefined<components["schemas"]["ExternalObservationResponse"]> & {
  candidate_status: string | null;
  reason: string | null;
};
export type ExternalWorkflowRunResponse = RequiredDefined<components["schemas"]["ExternalWorkflowRunResponse"]>;
export type ExternalArtifactResponse = RequiredDefined<components["schemas"]["ExternalArtifactResponse"]>;
export type ExternalWorkflowRunListResponse = Omit<
  RequiredDefined<components["schemas"]["ExternalWorkflowRunListResponse"]>,
  "items"
> & { items: ExternalWorkflowRunResponse[] };
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
export type ResearchCaseListResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchCaseListResponse"]>,
  "items"
> & {
  items: ResearchCaseResponse[];
};
export type ResearchRunResponse = RequiredDefined<components["schemas"]["ResearchRunResponse"]>;
export type ResearchRunListResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchRunListResponse"]>,
  "items"
> & {
  items: ResearchRunResponse[];
};
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
export type ResearchCaseWorkspaceArtifactView = {
  logical_uri: string;
  content_hash: string;
  media_type: string;
  size_bytes: number;
  run_id: string;
  created_at: string;
};
export type ResearchCaseWorkspaceDiscoveryView = {
  evidence_id: string;
  observation_id: string;
  run_id: string;
  producer: string;
  as_of: string;
  observed_at: string;
  source_uri: string;
  content_hash: string;
  admission_status: string;
  admission: Record<string, unknown>;
  artifact: ResearchCaseWorkspaceArtifactView | null;
};
export type ResearchCaseWorkspaceTimelineEventType =
  components["schemas"]["ResearchCaseWorkspaceTimelineItem"]["event_type"];
export type ResearchCaseWorkspaceTimelineItem = RequiredDefined<
  components["schemas"]["ResearchCaseWorkspaceTimelineItem"]
>;
export type ResearchCaseWorkspaceResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchCaseWorkspaceResponse"]>,
  "evidence_packs" | "runs" | "results" | "external_discovery" | "timeline"
> & {
  evidence_packs: ResearchCaseWorkspaceEvidencePack[];
  runs: ResearchCaseWorkspaceRun[];
  results: (ResearchCaseWorkspaceResult | null)[];
  external_discovery: ResearchCaseWorkspaceDiscoveryView[];
  timeline?: ResearchCaseWorkspaceTimelineItem[];
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
export type ResearchCenterObservation = RequiredDefined<
  components["schemas"]["ResearchCenterObservationResponse"]
>;
export type ResearchCenterCandidatePoolSummary = RequiredDefined<
  components["schemas"]["ResearchCenterCandidatePoolSummaryResponse"]
>;
export type ResearchCenterOpportunitySummary = RequiredDefined<
  components["schemas"]["ResearchCenterOpportunitySummaryResponse"]
>;
export type ResearchCenterResearchSummary = RequiredDefined<
  components["schemas"]["ResearchCenterResearchSummaryResponse"]
>;
export type ResearchCenterDeliveryPipeline = RequiredDefined<
  components["schemas"]["ResearchCenterDeliveryPipelineResponse"]
>;
export type ResearchCenterDeliveryIntegration = RequiredDefined<
  components["schemas"]["ResearchCenterDeliveryIntegrationResponse"]
>;
export type ResearchCenterDeliveryArchive = RequiredDefined<
  components["schemas"]["ResearchCenterDeliveryArchiveResponse"]
>;
export type ResearchCenterDeliveryResearchRuns = RequiredDefined<
  components["schemas"]["ResearchCenterDeliveryResearchRunsResponse"]
>;
export type ResearchCenterDelivery = RequiredDefined<
  components["schemas"]["ResearchCenterDeliveryResponse"]
>;
type ResearchCenterBreadthWire = RequiredDefined<
  components["schemas"]["ResearchCenterBreadthResponse"]
>;
export type ResearchCenterBreadth =
  | (Omit<ResearchCenterBreadthWire, "state" | "observations"> & {
      state: "available";
      observations: ResearchCenterObservation[] | null;
    })
  | (Omit<ResearchCenterBreadthWire, "state"> & {
      state: "failed";
    });
export type ResearchCenterDataFreshness = RequiredDefined<
  components["schemas"]["ResearchCenterDataFreshnessResponse"]
>;
export type ResearchCenterCapability = RequiredDefined<
  components["schemas"]["ResearchCenterCapabilityResponse"]
>;
export type ResearchCenterCapabilities = RequiredDefined<
  components["schemas"]["ResearchCenterCapabilitiesResponse"]
>;
export type ResearchCenterMarket = Omit<
  RequiredDefined<components["schemas"]["ResearchCenterMarketResponse"]>,
  "breadth" | "data_freshness"
> & {
  breadth: ResearchCenterBreadth | null;
  data_freshness: ResearchCenterDataFreshness | null;
};
export type ResearchCenterResponse = Omit<
  RequiredDefined<components["schemas"]["ResearchCenterResponse"]>,
  "market" | "candidate_pool" | "opportunities" | "delivery"
> & {
  market: ResearchCenterMarket;
  candidate_pool: ResearchCenterCandidatePoolSummary;
  opportunities: ResearchCenterOpportunitySummary;
  research: ResearchCenterResearchSummary;
  delivery: ResearchCenterDelivery;
};
