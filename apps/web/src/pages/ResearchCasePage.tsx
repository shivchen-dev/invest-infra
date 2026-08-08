import { useParams } from "../router";
import {
  StatusBadge,
  WidgetFrame,
  type ResearchWidgetMeta,
} from "../research-workspace/runtime";

interface CaseSection {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly placeholder: string;
  readonly bulletItems: ReadonlyArray<string>;
}

const CASE_SECTIONS: ReadonlyArray<CaseSection> = [
  {
    id: "case-overview",
    title: "Case 概览",
    description: "研究问题、对象、状态与时间线",
    placeholder: "Case 概览将由 Case Workspace API 提供。",
    bulletItems: [
      "research_case_id / research_question",
      "instrument_id / ETF 主数据引用",
      "Case 状态、最近 Run 与更新时间",
    ],
  },
  {
    id: "evidence-pack",
    title: "Evidence Pack",
    description: "只读展示的 Evidence Pack 与 provenance",
    placeholder: "Evidence Pack 列表与 content_hash 待 Read API 接入。",
    bulletItems: [
      "schema_version / content_hash / quality / freshness",
      "Evidence Item 与 provider / dataset / revision",
      "Missing Evidence 的显式表达",
    ],
  },
  {
    id: "factor-snapshot",
    title: "Factor Snapshot",
    description: "来自 Analytics 的因子观测",
    placeholder: "Factor 观测与 provenance 由 Factor Snapshot API 提供。",
    bulletItems: [
      "return / trend / volatility / drawdown",
      "algorithm_version / parameter_version / as_of",
      "缺失因子的明确原因",
    ],
  },
  {
    id: "research-result",
    title: "Research Result",
    description: "仅展示已持久化的研究结论",
    placeholder: "Stance / Confidence / Horizon 来自 Research Result，浏览器不推导。",
    bulletItems: [
      "stance / confidence / horizon",
      "result_status / result_updated_at",
      "无结论时显示“尚无研究结论”",
    ],
  },
  {
    id: "risk-monitor",
    title: "Risk Monitor",
    description: "风险因素与失效条件",
    placeholder: "Risk 解释由 Research / AI 输出，不在浏览器内重新计算。",
    bulletItems: [
      "risk_factor / risk_source / observed_at",
      "invalidation_condition / current_status",
      "关联 Evidence ID",
    ],
  },
  {
    id: "report-viewer",
    title: "Report Viewer",
    description: "只读 Markdown 报告",
    placeholder: "Markdown Report Viewer 由 Report API 接入。",
    bulletItems: [
      "服务端 Markdown / 安全渲染",
      "Evidence ID 可跳转",
      "禁止编辑并回写",
    ],
  },
];

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
    page: "research-case",
    size,
    state,
    badgeLabel,
    provenance: "Read API · 待接入",
  };
}

export function ResearchCasePage() {
  const { caseId: rawCaseId } = useParams<{ caseId: string }>();
  const caseId = decodeCaseId(rawCaseId);

  return (
    <div className="cockpitSurface" data-page="research-case">
      <CrumbBar caseId={caseId} />

      <header className="pageHeader">
        <p className="pageEyebrow">Research Case</p>
        <h2 className="pageTitle">Research Case · {caseId || "未指定"}</h2>
        <p className="pageSubtitle">
          Evidence-first 研究工作台：所有展示数据由 Research API 提供；浏览器不计算投资结论。
        </p>
        <ReadOnlyHint />
      </header>

      <CaseMetaCard caseId={caseId} />

      <section className="pageSection" aria-labelledby="case-subnav-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="case-subnav-title">
            工作区分区
          </h3>
          <span className="sectionMeta">PR-W01 视觉骨架 · 数据接入由后续 PR 提供</span>
        </header>
        <nav className="cockpitCaseSubnav" aria-label="Case 工作区导航">
          {CASE_SECTIONS.map((section) => (
            <a
              key={section.id}
              href={`#case-${section.id}`}
              className="cockpitCaseSubnavLink"
            >
              {section.title}
            </a>
          ))}
        </nav>
      </section>

      <div className="cockpitWorkspaceGrid" aria-label="Research Case widgets">
        {CASE_SECTIONS.map((section) => (
          <WidgetFrame
            key={section.id}
            meta={buildMeta(
              section.id,
              section.title,
              section.description,
              "empty",
              "medium",
              "待数据接入",
            )}
          >
            <div className="cockpitWidgetPlaceholder">
              <strong>{section.placeholder}</strong>
              <ul>
                {section.bulletItems.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </WidgetFrame>
        ))}
      </div>

      <CaseEmptyState />
    </div>
  );
}

function CrumbBar({ caseId }: { caseId: string }) {
  return (
    <nav className="cockpitCrumb" aria-label="Research Case 路径">
      <a href="/dashboard">Dashboard</a>
      <span aria-hidden="true">/</span>
      <a href="/research/history">Research History</a>
      <span aria-hidden="true">/</span>
      <span className="cockpitCrumbCurrent">Case · {caseId || "未指定"}</span>
    </nav>
  );
}

function ReadOnlyHint() {
  return (
    <span className="cockpitReadOnlyHint" role="note">
      只读模式 · 浏览器不写入 Research 数据
    </span>
  );
}

function CaseMetaCard({ caseId }: { caseId: string }) {
  return (
    <section className="pageSection" aria-labelledby="case-meta-title">
      <header className="sectionHeader">
        <h3 className="sectionTitle" id="case-meta-title">
          Case 元数据
        </h3>
        <StatusBadge tone="info">PR-W01 骨架</StatusBadge>
      </header>
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Research Case ID</dt>
          <dd>{caseId || "—"}</dd>
        </div>
        <div>
          <dt>访问模式</dt>
          <dd>只读</dd>
        </div>
        <div>
          <dt>数据接入</dt>
          <dd>待 PR-W05 接入</dd>
        </div>
        <div>
          <dt>基础状态</dt>
          <dd>
            <StatusBadge tone="neutral">Empty</StatusBadge>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function CaseEmptyState() {
  return (
    <section className="cockpitEmptyState" aria-label="Research Case 占位说明">
      <p className="cockpitEmptyStateTitle">Research Case Workspace 暂未接入数据</p>
      <p className="cockpitEmptyStateDescription">
        本页仅展示 Research Cockpit 视觉骨架与 Widget 容器。所有数据将由后续 PR 从
        <code className="inlineCode"> GET /api/v1/research-cases/{`{case_id}`}/workspace </code>
        接入；浏览器不计算 stance、confidence 或 risk。
      </p>
      <p className="cockpitEmptyStateMeta">
        容器与状态触发器已就绪 · Evidence / Factor / Result / Risk / Report 板块均为占位
      </p>
    </section>
  );
}

function decodeCaseId(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
