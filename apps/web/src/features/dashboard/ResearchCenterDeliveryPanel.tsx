import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type {
  ResearchCenterDelivery,
  ResearchCenterDeliveryArchive,
  ResearchCenterDeliveryIntegration,
  ResearchCenterDeliveryPipeline,
  ResearchCenterDeliveryResearchRuns,
  ResearchCenterResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { LoadingState } from "../../components/LoadingState";
import { NavLink } from "../../router";
import { formatCount, formatDate, formatDateTime } from "../../utils/format";

type CenterQuery = UseQueryResult<ResearchCenterResponse, Error>;

const PIPELINE_STATE_LABELS: Record<
  ResearchCenterDeliveryPipeline["state"],
  string
> = {
  available: "available · 已完成最新一次 Pipeline",
  empty: "empty · 尚无 Pipeline 运行",
  running: "running · Pipeline 在飞",
  partial: "partial · 部分结果已落地",
  failed: "failed · Pipeline 查询失败",
};

const INTEGRATION_STATE_LABELS: Record<
  ResearchCenterDeliveryIntegration["state"],
  string
> = {
  available: "available · 外部工作流健康度可展示",
  empty: "empty · 尚无外部运行",
  failed: "failed · 外部工作流查询失败",
};

const ARCHIVE_STATE_LABELS: Record<
  ResearchCenterDeliveryArchive["state"],
  string
> = {
  available: "available · 已记录最新归档",
  empty: "empty · 尚无归档产物",
  failed: "failed · 归档查询失败",
};

const RESEARCH_RUNS_STATE_LABELS: Record<
  ResearchCenterDeliveryResearchRuns["state"],
  string
> = {
  available: "available · 已观测 Research Run",
  empty: "empty · 尚无 Research Run",
  failed: "failed · Research Run 查询失败",
};

const INTEGRATION_STATUS_LABELS: Record<string, string> = {
  healthy: "healthy · 外部工作流整体健康",
  degraded: "degraded · 外部工作流存在退化",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "未知错误";
}

function integrationStatusLabel(status: string | null): string {
  if (status === null) return "—";
  return INTEGRATION_STATUS_LABELS[status] ?? status;
}

function PipelineCard({
  pipeline,
}: {
  pipeline: ResearchCenterDeliveryPipeline;
}) {
  const detailLink = (
    <NavLink to="/operations">查看 Pipeline 运行详情</NavLink>
  );
  if (pipeline.state === "empty") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="empty"
        aria-label="Pipeline 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Pipeline</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Pipeline 状态 empty">
          <strong>empty</strong> · 尚无 Pipeline 运行
        </p>
        <EmptyState
          title="Pipeline · empty"
          description="当前没有 Pipeline 运行可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (pipeline.state === "failed") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="failed"
        aria-label="Pipeline 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Pipeline</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Pipeline 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Pipeline · failed"
          message={
            pipeline.reason
              ? `内部原因：${pipeline.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterDeliveryCard"
      data-state={pipeline.state}
      aria-label="Pipeline 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Pipeline</h4>
        <span className="sectionMeta">{pipeline.state}</span>
      </header>
      <p role="status" aria-label={`Pipeline 状态 ${pipeline.state}`}>
        <strong>{pipeline.state}</strong> ·{" "}
        {PIPELINE_STATE_LABELS[pipeline.state]}
      </p>
      <dl
        className="researchCenterDeliverySummary"
        aria-label="Pipeline 摘要指标"
      >
        <div>
          <dt>status</dt>
          <dd>
            <span className="statusPill statusPillNeutral">
              {pipeline.status ?? "—"}
            </span>
          </dd>
        </div>
        <div>
          <dt>started_at</dt>
          <dd>{formatDateTime(pipeline.started_at)}</dd>
        </div>
        <div>
          <dt>finished_at</dt>
          <dd>{formatDateTime(pipeline.finished_at)}</dd>
        </div>
        <div>
          <dt>business_completion_date</dt>
          <dd>{formatDate(pipeline.business_completion_date)}</dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

function IntegrationCard({
  integration,
}: {
  integration: ResearchCenterDeliveryIntegration;
}) {
  const detailLink = (
    <NavLink to="/automation">查看 Integration Health 详情</NavLink>
  );
  if (integration.state === "empty") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="empty"
        aria-label="Integration Health 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Integration Health</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Integration Health 状态 empty">
          <strong>empty</strong> · 尚无外部运行
        </p>
        <EmptyState
          title="Integration Health · empty"
          description="当前没有外部运行可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (integration.state === "failed") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="failed"
        aria-label="Integration Health 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Integration Health</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Integration Health 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Integration Health · failed"
          message={
            integration.reason
              ? `内部原因：${integration.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterDeliveryCard"
      data-state="available"
      aria-label="Integration Health 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Integration Health</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Integration Health 状态 available">
        <strong>available</strong> ·{" "}
        {INTEGRATION_STATE_LABELS[integration.state]}
      </p>
      <dl
        className="researchCenterDeliverySummary"
        aria-label="Integration Health 摘要指标"
      >
        <div>
          <dt>status</dt>
          <dd>
            <span className="statusPill statusPillNeutral">
              {integrationStatusLabel(integration.status)}
            </span>
          </dd>
        </div>
        <div>
          <dt>sample_size</dt>
          <dd>{formatCount(integration.sample_size)}</dd>
        </div>
        <div>
          <dt>latest_as_of</dt>
          <dd>{formatDate(integration.latest_as_of)}</dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

function ArchiveCard({
  archive,
}: {
  archive: ResearchCenterDeliveryArchive;
}) {
  const detailLink = (
    <NavLink to="/automation">查看 Archive 详情</NavLink>
  );
  if (archive.state === "empty") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="empty"
        aria-label="Archive 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Archive</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Archive 状态 empty">
          <strong>empty</strong> · 尚无归档产物
        </p>
        <EmptyState
          title="Archive · empty"
          description="当前没有归档产物可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (archive.state === "failed") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="failed"
        aria-label="Archive 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Archive</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Archive 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Archive · failed"
          message={
            archive.reason
              ? `内部原因：${archive.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterDeliveryCard"
      data-state="available"
      aria-label="Archive 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Archive</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Archive 状态 available">
        <strong>available</strong> · {ARCHIVE_STATE_LABELS[archive.state]}
      </p>
      <dl
        className="researchCenterDeliverySummary"
        aria-label="Archive 摘要指标"
      >
        <div>
          <dt>artifact_count</dt>
          <dd>{formatCount(archive.artifact_count)}</dd>
        </div>
        <div>
          <dt>latest_run_status</dt>
          <dd>{archive.latest_run_status ?? "—"}</dd>
        </div>
        <div>
          <dt>latest_as_of</dt>
          <dd>{formatDate(archive.latest_as_of)}</dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

function ResearchRunsCard({
  researchRuns,
}: {
  researchRuns: ResearchCenterDeliveryResearchRuns;
}) {
  const detailLink = (
    <NavLink to="/research/history">查看 Research Run 历史</NavLink>
  );
  if (researchRuns.state === "empty") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="empty"
        aria-label="Research Runs 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Research Runs</h4>
          <span className="sectionMeta">empty</span>
        </header>
        <p role="status" aria-label="Research Runs 状态 empty">
          <strong>empty</strong> · 尚无 Research Run
        </p>
        <EmptyState
          title="Research Runs · empty"
          description="当前没有 Research Run 可展示。"
        />
        {detailLink}
      </article>
    );
  }
  if (researchRuns.state === "failed") {
    return (
      <article
        className="researchCenterDeliveryCard"
        data-state="failed"
        aria-label="Research Runs 只读摘要"
      >
        <header className="sectionHeader">
          <h4 className="sectionTitle">Research Runs</h4>
          <span className="sectionMeta">failed</span>
        </header>
        <p role="status" aria-label="Research Runs 状态 failed">
          <strong>failed</strong> · 受控查询失败
        </p>
        <ErrorState
          title="Research Runs · failed"
          message={
            researchRuns.reason
              ? `内部原因：${researchRuns.reason}`
              : "未在响应中返回具体原因（已受控失败）。"
          }
        />
        {detailLink}
      </article>
    );
  }
  return (
    <article
      className="researchCenterDeliveryCard"
      data-state="available"
      aria-label="Research Runs 只读摘要"
    >
      <header className="sectionHeader">
        <h4 className="sectionTitle">Research Runs</h4>
        <span className="sectionMeta">available</span>
      </header>
      <p role="status" aria-label="Research Runs 状态 available">
        <strong>available</strong> ·{" "}
        {RESEARCH_RUNS_STATE_LABELS[researchRuns.state]}
      </p>
      <dl
        className="researchCenterDeliverySummary"
        aria-label="Research Runs 摘要指标"
      >
        <div>
          <dt>run_count</dt>
          <dd>{formatCount(researchRuns.run_count)}</dd>
        </div>
        <div>
          <dt>latest_status</dt>
          <dd>
            <span className="statusPill statusPillNeutral">
              {researchRuns.latest_status ?? "—"}
            </span>
          </dd>
        </div>
        <div>
          <dt>latest_started_at</dt>
          <dd>{formatDateTime(researchRuns.latest_started_at)}</dd>
        </div>
        <div>
          <dt>latest_finished_at</dt>
          <dd>{formatDateTime(researchRuns.latest_finished_at)}</dd>
        </div>
      </dl>
      {detailLink}
    </article>
  );
}

export function ResearchCenterDeliveryPanel({
  query,
}: {
  query: CenterQuery;
}) {
  if (query.isPending) {
    return (
      <LoadingState label="正在加载 Research Center 交付链" compact />
    );
  }
  if (query.isError) {
    return (
      <ErrorState
        title="无法读取 Research Center 交付链"
        message={describeError(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  const data = query.data;
  if (!data) {
    return <EmptyState title="暂无 Research Center 交付链" />;
  }
  return (
    <div
      className="researchCenterDeliveryPanel"
      data-source="research-center"
      aria-label="Research Center 交付链摘要"
    >
      <div className="researchCenterDeliveryGrid">
        <PipelineCard pipeline={data.delivery.pipeline} />
        <IntegrationCard integration={data.delivery.integration} />
        <ArchiveCard archive={data.delivery.archive} />
        <ResearchRunsCard researchRuns={data.delivery.research_runs} />
      </div>
    </div>
  );
}

export type { ResearchCenterDelivery };