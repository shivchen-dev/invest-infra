import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

describe("apiGet", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("returns a successful JSON response", async () => {
    const payload = { status: "fresh", count: 3 };
    stubFetch(jsonResponse(payload));
    const { apiGet } = await import("./client");

    await expect(apiGet<typeof payload>("/api/v1/status")).resolves.toEqual(
      payload,
    );
  });

  it.each([
    [404, "Candidate pool not found"],
    [422, "Invalid trade date"],
  ])("preserves detail for a %i response", async (status, detail) => {
    stubFetch(jsonResponse({ detail }, status));
    const { apiGet } = await import("./client");

    await expect(apiGet("/api/v1/resource")).rejects.toMatchObject({
      name: "ApiError",
      status,
      detail,
      message: detail,
    });
  });

  it("redacts detail from a 500 response", async () => {
    const sensitiveDetail = "database password was exposed";
    stubFetch(jsonResponse({ detail: sensitiveDetail }, 500));
    const { ApiError, apiGet } = await import("./client");

    const error = await apiGet("/api/v1/resource").catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 500,
      detail: undefined,
      message: "Request failed with status 500",
    });
    expect((error as Error).message).not.toContain(sensitiveDetail);
  });

  it("uses a generic error for a non-JSON response", async () => {
    stubFetch(
      new Response("Service unavailable", {
        status: 400,
        headers: { "Content-Type": "text/plain" },
      }),
    );
    const { apiGet } = await import("./client");

    await expect(apiGet("/api/v1/resource")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: undefined,
      message: "Request failed with status 400",
    });
  });

  it("forwards AbortSignal to fetch", async () => {
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
    const { API_BASE, apiGet } = await import("./client");
    const controller = new AbortController();

    const request = apiGet("/api/v1/resource", controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/v1/resource`, {
      signal: controller.signal,
    });
  });

  it("joins the configured API base and request path", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/base");
    const fetchMock = stubFetch(jsonResponse({ ok: true }));
    const { API_BASE, apiGet } = await import("./client");

    await apiGet("/api/v1/resource");

    expect(API_BASE).toBe("https://api.example.test/base");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/base/api/v1/resource",
      { signal: undefined },
    );
  });
});
