import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResearchCaseListResponse } from "./types";

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

const EMPTY_CASES: ResearchCaseListResponse = {
  items: [],
  limit: 20,
  offset: 0,
  total: 0,
};

const POPULATED_CASES: ResearchCaseListResponse = {
  items: [
    {
      case_id: "11111111-1111-1111-1111-111111111111",
      instrument_id: "22222222-2222-2222-2222-222222222222",
      as_of_date: "2026-08-08",
      question: "趋势通道判断",
      horizon: "30d",
      status: "open",
      created_at: "2026-08-09T00:00:00Z",
      candidate_pool_run_id: null,
      closed_at: null,
    },
  ],
  limit: 20,
  offset: 0,
  total: 1,
};

describe("fetchResearchCases", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns the case page JSON when the endpoint responds 200", async () => {
    stubFetch(jsonResponse(POPULATED_CASES));
    const { fetchResearchCases } = await import("./researchCases");

    await expect(
      fetchResearchCases({ limit: 20, offset: 0 }),
    ).resolves.toEqual(POPULATED_CASES);
  });

  it("targets /api/v1/research-cases with limit/offset query string", async () => {
    const fetchMock = stubFetch(jsonResponse(EMPTY_CASES));
    const { API_BASE } = await import("./client");
    const { fetchResearchCases } = await import("./researchCases");

    await fetchResearchCases({ limit: 20, offset: 40 });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-cases?limit=20&offset=40`,
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
    const { fetchResearchCases } = await import("./researchCases");
    const controller = new AbortController();

    const request = fetchResearchCases(
      { limit: 20, offset: 0 },
      controller.signal,
    );
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-cases?limit=20&offset=0`,
      { signal: controller.signal },
    );
  });

  it("uses the configured API base", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse(EMPTY_CASES));
    const { API_BASE } = await import("./client");
    const { fetchResearchCases } = await import("./researchCases");

    await fetchResearchCases({ limit: 20, offset: 0 });

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/research-cases?limit=20&offset=0",
      { signal: undefined },
    );
  });

  it("raises an ApiError on a non-2xx response", async () => {
    stubFetch(jsonResponse({ detail: "Research query failed" }, 500));
    const { ApiError } = await import("./client");
    const { fetchResearchCases } = await import("./researchCases");

    await expect(
      fetchResearchCases({ limit: 20, offset: 0 }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("researchCasesQueryKey", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds a tuple keyed by limit and offset via client.queryKeys", async () => {
    const { queryKeys } = await import("./client");
    const { researchCasesQueryKey } = await import("./researchCases");

    expect(researchCasesQueryKey({ limit: 20, offset: 40 })).toEqual(
      queryKeys.researchCases({ limit: 20, offset: 40 }),
    );
    expect(researchCasesQueryKey({ limit: 20, offset: 0 })).toEqual([
      "research-cases",
      { limit: 20, offset: 0 },
    ]);
  });
});
