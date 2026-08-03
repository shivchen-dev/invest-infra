import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { DataFreshnessStatus } from "../api/types";
import { StatusBanner } from "./StatusBanner";

const STATUS_CASES: Array<
  [DataFreshnessStatus, string, string, string]
> = [
  ["fresh", "数据已更新", "statusBannerFresh", "✓"],
  ["partial", "数据部分缺失", "statusBannerPartial", "!"],
  ["stale", "数据未更新到预期日期", "statusBannerStale", "…"],
  ["missing", "尚无发布结果", "statusBannerMissing", "·"],
  ["failed", "最新任务失败", "statusBannerFailed", "×"],
];

afterEach(() => {
  cleanup();
});

describe("StatusBanner", () => {
  it.each(STATUS_CASES)(
    "renders the %s status",
    (status, ariaLabel, statusClass, icon) => {
      render(
        <StatusBanner
          status={status}
          title={`${status} title`}
          description="Status description"
          details={[{ label: "Trade date", value: "2026-08-03" }]}
        />,
      );

      const banner = screen.getByRole("status", { name: ariaLabel });
      expect(banner).toHaveClass("statusBanner", statusClass);
      expect(within(banner).getByText(icon)).toHaveAttribute(
        "aria-hidden",
        "true",
      );
      expect(within(banner).getByRole("heading", { level: 2 })).toHaveTextContent(
        `${status} title`,
      );
      expect(within(banner).getByText("Status description")).toBeVisible();
      expect(within(banner).getByText("Trade date")).toBeVisible();
      expect(within(banner).getByText("2026-08-03")).toBeVisible();
    },
  );
});
