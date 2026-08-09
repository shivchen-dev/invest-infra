/**
 * Web contract-seam E2E for the read-only Research Cockpit.
 *
 * These tests pin the frozen Research API response contracts (PR-W03 /
 * PR-W05 / PR-W06) from the *browser* perspective by serving deterministic
 * fixtures via Playwright `page.route()`. They intentionally do NOT start
 * the FastAPI service, do NOT touch PostgreSQL, and do NOT exercise the
 * real endpoints — the API contract is owned by
 * `apps/api/tests/test_research_*` (server-side FastAPI TestClient +
 * PostgreSQL fixtures, see also `apps/api/openapi.json`). This file
 * guards the consumer side: that the workbench still renders the
 * cockpit against the frozen envelopes and does not log any
 * `ERR_CONNECTION_REFUSED` console errors.
 *
 * The route handlers below are anchored to the exact paths the cockpit
 * actually fetches; we deliberately do NOT install a catch-all so any
 * unexpected request (typo'd path, new endpoint, write call) still
 * surfaces as a real network failure and a console error.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

interface ResearchCaseFixture {
  case_id: string;
  instrument_id: string;
  as_of_date: string;
  question: string;
  horizon: string;
  status: string;
  created_at: string;
  candidate_pool_run_id: string | null;
  closed_at: string | null;
}

interface ResearchRunFixture {
  run_id: string;
  case_id: string;
  evidence_pack_id: string;
  playbook_key: string;
  runner_key: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  error_summary: string | null;
}

interface ResearchCaseListFixture {
  items: ResearchCaseFixture[];
  limit: number;
  offset: number;
  total: number;
}

interface ResearchRunListFixture {
  items: ResearchRunFixture[];
  limit: number;
  offset: number;
  total: number;
}

interface ResearchCaseWorkspaceFixture {
  case: ResearchCaseFixture;
  evidence_packs: unknown[];
  runs: ResearchRunFixture[];
  results: unknown[];
}

const HISTORY_CASE_FIXTURE: ResearchCaseListFixture = {
  items: [],
  limit: 20,
  offset: 0,
  total: 0,
};

const HISTORY_RUN_FIXTURE: ResearchRunListFixture = {
  items: [],
  limit: 20,
  offset: 0,
  total: 0,
};

const WORKSPACE_FIXTURE: ResearchCaseWorkspaceFixture = {
  case: {
    case_id: "case-e2e-001",
    instrument_id: "22222222-2222-2222-2222-222222222222",
    as_of_date: "2026-08-08",
    question: "趋势通道判断",
    horizon: "30d",
    status: "open",
    created_at: "2026-08-09T00:00:00Z",
    candidate_pool_run_id: null,
    closed_at: null,
  },
  evidence_packs: [],
  runs: [],
  results: [],
};

const RESEARCH_CASES_LIST_PATTERN = /\/api\/v1\/research-cases(?:\?|$)/;
const RESEARCH_RUNS_LIST_PATTERN = /\/api\/v1\/research-runs(?:\?|$)/;
const RESEARCH_CASE_WORKSPACE_PATTERN =
  /\/api\/v1\/research-cases\/[^/?]+\/workspace(?:\?|$)/;

function fulfillIfGet(route: Route, body: unknown, status = 200): Promise<void> {
  if (route.request().method() !== "GET") {
    return route.fallback();
  }
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installResearchApiRoutes(page: Page): Promise<void> {
  await page.route(RESEARCH_CASES_LIST_PATTERN, (route) =>
    fulfillIfGet(route, HISTORY_CASE_FIXTURE),
  );
  await page.route(RESEARCH_RUNS_LIST_PATTERN, (route) =>
    fulfillIfGet(route, HISTORY_RUN_FIXTURE),
  );
  await page.route(RESEARCH_CASE_WORKSPACE_PATTERN, (route) =>
    fulfillIfGet(route, WORKSPACE_FIXTURE),
  );
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      ),
    )
    .toBeLessThanOrEqual(390);
}

test.describe("Web Research Cockpit", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    await installResearchApiRoutes(page);
  });

  test("renders the read-only research history workspace", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto("/research/history");

    await expect(
      page.getByRole("heading", { name: "Research Case 与 Run 历史" }),
    ).toBeVisible();
    await expect(
      page.getByText("只读模式 · 浏览器不写入 Research 数据"),
    ).toBeVisible();
    await expect(page.locator("[data-widget-id]")).toHaveCount(3);
    await expectNoHorizontalOverflow(page);
    expect(consoleErrors).toEqual([]);
  });

  test("renders the read-only research case workspace", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto("/research/case-e2e-001");

    await expect(
      page.getByRole("heading", { name: "Research Case · case-e2e-001" }),
    ).toBeVisible();
    await expect(
      page.getByText("只读模式 · 浏览器不写入 Research 数据"),
    ).toBeVisible();
    await expect(page.locator("[data-widget-id]")).toHaveCount(6);
    await expectNoHorizontalOverflow(page);
    expect(consoleErrors).toEqual([]);
  });
});
