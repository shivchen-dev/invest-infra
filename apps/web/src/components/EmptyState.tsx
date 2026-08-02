interface EmptyStateProps {
  title: string;
  description?: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="emptyState" role="status">
      <p className="emptyStateTitle">{title}</p>
      {description && <p className="emptyStateDescription">{description}</p>}
    </div>
  );
}