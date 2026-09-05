# invest-infra 数据源治理与预采集长期计划 v0.1

> 治理状态：`DRAFT`
> 制定日期：2026-09-05
> 激活条件：Stage 4D Gate C 完成后，由用户独立授权
> 当前承接：Stage 4D 所需的近期 Dataset 来源准入仅以 `invest-infra-candidate-strategies-mvp-plan-v1.0.md` Slice 1C 为权威

## 1. 定位

本计划保存跨策略复用的数据源治理方向，不是当前派工入口。它解决长期问题：对每个生产 Dataset 明确来源、覆盖、字段语义、时点、质量、限流、成本、授权和降级路径。

当前系统已经具备 Provider Catalog/Factory、Provider routing/coverage/health、Raw Request/Attempt/Batch、TDX 股票日线 fallback、ETF/BaoStock fallback 和 WorkBuddy DataBundle。后续应复用并收敛这些能力，不重建平行平台。

## 2. 激活门槛

同时满足以下条件后，才评审是否激活：

1. Stage 4D Gate C 已完成或明确关闭；
2. 至少三个生产 Dataset 证明需要共享的限流、checkpoint 或 routing 能力；
3. 现有 Dataset 专用实现已暴露可量化的重复维护成本；
4. 首批目标 Dataset、数据许可、运行负责人和存储预算已确认；
5. 用户单独授权该计划进入 `ACTIVE`。

## 3. 长期候选能力

### 3.1 数据源治理索引

- 以 Dataset 为最小治理单位，关联内部 Provider 与外部 Connector/Tool；
- 区分声明、可构造、已接线、已探测和生产准入；
- 保存主源、fallback、交叉验证源、字段语义、`as_of`、授权和停止条件；
- 复用现有 coverage/quality/health 模型，不新建重复评分体系。

### 3.2 可复用采集策略

- 仅在多个真实 Dataset 复用需求成立后，抽取并发、QPS、`Retry-After`、退避、批次和 checkpoint；
- 继续复用 `raw.provider_requests / attempts / batches`、request key、payload hash 和幂等约束；
- fallback 必须按 Dataset 明确声明且 fail closed，不建设全局自动择源黑盒。

### 3.3 预采集数据产品

- 优先考虑低频、重复使用、时点敏感且来源已准入的数据；
- 一个 Dataset 一个垂直切片，分别冻结 Raw、Canonical 和只读消费接缝；
- WorkBuddy 只补充投研系统未覆盖的数据，不重复大批量获取已有可信数据；
- 本地客户端文件必须只读挂载，并通过完整性、更新时间和许可门禁。

### 3.4 运行观测

- 在生产采集形成稳定基线后，再增加成功率、429、延迟、新鲜度、覆盖率和 fallback 使用率观测；
- 优先复用现有 Provider health 和运行证据；没有明确处置动作的指标不建设告警；
- 凭据、Cookie、token 和敏感宿主机路径不得进入日志或报告。

## 4. 明确不做

- 不执行“大而全”的全部数据源接入；
- 不重做已完成的 TDX 股票日线或 ETF/BaoStock fallback；
- 不预建通用采集平台、通用规则引擎、消息队列或新对象存储；
- 不把可访问等同生产准入，不因字段缺失静默拼接多源；
- 不以多年历史完备度或回测数据仓库标准阻塞当前日常投研。

## 5. 未来拆分原则

激活后仍按以下顺序逐 Dataset 推进：

```text
真实需求
→ 只读探针
→ admit / research_only / reject
→ 最小预采集切片
→ 真实运行验收
→ 第三个复用案例出现后再抽取共享能力
```

每个切片必须有独立输入、输出、停止条件和验收证据；不得从本文直接恢复整套建设。
