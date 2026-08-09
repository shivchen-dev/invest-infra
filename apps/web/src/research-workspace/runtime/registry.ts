import type { ComponentType } from "react";
import type {
  ResearchWidgetContentProps,
  ResearchWidgetPage,
  ResearchWidgetSize,
} from "./types";

export interface ResearchWidgetDefinition {
  readonly key: string;
  readonly title: string;
  readonly description: string;
  readonly defaultSize: ResearchWidgetSize;
  readonly supportedPages: ReadonlyArray<ResearchWidgetPage>;
  readonly requiredData: ReadonlyArray<string>;
  readonly render: ComponentType<ResearchWidgetContentProps>;
}

export interface ResearchWidgetRegistry {
  readonly register: (definition: ResearchWidgetDefinition) => void;
  readonly get: (key: string) => ResearchWidgetDefinition | undefined;
  readonly getAll: () => ReadonlyArray<ResearchWidgetDefinition>;
}

export function createResearchWidgetRegistry(
  definitions: ReadonlyArray<ResearchWidgetDefinition> = [],
): ResearchWidgetRegistry {
  const definitionsByKey = new Map<string, ResearchWidgetDefinition>();

  const register = (definition: ResearchWidgetDefinition): void => {
    if (definitionsByKey.has(definition.key)) {
      throw new Error(`Research widget key already registered: ${definition.key}`);
    }
    definitionsByKey.set(definition.key, definition);
  };

  definitions.forEach(register);

  return {
    register,
    get: (key) => definitionsByKey.get(key),
    getAll: () =>
      [...definitionsByKey.values()].sort((left, right) =>
        left.key.localeCompare(right.key),
      ),
  };
}

const NoopRender: ComponentType<ResearchWidgetContentProps> = () => null;

const DEFAULT_WIDGETS: ReadonlyArray<ResearchWidgetDefinition> = [
  {
    key: "market-status",
    title: "Market Status",
    description: "市场状态观察与最近运行概览",
    defaultSize: "medium",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "research-summary",
    title: "Research Summary",
    description: "已发布研究结论摘要",
    defaultSize: "medium",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "evidence-pack",
    title: "Evidence Pack",
    description: "只读展示的 Evidence Pack 与 provenance",
    defaultSize: "wide",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "factor-snapshot",
    title: "Factor Snapshot",
    description: "来自 Analytics 的因子观测",
    defaultSize: "medium",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "research-run-timeline",
    title: "Research Run Timeline",
    description: "研究运行时间线",
    defaultSize: "wide",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "risk-monitor",
    title: "Risk Monitor",
    description: "风险因素与失效条件",
    defaultSize: "medium",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
  {
    key: "report-viewer",
    title: "Report Viewer",
    description: "只读 Markdown 报告",
    defaultSize: "wide",
    supportedPages: ["dashboard", "research-case"],
    requiredData: [],
    render: NoopRender,
  },
];

export const defaultResearchWidgetRegistry = createResearchWidgetRegistry(DEFAULT_WIDGETS);