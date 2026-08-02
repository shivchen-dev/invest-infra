export type DataFreshnessStatus =
  | "fresh"
  | "partial"
  | "stale"
  | "missing"
  | "failed";

export interface DataFreshnessResponse {
  as_of: string;
  latest_published_trade_date: string | null;
  universe_count: number;
  daily_bar_count: number;
  missing_count: number;
  candidate_count: number;
  snapshot_id: string | null;
  pipeline_run_id: string | null;
  pipeline_status: string | null;
  status: DataFreshnessStatus;
}

export interface RuleOutcome {
  rule_key: string;
  passed: boolean;
  severity: string;
  value: string | null;
  threshold: string | null;
  message: string | null;
}

export interface ExclusionReason {
  code: string;
  message: string;
}

export interface CandidatePoolItem {
  instrument_id: string;
  included: boolean;
  rank: number | null;
  total_score: string | null;
  metrics: Record<string, string>;
  rule_results: RuleOutcome[];
  exclusion_reasons: ExclusionReason[];
  symbol: string | null;
  name: string | null;
  exchange: string | null;
}

export interface CandidatePoolLatestResponse {
  run_id: string;
  trade_date: string;
  algorithm_key: string;
  algorithm_version: string;
  parameter_set_key: string;
  snapshot_id: string;
  content_hash: string;
  row_count: number;
  included_count: number;
  excluded_count: number;
  published_at: string | null;
  items: CandidatePoolItem[];
}

export interface CandidatePoolDiffEntry {
  instrument_id: string;
  symbol: string | null;
  name: string | null;
  exchange: string | null;
}

export interface CandidatePoolDiffResponse {
  trade_date: string;
  previous_trade_date: string | null;
  added: CandidatePoolDiffEntry[];
  retained: CandidatePoolDiffEntry[];
  removed: CandidatePoolDiffEntry[];
}

export interface PipelineRunResponse {
  id: string;
  job_key: string;
  partition_key: string | null;
  trigger_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_summary: string | null;
}

export interface PipelineRunListResponse {
  items: PipelineRunResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface InstrumentResponse {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  instrument_type: string;
  currency: string;
  status: string;
  is_active: boolean;
  list_date: string | null;
  delist_date: string | null;
  underlying_index: string | null;
  category: string | null;
}

export interface InstrumentListResponse {
  items: InstrumentResponse[];
  total: number;
  limit: number;
  offset: number;
}