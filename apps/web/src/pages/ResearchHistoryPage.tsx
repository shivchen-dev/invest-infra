import { useState } from "react";
import { type UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { useResearchCases } from "../api/researchCases";
import { useResearchRuns } from "../api/researchRuns";
import type {
  ResearchCaseListResponse,
  ResearchCaseResponse,
  ResearchRunListResponse,
  ResearchRunResponse,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import {
  WidgetFrame,
  type ResearchWidgetMeta,
} from "../research-workspace/runtime";
import { formatCount, formatDateTime } from "../utils/format";

const PAGE_SIZE = 20;
const HISTORY_SCOPES = [
  { id: "all", label: "全部" },
  { id: "case", label: "Case" },
  { id: "run", label: "Run" },
] as const;

type HistoryScope = (typeof HISTORY_SCOPES)[number]["id"];

interface PaginationState {
  readonly page: number;
  readonly offset: number;
}

const INITIAL_PAGINATION: PaginationState = { page: 0, offset: 0 };

export function ResearchHistoryPage() {
  const [scope, setScope] = useState<HistoryScope>("all");
  const [pagination, setPagination] = useState<PaginationState>(INITIAL_PAGINATION);

  const casesQuery = useResearchCases(
    { limit: PAGE_SIZE, offset: pagination.offset },
    { retry: shouldRetry },
  );
  const runsQuery = useResearchRuns(
    { limit: PAGE_SIZE, offset: pagination.offset },
    { retry: shouldRetry },
  );

  function handleScopeChange(next: HistoryScope) {
    if (next === scope) return;
    setScope(next);
    setPagination(INITIAL_PAGINATION);
  }

  function handlePreviousPage() {
    setPagination((state) => ({
      page: Math.max(0, state.page - 1),
      offset: Math.max(0, state.offset - PAGE_SIZE),
    }));
  }

  function handleNextPage(maxOffset: number) {
    setPagination((state) => ({
      page: state.page + 1,
      offset: Math.min(maxOffset, state.offset + PAGE_SIZE),
    }));
  }

  return (
    <div className="cockpitSurface" data-page="research-history">
      <nav className="cockpitCrumb" aria-label="Research History 路径">
        <a href="/dashboard">Dashboard</a>
        <span aria-hidden="true">/</span>
        <span className="cockpitCrumbCurrent">Research History</span>
      </nav>

      <header className="pageHeader">
        <p className="pageEyebrow">Research History</p>
        <h2 className="pageTitle">Research Case 与 Run 历史</h2>
        <p className="pageSubtitle">
          只读列表：所有结果来自 Research API；浏览器不创建、修改或重跑任何记录。
        </p>
        <span className="cockpitReadOnlyHint" role="note">
          只读模式 · 浏览器不写入 Research 数据
        </span>
      </header>

      <section className="pageSection" aria-labelledby="history-filter-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="history-filter-title">
            视图筛选
          </h3>
          <span className="sectionMeta">
            PR-W06 · 接入 research-cases + research-runs Read API
          </span>
        </header>
        <div className="cockpitCaseSubnav" role="tablist" aria-label="History 视图">
          {HISTORY_SCOPES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={scope === item.id}
              className={
                scope === item.id
                  ? "cockpitCaseSubnavActive"
                  : "cockpitCaseSubnavLink"
              }
              onClick={() => handleScopeChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <div className="cockpitWorkspaceGrid" aria-label="Research History widgets">
        <HistoryTableWidget
          scope={scope}
          casesQuery={casesQuery}
          runsQuery={runsQuery}
          pagination={pagination}
          onPreviousPage={handlePreviousPage}
          onNextPage={handleNextPage}
        />
        <HistorySummaryWidget
          casesQuery={casesQuery}
          runsQuery={runsQuery}
        />
        <HistoryProvenanceWidget
          casesQuery={casesQuery}
          runsQuery={runsQuery}
        />
      </div>
    </div>
  );
}

type CasesQuery = ReturnType<typeof useResearchCases>;
type RunsQuery = ReturnType<typeof useResearchRuns>;

const TABLE_TITLE = "Research Case 与 Run 列表";
const TABLE_DESCRIPTION =
  "按时间倒序展示已发布的 Case / Run，附带状态与时间。";
const SUMMARY_TITLE = "Research 摘要";
const SUMMARY_DESCRIPTION =
  "最近 Case / Run 数量、当前 offset 与本地刷新时间。";
const PROVENANCE_TITLE = "数据来源";
const PROVENANCE_DESCRIPTION =
  "History 数据由 Research API 提供，浏览器仅展示。";
const TABLE_PROVENANCE =
  "Read API · /api/v1/research-cases · /api/v1/research-runs";

function HistoryTableWidget({
  scope,
  casesQuery,
  runsQuery,
  pagination,
  onPreviousPage,
  onNextPage,
}: {
  scope: HistoryScope;
  casesQuery: CasesQuery;
  runsQuery: RunsQuery;
  pagination: PaginationState;
  onPreviousPage: () => void;
  onNextPage: (maxOffset: number) => void;
}) {
  if (scope === "all") {
    return (
      <CombinedHistoryTableWidget
        casesQuery={casesQuery}
        runsQuery={runsQuery}
        pagination={pagination}
        onPreviousPage={onPreviousPage}
        onNextPage={onNextPage}
      />
    );
  }
  if (scope === "case") {
    return (
      <SingleListTableWidget
        scope={scope}
        query={casesQuery}
        isFetching={casesQuery.isFetching}
        failureLabel="无法读取 Research Case"
        pagination={pagination}
        onPreviousPage={onPreviousPage}
        onNextPage={onNextPage}
        refetchBoth={() => {
          void casesQuery.refetch();
          void runsQuery.refetch();
        }}
      />
    );
  }
  return (
    <SingleListTableWidget
      scope={scope}
      query={runsQuery}
      isFetching={runsQuery.isFetching}
      failureLabel="无法读取 Research Run"
      pagination={pagination}
      onPreviousPage={onPreviousPage}
      onNextPage={onNextPage}
      refetchBoth={() => {
        void casesQuery.refetch();
        void runsQuery.refetch();
      }}
    />
  );
}

function CombinedHistoryTableWidget({
  casesQuery,
  runsQuery,
  pagination,
  onPreviousPage,
  onNextPage,
}: {
  casesQuery: CasesQuery;
  runsQuery: RunsQuery;
  pagination: PaginationState;
  onPreviousPage: () => void;
  onNextPage: (maxOffset: number) => void;
}) {
  const pending = casesQuery.isPending || runsQuery.isPending;
  const failed = casesQuery.isError || runsQuery.isError;

  if (pending) {
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "loading",
          "wide",
          "正在加载",
        )}
      >
        <LoadingState label={`正在加载 全部 History`} />
      </WidgetFrame>
    );
  }

  if (failed) {
    const error =
      (casesQuery.error as Error | null) ?? (runsQuery.error as Error | null);
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "failed",
          "wide",
          "读取失败",
        )}
      >
        <ErrorState
          title="无法读取 Research History"
          message={describeError(error)}
          onRetry={() => {
            void casesQuery.refetch();
            void runsQuery.refetch();
          }}
        />
      </WidgetFrame>
    );
  }

  const casesData = casesQuery.data;
  const runsData = runsQuery.data;
  if (!casesData || !runsData) {
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "empty",
          "wide",
          "暂无数据",
        )}
      >
        <EmptyState title="暂无 Research History 数据" />
      </WidgetFrame>
    );
  }

  const primaryRows = casesToRows(casesData.items);
  const secondaryRows = runsToRows(runsData.items);
  const rows = sortHistoryRowsByUpdatedAt([
    ...primaryRows,
    ...secondaryRows,
  ]);

  const primaryTotal = casesData.total;
  const secondaryTotal = runsData.total;
  const combinedOffsetMax = computeCombinedOffsetMax(
    "all",
    pagination.offset,
    primaryTotal,
    secondaryTotal,
  );

  const previousDisabled = pagination.offset <= 0;
  const nextDisabled = combinedOffsetMax <= pagination.offset;
  const widgetState: ResearchWidgetMeta["state"] =
    rows.length === 0 ? "empty" : "ready";
  const isFetching = casesQuery.isFetching || runsQuery.isFetching;

  const meta = buildMeta(
    "history-table",
    TABLE_TITLE,
    TABLE_DESCRIPTION,
    isFetching ? "stale" : widgetState,
    "wide",
    rows.length === 0 ? "暂无数据" : `Page ${pagination.page + 1}`,
  );

  return (
    <WidgetFrame meta={meta}>
      <HistoryTable
        scope={"all" as HistoryScope}
        rows={rows}
        primaryTotal={primaryTotal}
        secondaryTotal={secondaryTotal}
        combinedOffsetMax={combinedOffsetMax}
        previousDisabled={previousDisabled}
        nextDisabled={nextDisabled}
        isCombined={true}
        isFetching={isFetching}
        pagination={pagination}
        onPreviousPage={onPreviousPage}
        onNextPage={() => onNextPage(combinedOffsetMax)}
      />
    </WidgetFrame>
  );
}

function SingleListTableWidget<TData extends ResearchCaseListResponse | ResearchRunListResponse>({
  scope,
  query,
  isFetching,
  failureLabel,
  pagination,
  onPreviousPage,
  onNextPage,
  refetchBoth,
}: {
  scope: HistoryScope;
  query: UseQueryResult<TData, Error>;
  isFetching: boolean;
  failureLabel: string;
  pagination: PaginationState;
  onPreviousPage: () => void;
  onNextPage: (maxOffset: number) => void;
  refetchBoth: () => void;
}) {
  if (query.isPending) {
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "loading",
          "wide",
          "正在加载",
        )}
      >
        <LoadingState label={`正在加载 ${scopeLabel(scope)} History`} />
      </WidgetFrame>
    );
  }

  if (query.isError) {
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "failed",
          "wide",
          "读取失败",
        )}
      >
        <ErrorState
          title={failureLabel}
          message={describeError(query.error)}
          onRetry={refetchBoth}
        />
      </WidgetFrame>
    );
  }

  const data = query.data;
  if (!data) {
    return (
      <WidgetFrame
        meta={buildMeta(
          "history-table",
          TABLE_TITLE,
          TABLE_DESCRIPTION,
          "empty",
          "wide",
          "暂无数据",
        )}
      >
        <EmptyState title="暂无 Research History 数据" />
      </WidgetFrame>
    );
  }

  const rows =
    scope === "case"
      ? casesToRows(data.items as ResearchCaseResponse[])
      : runsToRows(data.items as ResearchRunResponse[]);

  const combinedOffsetMax = computeCombinedOffsetMax(
    scope,
    pagination.offset,
    data.total,
    0,
  );
  const previousDisabled = pagination.offset <= 0;
  const nextDisabled = combinedOffsetMax <= pagination.offset;
  const widgetState: ResearchWidgetMeta["state"] =
    rows.length === 0 ? "empty" : "ready";

  const meta = buildMeta(
    "history-table",
    TABLE_TITLE,
    TABLE_DESCRIPTION,
    isFetching ? "stale" : widgetState,
    "wide",
    rows.length === 0 ? "暂无数据" : `Page ${pagination.page + 1}`,
  );

  return (
    <WidgetFrame meta={meta}>
      <HistoryTable
        scope={scope}
        rows={rows}
        primaryTotal={data.total}
        secondaryTotal={0}
        combinedOffsetMax={combinedOffsetMax}
        previousDisabled={previousDisabled}
        nextDisabled={nextDisabled}
        isCombined={false}
        isFetching={isFetching}
        pagination={pagination}
        onPreviousPage={onPreviousPage}
        onNextPage={() => onNextPage(combinedOffsetMax)}
      />
    </WidgetFrame>
  );
}

function HistoryTable({
  scope,
  rows,
  primaryTotal,
  secondaryTotal,
  combinedOffsetMax,
  previousDisabled,
  nextDisabled,
  isCombined,
  isFetching,
  pagination,
  onPreviousPage,
  onNextPage,
}: {
  scope: HistoryScope;
  rows: HistoryRow[];
  primaryTotal: number;
  secondaryTotal: number;
  combinedOffsetMax: number;
  previousDisabled: boolean;
  nextDisabled: boolean;
  isCombined: boolean;
  isFetching: boolean;
  pagination: PaginationState;
  onPreviousPage: () => void;
  onNextPage: () => void;
}) {
  if (rows.length === 0) {
    return <EmptyState title={`尚无 ${scopeLabel(scope)} History 数据`} />;
  }
  return (
    <div className="cockpitHistoryStack">
      <div
        className="cockpitScrollTable"
        role="region"
        aria-label={`${scopeLabel(scope)} History 列表`}
      >
        <table className="cockpitHistoryTable">
          <thead>
            <tr>
              <th scope="col">类型</th>
              <th scope="col">Case / Run</th>
              <th scope="col">对象</th>
              <th scope="col">状态</th>
              <th scope="col">更新时间</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.kind}-${row.id}`} data-history-kind={row.kind}>
                <td>
                  <span className="cockpitHistoryKind">{row.kindLabel}</span>
                </td>
                <td className="cockpitHistoryId">{row.id}</td>
                <td>{row.subject}</td>
                <td>{row.status}</td>
                <td>{row.updatedAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <HistoryPagination
        scope={scope}
        rowCount={rows.length}
        primaryTotal={primaryTotal}
        secondaryTotal={secondaryTotal}
        combinedOffsetMax={combinedOffsetMax}
        previousDisabled={previousDisabled}
        nextDisabled={nextDisabled}
        isCombined={isCombined}
        isFetching={isFetching}
        pagination={pagination}
        onPreviousPage={onPreviousPage}
        onNextPage={onNextPage}
      />
    </div>
  );
}

function HistoryPagination({
  scope,
  rowCount,
  primaryTotal,
  secondaryTotal,
  combinedOffsetMax,
  previousDisabled,
  nextDisabled,
  isCombined,
  isFetching,
  pagination,
  onPreviousPage,
  onNextPage,
}: {
  scope: HistoryScope;
  rowCount: number;
  primaryTotal: number;
  secondaryTotal: number;
  combinedOffsetMax: number;
  previousDisabled: boolean;
  nextDisabled: boolean;
  isCombined: boolean;
  isFetching: boolean;
  pagination: PaginationState;
  onPreviousPage: () => void;
  onNextPage: () => void;
}) {
  const startIndex = rowCount === 0 ? pagination.offset : pagination.offset + 1;
  const endIndex = pagination.offset + rowCount;
  const showNextLabel = combinedOffsetMax > pagination.offset + PAGE_SIZE;
  const nextOffset = Math.min(combinedOffsetMax, pagination.offset + PAGE_SIZE);
  return (
    <nav
      className="cockpitHistoryPagination"
      aria-label="Research History 分页"
    >
      <p className="cockpitHistoryPaginationMeta">
        {isCombined
          ? `显示条目 ${formatCount(startIndex)}-${formatCount(endIndex)} · 服务端 Case total ${formatCount(primaryTotal)} · Run total ${formatCount(secondaryTotal)}`
          : `显示 ${scopeLabel(scope)} 条目 ${formatCount(startIndex)}-${formatCount(endIndex)} / 共 ${formatCount(primaryTotal)} · 每次拉取 ${PAGE_SIZE} 条`}
        {isFetching ? " · 正在刷新" : ""}
      </p>
      <div className="cockpitHistoryPaginationControls">
        <button
          type="button"
          className="cockpitHistoryPaginationButton"
          onClick={onPreviousPage}
          disabled={previousDisabled}
          aria-label="上一页"
        >
          上一页
        </button>
        <span className="cockpitHistoryPaginationPosition" aria-live="polite">
          offset {formatCount(pagination.offset)} /
          next {showNextLabel ? formatCount(nextOffset) : "—"}
        </span>
        <button
          type="button"
          className="cockpitHistoryPaginationButton"
          onClick={onNextPage}
          disabled={nextDisabled}
          aria-label="下一页"
        >
          下一页
        </button>
      </div>
    </nav>
  );
}

function HistorySummaryWidget({
  casesQuery,
  runsQuery,
}: {
  casesQuery: CasesQuery;
  runsQuery: RunsQuery;
}) {
  const refreshedAt = pickRefreshedAt(casesQuery, runsQuery);
  const meta = buildMeta(
    "history-summary",
    SUMMARY_TITLE,
    SUMMARY_DESCRIPTION,
    deriveSummaryState(casesQuery, runsQuery),
    "small",
    summaryBadge(casesQuery, runsQuery),
  );
  return (
    <WidgetFrame meta={meta}>
      <dl className="cockpitKeyValueList">
        <div>
          <dt>Case 总数</dt>
          <dd>
            {casesQuery.data?.total !== undefined
              ? formatCount(casesQuery.data.total)
              : "—"}
          </dd>
        </div>
        <div>
          <dt>Run 总数</dt>
          <dd>
            {runsQuery.data?.total !== undefined
              ? formatCount(runsQuery.data.total)
              : "—"}
          </dd>
        </div>
        <div>
          <dt>页面 offset</dt>
          <dd>{formatCount(casesQuery.data?.offset ?? 0)}</dd>
        </div>
        <div>
          <dt>最近刷新</dt>
          <dd>{refreshedAt ?? "—"}</dd>
        </div>
      </dl>
    </WidgetFrame>
  );
}

function HistoryProvenanceWidget({
  casesQuery,
  runsQuery,
}: {
  casesQuery: CasesQuery;
  runsQuery: RunsQuery;
}) {
  const anyLoading = casesQuery.isPending || runsQuery.isPending;
  const anyFailed = casesQuery.isError || runsQuery.isError;
  const meta = buildMeta(
    "history-provenance",
    PROVENANCE_TITLE,
    PROVENANCE_DESCRIPTION,
    anyFailed ? "failed" : anyLoading ? "loading" : "ready",
    "small",
    anyFailed ? "读取失败" : anyLoading ? "正在加载" : "Read API",
  );
  return (
    <WidgetFrame meta={meta}>
      <p className="cockpitCaption">History 数据由 Research API 提供。</p>
      <ul className="cockpitHistoryProvenanceList">
        <li>
          <code>GET /api/v1/research-cases?limit={PAGE_SIZE}&amp;offset=</code>
          <span> → {describeQueryState(casesQuery)}</span>
        </li>
        <li>
          <code>GET /api/v1/research-runs?limit={PAGE_SIZE}&amp;offset=</code>
          <span> → {describeQueryState(runsQuery)}</span>
        </li>
      </ul>
      <p className="cockpitCaption">
        浏览器不修改 Evidence、Research Result 或 AI 判断；本页面只读。
      </p>
    </WidgetFrame>
  );
}

export interface HistoryRow {
  kind: "case" | "run";
  kindLabel: string;
  id: string;
  subject: string;
  status: string;
  updatedAt: string;
}

function casesToRows(cases: ResearchCaseResponse[]): HistoryRow[] {
  return cases.map((row) => ({
    kind: "case",
    kindLabel: "Case",
    id: row.case_id,
    subject: row.instrument_id || "—",
    status: row.status || "unknown",
    updatedAt: row.closed_at ?? row.created_at ?? "—",
  }));
}

function runsToRows(runs: ResearchRunResponse[]): HistoryRow[] {
  return runs.map((row) => ({
    kind: "run",
    kindLabel: "Run",
    id: row.run_id,
    subject: row.playbook_key || row.runner_key || "—",
    status: row.status || "unknown",
    updatedAt: row.finished_at ?? row.started_at ?? "—",
  }));
}

function scopeLabel(scope: HistoryScope): string {
  if (scope === "all") return "全部";
  if (scope === "case") return "Case";
  return "Run";
}

function buildMeta(
  id: string,
  title: string,
  description: string,
  state: ResearchWidgetMeta["state"],
  size: ResearchWidgetMeta["size"],
  badgeLabel: string,
): ResearchWidgetMeta {
  return {
    id,
    title,
    description,
    page: "dashboard",
    size,
    state,
    badgeLabel,
    provenance: TABLE_PROVENANCE,
  };
}

function deriveSummaryState(
  casesQuery: CasesQuery,
  runsQuery: RunsQuery,
): ResearchWidgetMeta["state"] {
  if (casesQuery.isPending || runsQuery.isPending) return "loading";
  if (casesQuery.isError || runsQuery.isError) return "failed";
  if (casesQuery.data || runsQuery.data) return "ready";
  return "idle";
}

function summaryBadge(
  casesQuery: CasesQuery,
  runsQuery: RunsQuery,
): string {
  if (casesQuery.isError || runsQuery.isError) return "读取失败";
  if (casesQuery.isPending || runsQuery.isPending) return "正在加载";
  if (!casesQuery.data && !runsQuery.data) return "暂无数据";
  return "已就绪";
}

function pickRefreshedAt(
  casesQuery: CasesQuery,
  runsQuery: RunsQuery,
): string | null {
  const updates = [casesQuery.dataUpdatedAt, runsQuery.dataUpdatedAt].filter(
    (value): value is number => typeof value === "number",
  );
  if (updates.length === 0) return null;
  return formatDateTime(new Date(Math.max(...updates)).toISOString());
}

function describeQueryState(query: {
  isPending: boolean;
  isError: boolean;
  data?: unknown;
}): string {
  if (query.isPending) return "正在加载";
  if (query.isError) return "读取失败";
  if (query.data) return "已就绪";
  return "Idle";
}

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status === 404) return false;
  return failureCount < 3;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.message;
  if (error instanceof Error) return error.message;
  return "未知错误";
}

export function computeCombinedOffsetMax(
  scope: HistoryScope,
  offset: number,
  primaryTotal: number,
  secondaryTotal: number,
): number {
  function lastValidOffset(total: number): number {
    if (total <= 0) return 0;
    return Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE;
  }
  if (scope === "case") {
    return Math.max(offset, lastValidOffset(primaryTotal));
  }
  if (scope === "run") {
    return Math.max(offset, lastValidOffset(primaryTotal));
  }
  return Math.max(
    offset,
    Math.max(
      lastValidOffset(primaryTotal),
      lastValidOffset(secondaryTotal),
    ),
  );
}

function parseHistoryTimestampMs(value: string): number | null {
  if (!value || value === "—") return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

function compareHistoryRowsByUpdatedAt(
  a: HistoryRow,
  b: HistoryRow,
): number {
  const aMs = parseHistoryTimestampMs(a.updatedAt);
  const bMs = parseHistoryTimestampMs(b.updatedAt);
  if (aMs !== bMs) {
    if (aMs === null) return 1;
    if (bMs === null) return -1;
    return bMs - aMs;
  }
  if (a.kind !== b.kind) {
    return a.kind < b.kind ? -1 : 1;
  }
  if (a.id < b.id) return -1;
  if (a.id > b.id) return 1;
  return 0;
}

export function sortHistoryRowsByUpdatedAt(
  rows: readonly HistoryRow[],
): HistoryRow[] {
  return [...rows].sort(compareHistoryRowsByUpdatedAt);
}
