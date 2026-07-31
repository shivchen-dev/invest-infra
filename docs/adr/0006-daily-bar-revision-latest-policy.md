# ADR-0006：DailyBar revision、latest view 与修订策略

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

当前迁移 `apps/migrations/migrations/versions/20260730_0001_initial.py`（原 `apps/api/migrations/`，2026-07-31 迁移至独立 migration app）只创建 `core.instruments` 和孤立的 `app.pipeline_runs`，没有日行情。计划文档建议 revision 主键和 latest view，但未完全定义相同内容重采、并发分配 revision、来源变化或历史结果处理。

## Decision

1. `core.daily_bars` 使用复合主键：

   ```text
   PRIMARY KEY (instrument_id, trade_date, adjustment, revision)
   CHECK (revision >= 1)
   ```

   `instrument_id` 外键指向 `core.instruments.id`；`source_batch_id` 外键指向 `raw.provider_batches.id`。Phase 1 adjustment 仅允许 `none`。
2. 逻辑行情键是 `(instrument_id, trade_date, adjustment)`。revision 从 1 开始并在逻辑键内严格单调递增，旧 revision 永不 update/delete；修复只能 append 新 revision。
3. 标准化写入必须在 storage Unit of Work 的单个 PostgreSQL 事务内完成。每个逻辑键先获取 transaction-scoped advisory lock（锁键由带版本前缀的逻辑键稳定映射），再读取最新 revision：
   - 尚无记录：插入 revision 1；
   - 最新 `row_hash` 相同：no-op，返回已有行，不新增 revision；
   - `row_hash` 不同：插入 `latest.revision + 1`。
   唯一约束是最终并发保护；冲突必须重新读取并按同一规则判定，不得盲目重试插入。
4. 来源或 payload 改变但标准业务内容未变时不新增 revision；该次采集仍由独立 `raw.provider_batches` 保留。若需要建立“批次曾观察到该行”的多对多 lineage，应使用独立关联表，不能改写旧行的 `source_batch_id`。
5. `core.latest_daily_bars` 是只读 view，以 `row_number() over (partition by instrument_id, trade_date, adjustment order by revision desc)` 选择 `revision=最大值`。应用不得把 `created_at` 或 `observed_at` 当作 latest 判据。
6. Repository 必须提供两类显式读取：`get_latest(...)` 供新快照构建；`get_exact(..., revision)` 供重放。禁止候选池重放查询 latest view。
7. 历史修订不会自动改变既有 input snapshot、候选池运行或已发布结果。新 revision 触发质量评估；需要更新候选池时创建新 snapshot 和新 run，经验证后再发布/切换 publication pointer。
8. 删除、坏数据撤销或供应商回滚也以新 revision/显式有效性状态表达。Phase 1 不做物理删除。若确认一行无任何可信值，使用单独 invalidation 机制并阻止 latest view 暴露，必须通过后续迁移和测试明确实现，不能写零值 tombstone。
9. `row_hash` 算法版本必须存储或可由 schema version 确定；改变 canonicalization 不能静默制造行情 revision，应作为受控数据迁移处理。

## Consequences

- 写入会因每个逻辑键加锁而串行化，但不同标的/日期可并发，符合首期规模。
- 重采相同内容幂等；供应商修订保留完整历史。
- latest view 适合构造新输入，不适合历史重放；快照必须存精确 revision。
- 当前数据库模型和 Alembic 需要增量迁移，不能把现有 `pipeline_runs` 当作该能力已经存在。

## Alternatives

- **覆盖同一日期行：Rejected。** 无法审计历史候选池输入。
- **以 observed_at 作为版本：Rejected。** 并发和供应商时钟会导致不稳定排序。
- **总是为重采新增 revision：Rejected。** 相同内容重跑不幂等。
- **使用 PostgreSQL trigger 隐式分配 revision：Rejected。** 领域决策、hash 比较和测试边界不透明。
