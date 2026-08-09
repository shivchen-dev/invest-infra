import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResearchRunTimelineWidget } from "./ResearchRunTimelineWidget";
import {
  buildDashboardResponse,
  buildRun,
  errorQuery,
  pendingQuery,
  successQuery,
} from "./test-helpers";

afterEach(() => {
  cleanup();
});

function getWidget() {
  return screen
    .getByRole("heading", { name: "Research Run Timeline" })
    .closest("article") as HTMLElement;
}

describe("ResearchRunTimelineWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<ResearchRunTimelineWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveTextContent("正在等待 Research Run Timeline 响应");
  });

  it("renders the empty state when there are no recent runs", () => {
    render(
      <ResearchRunTimelineWidget query={successQuery(buildDashboardResponse())} />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Recent Runs · 空");
  });

  it("renders the recent runs table with API-provided status strings verbatim", () => {
    const runs = [
      buildRun({ run_id: "run-1", status: "succeeded" }),
      buildRun({ run_id: "run-2", status: "failed" }),
      buildRun({
        run_id: "run-3",
        status: "running",
        finished_at: null,
      }),
    ];

    render(
      <ResearchRunTimelineWidget
        query={successQuery(buildDashboardResponse({ recentRuns: runs }))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "ready");
    const table = within(widget).getByRole("table");
    expect(table).toBeInTheDocument();
    expect(within(table).getByText("run-1")).toBeInTheDocument();
    expect(within(table).getByText("run-2")).toBeInTheDocument();
    expect(within(table).getByText("run-3")).toBeInTheDocument();
    // Status strings should appear exactly as the API returned them.
    expect(within(table).getByText("succeeded")).toBeInTheDocument();
    expect(within(table).getByText("failed")).toBeInTheDocument();
    expect(within(table).getByText("running")).toBeInTheDocument();
  });

  it("does not invent a state machine — passes raw status through to the badge", () => {
    render(
      <ResearchRunTimelineWidget
        query={successQuery(
          buildDashboardResponse({
            recentRuns: [buildRun({ status: "started_pending_evidence" })],
          }),
        )}
      />,
    );

    const widget = getWidget();
    const table = within(widget).getByRole("table");
    expect(within(table).getByText("started_pending_evidence")).toBeInTheDocument();
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <ResearchRunTimelineWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Research Run Timeline");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
