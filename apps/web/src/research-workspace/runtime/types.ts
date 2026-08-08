export type ResearchWidgetSize = "small" | "medium" | "wide";

export type ResearchWidgetPage = "dashboard" | "research-case";

export type ResearchWidgetState =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "stale"
  | "failed";

export type ResearchWidgetTone =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "info";

export interface ResearchWidgetMeta {
  id: string;
  title: string;
  description: string;
  page: ResearchWidgetPage;
  size: ResearchWidgetSize;
  state: ResearchWidgetState;
  tone?: ResearchWidgetTone;
  generatedAt?: string | null;
  asOf?: string | null;
  badgeLabel?: string;
  provenance?: string;
}

export interface ResearchWidgetContentProps {
  readonly meta: ResearchWidgetMeta;
}

export interface ResearchWidgetSlots {
  readonly header?: React.ReactNode;
  readonly footer?: React.ReactNode;
  readonly children: React.ReactNode;
}
