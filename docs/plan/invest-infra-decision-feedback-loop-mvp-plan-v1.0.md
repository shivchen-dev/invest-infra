# 投研决策反馈闭环 MVP 实施计划 v1.0

> 治理状态：`DRAFT`（已制定，未激活、未授权实施）
> 制定日期：2026-09-02
> 依赖：Stage 4D Gate 3 真实链路验收、Candidate 2.0.0 lineage 可读、生产行情自然调度终验
> 替代关系：不替代现有计划；从 Stage 4D 的正式候选与研究结果向后延伸

## 1. 最小业务目标

让每个正式候选都能回答三个问题：当前应如何处理、后续表现如何、该结果对策略复盘意味着什么。

```text
正式 Candidate / ResearchResult
→ 人工确认的行动建议
→ T+5 / T+10 / T+20 前瞻观察
→ 按 StrategyVersion 聚合复盘
→ 人工决定是否另行发起策略变更
```

本计划不建设交易系统，也不把候选信号转换为自动买卖决定。

## 2. 权威边界与设计决定

1. PostgreSQL 保存结构化业务状态，是行动建议、观察结果和策略评价的唯一权威源；外部报告只作为带 hash 的来源证据。
2. `CandidatePoolItem`、`ResearchCase/ResearchResult` 和 `StrategyVersion` 继续保持现有职责。首版不引入覆盖发现、研究、交易和复盘的通用 `InvestmentCase` 聚合。
3. 行动建议必须由授权用户确认；WorkBuddy 或其他 Agent 可以形成草案和证据，但不能自行批准。
4. T+5/T+10/T+20 是从正式 `as_of` 向前观察的固定检查点，不是历史回测、收益承诺或参数寻优。
5. 观察结果绑定证券、候选、策略版本/hash、基准、价格口径和数据快照；缺数使用 `unavailable/partial/stale`，不得填零或静默换口径。
6. 策略评价只生成可审计的复盘事实，不自动调整权重、批准新策略或激活版本。

## 3. 范围

### 3.1 当前必需

- 对正式候选创建行动建议草案，并由人工确认 `observe / research / dismiss`；
- 保存理由、证据引用、触发条件、失效条件、有效期和确认人；
- 在 T+5/T+10/T+20 生成前瞻观察，记录区间收益、最大有利/不利波动、最大回撤及条件触发情况；
- 按不可变 `StrategyVersion` 聚合样本量、状态分布、收益分布、回撤和失败原因；
- 提供只读 API，并在中心投研平台展示行动、观察和复盘状态。

### 3.2 安全底线

- 候选、研究结论、行动建议、实际持仓、订单和成交/回报是不同领域事实；本 MVP 不创建或推断后三类事实；
- 所有写入具备幂等键、审计时间、主体身份和来源 hash；
- 修订采用追加记录或显式版本，不覆盖历史结论；
- 未来数据不足、停牌、除权口径不明或策略身份不一致时 fail closed；
- 单个候选结果不得自动改变整个策略评价或策略版本。

### 3.3 明确不做

- 自动买卖、下单、仓位分配或收益承诺；
- 历史回测平台、参数搜索、在线学习和自动调权；
- 年度/月度资产配置体系；
- 9 Agent 或通用工作流编排器；
- 为已有替代路径的字段继续扩充金融 MCP；
- 实际持仓纪律；该能力继续受独立 `position-discipline` 合同约束。

## 4. 依赖图

```text
Stage 4D Gate 3 + Candidate lineage + StrategyVersion
                         │
                         ▼
阶段 1：行动建议卡
                         │
                         ▼
阶段 2：前瞻结果跟踪 ── 市场数据快照/交易日历
                         │
                         ▼
阶段 3：策略复盘 ────── 中心投研只读展示
```

三个阶段必须顺序实施；前一阶段 Gate 未通过，不启动下一阶段。

## 5. 阶段 1：行动建议卡

### 任务 1.1：冻结行动建议合同

定义最小 `ActionRecommendation` 合同及关闭词汇：

- 身份：recommendation ID、candidate ID、research result ID（可空）、strategy key/version/hash；
- 内容：`observe / research / dismiss`、理由、触发条件、失效条件、有效期；
- 治理：`draft / confirmed / expired / superseded`、创建者、确认者、时间和版本；
- 证据：Evidence 或归档 artifact 的稳定引用及 hash。

**验收标准：** 候选与行动不混用；未知状态拒绝；草案不能冒充人工确认；过期和替代关系可追溯。

**预计范围：** S，合同与 ADR；不写业务代码。

### 任务 1.2：交付行动建议纵向切片

依次实现 Domain、Migration、Repository/UoW、Application Command/Query、API 和聚焦测试。Command 仅接受受控人工确认；Query 不暴露内部路径或凭据。

**验收标准：**

- 同一幂等键重复提交不产生第二条记录，内容冲突明确失败；
- 未准入候选、失配策略 hash、失效 Evidence 和越权确认均 fail closed；
- API 覆盖 create draft、confirm、supersede、get/list 及 404/409/422；
- migration upgrade/downgrade、存储 roundtrip、架构检查和 OpenAPI 检查通过。

**预计范围：** 拆成 2–3 个 M 实现任务，每个任务不超过约 5 个文件；代码按 OpenCode 实现、Codex 只读复核、ARC 最终验收。

### Gate 1：行动建议可审计

- [ ] 一条真实正式候选已生成草案并由人工确认；
- [ ] 来源 Candidate、ResearchResult、StrategyVersion 和 Evidence 可回溯；
- [ ] 草案、确认、过期和替代状态在 API 中语义分离；
- [ ] 不产生 buy/sell/order/position 等交易语义。

## 6. 阶段 2：前瞻结果跟踪

### 任务 2.1：冻结观察口径

定义 `ForwardObservation`：基准时点、目标检查点、证券和基准、已确认的 recommendation ID/version/hash、复权口径、价格来源、快照 hash、收益、最大有利/不利波动、最大回撤、条件触发结果及质量状态。

统一约定 T+n 表示正式 `as_of` 后第 n 个有效交易日；非交易日不以自然日替代。合同必须冻结交易日历 ID/version、交易所、时区、数据截止时间、基准/终点 session 与价格字段、复权因子口径/version、基准计算口径及基准快照 hash。收益和回撤使用 Decimal，并明确百分比/比例单位。

**验收标准：** 时间、单位、复权、基准和缺数语义无歧义；未来信息不能写入尚未到期的检查点。

**预计范围：** S，合同与真实行情探针。

### 任务 2.2：交付观察生成纵向切片

实现到期检查、行情读取、确定性计算、持久化和只读 API。调度只处理已到期且尚无终态观察的记录；单条失败不污染其他候选。每条观察必须绑定在基准 `as_of` 时已确认、未过期且未被替代的行动建议；草案、事后确认、过期或 superseded 建议一律 fail closed。

**验收标准：**

- T+5/T+10/T+20 到期判断使用交易日历并可复现；
- 相同输入快照重复运行得到相同 hash 和指标；
- 停牌、缺价、过期源和口径冲突分别记录 `partial/unavailable/stale/conflict`；
- 不完整记录不得进入完整样本统计。

**预计范围：** 2–3 个 M 任务；先 Domain 计算与测试，再存储/API，最后 Dagster 调度。

### Gate 2：结果观察可复现

- [ ] 至少一批在首个可用观察检查点之前完成正式登记和行动确认的真实候选，已在计划激活后自然到达一个检查点并生成观察；禁止事后纳入已知 T+n 结果的候选或补写历史结果作为 Gate 证据；
- [ ] 原始行情快照、计算输入、公式、结果和 hash 可复核；
- [ ] 重跑幂等，缺数和停牌不被表示为零收益；
- [ ] API 能区分 pending、complete、partial、unavailable、stale 和 conflict。

## 7. 阶段 3：策略复盘

### 任务 3.1：建立策略评价投影

按 `strategy_key + version + artifact_hash + observation_window` 聚合观察结果，最小输出：样本量、完整样本量、状态分布、收益中位数和分位数、最大回撤分布、触发/失效原因分布及数据截至时间。任务合同必须冻结正整数 `minimum_complete_samples` 或其版本化配置来源，并将阈值及配置版本纳入评价身份；不得使用实现默认值或运行时临时参数改变样本充足性结论。

**验收标准：**

- 不跨策略版本或 hash 合并；
- 样本不足时显示 `insufficient_sample`，不形成优劣结论；
- 单源、partial、unavailable、stale 和 conflict 样本数量分别单列；
- 聚合可从明细观察确定性重建。

**预计范围：** M，Application Query + API + 测试；首版优先读取时聚合，不预建通用指标仓库。

### 任务 3.2：接入中心投研只读窗口

在中心平台增加三个只读入口：待确认行动、到期/异常观察、策略版本复盘。页面只展示服务端 read model，不在浏览器计算业务指标。

**验收标准：**

- Candidate、Research、Action、Observation、Strategy Evaluation 状态不混用；
- loading/empty/pending/partial/unavailable/stale/conflict 状态齐全；
- 每项指标能回答来源、截至时间、样本范围和策略版本；
- 页面刷新后完全从服务端恢复，Web 测试和真实环境只读验收通过。

**预计范围：** 2 个 M 任务，先 API 聚合，再 Web 展示。

### Gate 3：反馈闭环 MVP 完成

- [ ] 至少一个真实候选贯通 Candidate → Action → ForwardObservation → StrategyEvaluation；
- [ ] 三个层次的身份、时间、来源和 hash 可完整追溯；
- [ ] 负面路径、权限、幂等、迁移、API、Web 和真实运行验收通过；
- [ ] 系统没有自动交易、自动调权或自动发布策略的入口；
- [ ] 是否发起策略变更由用户独立决策和授权。

## 8. 激活条件与停止条件

### 8.1 从 DRAFT 转为 ACTIVE 的条件

- Stage 4D Gate 3 已通过真实 WorkBuddy 两阶段候选链路验收；
- Candidate lineage 和 active StrategyVersion API 在生产环境稳定可读；
- ETF 数据层已完成一次自然调度终验；
- 用户对本计划独立授权实施；
- `docs/plan/README.md` 调整当前活动主线后再开始代码改动。

### 8.2 停止并重新评审

- 必须引入实际持仓、订单、成交或券商账户数据才能继续；
- 需要建立通用 Investment Case 或工作流编排器；
- 行情口径无法稳定支持确定性前瞻观察；
- 需要自动改变策略权重、批准或激活策略；
- 单个任务预计触及超过 5 个文件且不能继续垂直拆分。

## 9. 验证与交付规则

- 每个实现任务独立授权、实现、测试和验收，不因计划获批自动获得代码、部署或业务写入授权；
- ≥10 行代码改动由 OpenCode 增量实现，Codex 进行只读质量与负面路径复核，ARC 独立运行测试并检查工作树；
- 每个 Gate 保存可复现验收记录，包括 commit、命令、测试结果、真实实体 ID、as_of 和 hash；
- 不使用 fixture 代替最终真实链路验收；
- 不自动 commit、push、部署、启动调度或生成业务记录。

## 10. Definition of Done

- 三个 Gate 全部通过；
- 每个正式候选可以追溯行动建议、观察结果和所属策略版本评价；
- 数据质量状态不会被转换成零值或成功；
- 复盘只提供事实与统计，不形成自动投资决定；
- 中心投研平台能够只读展示完整反馈链；
- 计划、代码、数据库、API、UI 和真实验收的语义一致。
