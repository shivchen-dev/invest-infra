# invest-infra Stage 4C：日频市场状态闭环实施计划

> 文档版本：v1.1（收敛版）
> 状态：已验收，待用户关闭
> 实现基线：`7b3468d`（已推送）
> 前置：Stage 4B 的 A 股日线主备链路、Market Temperature 与既有 Market Breadth 能力

## 1. 目标与完成定义

Stage 4C 只交付一个可独立验收的能力：基于可追溯的 A 股日线事实，确定性地产出
市场宽度与涨跌停情绪快照。

4C 完成必须满足：

- Tushare 主源与 TDX fallback 的 `prev_close` 语义一致且可验证；
- 价格限制规则、版本、生效日期和未知状态有明确合同；
- `stock_price_limits` Raw/Core 事实可持久化、重放和审计；
- Market Breadth v2 与 Limit Sentiment 可从同一日频事实独立重算；
- 主源失败、数据不完整、过期或规则未知时 fail-closed，不发布伪造的 complete snapshot；
- PostgreSQL migration、round-trip、focused tests、全量回归和架构检查通过。

本阶段不要求分钟线、板块轮动、TDX GUI、财务文件或 Research Bundle 集成完成。

## 2. 当前状态

已完成：

- TDX 日线 `prev_close` 推导与边界测试；
- 版本化价格限制 Domain policy 与 fixture provider；
- Market Breadth v2 Domain、Pipeline 发布和 Asset 激活；
- Limit Sentiment Domain 合同、聚合器及 Pipeline 持久化服务。

验收证据（2026-08-13）：

- Pipeline 全量测试：`1887 passed`；
- migration / PostgreSQL 16 验证通过，包含 upgrade、rollback/upgrade 与 round-trip；
- seeded replay 验证通过，结果可确定性重放；
- Tushare/TDX 跨源 close、`prev_close` 与覆盖率一致性验证通过；
- 主源失败、数据不足、过期、partial/stale 与未知规则均遵守 fail-closed 门禁；
- Ruff、format、`git diff --check` 与工作树差异检查通过。

原计划中曾列为未完成、现已完成的 4C-MVP 项：

- `stock_price_limits` 正式 Raw/Core persistence；
- Tushare/TDX 逐日、一致性和降级检查；
- Market Breadth / Limit Sentiment 的 PostgreSQL round-trip；
- Checkpoint B：迁移升级/回滚、失败降级和 seeded replay 验收。

## 3. 收敛后的架构边界

```text
日线 Provider evidence
        ↓
stock_daily_bars + stock_price_limits（Core facts）
        ├── Market Breadth v2
        └── Limit Sentiment
                 ↓
       complete/partial observation snapshot
```

本阶段只要求 Raw provenance → Core facts → Analytics observation 这条链路。
ResearchEvidenceBundle 只保留兼容性验证，不作为 4C 的新集成面；不新增 UI、评分
算法或盘中推断。

Limit Sentiment 首批指标限定为收盘可证明的指标：涨停触及数、收盘涨停数、跌停触及数、
收盘跌停数及其覆盖/未知计数。连板、开板率、封板率必须等分钟或盘中证据完成后另立
切片，不能由收盘价推导。

## 4. 实施任务

### Task 1：冻结日频合同与规则

- [ ] 明确 `stock_price_limits` Raw/Core 字段、来源批次、规则版本和 observation identity；
- [ ] 将未知证券类别、缺失前收、停牌和过期数据定义为显式状态；
- [ ] 保持既有 Provider catalog/routing 行为不变。

验收：合同文档、规则 fixture、catalog/routing focused tests 通过。

### Task 2：建设价格限制事实持久化

- [ ] 增加 migration、repository 和 Unit of Work 接线；
- [ ] 从规范日线和版本化规则生成 `stock_price_limits`；
- [ ] 支持幂等写入、revision/provenance 和 partial 状态，不覆盖历史批次。

验收：空输入、缺失规则、重复证券、跨日和重放测试通过。

### Task 3：收口日频 Analytics

- [ ] 将 Market Breadth v2 与 Limit Sentiment 接入同一日频事实边界；
- [ ] 明确 complete/partial/stale 发布门禁；
- [ ] 固定 hash、scope、observation identity 的确定性。

验收：Domain、Pipeline、PostgreSQL round-trip 和失败降级测试通过。

### Task 4：跨源一致性与 Checkpoint B

- [ ] 对同一交易日和 universe 做 Tushare/TDX `close`、`prev_close`、覆盖率比较；
- [ ] 主源失败时验证 TDX fallback；证据不足时不得静默补值；
- [ ] 完成 migration upgrade → downgrade/rollback → upgrade 和 seeded replay。

验收：全量测试、Ruff、架构检查、`git diff --check` 和工作树审计通过。

## 5. 交付顺序与停止条件

按 Task 1 → 2 → 3 → 4 串行推进，每个任务完成后独立验证并提交。Checkpoint B
通过后，4C-MVP 即视为完成；不因后续扩展能力未实现而继续扩大本阶段。

## 6. 明确延期（独立后续项目）

- 板块字典、历史成员快照与 Block Rotation；
- `.lc1/.lc5` 分钟线、增量高水位和容量基准；
- 开板、封板、盘中动能和连板分析；
- TDX GUI 状态机、公式执行与导出解析；
- `gpcw` 财务文件 Provider；
- ResearchEvidenceBundle 新快照注册、ContextProjection 扩展；
- 北向、主力资金流、Tick、Level-2、盘口、评分、回测、交易和 Dashboard/UI。

这些项目可各自建立实施计划，不属于 4C-MVP 的未完成项，也不阻塞本阶段验收。
