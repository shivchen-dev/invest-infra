export function ReprocessHint() {
  return (
    <div className="operationsRerunHint">
      <p className="operationsRerunNote">
        仅作命令提示，不会触发任何写操作；请在确认网络影响后由运维执行。
      </p>
      <pre className="operationsRerunCode" aria-label="重跑命令">
        <code>{`make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1`}</code>
      </pre>
    </div>
  );
}