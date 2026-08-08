import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Router } from "../router";
import { ResearchHistoryPage } from "./ResearchHistoryPage";

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function renderHistory(path: string) {
  setPathname(path);
  return render(
    <Router routes={[{ path: "/research/history", element: <ResearchHistoryPage /> }]} />,
  );
}

afterEach(() => {
  cleanup();
});

describe("ResearchHistoryPage", () => {
  it("renders the page header, scope tabs, and empty-state placeholders", () => {
    renderHistory("/research/history");

    expect(
      screen.getByRole("heading", { name: "Research Case 与 Run 历史" }),
    ).toBeInTheDocument();

    const breadcrumb = screen.getByLabelText("Research History 路径");
    expect(within(breadcrumb).getByText("Dashboard")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("Research History")).toBeInTheDocument();

    const tablist = screen.getByRole("tablist", { name: "History 视图" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["全部", "Case", "Run"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    expect(
      screen.getByText((text) => text.includes("尚无 Research History 数据")),
    ).toBeInTheDocument();
  });

  it("switches the active scope when a tab is clicked", () => {
    renderHistory("/research/history");

    const tablist = screen.getByRole("tablist", { name: "History 视图" });
    const tabs = within(tablist).getAllByRole("tab");

    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");

    fireEvent.click(tabs[1]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });

  it("renders the widget grid with the table and summary cards", () => {
    renderHistory("/research/history");

    const grid = screen.getByLabelText("Research History widgets");
    // The grid renders 3 widgets, each with a header title.
    expect(within(grid).getByText("Research Case 与 Run 列表")).toBeInTheDocument();
    expect(within(grid).getByText("Research 摘要")).toBeInTheDocument();
    expect(within(grid).getByText("数据来源")).toBeInTheDocument();

    expect(
      screen.getByRole("region", { name: "History 列表占位" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Case 总数")).toBeInTheDocument();
    expect(screen.getByText("Run 总数")).toBeInTheDocument();
    expect(screen.getByText("最近刷新")).toBeInTheDocument();
  });

  it("marks the page as read-only and includes a data provenance caption", () => {
    renderHistory("/research/history");

    expect(
      screen.getByText("只读模式 · 浏览器不写入 Research 数据"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/所有 Case \/ Run 记录来自 Research API/),
    ).toBeInTheDocument();
  });
});
