import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResearchDashboardResponse } from "./types";

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

const EMPTY_DASHBOARD: ResearchDashboardResponse = {
  schema_version: "1.0.0",
  generated_at: "2026-08-09T01:15:00Z",
  as_of_date: null,
  data_quality: "empty",
  freshness: "unknown",
  market_status: {
    state: "unavailable",
    reason: "no market dashboard source registered",
  },
  research_summary: {
    case_count: 0,
    run_count: 0,
    latest_case: null,
  },
  evidence_status: {
    state: "empty",
    case_id: null,
    pack_id: null,
    schema_version: null,
    factor_set_key: null,
    factor_set_version: null,
    quality_status: null,
    freshness_status: null,
  },
  recent_runs: [],
};

describe("fetchResearchDashboard", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns the dashboard JSON when the endpoint responds 200", async () => {
    stubFetch(jsonResponse(EMPTY_DASHBOARD));
    const { fetchResearchDashboard } = await import("./researchDashboard");

    await expect(
      fetchResearchDashboard(),
    ).resolves.toEqual(EMPTY_DASHBOARD);
  });

  it("targets /api/v1/research-dashboard with no query string", async () => {
    const fetchMock = stubFetch(jsonResponse(EMPTY_DASHBOARD));
    const { API_BASE } = await import("./client");
    const { fetchResearchDashboard } = await import("./researchDashboard");

    await fetchResearchDashboard();

    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/v1/research-dashboard`, {
      signal: undefined,
    });
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
    const { fetchResearchDashboard } = await import("./researchDashboard");
    const controller = new AbortController();

    const request = fetchResearchDashboard(controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-dashboard`,
      { signal: controller.signal },
    );
  });

  it("uses the configured API base", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse(EMPTY_DASHBOARD));
    const { API_BASE } = await import("./client");
    const { fetchResearchDashboard } = await import("./researchDashboard");

    await fetchResearchDashboard();

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/research-dashboard",
      { signal: undefined },
    );
  });

  it("raises an ApiError on a non-2xx response", async () => {
    stubFetch(jsonResponse({ detail: "Research query failed" }, 500));
    const { ApiError } = await import("./client");
    const { fetchResearchDashboard } = await import("./researchDashboard");

    await expect(fetchResearchDashboard()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("researchDashboardQueryKey", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("matches the research-dashboard React Query key", async () => {
    const { queryKeys } = await import("./client");
    const { researchDashboardQueryKey } = await import("./researchDashboard");
    expect(researchDashboardQueryKey).toEqual(queryKeys.researchDashboard);
    expect(researchDashboardQueryKey).toEqual(["research-dashboard"]);
  });
});
