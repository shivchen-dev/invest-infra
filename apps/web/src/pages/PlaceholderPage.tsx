import { useParams } from "../router";

interface PlaceholderPageProps {
  title: string;
  description: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  const params = useParams<{ instrumentId?: string }>();
  return (
    <div className="placeholderPage">
      <p className="pageEyebrow">{title}</p>
      <h2 className="pageTitle">{title}</h2>
      {params.instrumentId !== undefined && (
        <p className="pageSubtitle">
          当前 ETF ID：<code className="inlineCode">{params.instrumentId}</code>
        </p>
      )}
      <p className="placeholderDescription">{description}</p>
    </div>
  );
}