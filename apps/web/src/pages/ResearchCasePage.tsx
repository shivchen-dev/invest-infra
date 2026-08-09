import { useResearchCaseWorkspace } from "../api/researchCaseWorkspace";
import type {
  EvidencePackResponse,
  ResearchCaseWorkspaceResponse,
  ResearchResultResponse,
  ResearchRunResponse,
} from "../api/types";
import {
  StatusBadge,
  WidgetFrame,
  type ResearchWidgetMeta,
} from "../research-workspace/runtime";
import { useParams } from "../router";

interface CaseSection {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly unavailableTitle: string;
  readonly unavailableReason: string;
}

const CASE_SECTIONS: ReadonlyArray<CaseSection> = [
  {
    id: "case-overview",
    title: "Case 概览",
    description: "研究问题、对象、状态与时间线",
    unavailableTitle: "Case 概览暂未加载",
    unavailableReason: "Case 元数据来自 workspace.case；等待 Read API 返回。",
  },
  {
    id: "evidence-pack",
    title: "Evidence Pack",
    description: "只读展示的 Evidence Pack 与 provenance",
    unavailableTitle: "Evidence Pack 暂未加载",
    unavailableReason: "Evidence 列表与 content_hash 由 workspace.evidence_packs 提供。",
  },
  {
    id: "factor-snapshot",
    title: "Factor Snapshot",
    description: "来自 Analytics 的因子观测",
    unavailableTitle: "Factor Snapshot · 暂未接入",
    unavailableReason: "workspace 契约未提供 factor 字段，不在浏览器内推导。",
  },
  {
    id: "research-result",
    title: "Research Result",
    description: "仅展示已持久化的研究结论",
    unavailableTitle: "Research Result 暂未加载",
    unavailableReason: "结论来自 workspace.results（与 runs 位置一一对应）。",
  },
  {
    id: "risk-monitor",
    title: "Risk Monitor",
    description: "风险因素与失效条件",
    unavailableTitle: "Risk Monitor · 暂未接入",
    unavailableReason: "workspace 契约未提供 risk_factor 字段，不在浏览器内重新计算。",
  },
  {
    id: "report-viewer",
    title: "Report Viewer",
    description: "只读 Markdown 报告",
    unavailableTitle: "Report Viewer · 暂无报告",
    unavailableReason: "workspace.results 中没有可展示的 report_markdown。",
  },
];

const WORKSPACE_PROVENANCE =
  "Read API · GET /api/v1/research-cases/{case_id}/workspace";

export function ResearchCasePage() {
  const { caseId: rawCaseId } = useParams<{ caseId: string }>();
  const caseId = decodeCaseId(rawCaseId);
  const workspace = useResearchCaseWorkspace(caseId || null);

  return (
    <div className="cockpitSurface" data-page="research-case">
      <CrumbBar caseId={caseId} />

      <header className="pageHeader">
        <p className="pageEyebrow">Research Case</p>
        <h2 className="pageTitle">
          Research Case · {caseId || "未指定"}
        </h2>
        <p className="pageSubtitle">
          Evidence-first 研究工作台：所有展示数据由 Research API 提供；浏览器不计算投资结论。
        </p>
        <ReadOnlyHint />
      </header>

      <CaseMetaCard caseId={caseId} workspace={workspace} />

      <section className="pageSection" aria-labelledby="case-subnav-title">
        <header className="sectionHeader">
          <h3 className="sectionTitle" id="case-subnav-title">
            工作区分区
          </h3>
          <span className="sectionMeta">
            PR-W05 · Workspace Read API 已接入 · Factor / Risk 暂由后续 PR 提供
          </span>
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
          <SectionSlot
            key={section.id}
            section={section}
            caseId={caseId}
            workspace={workspace}
          />
        ))}
      </div>
    </div>
  );
}

function SectionSlot({
  section,
  caseId,
  workspace,
}: {
  section: CaseSection;
  caseId: string;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  if (section.id === "case-overview") {
    return (
      <CaseOverviewWidget
        section={section}
        caseId={caseId}
        workspace={workspace}
      />
    );
  }
  if (section.id === "evidence-pack") {
    return (
      <EvidencePackWidget section={section} workspace={workspace} />
    );
  }
  if (section.id === "research-result") {
    return (
      <ResearchResultWidget section={section} workspace={workspace} />
    );
  }
  if (section.id === "report-viewer") {
    return <ReportViewerWidget section={section} workspace={workspace} />;
  }
  return (
    <UnavailableWidget
      section={section}
      workspace={workspace}
    />
  );
}

function buildWorkspaceMeta(
  section: CaseSection,
  workspace: ReturnType<typeof useResearchCaseWorkspace>,
  overrides: Partial<ResearchWidgetMeta>,
): ResearchWidgetMeta {
  const state = resolveWorkspaceState(workspace);
  return {
    id: section.id,
    title: section.title,
    description: section.description,
    page: "research-case",
    size: "medium",
    state,
    badgeLabel: WORKSPACE_BADGE_LABELS[state],
    provenance: WORKSPACE_PROVENANCE,
    ...overrides,
  };
}

function buildUnavailableMeta(
  section: CaseSection,
  workspace: ReturnType<typeof useResearchCaseWorkspace>,
  tone: ResearchWidgetMeta["tone"] = "neutral",
): ResearchWidgetMeta {
  const state = workspace.data ? "empty" : resolveWorkspaceState(workspace);
  return {
    id: section.id,
    title: section.title,
    description: section.description,
    page: "research-case",
    size: "medium",
    state,
    tone,
    badgeLabel: workspace.data ? "暂未接入" : WORKSPACE_BADGE_LABELS[state],
    provenance: WORKSPACE_PROVENANCE,
  };
}

type WorkspaceWidgetState = ResearchWidgetMeta["state"];

const WORKSPACE_BADGE_LABELS: Record<WorkspaceWidgetState, string> = {
  loading: "正在加载",
  ready: "已就绪",
  empty: "暂无可展示数据",
  failed: "读取失败",
  idle: "等待数据",
  stale: "数据已过期",
};

function resolveWorkspaceState(
  workspace: ReturnType<typeof useResearchCaseWorkspace>,
): WorkspaceWidgetState {
  if (workspace.isPending) return "loading";
  if (workspace.isError) return "failed";
  if (!workspace.data) return "empty";
  return "ready";
}

function WorkspaceFailure({
  workspace,
}: {
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  if (!workspace.isError) return null;
  const message =
    workspace.error instanceof Error
      ? workspace.error.message
      : "无法读取 Case Workspace";
  return (
    <div className="cockpitFailureAlert" role="alert">
      <strong>无法读取 Case Workspace</strong>
      <p>{message}</p>
    </div>
  );
}

function WorkspaceLoading() {
  return (
    <div className="cockpitWidgetPlaceholder" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>正在加载 Case Workspace…</span>
    </div>
  );
}

function CaseOverviewWidget({
  section,
  caseId,
  workspace,
}: {
  section: CaseSection;
  caseId: string;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const meta = buildWorkspaceMeta(section, workspace, {
    size: "wide",
    generatedAt: workspace.data?.case.created_at ?? null,
    asOf: workspace.data?.case.as_of_date ?? null,
  });
  return (
    <WidgetFrame meta={meta}>
      <WorkspaceLoadingGate workspace={workspace}>
        {(data) => <CaseOverviewBody caseId={caseId} data={data} />}
      </WorkspaceLoadingGate>
    </WidgetFrame>
  );
}

function CaseOverviewBody({
  caseId,
  data,
}: {
  caseId: string;
  data: ResearchCaseWorkspaceResponse;
}) {
  const caseRow = data.case;
  return (
    <div className="cockpitWidgetStack">
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Research Case ID</dt>
          <dd>{caseRow.case_id || caseId || "—"}</dd>
        </div>
        <div>
          <dt>研究问题</dt>
          <dd>{caseRow.question || "—"}</dd>
        </div>
        <div>
          <dt>Instrument ID</dt>
          <dd>{caseRow.instrument_id || "—"}</dd>
        </div>
        <div>
          <dt>Horizon</dt>
          <dd>{caseRow.horizon || "—"}</dd>
        </div>
        <div>
          <dt>观察日期 (as_of)</dt>
          <dd>{caseRow.as_of_date || "—"}</dd>
        </div>
        <div>
          <dt>Case 状态</dt>
          <dd>
            <StatusBadge tone="info">{caseRow.status || "unknown"}</StatusBadge>
          </dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{caseRow.created_at || "—"}</dd>
        </div>
        <div>
          <dt>关闭时间</dt>
          <dd>{caseRow.closed_at ?? "—"}</dd>
        </div>
      </dl>
    </div>
  );
}

function EvidencePackWidget({
  section,
  workspace,
}: {
  section: CaseSection;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const meta = buildWorkspaceMeta(section, workspace, {
    badgeLabel:
      workspace.data && workspace.data.evidence_packs.length === 0
        ? "Empty"
        : undefined,
    generatedAt: pickLatestEvidenceTimestamp(workspace.data),
  });
  return (
    <WidgetFrame meta={meta}>
      <WorkspaceLoadingGate workspace={workspace}>
        {(data) => <EvidencePackBody data={data} />}
      </WorkspaceLoadingGate>
    </WidgetFrame>
  );
}

function EvidencePackBody({
  data,
}: {
  data: ResearchCaseWorkspaceResponse;
}) {
  if (data.evidence_packs.length === 0) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>暂无 Evidence Pack</strong>
        <p>本 Case 未绑定 Evidence Pack；浏览器不会自动推导 Evidence。</p>
      </div>
    );
  }
  return (
    <ul className="cockpitEvidencePackList">
      {data.evidence_packs.map((pack) => (
        <li key={pack.pack_id ?? pack.pack_hash} className="cockpitEvidencePackItem">
          <EvidencePackSummary pack={pack} />
        </li>
      ))}
    </ul>
  );
}

function EvidencePackSummary({ pack }: { pack: EvidencePackResponse }) {
  return (
    <div className="cockpitWidgetStack">
      <div className="cockpitEvidencePackHeader">
        <span className="cockpitEvidencePackHash">
          {pack.pack_hash || "—"}
        </span>
        <StatusBadge
          tone={qualityTone(pack.data_quality.quality_status)}
          title={`quality_status: ${pack.data_quality.quality_status}`}
        >
          {pack.data_quality.quality_status || "unknown"}
        </StatusBadge>
        <StatusBadge tone="neutral">
          freshness: {pack.data_quality.freshness_status || "unknown"}
        </StatusBadge>
      </div>
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Pack ID</dt>
          <dd>{pack.pack_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Schema Version</dt>
          <dd>{pack.schema_version || "—"}</dd>
        </div>
        <div>
          <dt>Factor Set</dt>
          <dd>
            {pack.factor_set_key || "—"}@{pack.factor_set_version || "—"}
          </dd>
        </div>
        <div>
          <dt>Instrument</dt>
          <dd>
            {pack.instrument.symbol} · {pack.instrument.exchange}
          </dd>
        </div>
        <div>
          <dt>Generated At</dt>
          <dd>{pack.generated_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Warnings</dt>
          <dd>{pack.warnings.length === 0 ? "—" : pack.warnings.length}</dd>
        </div>
      </dl>
    </div>
  );
}

function qualityTone(status: string): ResearchWidgetMeta["tone"] {
  if (status === "ok" || status === "complete") return "success";
  if (status === "failed" || status === "conflict") return "danger";
  if (status === "partial" || status === "stale") return "warning";
  return "neutral";
}

function ResearchResultWidget({
  section,
  workspace,
}: {
  section: CaseSection;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const hasResult =
    workspace.data?.results.some((result) => result !== null) ?? false;
  const meta = buildWorkspaceMeta(section, workspace, {
    badgeLabel: hasResult
      ? "已就绪"
      : workspace.data
        ? "Empty"
        : undefined,
  });
  return (
    <WidgetFrame meta={meta}>
      <WorkspaceLoadingGate workspace={workspace}>
        {(data) => <ResearchResultBody data={data} />}
      </WorkspaceLoadingGate>
    </WidgetFrame>
  );
}

function ReportViewerWidget({
  section,
  workspace,
}: {
  section: CaseSection;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const latestResult = pickLatestResult(workspace.data);
  const hasReport = Boolean(latestResult?.report_markdown?.trim());
  const meta = buildWorkspaceMeta(section, workspace, {
    size: "wide",
    badgeLabel: hasReport
      ? "已就绪"
      : workspace.data
        ? "Empty"
        : undefined,
    generatedAt: latestResult?.created_at ?? null,
  });
  return (
    <WidgetFrame meta={meta}>
      <WorkspaceLoadingGate workspace={workspace}>
        {(data) => <ReportViewerBody data={data} />}
      </WorkspaceLoadingGate>
    </WidgetFrame>
  );
}

function ReportViewerBody({
  data,
}: {
  data: ResearchCaseWorkspaceResponse;
}) {
  const latestResult = pickLatestResult(data);
  const reportMarkdown =
    typeof latestResult?.report_markdown === "string"
      ? latestResult.report_markdown
      : "";

  if (!reportMarkdown.trim()) {
    return (
      <div className="cockpitWidgetPlaceholder" role="status">
        <strong>暂无报告</strong>
        <p>本 Case 尚无 Result 或 Result 未提供 report_markdown。</p>
      </div>
    );
  }

  return (
    <div className="cockpitReportViewer" data-report-read-only="true">
      <p className="cockpitCaption">只读展示 · 来源于最新可用 Research Result</p>
      <pre className="cockpitReportMarkdown">{reportMarkdown}</pre>
    </div>
  );
}

function pickLatestResult(
  data: ResearchCaseWorkspaceResponse | undefined,
): ResearchResultResponse | null {
  if (!data) return null;
  for (let index = data.results.length - 1; index >= 0; index -= 1) {
    const result = data.results[index];
    if (result) return result;
  }
  return null;
}

function ResearchResultBody({
  data,
}: {
  data: ResearchCaseWorkspaceResponse;
}) {
  const pairs = data.runs.map((run, index) => ({
    run,
    result: data.results[index] ?? null,
  }));
  const anyResult = pairs.some((pair) => pair.result !== null);
  if (pairs.length === 0) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>尚无 Run 与 Result</strong>
        <p>本 Case 暂无触发的 Run；浏览器不会预先生成研究结论。</p>
      </div>
    );
  }
  return (
    <div className="cockpitWidgetStack">
      <p className="cockpitCaption">
        Run / Result 按位置配对：runs[i] ↔ results[i]，results[i] 为 null 表示该 Run 尚未发布结论。
      </p>
      {!anyResult && (
        <div className="cockpitWidgetPlaceholder">
          <strong>尚无研究结论</strong>
          <p>Runs 尚未发布 Result；浏览器不会自动推导结论。</p>
        </div>
      )}
      <ul className="cockpitRunResultList">
        {pairs.map((pair) => (
          <li key={pair.run.run_id} className="cockpitRunResultItem">
            <RunSummary run={pair.run} />
            <ResultSummary result={pair.result} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function RunSummary({ run }: { run: ResearchRunResponse }) {
  return (
    <div className="cockpitWidgetStack">
      <div className="cockpitEvidencePackHeader">
        <span className="cockpitEvidencePackHash">run · {run.run_id}</span>
        <StatusBadge
          tone={runStatusTone(run.status)}
          title={`status: ${run.status}`}
        >
          {run.status || "unknown"}
        </StatusBadge>
      </div>
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Playbook</dt>
          <dd>{run.playbook_key || "—"}</dd>
        </div>
        <div>
          <dt>Runner</dt>
          <dd>{run.runner_key || "—"}</dd>
        </div>
        <div>
          <dt>Attempt</dt>
          <dd>{run.attempt ?? "—"}</dd>
        </div>
        <div>
          <dt>Started At</dt>
          <dd>{run.started_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Finished At</dt>
          <dd>{run.finished_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Evidence Pack</dt>
          <dd>{run.evidence_pack_id || "—"}</dd>
        </div>
        {run.error_summary && (
          <div>
            <dt>Error Summary</dt>
            <dd>{run.error_summary}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function ResultSummary({
  result,
}: {
  result: ResearchResultResponse | null;
}) {
  if (!result) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>尚无 Result</strong>
        <p>该 Run 尚未发布 Result。</p>
      </div>
    );
  }
  return (
    <div className="cockpitWidgetStack">
      <div className="cockpitEvidencePackHeader">
        <span className="cockpitEvidencePackHash">
          result · {result.result_id}
        </span>
        <StatusBadge tone="info">
          adapter {result.adapter_version || "—"}
        </StatusBadge>
      </div>
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Model</dt>
          <dd>
            {result.model_key || "—"}@{result.model_version || "—"}
          </dd>
        </div>
        <div>
          <dt>Playbook Version</dt>
          <dd>{result.playbook_version || "—"}</dd>
        </div>
        <div>
          <dt>Evidence Pack</dt>
          <dd>{result.evidence_pack_id || "—"}</dd>
        </div>
        <div>
          <dt>Created At</dt>
          <dd>{result.created_at || "—"}</dd>
        </div>
        <div>
          <dt>Evidence Ids</dt>
          <dd>
            {result.evidence_ids.length === 0
              ? "—"
              : result.evidence_ids.join(", ")}
          </dd>
        </div>
        <div>
          <dt>Risks</dt>
          <dd>
            {result.risks.length === 0 ? "—" : result.risks.join("; ")}
          </dd>
        </div>
      </dl>
      <details>
        <summary>Conclusion</summary>
        <p>{result.conclusion || "—"}</p>
      </details>
    </div>
  );
}

function runStatusTone(status: string): ResearchWidgetMeta["tone"] {
  if (status === "succeeded" || status === "success") return "success";
  if (status === "failed" || status === "error") return "danger";
  if (status === "running" || status === "pending") return "info";
  if (status === "skipped" || status === "cancelled") return "warning";
  return "neutral";
}

function UnavailableWidget({
  section,
  workspace,
}: {
  section: CaseSection;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const meta = buildUnavailableMeta(section, workspace, "neutral");
  return (
    <WidgetFrame meta={meta}>
      <WorkspaceLoadingGate workspace={workspace}>
        {() => (
          <div className="cockpitWidgetPlaceholder">
            <strong>{section.unavailableTitle}</strong>
            <p>{section.unavailableReason}</p>
            <p className="cockpitWidgetPlaceholderMeta">
              当前 workspace 契约不提供该区块所需字段；浏览器不会自行推导数据。
            </p>
          </div>
        )}
      </WorkspaceLoadingGate>
    </WidgetFrame>
  );
}

function WorkspaceLoadingGate({
  workspace,
  children,
}: {
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
  children: (data: ResearchCaseWorkspaceResponse) => React.ReactNode;
}) {
  if (workspace.isPending) return <WorkspaceLoading />;
  if (workspace.isError) return <WorkspaceFailure workspace={workspace} />;
  if (!workspace.data) {
    return (
      <div className="cockpitWidgetPlaceholder">
        <strong>暂无数据</strong>
        <p>Workspace 响应为空。</p>
      </div>
    );
  }
  return <>{children(workspace.data)}</>;
}

function pickLatestEvidenceTimestamp(
  data: ResearchCaseWorkspaceResponse | undefined,
): string | null {
  if (!data) return null;
  const timestamps = data.evidence_packs
    .map((pack) => pack.generated_at)
    .filter((value): value is string => Boolean(value));
  if (timestamps.length === 0) return null;
  return timestamps.sort().slice(-1)[0] ?? null;
}

function CrumbBar({ caseId }: { caseId: string }) {
  return (
    <nav className="cockpitCrumb" aria-label="Research Case 路径">
      <a href="/dashboard">Dashboard</a>
      <span aria-hidden="true">/</span>
      <a href="/research/history">Research History</a>
      <span aria-hidden="true">/</span>
      <span className="cockpitCrumbCurrent">
        Case · {caseId || "未指定"}
      </span>
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

function CaseMetaCard({
  caseId,
  workspace,
}: {
  caseId: string;
  workspace: ReturnType<typeof useResearchCaseWorkspace>;
}) {
  const tone = caseMetaTone(workspace);
  const statusLabel = caseMetaLabel(workspace);
  return (
    <section className="pageSection" aria-labelledby="case-meta-title">
      <header className="sectionHeader">
        <h3 className="sectionTitle" id="case-meta-title">
          Case 元数据
        </h3>
        <StatusBadge tone={tone}>{statusLabel}</StatusBadge>
      </header>
      <dl className="cockpitCaseMeta">
        <div>
          <dt>Research Case ID</dt>
          <dd>{workspace.data?.case.case_id || caseId || "—"}</dd>
        </div>
        <div>
          <dt>访问模式</dt>
          <dd>只读</dd>
        </div>
        <div>
          <dt>数据接入</dt>
          <dd>PR-W05 Workspace Read API</dd>
        </div>
        <div>
          <dt>基础状态</dt>
          <dd>
            <StatusBadge tone={tone}>{statusLabel}</StatusBadge>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function caseMetaTone(
  workspace: ReturnType<typeof useResearchCaseWorkspace>,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (workspace.isError) return "danger";
  if (workspace.isPending) return "info";
  if (workspace.data) return "success";
  return "neutral";
}

function caseMetaLabel(
  workspace: ReturnType<typeof useResearchCaseWorkspace>,
): string {
  if (workspace.isPending) return "Loading";
  if (workspace.isError) return "Failed";
  if (workspace.data) return "Ready";
  return "Empty";
}

function decodeCaseId(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
