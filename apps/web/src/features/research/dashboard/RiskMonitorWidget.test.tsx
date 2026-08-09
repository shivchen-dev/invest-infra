import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RiskMonitorWidget } from "./RiskMonitorWidget";
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
  return screen.getByRole("heading", { name: "Risk Monitor" }).closest("article") as HTMLElement;
}

describe("RiskMonitorWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<RiskMonitorWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveTextContent("正在等待 Risk Monitor 响应");
  });

  it("always renders the explicit unavailable state in PR-W04 — no fake risk conclusions", () => {
    render(
      <RiskMonitorWidget
        query={successQuery(
          buildDashboardResponse({
            evidenceStatus: {
              state: "available",
              case_id: "case-1",
              pack_id: "pack-1",
              schema_version: "1.0.0",
              factor_set_key: "factor.basic",
              factor_set_version: "1",
              quality_status: "ok",
              freshness_status: "current",
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Risk Monitor · unavailable");
    expect(widget).toHaveTextContent("PR-W04 尚未接入风险负载");
    // Must not surface any risk/invalidation language.
    expect(within(widget).queryByText(/invalidation|fail|risk_factor/i)).not.toBeInTheDocument();
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <RiskMonitorWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Risk Monitor");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
