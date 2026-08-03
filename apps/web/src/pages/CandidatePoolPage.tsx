import {
  Fragment,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  fetchCandidatePoolLatest,
  fetchCandidatePoolLatestDiff,
  latestCandidateDiffQueryKey,
  latestCandidatePoolQueryKey,
} from "../api/candidatePool";
import { ApiError } from "../api/client";
import type {
  CandidatePoolDiffEntry,
  CandidatePoolDiffResponse,
  CandidatePoolItem,
  CandidatePoolLatestResponse,
  ExclusionReason,
  RuleOutcome,
} from "../api/types";
import { CandidatePoolMetadata } from "../features/candidatePool/CandidatePoolMetadata";
import {
  exclusionReasonLabel,
  reasonFilterLabel,
} from "../features/candidatePool/exclusionLabels";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { NavLink, useNavigate } from "../router";
import {
  formatAmount,
  formatCount,
  formatDate,
  formatDecimal,
} from "../utils/format";

const REFETCH_INTERVAL = 5 * 60_000;

type CandidateTab = "included" | "excluded" | "all";

const TABS: ReadonlyArray<{ value: CandidateTab; label: string }> = [
  { value: "included", label: "入选" },
  { value: "excluded", label: "排除" },
  { value: "all", label: "全部" },
];

export function CandidatePoolPage() {
  const latestPool = useQuery<CandidatePoolLatestResponse>({
    queryKey: latestCandidatePoolQueryKey,
    queryFn: ({ signal }) => fetchCandidatePoolLatest(signal),
    refetchInterval: REFETCH_INTERVAL,
    retry: shouldRetry,
  });
  const latestDiff = useQuery<CandidatePoolDiffResponse>({
    queryKey: latestCandidateDiffQueryKey,
    queryFn: ({ signal }) => fetchCandidatePoolLatestDiff(signal),
    refetchInterval: REFETCH_INTERVAL,
    retry: shouldRetry,
  });

  if (latestPool.isPending) {
    return (
      <div className="candidatePoolPage">
        <PageHeader />
        <LoadingState label="正在加载最新候选池" />
      </div>
    );
  }

  if (latestPool.isError) {
    return (
      <div className="candidatePoolPage">
        <PageHeader />
        {isNotFound(latestPool.error) ? (
          <EmptyState
            title="尚无候选池"
            description="系统还没有已发布的候选池结果。"
          />
        ) : (
          <ErrorState
            title="无法读取最新候选池"
            message={describeError(latestPool.error)}
            onRetry={() => {
              void latestPool.refetch();
            }}
          />
        )}
      </div>
    );
  }

  const pool = latestPool.data;
  if (!pool) {
    return (
      <div className="candidatePoolPage">
        <PageHeader />
        <EmptyState title="暂无候选池数据" />
      </div>
    );
  }

  return (
    <div className="candidatePoolPage">
      <PageHeader />
      <CandidatePoolMetadata pool={pool} />
      <CandidatePoolExplorer items={pool.items} />

      <section className="pageSection" aria-labelledby="candidate-diff-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="candidate-diff-title">
            候选池变化
          </h3>
          {latestDiff.data && (
            <span className="sectionMeta">
              对比 {formatDate(latestDiff.data.previous_trade_date)} →{" "}
              {formatDate(latestDiff.data.trade_date)}
            </span>
          )}
        </header>
        <DiffSection query={latestDiff} />
      </section>
    </div>
  );
}

function PageHeader() {
  return (
    <header className="pageHeader">
      <p className="pageEyebrow">Candidate Pool</p>
      <h2 className="pageTitle">候选池</h2>
      <p className="pageSubtitle">查看最新筛选结果、排除依据与跨期变化。</p>
    </header>
  );
}

function CandidatePoolExplorer({ items }: { items: CandidatePoolItem[] }) {
  const [activeTab, setActiveTab] = useState<CandidateTab>("included");
  const [search, setSearch] = useState("");
  const [exchange, setExchange] = useState("");
  const [reasonCode, setReasonCode] = useState("");

  const exchangeOptions = useMemo(() => uniqueExchanges(items), [items]);
  const reasonOptions = useMemo(() => exclusionReasonOptions(items), [items]);
  const itemsForTab = useMemo(
    () =>
      items.filter((item) => {
        if (activeTab === "included") return item.included;
        if (activeTab === "excluded") return !item.included;
        return true;
      }),
    [activeTab, items],
  );
  const filteredItems = useMemo(() => {
    const normalizedSearch = normalize(search.trim());
    const normalizedExchange = normalize(exchange);
    const normalizedReason = normalize(reasonCode);

    return itemsForTab.filter((item) => {
      if (
        normalizedSearch &&
        ![item.symbol, item.name].some((value) =>
          normalize(value ?? "").includes(normalizedSearch),
        )
      ) {
        return false;
      }
      if (
        normalizedExchange &&
        normalize(item.exchange ?? "") !== normalizedExchange
      ) {
        return false;
      }
      if (
        activeTab !== "included" &&
        normalizedReason &&
        !item.exclusion_reasons.some(
          (reason) => normalize(reason.code) === normalizedReason,
        )
      ) {
        return false;
      }
      return true;
    });
  }, [activeTab, exchange, itemsForTab, reasonCode, search]);

  const includedItems = sortCandidateItems(
    filteredItems.filter((item) => item.included),
    true,
  );
  const excludedItems = sortCandidateItems(
    filteredItems.filter((item) => !item.included),
    false,
  );
  const selectedTabId = `candidate-tab-${activeTab}`;

  const tabCount = (tab: CandidateTab): number => {
    if (tab === "included") return items.filter((item) => item.included).length;
    if (tab === "excluded") return items.filter((item) => !item.included).length;
    return items.length;
  };

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % TABS.length;
    if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + TABS.length) % TABS.length;
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = TABS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    setActiveTab(TABS[nextIndex].value);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
      '[role="tab"]',
    );
    buttons?.[nextIndex]?.focus();
  };

  return (
    <section className="pageSection" aria-labelledby="candidate-items-title">
      <header className="sectionHeader">
        <h3 className="sectionTitle" id="candidate-items-title">
          候选明细
        </h3>
        <span className="sectionMeta" aria-live="polite">
          筛选后 {formatCount(filteredItems.length)} / {formatCount(itemsForTab.length)}
        </span>
      </header>

      <div className="candidateTabs" role="tablist" aria-label="候选池状态">
        {TABS.map((tab, index) => {
          const selected = activeTab === tab.value;
          return (
            <button
              key={tab.value}
              type="button"
              id={`candidate-tab-${tab.value}`}
              className={`candidateTab${selected ? " candidateTabActive" : ""}`}
              role="tab"
              aria-selected={selected}
              aria-controls="candidate-result-panel"
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveTab(tab.value)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              {tab.label}
              <span className="candidateTabCount">{formatCount(tabCount(tab.value))}</span>
            </button>
          );
        })}
      </div>

      <div className="candidateFilters" role="search" aria-label="筛选候选池">
        <label className="candidateFilter candidateFilterSearch">
          <span>代码或名称</span>
          <input
            type="search"
            value={search}
            placeholder="输入代码或名称"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="candidateFilter">
          <span>交易所</span>
          <select
            value={exchange}
            onChange={(event) => setExchange(event.target.value)}
          >
            <option value="">全部交易所</option>
            {exchangeOptions.map((option) => (
              <option key={normalize(option)} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        {activeTab !== "included" && (
          <label className="candidateFilter">
            <span>排除原因</span>
            <select
              value={reasonCode}
              onChange={(event) => setReasonCode(event.target.value)}
            >
              <option value="">全部原因</option>
              {reasonOptions.map((option) => (
                <option key={normalize(option.code)} value={option.code}>
                  {reasonFilterLabel(option.code)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div
        id="candidate-result-panel"
        role="tabpanel"
        aria-labelledby={selectedTabId}
        tabIndex={0}
        className="candidateResultPanel"
      >
        {filteredItems.length === 0 ? (
          <EmptyState
            title="没有符合条件的候选"
            description="请调整搜索词或筛选条件。"
          />
        ) : activeTab === "included" ? (
          <CandidateTable items={includedItems} mode="included" />
        ) : activeTab === "excluded" ? (
          <CandidateTable items={excludedItems} mode="excluded" />
        ) : (
          <div className="candidateAllTables">
            {includedItems.length > 0 && (
              <TableGroup title="入选" count={includedItems.length}>
                <CandidateTable items={includedItems} mode="included" />
              </TableGroup>
            )}
            {excludedItems.length > 0 && (
              <TableGroup title="排除" count={excludedItems.length}>
                <CandidateTable items={excludedItems} mode="excluded" />
              </TableGroup>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function TableGroup({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="candidateTableGroup" aria-label={`${title}候选`}>
      <h4 className="candidateTableTitle">
        {title} <span>{formatCount(count)}</span>
      </h4>
      {children}
    </section>
  );
}

function uniqueExchanges(items: CandidatePoolItem[]): string[] {
  const values = new Map<string, string>();
  for (const item of items) {
    const value = item.exchange?.trim();
    if (value) values.set(normalize(value), value);
  }
  return [...values.values()].sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function exclusionReasonOptions(
  items: CandidatePoolItem[],
): ExclusionReason[] {
  const reasons = new Map<string, ExclusionReason>();
  for (const item of items) {
    for (const reason of item.exclusion_reasons) {
      const key = normalize(reason.code);
      if (key && !reasons.has(key)) reasons.set(key, reason);
    }
  }
  return [...reasons.values()].sort((a, b) =>
    exclusionReasonLabel(a.code).localeCompare(exclusionReasonLabel(b.code), "zh-CN"),
  );
}

function sortCandidateItems(
  items: CandidatePoolItem[],
  included: boolean,
): CandidatePoolItem[] {
  return items.slice().sort((a, b) => {
    if (included) {
      const rankDifference =
        (a.rank ?? Number.POSITIVE_INFINITY) -
        (b.rank ?? Number.POSITIVE_INFINITY);
      if (rankDifference !== 0) return rankDifference;
    }
    return candidateLabel(a).localeCompare(candidateLabel(b), "zh-CN", {
      numeric: true,
    });
  });
}

function candidateLabel(item: CandidatePoolItem): string {
  return item.symbol ?? item.name ?? item.instrument_id;
}

function normalize(value: string): string {
  return value.toLocaleLowerCase();
}

function CandidateTable({
  items,
  mode,
}: {
  items: CandidatePoolItem[];
  mode: "included" | "excluded";
}) {
  const navigate = useNavigate();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const navigateToItem = (item: CandidatePoolItem) => {
    navigate(instrumentPath(item.instrument_id));
  };

  const handleRowKeyDown = (
    event: KeyboardEvent<HTMLTableRowElement>,
    item: CandidatePoolItem,
  ) => {
    if (event.target === event.currentTarget && event.key === "Enter") {
      event.preventDefault();
      navigateToItem(item);
    }
  };

  return (
    <div className="dataTableWrapper">
      <table
        className="dataTable candidatePoolTable"
        aria-label={mode === "included" ? "入选候选" : "排除候选"}
      >
        <thead>
          {mode === "included" ? (
            <tr>
              <th scope="col">排名</th>
              <th scope="col">代码</th>
              <th scope="col">名称</th>
              <th scope="col">交易所</th>
              <th scope="col">成交额</th>
              <th scope="col">成交量</th>
              <th scope="col">总分</th>
              <th scope="col">状态</th>
              <th scope="col">详情</th>
            </tr>
          ) : (
            <tr>
              <th scope="col">代码</th>
              <th scope="col">名称</th>
              <th scope="col">交易所</th>
              <th scope="col">主要排除原因</th>
              <th scope="col">原始 Code</th>
              <th scope="col">观测值 / 阈值</th>
              <th scope="col">详情</th>
            </tr>
          )}
        </thead>
        <tbody>
          {items.map((item) => {
            const reason = primaryExclusionReason(item);
            const rule = matchingRule(item, reason);
            const expanded = expandedId === item.instrument_id;
            const detailId = `candidate-details-${mode}-${encodeURIComponent(
              item.instrument_id,
            )}`;
            return (
              <Fragment key={item.instrument_id}>
                <tr
                  className={`candidatePoolRow${
                    expanded ? " candidatePoolRowExpanded" : ""
                  }`}
                  tabIndex={0}
                  aria-label={`查看 ${candidateLabel(item)} ETF 详情`}
                  onClick={() => navigateToItem(item)}
                  onKeyDown={(event) => handleRowKeyDown(event, item)}
                >
                  {mode === "included" ? (
                    <>
                      <td>{item.rank ?? "—"}</td>
                      <td>
                        <CandidateLink item={item} />
                      </td>
                      <td>{item.name ?? "—"}</td>
                      <td>{item.exchange ?? "—"}</td>
                      <td>
                        {formatAmount(
                          item.metrics.amount ?? item.metrics.turnover ?? null,
                        )}
                      </td>
                      <td>{formatCount(item.metrics.volume ?? null)}</td>
                      <td>{formatDecimal(item.total_score)}</td>
                      <td>
                        <span className="statusPill statusPillSuccess">入选</span>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>
                        <CandidateLink item={item} />
                      </td>
                      <td>{item.name ?? "—"}</td>
                      <td>{item.exchange ?? "—"}</td>
                      <td>{reason ? exclusionReasonLabel(reason.code) : "—"}</td>
                      <td>{reason?.code || "—"}</td>
                      <td
                        className="candidateObservation"
                        title={rule?.message ?? reason?.message ?? undefined}
                      >
                        {observationDisplay(rule, reason)}
                      </td>
                    </>
                  )}
                  <td className="candidateExpandCell">
                    <button
                      type="button"
                      className="candidateExpandButton"
                      aria-expanded={expanded}
                      aria-controls={detailId}
                      aria-label={`${expanded ? "收起" : "展开"} ${candidateLabel(
                        item,
                      )} 详情`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setExpandedId(expanded ? null : item.instrument_id);
                      }}
                    >
                      {expanded ? "收起" : "展开"}
                    </button>
                  </td>
                </tr>
                {expanded && (
                  <tr className="candidateDetailRow">
                    <td colSpan={mode === "included" ? 9 : 7}>
                      <CandidateItemDetails item={item} id={detailId} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CandidateLink({ item }: { item: CandidatePoolItem }) {
  return (
    <NavLink
      to={instrumentPath(item.instrument_id)}
      className="candidateSymbolLink"
      title={item.instrument_id}
      onClick={(event) => event.stopPropagation()}
    >
      {item.symbol ?? "—"}
    </NavLink>
  );
}

function CandidateItemDetails({
  item,
  id,
}: {
  item: CandidatePoolItem;
  id: string;
}) {
  const metrics = Object.entries(item.metrics).sort(([keyA], [keyB]) =>
    keyA.localeCompare(keyB, "zh-CN"),
  );

  return (
    <div className="candidateItemDetails" id={id}>
      <div className="candidateDetailIdentifier">
        <span>instrument_id</span>
        <code title={item.instrument_id}>{item.instrument_id}</code>
      </div>
      <div className="candidateDetailGrid">
        <section aria-label="Metrics">
          <h5>Metrics</h5>
          {metrics.length === 0 ? (
            <p className="candidateDetailEmpty">无指标数据</p>
          ) : (
            <dl className="candidateDetailValues">
              {metrics.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section aria-label="Rule results">
          <h5>Rule Results</h5>
          {item.rule_results.length === 0 ? (
            <p className="candidateDetailEmpty">无规则结果</p>
          ) : (
            <ul className="candidateRuleList">
              {item.rule_results.map((rule, index) => (
                <li key={`${rule.rule_key}-${index}`}>
                  <header className="candidateRuleHeader">
                    <code>{rule.rule_key || "—"}</code>
                    <span
                      className={`statusPill ${
                        rule.passed ? "statusPillSuccess" : "statusPillDanger"
                      }`}
                    >
                      {rule.passed ? "通过" : "未通过"}
                    </span>
                    <span className="candidateRuleSeverity">
                      {rule.severity || "—"}
                    </span>
                  </header>
                  <dl className="candidateRuleValues">
                    <div>
                      <dt>观测值</dt>
                      <dd>{rule.value ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>阈值</dt>
                      <dd>{rule.threshold ?? "—"}</dd>
                    </div>
                    <div className="candidateRuleMessage">
                      <dt>说明</dt>
                      <dd>{rule.message ?? "—"}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Exclusion reasons">
          <h5>Exclusion Reasons</h5>
          {item.exclusion_reasons.length === 0 ? (
            <p className="candidateDetailEmpty">无排除原因</p>
          ) : (
            <ul className="candidateReasonList">
              {item.exclusion_reasons.map((reason, index) => (
                <li key={`${reason.code}-${index}`}>
                  <strong>{exclusionReasonLabel(reason.code)}</strong>
                  <code>{reason.code || "—"}</code>
                  <span>{reason.message || "—"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function primaryExclusionReason(
  item: CandidatePoolItem,
): ExclusionReason | undefined {
  return item.exclusion_reasons[0];
}

function matchingRule(
  item: CandidatePoolItem,
  reason: ExclusionReason | undefined,
): RuleOutcome | undefined {
  const failedRules = item.rule_results.filter((rule) => !rule.passed);
  if (!reason) return failedRules.length === 1 ? failedRules[0] : undefined;
  const code = normalize(reason.code);
  const matching = failedRules.find((rule) => {
    const key = normalize(rule.rule_key);
    return key === code || key.endsWith(`.${code}`) || key.endsWith(`_${code}`);
  });
  return matching ?? (failedRules.length === 1 ? failedRules[0] : undefined);
}

function observationDisplay(
  rule: RuleOutcome | undefined,
  reason: ExclusionReason | undefined,
): string {
  if (rule && (rule.value !== null || rule.threshold !== null)) {
    return `${rule.value ?? "—"} / ${rule.threshold ?? "—"}`;
  }
  return rule?.message ?? reason?.message ?? "—";
}

type DiffQuery = UseQueryResult<CandidatePoolDiffResponse, Error>;

function DiffSection({ query }: { query: DiffQuery }) {
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
      <DiffColumn title="新增" tone="Success" entries={diff.added} />
      <DiffColumn title="保留" tone="Neutral" entries={diff.retained} />
      <DiffColumn title="移出" tone="Danger" entries={diff.removed} />
    </div>
  );
}

function DiffColumn({
  title,
  tone,
  entries,
}: {
  title: string;
  tone: "Success" | "Neutral" | "Danger";
  entries: CandidatePoolDiffEntry[];
}) {
  return (
    <div className={`diffColumn diffColumn-${tone}`}>
      <header className="diffColumnHeader">
        <h4>{title}</h4>
        <span className="diffColumnCount">{formatCount(entries.length)}</span>
      </header>
      {entries.length === 0 ? (
        <p className="diffEmpty">本期无{title}</p>
      ) : (
        <ul className="diffList">
          {entries.map((entry) => (
            <li key={entry.instrument_id} className="diffItem">
              <NavLink
                to={instrumentPath(entry.instrument_id)}
                className="candidateDiffLink"
                title={entry.instrument_id}
              >
                <span className="diffSymbol">
                  {entry.symbol ?? compactText(entry.instrument_id)}
                </span>
                {entry.name && <span className="diffName">{entry.name}</span>}
                {entry.exchange && (
                  <span className="diffExchange">{entry.exchange}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function compactText(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function instrumentPath(instrumentId: string): string {
  return `/etf/${encodeURIComponent(instrumentId)}`;
}

function shouldRetry(failureCount: number, error: Error): boolean {
  return !isNotFound(error) && failureCount < 3;
}

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.message;
  if (error instanceof Error) return error.message;
  return "未知错误";
}
