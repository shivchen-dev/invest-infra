import type { CandidatePoolLatestResponse } from "../../api/types";
import { formatCount, formatDate, formatDateTime } from "../../utils/format";

export function CandidatePoolMetadata({
  pool,
}: {
  pool: CandidatePoolLatestResponse;
}) {
  const algorithmVersion = [pool.algorithm_key, pool.algorithm_version]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="pageSection" aria-labelledby="candidate-metadata-title">
      <header className="sectionHeader">
        <h3 className="sectionTitle" id="candidate-metadata-title">
          最新发布
        </h3>
        <span className="sectionMeta">交易日 {formatDate(pool.trade_date)}</span>
      </header>
      <dl className="runSummary candidatePoolMetadata">
        <div>
          <dt>交易日</dt>
          <dd>{formatDate(pool.trade_date)}</dd>
        </div>
        <div>
          <dt>Run ID</dt>
          <dd>
            <CompactIdentifier value={pool.run_id} />
          </dd>
        </div>
        <div>
          <dt>Snapshot ID</dt>
          <dd>
            <CompactIdentifier value={pool.snapshot_id} />
          </dd>
        </div>
        <div>
          <dt>算法版本</dt>
          <dd>{algorithmVersion || "—"}</dd>
        </div>
        <div>
          <dt>参数集</dt>
          <dd>{pool.parameter_set_key || "—"}</dd>
        </div>
        <div>
          <dt>输入数</dt>
          <dd>{formatCount(pool.row_count)}</dd>
        </div>
        <div>
          <dt>入选数</dt>
          <dd>{formatCount(pool.included_count)}</dd>
        </div>
        <div>
          <dt>排除数</dt>
          <dd>{formatCount(pool.excluded_count)}</dd>
        </div>
        <div>
          <dt>发布时间</dt>
          <dd>{formatDateTime(pool.published_at)}</dd>
        </div>
      </dl>
    </section>
  );
}

function CompactIdentifier({ value }: { value: string }) {
  const display = value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
  return (
    <code className="candidatePoolIdentifier" title={value || undefined}>
      {display || "—"}
    </code>
  );
}