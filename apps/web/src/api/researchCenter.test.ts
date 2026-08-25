import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ResearchCenterBreadth,
  ResearchCenterCapabilities,
  ResearchCenterCapability,
  ResearchCenterDataFreshness,
  ResearchCenterDelivery,
  ResearchCenterMarket,
  ResearchCenterResponse,
} from "./types";

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

function makeCapability(
  overrides: Partial<ResearchCenterCapability> = {},
): ResearchCenterCapability {
  return {
    reason: "slice_2_not_implemented",
    state: "deferred",
    ...overrides,
  };
}

function makeCapabilities(
  overrides: Partial<ResearchCenterCapabilities> = {},
): ResearchCenterCapabilities {
  return {
    opportunities: makeCapability({ reason: "slice_2_not_implemented" }),
    research: makeCapability({ reason: "slice_2_not_implemented" }),
    delivery: makeCapability({ reason: "slice_3_not_implemented" }),
    strategy: makeCapability({
      reason: "strategy_iteration_contract_not_frozen",
      state: "unavailable",
    }),
    discipline: makeCapability({
      reason: "position_discipline_contract_not_frozen",
      state: "unavailable",
    }),
    ...overrides,
  };
}

function makeBreadth(
  overrides: Partial<ResearchCenterBreadth> = {},
): ResearchCenterBreadth {
  return {
    algorithm_version: "2.0.0",
    observations: [],
    scope_key: "ashare_active_universe_v1",
    scope_type: "ashare_universe",
    snapshot_id: "55555555-5555-5555-5555-555555555555",
    ...overrides,
    state: "available",
  };
}

function makeFreshness(
  overrides: Partial<ResearchCenterDataFreshness> = {},
): ResearchCenterDataFreshness {
  return {
    checked_at: "2026-08-15T13:00:00Z",
    daily_bar_count: 100,
    latest_published_trade_date: "2026-08-15",
    missing_count: 0,
    state: "available",
    status: "fresh",
    universe_count: 100,
    ...overrides,
  };
}

function makeMarket(
  overrides: Partial<ResearchCenterMarket> = {},
): ResearchCenterMarket {
  return {
    as_of_date: "2026-08-15",
    breadth: null,
    data_freshness: null,
    freshness_status: null,
    quality_status: null,
    state: "unavailable",
    ...overrides,
  };
}

function makeDelivery(
  overrides: Partial<ResearchCenterDelivery> = {},
): ResearchCenterDelivery {
  return {
    schema_version: "1.0.0",
    pipeline: {
      state: "empty",
      status: null,
      started_at: null,
      finished_at: null,
      business_completion_date: null,
      freshness_at: null,
      source: null,
      reason: null,
    },
    integration: {
      state: "empty",
      status: null,
      sample_size: null,
      producer_status_counts: null,
      intake_status_counts: null,
      latest_as_of: null,
      freshness_at: null,
      source: null,
      reason: null,
    },
    archive: {
      state: "empty",
      artifact_count: null,
      latest_run_status: null,
      latest_as_of: null,
      freshness_at: null,
      source: null,
      reason: null,
    },
    research_runs: {
      state: "empty",
      run_count: null,
      status_counts: null,
      latest_status: null,
      latest_started_at: null,
      latest_finished_at: null,
      freshness_at: null,
      source: null,
      reason: null,
    },
    ...overrides,
  };
}

const EMPTY_CENTER: ResearchCenterResponse = {
  schema_version: "1.0.0",
  generated_at: "2026-08-15T13:00:00Z",
  state: "unavailable",
  market: makeMarket(),
  capabilities: makeCapabilities(),
  candidate_pool: {
    state: "empty",
    run_id: null,
    trade_date: null,
    input_row_count: null,
    included_count: null,
    excluded_count: null,
    reason: null,
  },
  opportunities: {
    state: "empty",
    observation_count: null,
    latest_as_of: null,
    admission_status_counts: null,
    reason: null,
  },
  research: {
    schema_version: "1.0.0",
    state: "empty",
    case_count: 0,
    run_count: 0,
    latest_case: null,
    evidence: {
      state: "empty",
      pack_id: null,
      quality_status: null,
      freshness_status: null,
    },
  },
  delivery: makeDelivery(),
};

const UNAVAILABLE_FRESHNESS_MISSING_CENTER: ResearchCenterResponse = {
  schema_version: "1.0.0",
  generated_at: "2026-08-15T13:00:00Z",
  state: "unavailable",
  market: {
    as_of_date: null,
    breadth: null,
    data_freshness: {
      checked_at: "2026-08-12T01:30:00Z",
      daily_bar_count: 0,
      latest_published_trade_date: null,
      missing_count: 0,
      state: "unavailable",
      status: "missing",
      universe_count: 0,
    },
    freshness_status: "missing",
    quality_status: null,
    state: "unavailable",
  },
  capabilities: makeCapabilities(),
  candidate_pool: {
    state: "empty",
    run_id: null,
    trade_date: null,
    input_row_count: null,
    included_count: null,
    excluded_count: null,
    reason: null,
  },
  opportunities: {
    state: "empty",
    observation_count: null,
    latest_as_of: null,
    admission_status_counts: null,
    reason: null,
  },
  research: {
    schema_version: "1.0.0",
    state: "empty",
    case_count: 0,
    run_count: 0,
    latest_case: null,
    evidence: {
      state: "empty",
      pack_id: null,
      quality_status: null,
      freshness_status: null,
    },
  },
  delivery: makeDelivery(),
};

describe("fetchResearchCenter", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns the center JSON when the endpoint responds 200", async () => {
    stubFetch(jsonResponse(EMPTY_CENTER));
    const { fetchResearchCenter } = await import("./researchCenter");

    await expect(fetchResearchCenter()).resolves.toEqual(EMPTY_CENTER);
  });

  it("targets /api/v1/research-center with no query string", async () => {
    const fetchMock = stubFetch(jsonResponse(EMPTY_CENTER));
    const { API_BASE } = await import("./client");
    const { fetchResearchCenter } = await import("./researchCenter");

    await fetchResearchCenter();

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-center`,
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
    const { fetchResearchCenter } = await import("./researchCenter");
    const controller = new AbortController();

    const request = fetchResearchCenter(controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-center`,
      { signal: controller.signal },
    );
  });

  it("uses the configured API base", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse(EMPTY_CENTER));
    const { API_BASE } = await import("./client");
    const { fetchResearchCenter } = await import("./researchCenter");

    await fetchResearchCenter();

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/research-center",
      { signal: undefined },
    );
  });

  it("raises an ApiError on a non-2xx response", async () => {
    stubFetch(jsonResponse({ detail: "Research center unavailable" }, 503));
    const { ApiError } = await import("./client");
    const { fetchResearchCenter } = await import("./researchCenter");

    await expect(fetchResearchCenter()).rejects.toBeInstanceOf(ApiError);
  });

  it("preserves the unavailable/missing freshness wire shape with sentinel counts", async () => {
    stubFetch(jsonResponse(UNAVAILABLE_FRESHNESS_MISSING_CENTER));
    const { fetchResearchCenter } = await import("./researchCenter");

    const response = await fetchResearchCenter();

    expect(response.state).toBe("unavailable");
    expect(response.market.state).toBe("unavailable");
    expect(response.market.breadth).toBeNull();
    expect(response.market.as_of_date).toBeNull();
    expect(response.market.quality_status).toBeNull();
    expect(response.market.freshness_status).toBe("missing");

    const freshness = response.market.data_freshness;
    expect(freshness).not.toBeNull();
    if (freshness === null) {
      throw new Error("expected data_freshness to be present");
    }
    expect(freshness.state).toBe("unavailable");
    expect(freshness.status).toBe("missing");
    expect(freshness.latest_published_trade_date).toBeNull();
    expect(freshness.universe_count).toBe(0);
    expect(freshness.daily_bar_count).toBe(0);
    expect(freshness.missing_count).toBe(0);
    expect(freshness.checked_at).toBe("2026-08-12T01:30:00Z");
  });
});

describe("researchCenterQueryKey", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("matches the research-center React Query key", async () => {
    const { queryKeys } = await import("./client");
    const { researchCenterQueryKey } = await import("./researchCenter");

    expect(researchCenterQueryKey).toEqual(queryKeys.researchCenter);
    expect(researchCenterQueryKey).toEqual(["research-center"]);
  });
});
