import { apiGet, queryKeys } from "./client";
import type {
  CandidatePoolDiffResponse,
  CandidatePoolLatestResponse,
} from "./types";

export function fetchCandidatePoolLatest(
  signal?: AbortSignal,
): Promise<CandidatePoolLatestResponse> {
  return apiGet<CandidatePoolLatestResponse>(
    "/api/v1/candidate-pool/latest",
    signal,
  );
}

export function fetchCandidatePoolLatestDiff(
  signal?: AbortSignal,
): Promise<CandidatePoolDiffResponse> {
  return apiGet<CandidatePoolDiffResponse>(
    "/api/v1/candidate-pool/latest/diff",
    signal,
  );
}

export const latestCandidatePoolQueryKey = queryKeys.latestCandidatePool;
export const latestCandidateDiffQueryKey = queryKeys.latestCandidateDiff;