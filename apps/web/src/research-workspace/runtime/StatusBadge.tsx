import type { ReactNode } from "react";

export type StatusBadgeTone =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "info";

export interface StatusBadgeProps {
  readonly tone?: StatusBadgeTone;
  readonly children: ReactNode;
  readonly title?: string;
  readonly ariaLabel?: string;
}

const TONE_CLASS: Record<StatusBadgeTone, string> = {
  neutral: "cockpitBadge-Neutral",
  success: "cockpitBadge-Success",
  warning: "cockpitBadge-Warning",
  danger: "cockpitBadge-Danger",
  info: "cockpitBadge-Info",
};

export function StatusBadge({
  tone = "neutral",
  children,
  title,
  ariaLabel,
}: StatusBadgeProps) {
  return (
    <span
      className={`cockpitBadge ${TONE_CLASS[tone]}`}
      title={title}
      aria-label={ariaLabel ?? (typeof children === "string" ? children : undefined)}
    >
      <span className="cockpitBadgeDot" aria-hidden="true" />
      <span className="cockpitBadgeLabel">{children}</span>
    </span>
  );
}
