interface LoadingStateProps {
  label?: string;
  compact?: boolean;
}

export function LoadingState({
  label = "正在加载…",
  compact = false,
}: LoadingStateProps) {
  return (
    <div
      className={`loadingState${compact ? " loadingStateCompact" : ""}`}
      role="status"
      aria-live="polite"
    >
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}