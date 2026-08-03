import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  CandidatePoolDiffEntry,
  CandidatePoolDiffResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";

type DiffQuery = UseQueryResult<CandidatePoolDiffResponse, Error>;

type DiffColumnTone = "success" | "danger" | "neutral";

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export function CandidateDiffPanel({ query }: { query: DiffQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载候选池变化" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="尚无候选池差异"
          description="还没有可比较的发布结果。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取候选池变化"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const diff = query.data;
  if (!diff) {
    return <EmptyState title="暂无候选池差异数据" />;
  }
  return (
    <div className="diffGrid">
      <DiffColumn
        title="新增"
        tone="success"
        entries={diff.added}
        emptyText="本期无新增"
      />
      <DiffColumn
        title="保留"
        tone="neutral"
        entries={diff.retained}
        emptyText="本期无保留"
      />
      <DiffColumn
        title="移出"
        tone="danger"
        entries={diff.removed}
        emptyText="本期无移出"
      />
    </div>
  );
}

function DiffColumn({
  title,
  tone,
  entries,
  emptyText,
}: {
  title: string;
  tone: DiffColumnTone;
  entries: CandidatePoolDiffEntry[];
  emptyText: string;
}) {
  const columnClass = `diffColumn diffColumn-${tone}`;
  return (
    <div className={columnClass}>
      <header className="diffColumnHeader">
        <h4>{title}</h4>
        <span className="diffColumnCount">{entries.length}</span>
      </header>
      {entries.length === 0 ? (
        <p className="diffEmpty">{emptyText}</p>
      ) : (
        <ul className="diffList">
          {entries.map((entry) => (
            <li key={entry.instrument_id} className="diffItem">
              <span className="diffSymbol">{entry.symbol ?? "—"}</span>
              <span className="diffName">{entry.name ?? "未命名"}</span>
              {entry.exchange && (
                <span className="diffExchange">{entry.exchange}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}