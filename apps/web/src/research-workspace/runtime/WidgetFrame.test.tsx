import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WidgetFrame } from "./WidgetFrame";
import type { ResearchWidgetMeta } from "./types";

afterEach(() => {
  cleanup();
});

function baseMeta(overrides: Partial<ResearchWidgetMeta> = {}): ResearchWidgetMeta {
  return {
    id: "research-summary",
    title: "Research Summary",
    description: "摘要视图",
    page: "research-case",
    size: "medium",
    state: "ready",
    ...overrides,
  };
}

function getBadgeContainer(text: string): HTMLElement {
  const label = screen.getByText(text, { selector: ".cockpitBadgeLabel" });
  return label.parentElement as HTMLElement;
}

describe("WidgetFrame", () => {
  it("renders the widget title and description as accessible headers", () => {
    render(
      <WidgetFrame meta={baseMeta()}>
        <p>body content</p>
      </WidgetFrame>,
    );

    const region = screen.getByRole("heading", {
      name: "Research Summary",
      level: 3,
    });
    expect(region).toBeInTheDocument();
    expect(screen.getByText("摘要视图")).toBeInTheDocument();
  });

  it("maps each state to a readable status badge", () => {
    const { rerender } = render(
      <WidgetFrame meta={baseMeta({ state: "ready", badgeLabel: "已就绪" })}>
        <p>ready</p>
      </WidgetFrame>,
    );
    expect(getBadgeContainer("已就绪")).toHaveClass("cockpitBadge-Success");

    rerender(
      <WidgetFrame meta={baseMeta({ state: "loading" })}>
        <p>loading</p>
      </WidgetFrame>,
    );
    expect(getBadgeContainer("正在加载")).toHaveClass("cockpitBadge-Info");

    rerender(
      <WidgetFrame meta={baseMeta({ state: "empty" })}>
        <p>empty</p>
      </WidgetFrame>,
    );
    expect(getBadgeContainer("暂无可展示数据")).toHaveClass(
      "cockpitBadge-Neutral",
    );

    rerender(
      <WidgetFrame meta={baseMeta({ state: "stale" })}>
        <p>stale</p>
      </WidgetFrame>,
    );
    expect(getBadgeContainer("数据已过期")).toHaveClass("cockpitBadge-Warning");

    rerender(
      <WidgetFrame meta={baseMeta({ state: "failed" })}>
        <p>failed</p>
      </WidgetFrame>,
    );
    expect(getBadgeContainer("读取失败")).toHaveClass("cockpitBadge-Danger");
  });

  it("surfaces provenance and timestamps in the footer", () => {
    render(
      <WidgetFrame
        meta={baseMeta({
          provenance: "API · v1",
          generatedAt: "2026-08-03T12:00:00Z",
          asOf: "2026-08-02",
        })}
      >
        <p>body</p>
      </WidgetFrame>,
    );

    expect(screen.getByText("API · v1")).toBeInTheDocument();
    expect(screen.getByText("2026-08-02")).toBeInTheDocument();
    expect(screen.getByText("2026-08-03T12:00:00Z")).toBeInTheDocument();
  });

  it("exposes the widget id and metadata as data attributes for layout runtime", () => {
    const { container } = render(
      <WidgetFrame meta={baseMeta({ id: "evidence-pack", size: "wide" })}>
        <p>content</p>
      </WidgetFrame>,
    );

    const article = container.querySelector("article.cockpitWidget");
    expect(article).not.toBeNull();
    expect(article).toHaveAttribute("data-widget-id", "evidence-pack");
    expect(article).toHaveAttribute("data-widget-page", "research-case");
    expect(article).toHaveAttribute("data-widget-size", "wide");
    expect(article).toHaveAttribute("data-widget-state", "ready");
  });

  it("hides the header when hideHeader is true", () => {
    render(
      <WidgetFrame meta={baseMeta()} hideHeader>
        <p>only body</p>
      </WidgetFrame>,
    );

    expect(screen.queryByRole("heading", { name: "Research Summary" })).toBeNull();
    expect(screen.getByText("only body")).toBeInTheDocument();
  });

  it("renders the provided footer node even when no timestamps exist", () => {
    render(
      <WidgetFrame
        meta={baseMeta({ generatedAt: null, asOf: null })}
        footer={<span>footer note</span>}
      >
        <p>body</p>
      </WidgetFrame>,
    );

    expect(screen.getByText("footer note")).toBeInTheDocument();
  });
});
