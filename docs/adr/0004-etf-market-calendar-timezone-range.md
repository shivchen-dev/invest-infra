# ADR-0004：ETF 市场、交易所、时区与交易日范围

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

当前 mock 数据在 `apps/pipeline/src/invest_pipeline/providers.py` 使用 `SSE` 和 `SZSE`，现有 `Instrument.exchange` 仍是任意字符串。计划文档示例也仅列出 SSE/SZSE，但没有冻结时区、交易日历版本或请求边界。日线分区若混用 UTC 日期、自然日或执行日期，将破坏幂等和重放。

## Decision

1. Phase 1 市场范围仅为**中国大陆证券交易所挂牌的场内 ETF**，交易所代码仅接受 `SSE`（上海证券交易所）和 `SZSE`（深圳证券交易所）。不包含港交所、北交所、场外基金、跨境市场本地挂牌证券或股票/指数。
2. 市场时区固定为 IANA `Asia/Shanghai`。业务 `trade_date` 是该时区的交易日日期，数据库使用 PostgreSQL `date`；采集时间、观测时间和发布时间使用 `timestamptz` 并按 UTC 存储/传输，展示时可转换为 `Asia/Shanghai`。
3. Provider symbols 必须映射到内部稳定 `instrument_id` 和规范化 `(exchange, symbol)`；同一数字代码在任何接口中不得脱离 exchange 使用。现有 `core.instruments` 以 symbol 为主键只是骨架，Phase 1 迁移必须改为 UUID 主键及交易所有关唯一约束。
4. 日行情请求区间为包含首尾的闭区间 `[start_date, end_date]`。仅对版本化交易日历中标记为开市的日期创建业务分区；周末、法定休市日不得生成 `missing` bar。
5. `start_date` 不得早于标的 `list_date`；`end_date` 不得晚于当前已完成的本地交易日。收盘完成判定由配置的市场 cutoff 控制，默认值在 Provider 契约验证后配置，M0 不猜测发布时间。
6. Phase 1 不冻结一个虚假的全历史起始日。生产回补范围为 `max(configured_backfill_start, instrument.list_date)` 到用户请求的最后完整交易日；`configured_backfill_start` 在 Provider 历史能力和候选算法 lookback 确认后由用户批准。首个 smoke slice 允许一个已完成交易日。
7. 交易日历必须作为有来源和版本的输入持久化或可精确重建，至少绑定 `calendar_key`、`calendar_version/content_hash`、exchange、date 和 open/closed。Provider 日行情返回不能单独决定某日是否为交易日。
8. SSE 与 SZSE 日历分别保存；只有在版本内容相同且显式验证后才能共用分区集合。临时休市或事后修订生成新的 calendar version，不静默覆盖曾用于运行的版本。

## Consequences

- 分区键稳定为 `YYYY-MM-DD` 本地交易日，执行时间不能替代分区。
- 数据库和领域模型需引入受限 exchange 类型、UUID instrument ID、上市日期以及版本化日历边界。
- Provider 未确认前，全历史回补起点和收盘可用 cutoff 保持待决，不阻塞 schema/contract 工作。

## Alternatives

- **用 UTC 日期作为 trade date：Rejected。** 中国市场业务日期应与交易所本地日期一致。
- **周一至周五即交易日：Rejected。** 无法处理节假日和临时休市。
- **首期包含所有市场 ETF：Rejected。** 货币、时区、日历和代码规则尚未建立。
- **现在固定一个最早历史日期：Rejected。** 仓库没有 Provider 历史覆盖或算法窗口证据。
