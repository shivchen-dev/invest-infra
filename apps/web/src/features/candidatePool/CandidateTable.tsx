import { Fragment, useState, type KeyboardEvent, type ReactNode } from "react";
import type { CandidatePoolItem, ExclusionReason, RuleOutcome } from "../../api/types";
import { CandidateRowDetails } from "./CandidateRowDetails";
import { exclusionReasonLabel } from "./exclusionLabels";
import { NavLink, useNavigate } from "../../router";
import { formatAmount, formatCount, formatDecimal } from "../../utils/format";

function instrumentPath(instrumentId: string): string {
  return `/etf/${encodeURIComponent(instrumentId)}`;
}

export function TableGroup({
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

export function CandidateTable({
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
                      <CandidateRowDetails item={item} id={detailId} />
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

function candidateLabel(item: CandidatePoolItem): string {
  return item.symbol ?? item.name ?? item.instrument_id;
}

function primaryExclusionReason(
  item: CandidatePoolItem,
): ExclusionReason | undefined {
  return item.exclusion_reasons[0];
}

function normalize(value: string): string {
  return value.toLocaleLowerCase();
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
