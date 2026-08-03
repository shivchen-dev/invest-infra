import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  CandidatePoolItem,
  CandidatePoolLatestResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { formatAmount, formatCount } from "../../utils/format";

const TOP_N = 10;

type PoolQuery = UseQueryResult<CandidatePoolLatestResponse, Error>;

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

export function TopCandidatesPanel({ query }: { query: PoolQuery }) {
  if (query.isPending) {
    return <LoadingState label="正在加载最新候选" compact />;
  }
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <EmptyState
          title="尚无候选结果"
          description="还没有发布的候选池。"
        />
      );
    }
    return (
      <ErrorState
        title="无法读取最新候选"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无候选结果" />;
  }
  const included = data.items
    .filter((item: CandidatePoolItem) => item.included)
    .slice()
    .sort((a, b) => {
      const rankA = a.rank ?? Number.POSITIVE_INFINITY;
      const rankB = b.rank ?? Number.POSITIVE_INFINITY;
      return rankA - rankB;
    })
    .slice(0, TOP_N);

  if (included.length === 0) {
    return (
      <EmptyState
        title="本期暂无入选候选"
        description={`本期共 ${formatCount(data.row_count)} 只标的，0 只入选。`}
      />
    );
  }

  return (
    <div className="dataTableWrapper">
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">排名</th>
            <th scope="col">代码</th>
            <th scope="col">名称</th>
            <th scope="col">交易所</th>
            <th scope="col">成交额</th>
            <th scope="col">状态</th>
          </tr>
        </thead>
        <tbody>
          {included.map((item) => (
            <tr key={item.instrument_id}>
              <td>{item.rank ?? "—"}</td>
              <td>{item.symbol ?? "—"}</td>
              <td>{item.name ?? "—"}</td>
              <td>{item.exchange ?? "—"}</td>
              <td>{formatAmount(item.metrics.turnover ?? null)}</td>
              <td>
                <span className="statusPill statusPillSuccess">入选</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}