# ADR-0007：input_snapshots 精确输入绑定与哈希规则

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

计划文档中的 `analytics.input_snapshots` 只记录 query 和整体 hash，无法单独证明每一行实际使用的 revision。候选池需要当前交易日及 lookback 历史，因此仅在 snapshot parent 上保存一个 trade date 也不足以重放。

## Decision

1. `analytics.input_snapshots` 保存不可变快照头：`id`、`dataset_key`、`schema_version`、`as_of_trade_date`、`adjustment`、`calendar_key/version`、规范化 `query_definition`、`query_hash`、`row_count`、`content_sha256`、观测时间范围和 `created_at`。
2. 新增不可变明细表 `analytics.input_snapshot_rows`，每一个算法输入行情行必须保存：

   ```text
   snapshot_id
   instrument_id
   trade_date
   adjustment
   revision
   row_hash
   ```

   主键为 `(snapshot_id, instrument_id, trade_date, adjustment)`；外键 `(instrument_id, trade_date, adjustment, revision)` 精确引用 `core.daily_bars` 复合主键。`row_hash` 必须与被引用行相等，并由创建服务校验。禁止只保存日期范围或 `max(revision)`。
3. 若算法还使用 instrument 属性或其他数据集，它们也必须拥有精确版本绑定；Phase 1 在候选算法实现前需选择“版本化 instrument snapshot rows”或将实际使用的不可变 instrument 字段纳入同一 snapshot schema。仅引用可变 `core.instruments` 当前行不满足重放。
4. 快照构建在 `REPEATABLE READ` 事务中执行：解析版本化交易日历和 eligible instruments，读取所需 `core.latest_daily_bars`，验证覆盖/口径，批量插入 snapshot rows，再计算并写入头部 hash。事务提交后快照不可修改。
5. 哈希算法固定为 SHA-256，输入是 UTF-8 canonical JSON Lines：
   - 第一行是 `{"hash_schema":"input-snapshot-v1","dataset_key":...,"query":...}`；
   - 后续每行只含 `instrument_id`（小写标准 UUID 字符串）、`trade_date`（`YYYY-MM-DD`）、`adjustment`、十进制整数 `revision`、小写 64 位 hex `row_hash`；
   - key 按字典序输出，无额外空白，JSON 字符串采用 UTF-8、不得依赖 locale；
   - 明细按 `(instrument_id 字符串, trade_date, adjustment, revision)` 升序；
   - 行以 `\n` 分隔，末行也有 `\n`。
6. `query_definition` 使用同一 canonical JSON 规则：对象 key 字典序；数组保留业务顺序，集合必须先按规范值排序；日期用 ISO 8601；Decimal 用无指数、去除无意义尾零但至少保留一个整数位的字符串；禁止 NaN/Infinity、float、时间默认值和未排序 map。`query_hash` 是该 canonical JSON UTF-8 bytes 的 SHA-256。
7. `content_sha256` 覆盖 header 和所有 row bindings，因此同时绑定 query、calendar/adjustment 以及每行 revision/hash。相同定义和相同行集合必须产生相同 hash。
8. 快照头建立 `UNIQUE(dataset_key, schema_version, query_hash, content_sha256)`。并发创建相同快照时一个事务成功，另一个读取并复用已有 snapshot；不得产生语义重复快照。
9. 重放通过 snapshot rows 连接 `core.daily_bars` 的精确复合键，并重新验证 row hash 与 content hash。任何缺行或 hash 不一致都是完整性错误，禁止回退到 latest view。

## Consequences

- 快照明细会增加存储，但换取逐行 lineage 和确定性重放。
- 候选池算法输入范围（包括 lookback）必须在 query definition 中显式表达。
- 可变 instrument 主数据的版本化是候选池编码前置条件，不能被行情快照掩盖。

## Alternatives

- **只保存整体 content hash：Rejected。** 无法定位或强制加载具体 revision。
- **只保存 source batch ID：Rejected。** 一个算法输入可能跨多批次和多日。
- **重放时查询 latest view：Rejected。** 历史修订会改变结果。
- **哈希数据库查询返回顺序：Rejected。** 查询计划和 locale 可能导致不稳定。
