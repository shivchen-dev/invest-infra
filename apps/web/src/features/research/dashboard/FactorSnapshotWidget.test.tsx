import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FactorSnapshotWidget } from "./FactorSnapshotWidget";
import {
  buildDashboardResponse,
  errorQuery,
  pendingQuery,
  successQuery,
} from "./test-helpers";

afterEach(() => {
  cleanup();
});

function getWidget() {
  return screen.getByRole("heading", { name: "Factor Snapshot" }).closest("article") as HTMLElement;
}

describe("FactorSnapshotWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<FactorSnapshotWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveTextContent("正在等待 Factor Snapshot 响应");
  });

  it("always renders the explicit unavailable state in PR-W04 — no fake factor values", () => {
    render(
      <FactorSnapshotWidget
        query={successQuery(
          buildDashboardResponse({
            // Even with partial data and a fresh as_of_date, the widget must
            // not render any factor numbers.
            dataQuality: "partial",
            freshness: "current",
            asOfDate: "2026-08-08",
            researchSummary: {
              case_count: 4,
              run_count: 6,
              latest_case: null,
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Factor Snapshot · unavailable");
    expect(widget).toHaveTextContent("PR-W04 尚未接入因子负载");
    // Must not surface any numeric factor values.
    expect(within(widget).queryByText(/return|trend|volatility|drawdown/)).not.toBeInTheDocument();
    // Must not contain buy/sell/position controls.
    expect(within(widget).queryByText(/buy|sell|position/i)).not.toBeInTheDocument();
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <FactorSnapshotWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Factor Snapshot");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
