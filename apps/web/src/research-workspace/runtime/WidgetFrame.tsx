import type { ReactNode } from "react";
import { StatusBadge, type StatusBadgeTone } from "./StatusBadge";
import type {
  ResearchWidgetContentProps,
  ResearchWidgetMeta,
  ResearchWidgetState,
} from "./types";

const STATE_MESSAGES: Record<ResearchWidgetState, string> = {
  idle: "等待数据",
  loading: "正在加载",
  ready: "已就绪",
  empty: "暂无可展示数据",
  stale: "数据已过期",
  failed: "读取失败",
};

const STATE_TONE: Record<ResearchWidgetState, StatusBadgeTone> = {
  idle: "neutral",
  loading: "info",
  ready: "success",
  empty: "neutral",
  stale: "warning",
  failed: "danger",
};

export interface WidgetFrameProps extends ResearchWidgetContentProps {
  readonly children: ReactNode;
  readonly footer?: ReactNode;
  readonly hideHeader?: boolean;
}

export function WidgetFrame({
  meta,
  children,
  footer,
  hideHeader = false,
}: WidgetFrameProps) {
  const stateBadgeLabel = meta.badgeLabel ?? STATE_MESSAGES[meta.state];
  const generatedAt = meta.generatedAt ?? null;
  return (
    <article
      className={widgetClass(meta)}
      data-widget-id={meta.id}
      data-widget-state={meta.state}
      data-widget-page={meta.page}
      data-widget-size={meta.size}
      aria-labelledby={`widget-${meta.id}-title`}
    >
      {!hideHeader && (
        <header className="cockpitWidgetHeader">
          <div className="cockpitWidgetHeaderText">
            <p className="cockpitWidgetEyebrow">{pageLabel(meta)}</p>
            <h3 className="cockpitWidgetTitle" id={`widget-${meta.id}-title`}>
              {meta.title}
            </h3>
            <p className="cockpitWidgetDescription">{meta.description}</p>
          </div>
          <div className="cockpitWidgetHeaderMeta">
            <StatusBadge tone={STATE_TONE[meta.state]}>
              {stateBadgeLabel}
            </StatusBadge>
            {meta.provenance && (
              <span className="cockpitWidgetProvenance" title={meta.provenance}>
                {meta.provenance}
              </span>
            )}
          </div>
        </header>
      )}
      <div className="cockpitWidgetBody">{children}</div>
      {(footer || generatedAt || meta.asOf) && (
        <footer className="cockpitWidgetFooter">
          {footer}
          <ProvenanceTrail generatedAt={generatedAt} asOf={meta.asOf ?? null} />
        </footer>
      )}
    </article>
  );
}

function widgetClass(meta: ResearchWidgetMeta): string {
  return `cockpitWidget cockpitWidget-${meta.size} cockpitWidgetTone-${
    meta.tone ?? "neutral"
  }`;
}

function pageLabel(meta: ResearchWidgetMeta): string {
  return meta.page === "dashboard" ? "Dashboard" : "Research Case";
}

function ProvenanceTrail({
  generatedAt,
  asOf,
}: {
  generatedAt: string | null;
  asOf: string | null;
}) {
  if (!generatedAt && !asOf) return null;
  return (
    <dl className="cockpitWidgetProvenanceTrail">
      {asOf && (
        <div>
          <dt>观察日期</dt>
          <dd>{asOf}</dd>
        </div>
      )}
      {generatedAt && (
        <div>
          <dt>生成时间</dt>
          <dd>{generatedAt}</dd>
        </div>
      )}
    </dl>
  );
}
