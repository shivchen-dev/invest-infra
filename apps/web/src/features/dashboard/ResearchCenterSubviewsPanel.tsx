import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  ResearchCenterCandidatePoolSummary,
  ResearchCenterOpportunitySummary,
  ResearchCenterResearchSummary,
  ResearchCenterResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { NavLink } from "../../router";
import { formatCount, formatDate } from "../../utils/format";

type CenterQuery = UseQueryResult<ResearchCenterResponse, Error>;

const ADMISSION_STATUS_LABELS: Record<string, string> = {
  pending: "待验证",
  corroborated: "已交叉验证",
  admitted: "已准入",
  rejected: "已拒绝",
  conflict: "冲突",
};

const ADMISSION_STATUS_ORDER: ReadonlyArray<string> = [
  "pending",
  "corroborated",
  "admitted",
  "rejected",
  "conflict",
];

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

function describeCandidatePoolState(
  summary: ResearchCenterCandidatePoolSummary,
): string {
  if (summary.state === "available") return "已发布最新候选池";
  if (summary.state === "empty") return "empty · 暂未发布候选池";
  return "failed · 候选池查询失败";
}

function describeOpportunityState(
  summary: ResearchCenterOpportunitySummary,
): string {
  if (summary.state === "available") return "已拉取外部观察";
  if (summary.state === "empty") return "empty · 暂无外部观察";
  return "failed · 外部观察查询失败";
}

function admissionStatusLabel(status: string): string {
  return ADMISSION_STATUS_LABELS[status] ?? status;
}

function CandidatePoolCard({
  summary,
}: {
  summary: ResearchCenterCandidatePoolSummary;
}) {
  const detailLink = (
    <NavLink to="/candidate-pool">查看 Candidate Pool 详情</NavLink>
  );
  if (summary.state === "empty") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="empty"
        aria-label="Candidate Pool 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Candidate Pool</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Candidate Pool 状态 empty">
          <strong>empty</strong> · 暂无已发布的候选池
        </p>
        <EmptyState
          title="Candidate Pool · empty"
          description="当前没有可展示的已发布运行。"
        />
        {detailLink}
      </article>
    );
  }
  if (summary.state === "failed") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="failed"
        aria-label="Candidate Pool 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Candidate Pool</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Candidate Pool 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Candidate Pool · failed"
          message={
            summary.reason
              ? `内部原因：${summary.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterSubviewCard"
      data-state="available"
      aria-label="Candidate Pool 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Candidate Pool</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Candidate Pool 状态 available">
        <strong>available</strong> · {describeCandidatePoolState(summary)}
      </p>
      <dl
        className="researchCenterSubviewSummary"
        aria-label="Candidate Pool 摘要指标"
      >
        <div>
          <dt>trade_date</dt>
          <dd>{formatDate(summary.trade_date)}</dd>
        </div>
        <div>
          <dt>input_row_count</dt>
          <dd>
            {formatCount(summary.input_row_count)}
            <span className="researchCenterSubviewSuffix">行</span>
          </dd>
        </div>
        <div>
          <dt>included_count</dt>
          <dd>
            {formatCount(summary.included_count)}
            <span className="researchCenterSubviewSuffix">只</span>
          </dd>
        </div>
        <div>
          <dt>excluded_count</dt>
          <dd>
            {formatCount(summary.excluded_count)}
            <span className="researchCenterSubviewSuffix">只</span>
          </dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

function OpportunityRadarCard({
  summary,
}: {
  summary: ResearchCenterOpportunitySummary;
}) {
  const detailLink = (
    <NavLink to="/opportunity-radar">查看 Opportunity Radar 详情</NavLink>
  );
  if (summary.state === "empty") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="empty"
        aria-label="Opportunity Radar 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Opportunity Radar</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Opportunity Radar 状态 empty">
          <strong>empty</strong> · 暂无外部观察
        </p>
        <EmptyState
          title="Opportunity Radar · empty"
          description="当前没有外部观察可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (summary.state === "failed") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="failed"
        aria-label="Opportunity Radar 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Opportunity Radar</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Opportunity Radar 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Opportunity Radar · failed"
          message={
            summary.reason
              ? `内部原因：${summary.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  const counts = summary.admission_status_counts ?? {};
  const orderedKeys = [
    ...ADMISSION_STATUS_ORDER.filter((key) => key in counts),
    ...Object.keys(counts).filter((key) => !ADMISSION_STATUS_ORDER.includes(key)),
  ];
  return (
    <article
      className="researchCenterSubviewCard"
      data-state="available"
      aria-label="Opportunity Radar 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Opportunity Radar</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Opportunity Radar 状态 available">
        <strong>available</strong> · {describeOpportunityState(summary)}
      </p>
      <dl
        className="researchCenterSubviewSummary"
        aria-label="Opportunity Radar 摘要指标"
      >
        <div>
          <dt>ExternalObservation count</dt>
          <dd>
            {formatCount(summary.observation_count)}
            <span className="researchCenterSubviewSuffix">条</span>
          </dd>
        </div>
        <div>
          <dt>latest_as_of</dt>
          <dd>{formatDate(summary.latest_as_of)}</dd>
        </div>
      </dl>
      <section
        aria-label="Admission status counts"
        className="researchCenterSubviewAdmission"
      >
        <h5 className="researchCenterSubviewAdmissionTitle">
          Admission status counts
        </h5>
        {orderedKeys.length === 0 ? (
          <p className="researchCenterSubviewAdmissionEmpty">
            Admission status counts 无条目
          </p>
        ) : (
          <ul className="researchCenterSubviewAdmissionList">
            {orderedKeys.map((key) => (
              <li key={key}>
                <span className="statusPill statusPillNeutral">
                  {admissionStatusLabel(key)}
                </span>
                <span className="researchCenterSubviewAdmissionCount">
                  {formatCount(counts[key])} 条
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {detailLink}
    </article>
  );
}

function ResearchCard({
  summary,
}: {
  summary: ResearchCenterResearchSummary;
}) {
  const detailLink = <NavLink to="/research/history">查看 Research 历史</NavLink>;
  if (summary.state === "empty") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="empty"
        aria-label="Research 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Research</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Research 状态 empty">
          <strong>empty</strong> · 暂无已发布的研究案例
        </p>
        <EmptyState
          title="Research · empty"
          description="当前没有已发布的研究案例可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (summary.state === "failed") {
    return (
      <article
        className="researchCenterSubviewCard"
        data-state="failed"
        aria-label="Research 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Research</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Research 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Research · failed"
          message="未在响应中返回具体原因（已受控失败）。"
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterSubviewCard"
      data-state="available"
      aria-label="Research 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Research</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Research 状态 available">
        <strong>available</strong> · 已发布研究案例可展示
      </p>
      <dl
        className="researchCenterSubviewSummary"
        aria-label="Research 摘要指标"
      >
        <div>
          <dt>case_count</dt>
          <dd>{formatCount(summary.case_count)}</dd>
        </div>
        <div>
          <dt>run_count</dt>
          <dd>{formatCount(summary.run_count)}</dd>
        </div>
        <div>
          <dt>latest_case.case_id</dt>
          <dd>{summary.latest_case?.case_id ?? "—"}</dd>
        </div>
        <div>
          <dt>latest_case.as_of_date</dt>
          <dd>{formatDate(summary.latest_case?.as_of_date)}</dd>
        </div>
        <div>
          <dt>evidence.pack_id</dt>
          <dd>{summary.evidence.pack_id ?? "—"}</dd>
        </div>
        <div>
          <dt>evidence.quality_status</dt>
          <dd>{summary.evidence.quality_status ?? "—"}</dd>
        </div>
        <div>
          <dt>evidence.freshness_status</dt>
          <dd>{summary.evidence.freshness_status ?? "—"}</dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

export function ResearchCenterSubviewsPanel({
  query,
}: {
  query: CenterQuery;
}) {
  if (query.isPending) {
    return (
      <LoadingState label="正在加载 Research Center 子视图" compact />
    );
  }
  if (query.isError) {
    return (
      <ErrorState
        title="无法读取 Research Center 子视图"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无 Research Center 子视图" />;
  }
  return (
    <div
      className="researchCenterSubviewsPanel"
      data-source="research-center"
      aria-label="Research Center 子视图摘要"
    >
      <div className="researchCenterSubviewsGrid">
        <ResearchCard summary={data.research} />
        <CandidatePoolCard summary={data.candidate_pool} />
        <OpportunityRadarCard summary={data.opportunities} />
      </div>
    </div>
  );
}
