export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

interface ErrorBody {
  detail?: unknown;
}

function extractDetail(body: unknown): string | undefined {
  if (body && typeof body === "object") {
    const candidate = (body as ErrorBody).detail;
    if (typeof candidate === "string" && candidate.length > 0) {
      return candidate;
    }
    if (candidate && typeof candidate === "object") {
      try {
        return JSON.stringify(candidate);
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}

export async function apiGet<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });

  if (!response.ok) {
    const raw = await response.json().catch(() => null);
    const detail =
      response.status === 500 ? undefined : extractDetail(raw);
    throw new ApiError(
      detail ?? `Request failed with status ${response.status}`,
      response.status,
      detail,
    );
  }

  return (await response.json()) as T;
}

export const queryKeys = {
  freshness: ["data-freshness"] as const,
  latestCandidatePool: ["candidate-pool", "latest"] as const,
  latestCandidateDiff: ["candidate-pool", "latest", "diff"] as const,
  latestPipelineRun: ["pipeline-runs", "latest"] as const,
  pipelineRuns: (filters: { limit: number; offset: number }) =>
    ["pipeline-runs", filters] as const,
};