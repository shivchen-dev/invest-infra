# Stage 4C Core Data Layer Integration — Todo

## 4C-MVP：日频市场状态闭环

- [x] 冻结 `stock_price_limits` Raw/Core 合同、规则版本和 fail-closed 状态
- [x] 建设 `stock_price_limits` migration、repository、UoW 与发布服务
- [x] 完成幂等、revision、provenance、缺失前收和未知规则测试
- [x] 完成 TDX `prev_close` 推导与边界测试
- [x] 完成版本化价格限制 Domain policy 与 fixture provider
- [x] 完成 Market Breadth v2 Domain、Pipeline 发布与 Asset 激活
- [x] 完成 Limit Sentiment Domain 合同、聚合器与 Pipeline 持久化服务
- [x] 完成 Market Breadth / Limit Sentiment PostgreSQL round-trip
- [x] 完成 Tushare/TDX close、prev_close、覆盖率一致性检查
- [x] 完成主源失败、过期、partial/stale 的降级验证（fail-closed 门禁）
- [x] 完成 migration rollback/upgrade 与 seeded replay
- [x] Checkpoint B：全量测试、Ruff、架构检查、diff 检查、工作树审计
- [x] 用户已确认验收，4C-MVP closed

## 明确延期，不阻塞 4C-MVP

- [ ] 板块字典、成员 snapshot persistence 与 Block Rotation
- [ ] `.lc1/.lc5` 分钟线、增量、高水位、容量和性能基准
- [ ] 开板、封板、连板及盘中动能
- [ ] TDX GUI 状态机、公式白名单与导出解析
- [ ] `gpcw` 财务 Provider
- [ ] ResearchEvidenceBundle 新快照注册与 ContextProjection 扩展

## 永久不在本阶段

- Dashboard/UI、投资评分、回测、交易
- 北向、主力资金流、Tick、Level-2、盘口
- 未授权私有在线协议生产化
- 历史板块成员回填
