import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  EvidencePackResponse,
  ResearchCaseResponse,
  ResearchCaseWorkspaceResponse,
  ResearchResultResponse,
  ResearchRunResponse,
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

function makeCase(
  overrides: Partial<ResearchCaseResponse> = {},
): ResearchCaseResponse {
  return {
    case_id: "11111111-1111-1111-1111-111111111111",
    instrument_id: "22222222-2222-2222-2222-222222222222",
    as_of_date: "2026-08-08",
    question: "趋势通道判断",
    horizon: "30d",
    status: "open",
    created_at: "2026-08-09T00:00:00Z",
    candidate_pool_run_id: null,
    closed_at: null,
    ...overrides,
  };
}

function makeRun(
  overrides: Partial<ResearchRunResponse> = {},
): ResearchRunResponse {
  return {
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
    ...overrides,
  };
}

function makeResult(
  overrides: Partial<ResearchResultResponse> = {},
): ResearchResultResponse {
  return {
    result_id: "55555555-5555-5555-5555-555555555555",
    run_id: "33333333-3333-3333-3333-333333333333",
    evidence_pack_id: "44444444-4444-4444-4444-444444444444",
    model_key: "model.basic",
    model_version: "1.0.0",
    adapter_version: "1",
    playbook_version: "1.0.0",
    conclusion: "趋势向上",
    report_markdown: "# 趋势向上",
    evidence_ids: ["evidence-1"],
    risks: [],
    created_at: "2026-08-09T00:35:00Z",
    ...overrides,
  };
}

function makeEvidencePack(
  overrides: Partial<EvidencePackResponse> = {},
): EvidencePackResponse {
  return {
    pack_id: "44444444-4444-4444-4444-444444444444",
    pack_hash: "deadbeef",
    schema_version: "1.0.0",
    factor_set_key: "factor.basic",
    factor_set_version: "1",
    generated_at: "2026-08-09T00:10:00Z",
    case: {
      case_id: "11111111-1111-1111-1111-111111111111",
      instrument_id: "22222222-2222-2222-2222-222222222222",
      as_of_date: "2026-08-08",
      question: "趋势通道判断",
      horizon: "30d",
    },
    instrument: {
      instrument_id: "22222222-2222-2222-2222-222222222222",
      symbol: "ETF.SYMBOL",
      exchange: "SH",
      currency: "CNY",
      name: "示例 ETF",
    },
    market_snapshot: {
      currency: "CNY",
      latest_close: "1.234",
      latest_trade_date: "2026-08-08",
      observed_trading_days: 22,
      valid_price_days: 22,
      suspended_days: 0,
    },
    data_quality: {
      quality_status: "ok",
      freshness_status: "current",
      conflict_detected: false,
      target_trading_days: 22,
      observed_trading_days: 22,
      valid_price_days: 22,
      suspended_days: 0,
      invalid_days: 0,
    },
    factors: [],
    source_refs: [],
    missing_fields: [],
    warnings: [],
    ...overrides,
  };
}

function makeWorkspace(
  overrides: Partial<ResearchCaseWorkspaceResponse> = {},
): ResearchCaseWorkspaceResponse {
  return {
    case: makeCase(),
    evidence_packs: [],
    runs: [],
    results: [],
    ...overrides,
  };
}

describe("fetchResearchCaseWorkspace", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns the workspace JSON when the endpoint responds 200", async () => {
    const payload = makeWorkspace({
      evidence_packs: [makeEvidencePack()],
      runs: [makeRun()],
      results: [makeResult()],
    });
    stubFetch(jsonResponse(payload));

    const { fetchResearchCaseWorkspace } = await import(
      "./researchCaseWorkspace"
    );

    await expect(
      fetchResearchCaseWorkspace("11111111-1111-1111-1111-111111111111"),
    ).resolves.toEqual(payload);
  });

  it("targets the per-case workspace path with the encoded case id", async () => {
    const fetchMock = stubFetch(jsonResponse(makeWorkspace()));
    const { API_BASE } = await import("./client");
    const { fetchResearchCaseWorkspace } = await import(
      "./researchCaseWorkspace"
    );

    await fetchResearchCaseWorkspace("case/with spaces & symbols");

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-cases/case%2Fwith%20spaces%20%26%20symbols/workspace`,
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
    const { fetchResearchCaseWorkspace } = await import(
      "./researchCaseWorkspace"
    );
    const controller = new AbortController();

    const request = fetchResearchCaseWorkspace(
      "11111111-1111-1111-1111-111111111111",
      controller.signal,
    );
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/research-cases/11111111-1111-1111-1111-111111111111/workspace`,
      { signal: controller.signal },
    );
  });

  it("uses the configured API base", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse(makeWorkspace()));
    const { API_BASE } = await import("./client");
    const { fetchResearchCaseWorkspace } = await import(
      "./researchCaseWorkspace"
    );

    await fetchResearchCaseWorkspace("case-1");

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/research-cases/case-1/workspace",
      { signal: undefined },
    );
  });

  it("raises an ApiError on a non-2xx response", async () => {
    stubFetch(jsonResponse({ detail: "Research Case not found" }, 404));
    const { ApiError } = await import("./client");
    const { fetchResearchCaseWorkspace } = await import(
      "./researchCaseWorkspace"
    );

    await expect(
      fetchResearchCaseWorkspace("missing-case"),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("researchCaseWorkspaceQueryKey", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds a tuple keyed by case id and is exposed via client.queryKeys", async () => {
    const { queryKeys } = await import("./client");
    const { researchCaseWorkspaceQueryKey } = await import(
      "./researchCaseWorkspace"
    );

    expect(researchCaseWorkspaceQueryKey("case-1")).toEqual(
      queryKeys.researchCaseWorkspace("case-1"),
    );
    expect(researchCaseWorkspaceQueryKey("case-1")).toEqual([
      "research-case",
      "case-1",
      "workspace",
    ]);
  });
});
