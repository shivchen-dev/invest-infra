# Stage 4C Core Data Layer Integration — Todo

## Phase 0：合同与可行性

- [ ] 冻结 dataset、capability、Provider key 与 owner
- [ ] 冻结 raw/core/analytics schema、hash、quality、freshness 合同
- [ ] 完成 `.lc1/.lc5`、block、gpcw 真实样本 Spike
- [ ] 完成 `mootdx` 采用方式 ADR 与 MIT notice 策略
- [ ] 生成覆盖率、历史深度、缺口率和容量基线
- [ ] Checkpoint A：人工审核合同、ADR、样本和覆盖阈值

## Phase 1：日频市场状态

- [ ] 补齐 TDX `prev_close` 语义和边界测试
- [ ] 冻结 A 股价格限制规则与版本
- [ ] 建设 `stock_price_limits` Raw/Core 事实
- [ ] 扩展 Market Breadth v2
- [ ] 发布 Limit Sentiment 日频观察
- [ ] 完成 Tushare/TDX 一致性检查
- [ ] Checkpoint B：日频闭环、迁移和降级验证

## Phase 2：板块轮动

- [ ] 建设 `tdx_local_block` Provider
- [ ] 建设板块字典与成员 snapshot persistence
- [ ] 实现 snapshot diff、改名和删除语义
- [ ] 生成行业/概念日频聚合
- [ ] 发布 Block Rotation 观察
- [ ] 增加历史穿越防护
- [ ] Checkpoint C：轮动事实追溯与覆盖降级验证

## Phase 3：分钟行情

- [ ] 实现 `.lc1/.lc5` 窄 reader 与 golden tests
- [ ] 建设 `tdx_offline_minute` Provider
- [ ] 建设分钟 persistence、分区与增量高水位
- [ ] 实现 revision、缺口和乱序检测
- [ ] 建设开板/封板/分钟成交动能证据
- [ ] 完成容量和性能基准
- [ ] Checkpoint D：分钟回放、存储预算与盘中证据验证

## Phase 4：TDX GUI 原生分析

- [ ] 冻结白名单公式、参数、universe 与客户端版本合同
- [ ] 实现启动/登录/刷新/执行/导出/解析状态机
- [ ] 固化 ASCII 文件名、GB18030、Tab/schema 契约
- [ ] 建设 `tdx_gui_analysis` Raw/Core 链路
- [ ] 实现命中数、行数、schema、hash 一致性门禁
- [ ] 完成一个白名单公式无人值守 E2E
- [ ] Checkpoint E：故障注入、不污染 Core、现有实例隔离

## Phase 5：Research 与验收

- [ ] 注册 complete Analytics snapshot 到 ResearchEvidenceBundle
- [ ] 扩展 ContextProjection 和 Evidence ID 校验
- [ ] 保持旧 EvidencePack/ResearchRun 兼容
- [ ] 完成 seeded Case 全链路回放
- [ ] 完成主源失败、损坏文件和 GUI 漂移降级验收
- [ ] 生成 coverage、capacity、license 和 Stage 4C acceptance report
- [ ] Final：ARC 独立检查、全量测试、工作树审计、用户审核

## 明确不在本清单

- Dashboard/UI
- 北向/主力资金流
- Tick/Level-2/盘口
- 私有行情协议生产化
- 历史板块成员回填
- 多公式批量运行、投资评分、回测和交易
