# ADR-0015：ExternalObservation 服务端准入裁决

- 状态：Accepted
- 日期：2026-08-25
- 适用范围：Stage 4D Gate 3、ExternalObservation、Evidence、Research Case
- 相关 ADR：ADR-0014

## 1. 背景

`ExternalObservation` 是外部工作流产生的事实候选，不等于正式 Evidence。Gate 3 需要将 Observation 安全地连接到 Evidence 和 Research Case，同时避免外部客户端伪造验证结果或直接批准自身输出。

现有领域模型已经提供 `AdmissionStatus`、`AdmissionVerification` 和 `evaluate_admission`，但早期 Command API 仍接收 `identity_ok`、`freshness_ok`、`unit_ok` 等布尔字段。这些字段只能作为过渡实现，不能成为最终权威输入。

## 2. 决策

采用服务端计算准入结论：

```text
客户端命令
  → 服务端读取 Observation / Artifact / Instrument / 历史事实
  → 版本化规则执行身份、时效、口径、交叉校验和冲突检测
  → 生成 AdmissionDecision
  → 保存状态与完整审计元数据
```

服务端是准入结论的唯一权威。客户端、WorkBuddy 和浏览器不得提交或覆盖验证结论，不得直接写数据库。

## 3. 判定规则

### 3.1 确定性检查

- 身份：Observation 的 symbol/instrument、source 和 payload 身份字段必须能映射到唯一受支持标的；无法唯一映射时拒绝或进入待核验状态。
- 时效：`observed_at` 与 `as_of` 必须满足规则版本定义的新鲜度窗口；缺少时间或时区不通过。
- 口径：数值、单位、币种、定义和字段类型必须与目标 Observation contract 一致；缺失或不一致不通过。

### 3.2 事实交叉校验

- 服务端查询同源或内部历史 Observation/Evidence，比较标的、日期、单位和内容 hash。
- 不同来源对同一事实给出不可消解的不同内容时，状态为 `conflict`。
- 需要人工或后续来源补充、但没有明确冲突时，可为 `corroborated`，不能直接视为 `admitted`。
- 没有足够数据执行检查时，不得以默认值代替检查结果。

### 3.3 状态与下游门禁

- `admitted`：所有必需检查通过，允许生成 ExternalEvidenceItem。
- `rejected`：必需检查失败且不存在待核验路径，不允许生成 Evidence。
- `conflict`：存在未消解冲突，不允许生成 Evidence。
- `corroborated`：已有支持性事实但仍需完成准入条件，不允许生成正式 Evidence。
- 只有 `admitted` Observation 能创建/关联 ExternalEvidenceItem 和 Research Case。

## 4. 审计与幂等

每次最终裁决必须保存：`rules_version`、决定主体、决定时间、原因、检查明细、Observation/run 来源、Artifact/hash 引用及 `Idempotency-Key`。相同幂等键重复提交返回原裁决；不同幂等键不得覆盖终态裁决。

## 5. 迁移要求

Slice B 必须完成以下迁移：

1. 将验证器输入从客户端布尔值改为服务端 `AdmissionCheckContext`；
2. 收窄公开 Request Schema，只保留 Observation 标识、幂等键和必要操作上下文；
3. 补齐缺失数据、冲突、重复请求和终态覆盖的 API/domain 测试；
4. 更新 OpenAPI 与生成客户端；
5. 在以上验证完成前保持准入写入 feature flag 关闭。

## 6. 不在本 ADR 范围内

本 ADR 不决定投资方向、候选是否值得投资或 ResearchResult 的投研结论；这些仍按 ADR-0014 由 CIA 和正式研究流程负责。
