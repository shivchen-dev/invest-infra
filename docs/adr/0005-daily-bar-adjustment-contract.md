# ADR-0005：日行情复权口径与数据契约

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

当前仓库没有 `DailyBar` 领域对象或日行情表。计划文档列出 `none/qfq/hfq`，但候选池示例没有证明某个复权算法或供应商口径。不同来源对前复权、后复权、分红和拆分的定义可能不同；混合口径会令收益和阈值不可重放。

## Decision

1. Phase 1 的唯一可采集、标准化和供候选池使用的复权口径是 `adjustment="none"`，即 Provider 明确定义的未复权交易价格。Provider 无法证明该语义时不得进入生产。
2. `qfq` 和 `hfq` 保留为领域枚举扩展值，但 Phase 1 不生产、不回退推导、不与 `none` 混算。未来启用时必须新增 ADR，冻结公司行动数据、基准日、公式和重算策略。
3. 一行标准 `DailyBar` 必须显式包含：
   - `instrument_id: UUID`、`trade_date: date`、`adjustment: none`；
   - `open/high/low/close: Decimal`，币种由 instrument 指定，Phase 1 为 CNY；
   - `prev_close: Decimal | null`；
   - `volume: Decimal | null`、`amount: Decimal | null`，单位必须在 adapter contract 中固定为“份”和“CNY”；
   - `trading_status: normal | suspended`；
   - `source_provider`、`source_batch_id`、`observed_at`、`revision`、`row_hash`。
4. `nav`、`iopv`、`premium_rate` 不属于 Phase 1 日 OHLCV 的必需契约；即使 Provider 返回，也不得在首版候选算法中隐式使用。需要使用时另行定义时间点和单位。
5. 数值入库使用计划文档规定的 PostgreSQL `numeric` 精度；领域和哈希路径使用 `Decimal`，禁止二进制 float。Adapter 必须先按已确认单位转换，再由领域校验。
6. 合法性最低规则：价格严格大于零；`high >= max(open, close, low)`；`low <= min(open, close, high)`；volume/amount 非负。`normal` 行应有成交字段；停牌行不得伪造 OHLC 或零价格，Provider 若只返回前收盘填充值，必须在契约 fixture 中识别并映射，不得当正常成交。
7. 交易日应有但 Provider 没返回的标的不创建合成 `DailyBar`；缺失由覆盖率/质量结果表达。自然休市日也不创建 bar。
8. `row_hash` 是标准化业务内容哈希，不含 revision、source batch、observed/created 时间；包括 schema version、instrument ID、trade date、adjustment、规范化 OHLC、prev_close、volume、amount、trading status 和币种。具体序列化遵循 ADR-0007 的 canonical JSON 规则。
9. 原始 payload 字节哈希和标准 row hash 是不同证据：前者证明供应商响应，后者判断标准行内容是否变化。

## Consequences

- Phase 1 候选算法必须基于未复权数据设计并显式标注；任何依赖总回报的指标在公司行动口径冻结前不得上线。
- Provider 合同测试必须覆盖单位、停牌、缺失、非法 OHLC 和 Decimal 序列化。
- 不同 Provider 的相同标准内容可得到相同 row hash，但来源批次仍可追踪。

## Alternatives

- **默认使用前复权：Rejected。** 当前没有可审计的复权因子或供应商定义。
- **同时保存三种复权：Rejected。** 会扩大数据量并掩盖口径未确认问题。
- **用 float 入库和哈希：Rejected。** 跨运行序列化不稳定。
- **为缺失行填零：Rejected。** 会把数据缺失伪装成市场事实。
