# Stage 4D WorkBuddy 研究交付链执行清单

## P0 数据基础

- [ ] 检查 API 数据导入任务和数据库连接
- [ ] 生成一个已知 ETF 的 instruments 数据
- [ ] 生成该 ETF 的 daily-bars 数据
- [ ] 复核 data-freshness 非 `missing`

## P1 合同

- [ ] 冻结任务模板
- [ ] 冻结 `result.json` schema
- [ ] 冻结 `report.md` 模板
- [ ] 复核 `Z:\` / 宿主机映射路径
- [ ] 冻结 `strategy/candidate/research/observation` 阶段目录
- [ ] 冻结每个阶段的任务与结果合同
- [ ] 任务元数据强制包含 `stage/strategy_id/strategy_version/schema_version`
- [ ] 停止新任务写入旧单层 `inbox/results`

## P2 摄取

- [ ] 成功交付物 fixture
- [ ] partial/no-data/failed fixture
- [ ] 损坏 JSON fixture
- [ ] 重复交付物 fixture
- [ ] 验证归档、hash、幂等和重试

## P3 实际投研

- [ ] 发布已知 ETF 研究任务
- [ ] 检查 WorkBuddy 生成两个交付物
- [ ] 检查宿主机摄取
- [ ] 检查 ResearchCase / EvidencePack / ResearchRun
- [ ] 检查 ResearchResult 和 provenance

## P4 定时

- [ ] 分别配置 strategy/candidate/research/observation 取任务；strategy 默认人工触发
- [ ] 分别配置宿主机阶段结果扫描
- [ ] 连续运行两轮
- [ ] 验证重启恢复和重复幂等
- [ ] 验收通过后再启用自动开关
