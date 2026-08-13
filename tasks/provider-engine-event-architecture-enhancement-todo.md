# Provider–Engine–Event 架构增强 — Todo

## 当前状态

Phase 0 已通过，进入 Phase 1 实施。

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
- [ ] Stock Daily 单调用点迁移
- [ ] Checkpoint B 验收

## Phase 2：Stock Daily Application Engine

- [ ] command/outcome 合同
- [ ] Engine 生命周期
- [ ] Dagster Asset 迁移
- [ ] 手工入口迁移
- [ ] duplicate/failed/partial/stale/fallback 测试
- [ ] Checkpoint C 验收

## Phase 3：Provider Health

- [ ] 派生状态与 as_of 规则
- [ ] 只读 health snapshot
- [ ] Engine preflight 接线
- [ ] Checkpoint D 验收

## Phase 4：条件式批次事件

- [ ] 两消费者门禁成立，否则取消本阶段
- [ ] 最小事件合同
- [ ] 同步 run-scoped Dispatcher
- [ ] Stock Daily 单切片接线
- [ ] No-op 回滚路径
- [ ] Checkpoint E 验收

## Phase 5：最终验收

- [ ] focused/full tests
- [ ] Ruff
- [ ] 架构检查
- [ ] PostgreSQL round-trip/replay（涉及时）
- [ ] `git diff --check`
- [ ] 工作树审计
- [ ] 用户决定扩展下一个切片或关闭项目

## 永久非目标

- [ ] 不引入交易 Gateway、订单、持仓、账户或策略执行
- [ ] 不引入 vn.py 依赖或复制其代码
- [ ] 不引入消息队列、线程事件循环、微服务或新调度器
- [ ] 不扩大 Stage 4C 数据和分析范围
