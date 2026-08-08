import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Router } from "../router";
import { ResearchCasePage } from "./ResearchCasePage";

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function renderCasePage(path: string) {
  setPathname(path);
  return render(
    <Router routes={[{ path: "/research/:caseId", element: <ResearchCasePage /> }]} />,
  );
}

afterEach(() => {
  cleanup();
});

describe("ResearchCasePage", () => {
  it("renders the case header, decoded case id, and breadcrumb", () => {
    renderCasePage("/research/case-2026-08-03");

    expect(
      screen.getByRole("heading", { name: /Research Case · case-2026-08-03/ }),
    ).toBeInTheDocument();

    const breadcrumb = screen.getByLabelText("Research Case 路径");
    expect(within(breadcrumb).getByText("Dashboard")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("Research History")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("Case · case-2026-08-03")).toBeInTheDocument();
  });

  it("decodes a percent-encoded caseId", () => {
    renderCasePage("/research/case%2D2026-q3");

    expect(
      screen.getByRole("heading", { name: /Research Case · case-2026-q3/ }),
    ).toBeInTheDocument();
  });

  it("lists all six placeholder sections with empty/idle widget states", () => {
    renderCasePage("/research/case-x");

    const subnav = screen.getByLabelText("Case 工作区导航");
    const subnavLinks = within(subnav).getAllByRole("link");
    const labels = subnavLinks.map((link) => link.textContent);
    expect(labels).toEqual([
      "Case 概览",
      "Evidence Pack",
      "Factor Snapshot",
      "Research Result",
      "Risk Monitor",
      "Report Viewer",
    ]);

    const widgetGrid = screen.getByLabelText("Research Case widgets");
    const widgets = within(widgetGrid).getAllByText("待数据接入");
    expect(widgets).toHaveLength(6);
  });

  it("shows the empty-state copy without calling any API", () => {
    renderCasePage("/research/case-empty");

    expect(
      screen.getByText(/Research Case Workspace 暂未接入数据/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/所有数据将由后续 PR 从/),
    ).toBeInTheDocument();
  });

  it("highlights that the page is read-only and includes generated_at info for skeleton provenance", () => {
    renderCasePage("/research/case-x");

    const meta = screen.getByRole("region", { name: "Case 元数据" });
    expect(within(meta).getByText("PR-W01 骨架")).toBeInTheDocument();
    expect(within(meta).getByText("只读")).toBeInTheDocument();

    expect(
      screen.getAllByText("只读模式 · 浏览器不写入 Research 数据").length,
    ).toBeGreaterThanOrEqual(1);

    const widgetGrid = screen.getByLabelText("Research Case widgets");
    const badges = within(widgetGrid).getAllByText("待数据接入");
    expect(badges).toHaveLength(6);
  });
});
