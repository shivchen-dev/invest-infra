export type MetricTone = "neutral" | "success" | "warning" | "danger";

interface MetricCardProps {
  label: string;
  value: string | number | null | undefined;
  suffix?: string;
  valueAsText?: boolean;
  tone?: MetricTone;
}

const TONE_CLASS: Record<MetricTone, string> = {
  neutral: "",
  success: "metricCardSuccess",
  warning: "metricCardWarning",
  danger: "metricCardDanger",
};

export function MetricCard({
  label,
  value,
  suffix,
  valueAsText = false,
  tone = "neutral",
}: MetricCardProps) {
  const display =
    value === null || value === undefined || value === "" ? "—" : String(value);
  const showSuffix = Boolean(suffix) && display !== "—";
  return (
    <article
      className={`metricCard ${TONE_CLASS[tone]}`}
      aria-label={`${label}: ${display}`}
    >
      <p className="metricCardLabel">{label}</p>
      <p
        className={`metricCardValue${
          valueAsText ? " metricCardValueText" : ""
        }`}
      >
        <span>{display}</span>
        {showSuffix && <span className="metricCardSuffix">{suffix}</span>}
      </p>
    </article>
  );
}