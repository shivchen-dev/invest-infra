import { expect, test, type Page } from "@playwright/test";

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
