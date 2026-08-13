# Provider–Engine–Event 架构增强 — Todo

## 当前状态

本计划已完成 Stock Daily 垂直切片并关闭 Phase 4。后续扩展需要新的用户授权。

- [x] 完成现有代码只读架构核查
- [x] 完成 vn.py 可借鉴思想与不适用范围分析
- [x] 形成架构增强实施计划评审稿
- [x] 用户审核实施计划
- [x] 用户授权进入 Phase 0/详细设计

## Phase 0：前置门禁

- [x] Stage 4C-MVP Checkpoint B 完成
- [x] 用户确认关闭 Stage 4C-MVP
- [x] 冻结 Stock Daily 行为基线
- [x] Provider–Engine–Event ADR 通过评审

## Phase 1：Provider Runtime Registry

- [x] characterization tests
- [x] 最小 Registry
- [x] Stock Daily 单调用点迁移
- [x] Checkpoint B 验收

## Phase 2：Stock Daily Application Engine

- [x] command/outcome 合同
- [x] Engine 生命周期
- [x] Dagster Asset 迁移
- [x] 手工入口迁移（本计划明确不迁移，保留旧入口）
- [x] duplicate/failed/partial/stale/fallback 测试
- [x] Checkpoint C 验收

## Phase 3：Provider Health

- [x] 派生状态与 as_of 规则
- [x] 只读 health snapshot
- [x] Engine preflight 接线
- [x] Checkpoint D 验收

## Phase 4：条件式批次事件（已取消）

- [x] 两消费者门禁未成立，取消本阶段
- [x] 最小事件合同：不适用
- [x] 同步 run-scoped Dispatcher：不适用
- [x] Stock Daily 单切片接线：不适用
- [x] No-op 回滚路径：不适用
- [x] Checkpoint E 验收：不适用

## Phase 5：最终验收

- [x] focused/full tests
- [x] Ruff
- [x] 架构检查
- [x] PostgreSQL round-trip/replay（无 migration，判定不适用）
- [x] `git diff --check`
- [x] 工作树审计
- [x] 用户决定关闭当前计划；扩展下一个切片另行授权

## 永久非目标

- [ ] 不引入交易 Gateway、订单、持仓、账户或策略执行
- [ ] 不引入 vn.py 依赖或复制其代码
- [ ] 不引入消息队列、线程事件循环、微服务或新调度器
- [ ] 不扩大 Stage 4C 数据和分析范围
