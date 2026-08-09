import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MarketStatusWidget } from "./MarketStatusWidget";
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
  return screen.getByRole("heading", { name: "Market Status" }).closest("article") as HTMLElement;
}

describe("MarketStatusWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<MarketStatusWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveAttribute("data-widget-page", "dashboard");
    expect(widget).toHaveAttribute("data-widget-size", "medium");
    expect(widget).toHaveAttribute("data-widget-id", "market-status");
    expect(widget).toHaveTextContent("正在等待 Market Status 响应");
  });

  it("renders the explicit unavailable reason without inventing market data", () => {
    render(
      <MarketStatusWidget
        query={successQuery(
          buildDashboardResponse({
            marketStatus: {
              state: "unavailable",
              reason: "no market dashboard source registered",
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Market Status · unavailable");
    expect(widget).toHaveTextContent(
      "reason: no market dashboard source registered",
    );
    expect(widget).toHaveTextContent(
      "PR-W03 显式不渲染任何市场/因子衍生数据",
    );
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <MarketStatusWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Market Status");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
