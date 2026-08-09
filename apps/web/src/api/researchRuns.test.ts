import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResearchRunListResponse } from "./types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const EMPTY_RUNS: ResearchRunListResponse = {
  items: [],
  limit: 20,
  offset: 0,
  total: 0,
};

const POPULATED_RUNS: ResearchRunListResponse = {
  items: [
    {
      run_id: "33333333-3333-3333-3333-333333333333",
      case_id: "11111111-1111-1111-1111-111111111111",
      evidence_pack_id: "44444444-4444-4444-4444-444444444444",
      playbook_key: "playbook.default",
      runner_key: "runner.default",
      attempt: 1,
      started_at: "2026-08-09T00:00:00Z",
      finished_at: "2026-08-09T00:30:00Z",
      status: "succeeded",
      error_summary: null,
    },
  ],
  limit: 20,
  offset: 0,
  total: 1,
};

describe("fetchResearchRuns", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns the run page JSON when the endpoint responds 200", async () => {
    stubFetch(jsonResponse(POPULATED_RUNS));
    const { fetchResearchRuns } = await import("./researchRuns");

    await expect(
      fetchResearchRuns({ limit: 20, offset: 0 }),
    ).resolves.toEqual(POPULATED_RUNS);
  });

  it("targets /api/v1/research-runs with limit/offset query string", async () => {
    const fetchMock = stubFetch(jsonResponse(EMPTY_RUNS));
    const { API_BASE } = await import("./client");
    const { fetchResearchRuns } = await import("./researchRuns");

    await fetchResearchRuns({ limit: 20, offset: 60 });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-runs?limit=20&offset=60`,
      { signal: undefined },
    );
  });

  it("forwards an AbortSignal to fetch", async () => {
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          );
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { API_BASE } = await import("./client");
    const { fetchResearchRuns } = await import("./researchRuns");
    const controller = new AbortController();

    const request = fetchResearchRuns(
      { limit: 20, offset: 0 },
      controller.signal,
    );
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-runs?limit=20&offset=0`,
      { signal: controller.signal },
    );
  });

  it("uses the configured API base", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse(EMPTY_RUNS));
    const { API_BASE } = await import("./client");
    const { fetchResearchRuns } = await import("./researchRuns");

    await fetchResearchRuns({ limit: 20, offset: 0 });

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/research-runs?limit=20&offset=0",
      { signal: undefined },
    );
  });

  it("raises an ApiError on a non-2xx response", async () => {
    stubFetch(jsonResponse({ detail: "Research query failed" }, 500));
    const { ApiError } = await import("./client");
    const { fetchResearchRuns } = await import("./researchRuns");

    await expect(
      fetchResearchRuns({ limit: 20, offset: 0 }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("researchRunsQueryKey", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds a tuple keyed by limit and offset via client.queryKeys", async () => {
    const { queryKeys } = await import("./client");
    const { researchRunsQueryKey } = await import("./researchRuns");

    expect(researchRunsQueryKey({ limit: 20, offset: 60 })).toEqual(
      queryKeys.researchRuns({ limit: 20, offset: 60 }),
    );
    expect(researchRunsQueryKey({ limit: 20, offset: 0 })).toEqual([
      "research-runs",
      { limit: 20, offset: 0 },
    ]);
  });
});
