import type { DataFreshnessStatus } from "../api/types";

interface StatusBannerProps {
  status: DataFreshnessStatus;
  title: string;
  description?: string;
  details?: { label: string; value: string }[];
}

interface StatusMeta {
  className: string;
  icon: string;
  ariaLabel: string;
}

const STATUS_META: Record<DataFreshnessStatus, StatusMeta> = {
  fresh: {
    className: "statusBannerFresh",
    icon: "✓",
    ariaLabel: "数据已更新",
  },
  partial: {
    className: "statusBannerPartial",
    icon: "!",
    ariaLabel: "数据部分缺失",
  },
  stale: {
    className: "statusBannerStale",
    icon: "…",
    ariaLabel: "数据未更新到预期日期",
  },
  missing: {
    className: "statusBannerMissing",
    icon: "·",
    ariaLabel: "尚无发布结果",
  },
  failed: {
    className: "statusBannerFailed",
    icon: "×",
    ariaLabel: "最新任务失败",
  },
};

export function StatusBanner({
  status,
  title,
  description,
  details,
}: StatusBannerProps) {
  const meta = STATUS_META[status];
  return (
    <section
      className={`statusBanner ${meta.className}`}
      role="status"
      aria-live="polite"
      aria-label={meta.ariaLabel}
    >
      <div className="statusBannerHeader">
        <span className="statusBannerIcon" aria-hidden="true">
          {meta.icon}
        </span>
        <h2 className="statusBannerTitle">{title}</h2>
      </div>
      {description && (
        <p className="statusBannerDescription">{description}</p>
      )}
      {details && details.length > 0 && (
        <dl className="statusBannerDetails">
          {details.map((detail) => (
            <div key={detail.label}>
              <dt>{detail.label}</dt>
              <dd>{detail.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}