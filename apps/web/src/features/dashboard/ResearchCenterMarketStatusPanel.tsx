import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  ResearchCenterBreadth,
  ResearchCenterDataFreshness,
  ResearchCenterMarket,
  ResearchCenterObservation,
  ResearchCenterResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { NavLink } from "../../router";
import { formatCount, formatDate, formatDateTime } from "../../utils/format";

type CenterQuery = UseQueryResult<ResearchCenterResponse, Error>;

const MARKET_STATE_LABELS: Record<ResearchCenterMarket["state"], string> = {
  available: "available · 市场广度与数据新鲜度均可展示",
  partial: "partial · 仅部分来源可展示（请查看下方子区段）",
  unavailable: "unavailable · 两个市场来源均无可展示结果",
  failed: "failed · 受控查询失败（响应不含内部异常文本）",
};

const FRESHNESS_STATE_LABELS: Record<
  ResearchCenterDataFreshness["state"],
  string
> = {
  available: "available",
  partial: "partial",
  unavailable: "unavailable",
  failed: "failed",
};

const FRESHNESS_STATUS_LABELS: Record<
  ResearchCenterDataFreshness["status"],
  string
> = {
  fresh: "fresh · 数据已更新",
  partial: "partial · 数据部分缺失",
  stale: "stale · 数据未更新到预期日期",
  missing: "missing · 尚无发布结果",
  failed: "failed · 最新任务失败",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

function ObservationRow({
  observation,
}: {
  observation: ResearchCenterObservation;
}) {
  return (
    <tr>
      <td>{observation.key}</td>
      <td>{observation.value === null ? "—" : observation.value}</td>
      <td>{observation.unit}</td>
      <td>{formatDate(observation.observed_date)}</td>
      <td>{observation.source_kind}</td>
      <td>{observation.source_ref}</td>
      <td>{observation.quality_status}</td>
    </tr>
  );
}

function BreadthSection({ breadth }: { breadth: ResearchCenterBreadth | null }) {
  if (breadth === null) {
    return (
      <section aria-label="市场广度">
        <header className="sectionHeader">
          <h4 className="sectionTitle">市场广度</h4>
          <span className="sectionMeta">unavailable</span>
          <a href="/api/v1/market-breadth/latest">
            查看 Market Breadth 详情
          </a>
        </header>
        <EmptyState
          title="市场广度 · unavailable"
          description="Market Breadth 快照缺失，未渲染任何衍生指标或零值。"
        />
      </section>
    );
  }
  if (breadth.state === "failed") {
    return (
      <section aria-label="市场广度">
        <header className="sectionHeader">
          <h4 className="sectionTitle">市场广度</h4>
          <span className="sectionMeta">failed</span>
          <a href="/api/v1/market-breadth/latest">
            查看 Market Breadth 详情
          </a>
        </header>
        <ErrorState
          title="市场广度 · failed"
          message="Market Breadth 查询失败，未返回快照或 observation。"
        />
      </section>
    );
  }
  return (
    <section aria-label="市场广度">
      <header className="sectionHeader">
        <h4 className="sectionTitle">市场广度</h4>
        <span className="sectionMeta">
          snapshot_id {breadth.snapshot_id} · algorithm {breadth.algorithm_version}
        </span>
        <a href="/api/v1/market-breadth/latest">
          查看 Market Breadth 详情
        </a>
      </header>
      <dl className="runSummary">
        <div>
          <dt>scope_type</dt>
          <dd>{breadth.scope_type}</dd>
        </div>
        <div>
          <dt>scope_key</dt>
          <dd>{breadth.scope_key}</dd>
        </div>
      </dl>
      {breadth.observations === null || breadth.observations.length === 0 ? (
        <EmptyState
          title="市场广度 · 无 observation"
          description="该快照未注册任何 observation。"
        />
      ) : (
        <div className="dataTableWrapper">
          <table className="dataTable" aria-label="Market Breadth observations">
            <thead>
              <tr>
                <th scope="col">key</th>
                <th scope="col">value</th>
                <th scope="col">unit</th>
                <th scope="col">observed_date</th>
                <th scope="col">source_kind</th>
                <th scope="col">source_ref</th>
                <th scope="col">quality_status</th>
              </tr>
            </thead>
            <tbody>
              {breadth.observations.map((observation) => (
                <ObservationRow
                  key={observation.key}
                  observation={observation}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FreshnessSection({
  freshness,
}: {
  freshness: ResearchCenterDataFreshness | null;
}) {
  if (freshness === null) {
    return (
      <section aria-label="数据新鲜度">
        <header className="sectionHeader">
          <h4 className="sectionTitle">数据新鲜度</h4>
          <span className="sectionMeta">unavailable</span>
          <NavLink to="/operations">查看 Data Freshness 详情</NavLink>
        </header>
        <EmptyState
          title="数据新鲜度 · unavailable"
          description="Data Freshness 查询未返回可展示结果。"
        />
      </section>
    );
  }
  if (freshness.state === "failed" || freshness.status === "failed") {
    return (
      <section aria-label="数据新鲜度">
        <header className="sectionHeader">
          <h4 className="sectionTitle">数据新鲜度</h4>
          <span className="sectionMeta">failed</span>
          <NavLink to="/operations">查看 Data Freshness 详情</NavLink>
        </header>
        <ErrorState
          title="数据新鲜度 · failed"
          message="Data Freshness 查询失败，未返回发布日期或计数。"
        />
      </section>
    );
  }
  if (freshness.state === "unavailable" || freshness.status === "missing") {
    return (
      <section aria-label="数据新鲜度">
        <header className="sectionHeader">
          <h4 className="sectionTitle">数据新鲜度</h4>
          <span className="sectionMeta">
            {freshness.status === "missing"
              ? "missing · 尚无发布结果"
              : FRESHNESS_STATUS_LABELS[freshness.status]}
          </span>
          <NavLink to="/operations">查看 Data Freshness 详情</NavLink>
        </header>
        <dl className="runSummary">
          <div>
            <dt>status</dt>
            <dd>
              <span className="statusPill statusPillNeutral">
                {freshness.status}
              </span>
            </dd>
          </div>
          <div>
            <dt>state</dt>
            <dd>{FRESHNESS_STATE_LABELS[freshness.state]}</dd>
          </div>
          <div>
            <dt>checked_at</dt>
            <dd>{formatDateTime(freshness.checked_at)}</dd>
          </div>
        </dl>
        <EmptyState
          title={`数据新鲜度 · ${FRESHNESS_STATE_LABELS[freshness.state]} / ${freshness.status}`}
          description="unavailable 与 missing 含义不同；未渲染 0 值指标或推测的发布日期。"
        />
      </section>
    );
  }
  return (
    <section aria-label="数据新鲜度">
      <header className="sectionHeader">
        <h4 className="sectionTitle">数据新鲜度</h4>
        <span className="sectionMeta">
          {FRESHNESS_STATUS_LABELS[freshness.status]}
        </span>
        <NavLink to="/operations">查看 Data Freshness 详情</NavLink>
      </header>
      <dl className="runSummary">
        <div>
          <dt>status</dt>
          <dd>
            <span className="statusPill statusPillNeutral">
              {freshness.status}
            </span>
          </dd>
        </div>
        <div>
          <dt>state</dt>
          <dd>{FRESHNESS_STATE_LABELS[freshness.state]}</dd>
        </div>
        <div>
          <dt>checked_at</dt>
          <dd>{formatDateTime(freshness.checked_at)}</dd>
        </div>
        <div>
          <dt>latest_published_trade_date</dt>
          <dd>{formatDate(freshness.latest_published_trade_date)}</dd>
        </div>
        <div>
          <dt>universe_count</dt>
          <dd>{formatCount(freshness.universe_count)} 只</dd>
        </div>
        <div>
          <dt>daily_bar_count</dt>
          <dd>{formatCount(freshness.daily_bar_count)} 只</dd>
        </div>
        <div>
          <dt>missing_count</dt>
          <dd>{formatCount(freshness.missing_count)} 只</dd>
        </div>
      </dl>
    </section>
  );
}

export function ResearchCenterMarketStatusPanel({
  query,
}: {
  query: CenterQuery;
}) {
  if (query.isPending) {
    return (
      <LoadingState label="正在加载 Research Center 市场状态" compact />
    );
  }
  if (query.isError) {
    return (
      <ErrorState
        title="无法读取 Research Center 市场状态"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无 Research Center 市场状态" />;
  }
  const market = data.market;
  return (
    <div data-state={market.state} aria-label="Research Center 市场状态">
      <header className="sectionHeader">
        <h3 className="sectionTitle">Research Center 市场状态</h3>
        <span className="sectionMeta">
          Read API · /api/v1/research-center · schema {data.schema_version}
        </span>
      </header>
      <p role="status" aria-label={`市场状态 ${market.state}`}>
        市场状态 · <strong>{market.state}</strong> ·{" "}
        {MARKET_STATE_LABELS[market.state]}
      </p>
      <section aria-label="市场日期与质量">
        <header className="sectionHeader">
          <h4 className="sectionTitle">市场日期与质量</h4>
        </header>
        <dl className="runSummary">
          <div>
            <dt>as_of_date</dt>
            <dd>{formatDate(market.as_of_date)}</dd>
          </div>
          <div>
            <dt>generated_at</dt>
            <dd>{formatDateTime(data.generated_at)}</dd>
          </div>
          <div>
            <dt>quality_status</dt>
            <dd>{market.quality_status ?? "—"}</dd>
          </div>
          <div>
            <dt>freshness_status</dt>
            <dd>{market.freshness_status ?? "—"}</dd>
          </div>
        </dl>
      </section>
      <BreadthSection breadth={market.breadth} />
      <FreshnessSection freshness={market.data_freshness} />
    </div>
  );
}
