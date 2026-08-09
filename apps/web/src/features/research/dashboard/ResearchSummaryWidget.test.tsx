import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ResearchSummaryWidget } from "./ResearchSummaryWidget";
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
  return screen.getByRole("heading", { name: "Research Summary" }).closest("article") as HTMLElement;
}

describe("ResearchSummaryWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<ResearchSummaryWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveTextContent("正在等待 Research Summary 响应");
  });

  it("renders the empty state when there are no cases and no runs", () => {
    render(
      <ResearchSummaryWidget
        query={successQuery(buildDashboardResponse())}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Latest Case · 无可展示案例");
    // The counts are formatted via formatCount; both case and run counts are 0.
    expect(within(widget).getAllByText("0").length).toBeGreaterThanOrEqual(2);
  });

  it("renders exact case/run counts and latest-case metadata when data is available", () => {
    render(
      <ResearchSummaryWidget
        query={successQuery(
          buildDashboardResponse({
            researchSummary: {
              case_count: 3,
              run_count: 7,
              latest_case: {
                case_id: "case-1",
                instrument_id: "inst-1",
                as_of_date: "2026-08-08",
                question: "ETF 是否进入趋势通道？",
                horizon: "30d",
                status: "open",
                created_at: "2026-08-09T00:00:00Z",
                candidate_pool_run_id: null,
                closed_at: null,
              },
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "ready");
    expect(within(widget).getByText("3")).toBeInTheDocument();
    expect(within(widget).getByText("7")).toBeInTheDocument();
    expect(within(widget).getByText("case-1")).toBeInTheDocument();
    expect(within(widget).getByText("2026-08-08")).toBeInTheDocument();
    expect(
      within(widget).getByText("ETF 是否进入趋势通道？"),
    ).toBeInTheDocument();
    expect(within(widget).getByText("30d")).toBeInTheDocument();
    expect(within(widget).getByText("open")).toBeInTheDocument();
    // The widget renders a description that mentions stance/confidence
    // explicitly to convey that those fields are NOT surfaced; the only
    // way stance/confidence could leak through would be as data rendered
    // from `latest_case`, so assert no such data labels exist.
    expect(
      within(widget).queryByText("Stance"),
    ).not.toBeInTheDocument();
    expect(
      within(widget).queryByText("Confidence"),
    ).not.toBeInTheDocument();
  });

  it("renders the latest-case metadata even when counts are zero", () => {
    render(
      <ResearchSummaryWidget
        query={successQuery(
          buildDashboardResponse({
            researchSummary: {
              case_count: 0,
              run_count: 0,
              latest_case: {
                case_id: "case-only",
                instrument_id: "inst-only",
                as_of_date: "2026-08-08",
                question: "Edge case scenario?",
                horizon: "7d",
                status: "draft",
                created_at: "2026-08-09T00:00:00Z",
                candidate_pool_run_id: null,
                closed_at: null,
              },
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "ready");
    expect(within(widget).getByText("case-only")).toBeInTheDocument();
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <ResearchSummaryWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Research Summary");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
