# ADR-0008：候选池 calculated/validated/published 状态机

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

当前仓库尚无候选池模型。计划文档提出 `calculated → validated → published` 和 `rejected`，但未定义转换主体、并发发布、重新发布或默认读取。现有 `app.pipeline_runs` 仅有通用字段，见 `packages/storage/src/invest_storage/models.py`，不能视作候选池运行审计或发布机制。

业务阈值示例没有经过用户批准；M0 只能冻结数据接口、版本化和门禁边界。

## Decision

1. `analytics.candidate_pool_runs.status` 只允许 `calculated`、`validated`、`published`、`rejected`。创建 run 与全部 items 的事务完成后状态为 `calculated`；禁止先建空 run 再让 API 看见半成品。
2. 合法转换：

   ```text
   calculated -> validated
   calculated -> rejected
   validated  -> published
   validated  -> rejected
   ```

   `published` 和 `rejected` 对该 run 都是终态。不得回退或覆盖；更正必须创建新 run。
3. 每次转换以 compare-and-set SQL 在一个 Unit of Work 事务中执行（`WHERE id=? AND status=<expected>`），同时记录不可变状态事件：run ID、from/to、actor type/id、reason、quality result IDs、pipeline run ID 和时间。零行更新表示并发冲突。
4. `calculated -> validated` 只能由版本化质量策略执行。最低硬门禁是：snapshot 完整性通过、无 error 级数据质量结果、每个输入标的恰有一个 item、excluded 有原因、included 的 rank/score 完整、无 NaN/Infinity、算法/参数/输入版本非空。覆盖率、lookback、最低/最高入选数、日间漂移和投资阈值全部为**待用户批准的版本化参数**，M0 不采纳计划中的示例数字。
5. 发布在单个事务中：锁定 publication key，确认 run 为 `validated`、重新检查质量证据，转换为 `published`，写 `published_at` 和发布事件，并 upsert `analytics.candidate_pool_publications` 当前指针。
6. publication key 固定为 `(trade_date, algorithm_key, parameter_set_key)`；指针引用唯一当前 run。新版本发布可原子替换指针，旧 run 保持 `published` 作为历史并记录 `superseded_at`/事件。默认 API/Web 只通过 publication pointer 返回当前 run，并验证其 status 为 `published`；不得简单按 created_at 猜 latest。
7. 运行业务唯一性为 `(trade_date, algorithm_key, algorithm_version, parameter_hash, input_snapshot_id)`。普通重算复用已有 run；如需技术重试，记录在独立 pipeline/run-attempt 审计中，不复制相同业务结果。
8. candidate pool items 必须覆盖 snapshot 中全部 eligible instrument，每个 item 保存 included、rank/score、实际 metrics、逐规则结果和 exclusion reasons。算法核心是纯函数，显式接收 snapshot、算法版本、参数及计算上下文，不访问数据库、Provider、环境变量或当前时间。
9. `pipeline_runs`、Provider batches、snapshot、candidate run 和状态事件必须可关联，但各自职责不同。现有孤立 `app.pipeline_runs` 缺少 Dagster ID、分区、触发、配置、状态事件及外键，不能声称已完成运行审计。

## Consequences

- API 永远不会默认暴露 calculated/validated/rejected 或被新修订隐式改变的结果。
- 发布替换是原子的且保留历史；并发发布有确定赢家。
- 算法可在阈值未定前实现接口和 golden fixture 框架，但不得把示例参数当生产策略。

## Alternatives

- **计算完成即发布：Rejected。** 绕过数据质量和人工/策略门禁。
- **用一个 boolean `published`：Rejected。** 无法表达校验、拒绝和合法转换。
- **发布新 run 时把旧 run 改回 validated：Rejected。** 篡改历史状态。
- **按最大 created_at 查询 latest：Rejected。** calculated 或失败重试可能被误服务。
