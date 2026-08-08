import { useState } from "react";
import {
  StatusBadge,
  WidgetFrame,
  type ResearchWidgetMeta,
} from "../research-workspace/runtime";

const HISTORY_SCOPES = [
  { id: "all", label: "全部" },
  { id: "case", label: "Case" },
  { id: "run", label: "Run" },
] as const;

type HistoryScope = (typeof HISTORY_SCOPES)[number]["id"];

export function ResearchHistoryPage() {
  const [scope, setScope] = useState<HistoryScope>("all");

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
          <span className="sectionMeta">PR-W01 视觉骨架 · 数据接入由后续 PR 提供</span>
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
              onClick={() => setScope(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <div className="cockpitWorkspaceGrid" aria-label="Research History widgets">
        <WidgetFrame
          meta={buildMeta(
            "history-table",
            "Research Case 与 Run 列表",
            "按时间倒序展示已发布的 Case / Run，附带状态与时间。",
            "empty",
            "wide",
            "待数据接入",
          )}
        >
          <EmptyHistoryTable />
        </WidgetFrame>
        <WidgetFrame
          meta={buildMeta(
            "history-summary",
            "Research 摘要",
            "最近 Case / Run 数量与刷新时间。",
            "empty",
            "small",
            "待数据接入",
          )}
        >
          <SummaryEmptyState />
        </WidgetFrame>
        <WidgetFrame
          meta={buildMeta(
            "history-provenance",
            "数据来源",
            "History 数据由 Research API 提供，浏览器仅展示。",
            "idle",
            "small",
            "Idle",
          )}
        >
          <p className="cockpitCaption">
            所有 Case / Run 记录来自 Research API；浏览器不修改 Evidence、Research Result 或 AI 判断。
          </p>
        </WidgetFrame>
      </div>
    </div>
  );
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
    provenance: "Read API · 待接入",
  };
}

function EmptyHistoryTable() {
  return (
    <div className="cockpitScrollTable" role="region" aria-label="History 列表占位">
      <table className="cockpitHistoryTable">
        <thead>
          <tr>
            <th scope="col">Case / Run</th>
            <th scope="col">对象</th>
            <th scope="col">状态</th>
            <th scope="col">更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={4}>
              <div className="cockpitWidgetPlaceholder">
                <strong>尚无 Research History 数据</strong>
                <ul>
                  <li>后续 PR 将从 Research History API 拉取 Case / Run 列表</li>
                  <li>当前 PR 仅提供视觉骨架与容器，不触发任何 API 调用</li>
                  <li>列表排序与分页规则以最终 API 契约为准</li>
                </ul>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function SummaryEmptyState() {
  return (
    <dl className="cockpitKeyValueList">
      <div>
        <dt>Case 总数</dt>
        <dd>—</dd>
      </div>
      <div>
        <dt>Run 总数</dt>
        <dd>—</dd>
      </div>
      <div>
        <dt>最近刷新</dt>
        <dd>—</dd>
      </div>
    </dl>
  );
}
