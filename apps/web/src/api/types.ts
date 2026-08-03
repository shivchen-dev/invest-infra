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
