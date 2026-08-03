import type { KeyboardEvent } from "react";
import type { ExclusionReason } from "../../api/types";
import { formatCount } from "../../utils/format";
import { reasonFilterLabel } from "./exclusionLabels";

export type CandidateTab = "included" | "excluded" | "all";

const TABS: ReadonlyArray<{ value: CandidateTab; label: string }> = [
  { value: "included", label: "入选" },
  { value: "excluded", label: "排除" },
  { value: "all", label: "全部" },
];

type CandidateTabCounts = Record<CandidateTab, number>;

export function CandidateFilters({
  activeTab,
  onTabChange,
  tabCounts,
  search,
  onSearchChange,
  exchange,
  onExchangeChange,
  reasonCode,
  onReasonCodeChange,
  exchangeOptions,
  reasonOptions,
}: {
  activeTab: CandidateTab;
  onTabChange: (tab: CandidateTab) => void;
  tabCounts: CandidateTabCounts;
  search: string;
  onSearchChange: (value: string) => void;
  exchange: string;
  onExchangeChange: (value: string) => void;
  reasonCode: string;
  onReasonCodeChange: (value: string) => void;
  exchangeOptions: string[];
  reasonOptions: ExclusionReason[];
}) {
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
    onTabChange(TABS[nextIndex].value);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
      '[role="tab"]',
    );
    buttons?.[nextIndex]?.focus();
  };

  return (
    <>
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
              onClick={() => onTabChange(tab.value)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              {tab.label}
              <span className="candidateTabCount">{formatCount(tabCounts[tab.value])}</span>
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
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <label className="candidateFilter">
          <span>交易所</span>
          <select
            value={exchange}
            onChange={(event) => onExchangeChange(event.target.value)}
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
              onChange={(event) => onReasonCodeChange(event.target.value)}
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
    </>
  );
}

function normalize(value: string): string {
  return value.toLocaleLowerCase();
}
