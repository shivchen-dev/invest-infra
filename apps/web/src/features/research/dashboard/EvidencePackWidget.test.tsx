import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EvidencePackWidget } from "./EvidencePackWidget";
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
  return screen.getByRole("heading", { name: "Evidence Pack" }).closest("article") as HTMLElement;
}

describe("EvidencePackWidget", () => {
  it("renders a loading state when the dashboard query is pending", () => {
    render(<EvidencePackWidget query={pendingQuery()} />);

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "loading");
    expect(widget).toHaveTextContent("正在等待 Evidence Pack 响应");
  });

  it("renders the empty state when no evidence is available", () => {
    render(
      <EvidencePackWidget
        query={successQuery(
          buildDashboardResponse({
            evidenceStatus: {
              state: "empty",
              case_id: null,
              pack_id: null,
              schema_version: null,
              factor_set_key: null,
              factor_set_version: null,
              quality_status: null,
              freshness_status: null,
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent("Evidence Pack · empty");
    expect(widget).toHaveTextContent("暂无 Case，Evidence Pack 槽位保持 empty");
  });

  it("renders the empty state with the linked case id when a case exists without packs", () => {
    render(
      <EvidencePackWidget
        query={successQuery(
          buildDashboardResponse({
            evidenceStatus: {
              state: "empty",
              case_id: "case-1",
              pack_id: null,
              schema_version: null,
              factor_set_key: null,
              factor_set_version: null,
              quality_status: null,
              freshness_status: null,
            },
          }),
        )}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "empty");
    expect(widget).toHaveTextContent(
      "Case case-1 暂未绑定任何 Evidence Pack",
    );
  });

  it("renders pack identifiers and quality metadata when an evidence pack is available", () => {
    render(
      <EvidencePackWidget
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
    expect(widget).toHaveAttribute("data-widget-state", "ready");
    expect(within(widget).getByText("pack-1")).toBeInTheDocument();
    expect(within(widget).getByText("1.0.0")).toBeInTheDocument();
    expect(
      within(widget).getByText("factor.basic · 1"),
    ).toBeInTheDocument();
    expect(within(widget).getByText("ok")).toBeInTheDocument();
    expect(within(widget).getByText("current")).toBeInTheDocument();
  });

  it("surfaces the API error message when the dashboard query fails", () => {
    render(
      <EvidencePackWidget
        query={errorQuery(new Error("Research query failed"))}
      />,
    );

    const widget = getWidget();
    expect(widget).toHaveAttribute("data-widget-state", "failed");
    expect(widget).toHaveTextContent("无法读取 Evidence Pack");
    expect(widget).toHaveTextContent("Research query failed");
  });
});
