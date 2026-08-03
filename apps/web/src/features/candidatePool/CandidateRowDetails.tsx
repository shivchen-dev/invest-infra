import type { CandidatePoolItem } from "../../api/types";
import { exclusionReasonLabel } from "./exclusionLabels";

export function CandidateRowDetails({
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