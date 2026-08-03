import type { InstrumentResponse } from "../../api/types";
import { formatDate } from "../../utils/format";

interface InstrumentSummaryProps {
  instrument: InstrumentResponse;
}

export function InstrumentSummary({ instrument }: InstrumentSummaryProps) {
  return (
    <dl className="runSummary etfDetailMetadata">
      <div>
        <dt>代码</dt>
        <dd>{instrument.symbol ?? "—"}</dd>
      </div>
      <div>
        <dt>名称</dt>
        <dd>{instrument.name ?? "—"}</dd>
      </div>
      <div>
        <dt>交易所</dt>
        <dd>{instrument.exchange ?? "—"}</dd>
      </div>
      <div>
        <dt>类型</dt>
        <dd>{instrument.instrument_type ?? "—"}</dd>
      </div>
      <div>
        <dt>货币</dt>
        <dd>{instrument.currency ?? "—"}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>
          <span
            className={`statusPill ${
              instrument.is_active ? "statusPillSuccess" : "statusPillNeutral"
            }`}
          >
            {instrument.status || (instrument.is_active ? "active" : "inactive")}
          </span>
        </dd>
      </div>
      <div>
        <dt>上市日</dt>
        <dd>{formatDate(instrument.list_date)}</dd>
      </div>
      <div>
        <dt>退市日</dt>
        <dd>{formatDate(instrument.delist_date)}</dd>
      </div>
      <div>
        <dt>跟踪指数</dt>
        <dd>{instrument.underlying_index ?? "—"}</dd>
      </div>
      <div>
        <dt>分类</dt>
        <dd>{instrument.category ?? "—"}</dd>
      </div>
    </dl>
  );
}
