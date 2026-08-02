interface ErrorStateProps {
  title: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ title, message, onRetry }: ErrorStateProps) {
  return (
    <div className="errorState" role="alert">
      <p className="errorStateTitle">{title}</p>
      <p className="errorStateMessage">{message}</p>
      {onRetry && (
        <button
          type="button"
          className="errorStateRetry"
          onClick={onRetry}
        >
          重试
        </button>
      )}
    </div>
  );
}