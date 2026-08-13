# WorkBuddy 候选线索入口 MVP 执行清单

> 当前状态：业务定位已收缩；生产规则 2.0.0 和候选入口 M0 合同已冻结；代码尚未按新合同实施。

## 已完成：合同收缩

- [x] WorkBuddy 重新定位为候选线索生产者
- [x] 生产端必需产物收缩为单一 candidates JSON
- [x] 必需字段收缩为 run 身份、策略身份、status、symbol 和 reason
- [x] 评分、排名、阶段、source refs、Markdown、quality report 降为可选
- [x] legacy 三件套严格审计与候选入口分离
- [x] 冻结 `WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md`

## 待实施：M1 适配与校验

- [ ] Candidate Intake DTO / finding 模型
- [ ] 2.0.0 candidates JSON parser
- [ ] 1.1.1 / 1.1.2 三件套 candidate extractor
- [ ] run-level 轻量校验
- [ ] item-level 错误隔离
- [ ] 标准化 intake result

## 待实施：M2 归档与候选池

- [ ] 原始候选 artifact 不可变归档
- [ ] run 幂等与内容冲突保护
- [ ] symbol resolution
- [ ] `(trade_date, strategy_id, normalized_symbol)` 业务去重
- [ ] 无法映射项 `needs_symbol_resolution`
- [ ] 候选池投影

## 待验收：M3

- [ ] 现有 1.1.1 真实样本候选可提取
- [ ] 2.0.0 最小样本可导入
- [ ] 评分不可复算、ranking 缺失、source refs 不完整不阻断
- [ ] 单项拒绝不阻断同批其他项
- [ ] 重复导入幂等，冲突不覆盖
- [ ] focused tests 和 Pipeline 回归通过

## Legacy 能力

- [x] `workbuddy_reports` 严格报告审计代码保留
- [x] 明确 legacy 审计不是候选入池前置
- [ ] 代码和 CLI 命名中增加 legacy/audit 语义（待实施时处理）
