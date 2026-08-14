import { expect, test, type Page, type Route } from "@playwright/test";

const RUN_ID = "11111111-1111-1111-1111-111111111111";

async function json(route: Route, body: unknown): Promise<void> {
  if (route.request().method() !== "GET") return route.fallback();
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installRoutes(page: Page): Promise<void> {
  await page.route(/\/api\/v1\/opportunity-radar(?:\?|$)/, (route) =>
    json(route, [
      {
        observation_id: "22222222-2222-2222-2222-222222222222",
        run_id: RUN_ID,
        artifact_id: "33333333-3333-3333-3333-333333333333",
        observed_at: "2026-08-14T04:00:00Z",
        as_of: "2026-08-14",
        source_uri: "archive://runs/2026-08-14/wb-run/candidates.json",
        producer: "workbuddy",
        payload: { symbol: "510300" },
        symbol: "510300",
        instrument_id: null,
        admission_status: "pending",
        metadata: {},
      },
    ]),
  );
  await page.route(/\/api\/v1\/external-workflows(?:\?|$)/, (route) =>
    json(route, {
      items: [
        {
          run_id: RUN_ID,
          producer: "workbuddy",
          schema_version: "2.0.0",
          producer_status: "succeeded",
          intake_status: "accepted",
          started_at: "2026-08-14T04:00:00Z",
          finished_at: "2026-08-14T04:01:00Z",
          metadata: {},
        },
      ],
      limit: 20,
      offset: 0,
    }),
  );
  await page.route(/\/api\/v1\/external-workflows\/[^/]+\/artifacts(?:\?|$)/, (route) =>
    json(route, []),
  );
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)))
    .toBeLessThanOrEqual(390);
}

test.describe("Stage 4D read-only workbench", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test.beforeEach(async ({ page }) => {
    await installRoutes(page);
  });

  test("renders Opportunity Radar and filters by admission status", async ({ page }) => {
    await page.goto("/opportunity-radar");
    await expect(page.getByRole("heading", { name: "外部候选雷达" })).toBeVisible();
    await expect(page.getByText("510300")).toBeVisible();
    await page.getByLabel("准入状态").selectOption("pending");
    await expectNoHorizontalOverflow(page);
  });

  test("renders Automation Center as a read-only workflow view", async ({ page }) => {
    await page.goto("/automation");
    await expect(page.getByRole("heading", { name: "外部工作流中心" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "workbuddy" })).toBeVisible();
    await expect(page.getByText("succeeded")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
