import { describe, expect, it } from "vitest";
import {
  createResearchWidgetRegistry,
  defaultResearchWidgetRegistry,
  getFixedLayout,
  orderVisibleWidgetKeys,
} from "./index";

import type { ResearchWidgetPage } from "./types";

const definition = (key: string, pages: ReadonlyArray<ResearchWidgetPage> = ["dashboard"]) => ({
  key,
  title: key,
  description: key,
  defaultSize: "small" as const,
  supportedPages: pages,
  requiredData: [],
  render: () => null,
});

describe("research widget registry", () => {
  it("rejects duplicate registration", () => {
    const registry = createResearchWidgetRegistry([definition("alpha")]);
    expect(() => registry.register(definition("alpha"))).toThrow(
      "Research widget key already registered: alpha",
    );
  });

  it("looks up and lists definitions deterministically", () => {
    const registry = createResearchWidgetRegistry([definition("zeta"), definition("alpha")]);
    expect(registry.get("alpha")?.key).toBe("alpha");
    expect(registry.getAll().map((item) => item.key)).toEqual(["alpha", "zeta"]);
    expect(defaultResearchWidgetRegistry.getAll().map((item) => item.key)).toEqual([
      "evidence-pack",
      "factor-snapshot",
      "market-status",
      "report-viewer",
      "research-run-timeline",
      "research-summary",
      "risk-monitor",
    ]);
  });

  it("filters definitions by supported page", () => {
    const definitions = [definition("dashboard-only"), definition("case-only", ["research-case"])] as const;
    expect(
      getFixedLayout(["case-only", "dashboard-only"], "dashboard", definitions).widgetKeys,
    ).toEqual(["dashboard-only"]);
  });
});

describe("fixed layout", () => {
  it("preserves fixed order and filters visibility", () => {
    expect(orderVisibleWidgetKeys(["zeta", "alpha", "beta"], ["beta", "zeta"])).toEqual([
      "zeta",
      "beta",
    ]);
  });

  it("removes duplicate keys without changing their first position", () => {
    expect(orderVisibleWidgetKeys(["alpha", "beta", "alpha"])).toEqual(["alpha", "beta"]);
  });
});
