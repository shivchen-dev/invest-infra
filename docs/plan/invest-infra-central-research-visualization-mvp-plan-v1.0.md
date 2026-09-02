# 中心投研可视化平台 MVP 实施计划

> 文档版本：v1.1
> 文档状态：DEFERRED（数据覆盖与 Provider 韧性 P0 收口前暂停）
> 计划治理：`docs/plan/README.md`
> 制定日期：2026-08-15
> 最近更新：2026-09-02（按计划治理暂停，原方案内容保持不变）
> 上位蓝图：`docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md`
> 既有执行基线：`docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`

## 1. 决策摘要

中心投研可视化平台不是新建第二套系统。当前因 ETF 数据覆盖与 Provider 韧性调整为 P0，本计划暂停实施；恢复时仍在现有 React Web、FastAPI 只读查询、Research Dashboard、Opportunity Radar、Automation Center 和市场观察数据之上建立统一的投研入口。

平台服务于以下长期研究循环：

```text
真实市场数据与来源
→ 市场观察
→ 候选与研究判断
→ 策略版本迭代
→ 持仓纪律检查
→ 周期复盘
→ 保留、修订或废止研究假设
```

MVP 的职责是展示事实、时点、来源、状态、缺口和纪律偏离，不证明收益，不自动生成交易决定。

## 2. 产品定位

### 2.1 核心目标

- 一屏回答“市场现在怎样、正在研究什么、策略为何变化、持仓纪律是否偏离、数据是否可信”；
- 将市场事实、当时判断和后续结果分开保存和展示，避免事后改写；
- 让每项结论可追溯到 `as_of`、来源、数据质量、研究证据和策略版本；
- 用明确空状态暴露尚未建立的能力，不用模拟数据填充页面；
- 继续保持浏览器只读，MVP 不在 Web 内新增业务写入。

### 2.2 非目标

- 回测平台、参数寻优、收益预测和策略排名；
- 自动策略批准、激活、淘汰或参数修改；
- 自动交易、下单、仓位调整和券商连接；
- 通用 BI、通用流程设计器或可拖拽 Dashboard Builder；
- 为填满页面而提前建设数据库对象；
- 将归档成功解释为研究通过、策略有效或允许持仓。

## 3. 现有能力基线

| 能力 | 现状 | MVP 处理 |
|---|---|---|
| Web Shell / 路由 / 导航 | 已有 | 重组为投研中心信息架构 |
| 数据新鲜度与 Pipeline 状态 | 已有 | 保留为全局可信度信号 |
| Candidate Pool | 已有 | 作为内部候选事实展示 |
| Opportunity Radar | 已有 | 作为外部观察与准入展示 |
| Research Dashboard / Case / History | 已有 | 提升为中心平台主要研究入口 |
| Market Breadth API | 已有只读接口 | 接入市场观察垂直切片 |
| WorkBuddy 交付与归档 | 已有文件级闭环 | 展示交付状态，不直接读取共享目录 |
| 策略迭代正式合同 | 尚未冻结 | MVP 仅展示已有可验证材料或明确空状态 |
| 实际持仓纪律合同 | 尚未冻结 | MVP 仅提供空状态与能力说明，不虚构仓位 |

## 4. 信息架构

MVP 保留现有 `/dashboard` 作为中心入口，避免并存两个首页语义。

```text
/dashboard                 中心总览
/market                    市场观察
/candidate-pool            内部候选池
/opportunity-radar         外部机会与准入
/research/history          研究历史
/research/:caseId          单项研究工作区
/strategy                  策略观察与迭代状态
/discipline                持仓纪律状态
/automation                外部交付链观测
/operations                数据运行与新鲜度
```

其中 `/strategy` 与 `/discipline` 只有在对应只读合同存在时才展示真实业务列表；合同冻结前允许显示稳定、可解释的空状态，但不得建立临时 JSON 或前端常量作为业务权威源。

## 5. 中心总览的最小问题集

中心总览只聚合足以支持当天研判的问题，不复制所有详情页：

1. 数据截至什么时间，哪些数据过期或缺失？
2. 当前市场观察有哪些可验证事实？
3. 候选、外部观察和研究事项分别处于什么状态？
4. 最近策略材料或研究判断发生了什么变化？
5. 当前是否存在持仓纪律偏离或待复核事项？
6. WorkBuddy、Research 和 Pipeline 交付链是否正常？

每个卡片必须带：

- 数据来源或只读接口；
- `as_of` / `observed_at` / `generated_at` 中适用的时间；
- freshness / quality / unavailable 状态；
- 进入对应详情页的单一链接；
- 无数据时的明确原因。

## 6. 架构设计

### 6.1 读取链路

```text
PostgreSQL / 已验证归档投影
        ↓
既有 Repository Readers
        ↓
中心投研 Read Model Module
        ↓
GET /api/v1/research-center
        ↓
Web API Client / TanStack Query
        ↓
Center Dashboard Widgets
```

`research-center` 是一个深 Module：其 Interface 返回一个版本化、只读的中心聚合结果；市场、研究、候选、纪律和集成状态的组合逻辑留在 Implementation 内，不散落到多个 React 页面。

### 6.2 Seam 与 Adapter

- 外部 Interface：单个版本化 `ResearchCenterResponse`；
- 数据读取 seam：复用现有 Reader，不让中心 Module 直接执行原始 SQL；
- Web 只依赖中心响应和既有详情接口，不感知 Repository 或共享目录；
- WorkBuddy 文件只可通过已验证归档/标准化查询 Adapter 进入视图；浏览器不得读取宿主机路径；
- 未存在第二种实现时，不为每个卡片创建假想 port。

### 6.3 数据真实性规则

- 市场值必须来自已注册的真实只读数据源；
- `unavailable`、`stale`、`partial` 是正式状态，不转换成零值；
- 外部观察、内部事实和研究判断视觉分层；
- 当时判断和后续结果使用不同字段/记录，不覆盖历史；
- 策略、纪律没有正式合同前只显示能力空状态；
- Dashboard 不计算投资结论，不以颜色暗示买卖动作。

## 7. MVP 垂直切片

### Slice 0：信息架构与合同冻结

目标：冻结页面问题集、来源映射、状态词汇和响应合同，不写业务实现。

冻结合同：`docs/implementation/RESEARCH-CENTER-SLICE0-CONTRACT.md`。

验收标准：

- 每个 Dashboard 字段都有真实来源或明确 unavailable 原因；
- 没有回测、自动交易、自动批准字段；
- `/dashboard` 是唯一中心首页；
- 策略和纪律未定义能力不被伪造。

### Slice 1：市场真实状态

目标：把已有 Market Breadth、数据新鲜度和市场日期组合为首个端到端卡片。

验收标准：

- 展示来源、观察日期、质量和 freshness；
- 404、stale、partial 和服务错误均有确定状态；
- 不再把已有市场数据一律显示为 `no market dashboard source registered`；
- API、Web focused tests 和构建通过。

### Slice 2：研究与机会工作台

目标：聚合 Research Case/Run、Candidate Pool、Opportunity Radar 和 Evidence 状态，提供统一入口但不复制详情页。

验收标准：

- 内部候选、外部观察、正式研究三类状态不混用；
- 最新研究、待处理事项和证据质量可追溯；
- 每项摘要能进入现有详情页；
- 空、部分、失败和冲突状态均可展示。

### Slice 3：交付链与数据可信度

目标：聚合 Pipeline、Integration Health、WorkBuddy 交付/归档和 Research Run 的健康状态。

验收标准：

- 文件归档、业务准入和研究完成保持不同状态；
- 不返回宿主机绝对路径或敏感信息；
- cancelled orphan 等保守状态可解释但不阻断其他卡片；
- 页面刷新后状态可恢复。

#### Slice 3 增量：Candidate 2.0.0 只读追溯

目标：在不改变 Stage 4D 业务合同的前提下，把真实 Candidate 2.0.0 从
WorkBuddy 交付、校验、归档、摄取、Admission 到 Research Timeline 的既有事实
组织为可追溯只读视图，并展示 Candidate 已持久化的策略版本与上游
StageResult 绑定。该增量属于 Slice 3 的交付链可视化，不是 Slice 4 的策略迭代窗口。

依赖关系：

```text
3B-Web 可信度与脱敏卡片
  ↓
3C-L0 真实字段盘点与合同门禁
  ↓
3C-L1 最小只读投影（仅在现有字段足够时）
  ↓
3C-L2 Candidate / Research Timeline 展示
  ↓
3C-L3 真实 Candidate 2.0.0 E2E 与 Gate B 证据
```

##### Task 3B-Web：交付可信度卡片

**说明：** 消费现有 Slice 3B API 契约，在 Dashboard 交付链卡片中展示
freshness、source、partial/failed 原因和恢复状态，不新增第二次资源请求。

**验收标准：**

- 四个 delivery 子段独立显示 loading、empty、running、succeeded、partial、failed；
- 不展示宿主机路径、凭据、原始异常或浏览器推导的业务状态；
- 刷新后完全以服务端 read model 恢复状态。

**验证：** Web focused/full tests、typecheck、production build。

**预计范围：** M，优先限制在 Dashboard 卡片、对应测试和既有类型适配层。

##### Task 3C-L0：真实字段盘点与合同门禁

**说明：** 使用首份真实 Candidate 2.0.0、数据库只读结果、Research Workspace
响应和归档元数据，逐项确认以下事实是否已经存在且可安全投影：WorkBuddy run、
Candidate identity、末阶段策略 key/version/hash、上游 StageResult run/hash、归档状态、
摄取状态、Admission 决定、Research Case/Run/Result 标识与时间。

**验收标准：**

- 每个拟展示字段均映射到一个现有权威来源，并标明 nullable/unavailable 语义；
- 明确区分交付、归档、摄取、准入和研究完成，不用单一 `success` 合并；
- 输出“现有契约足够”或字段级缺口清单，不以 fixture 或前端常量补缺。

**验证：** AgentOA 结果、不可变 artifact、数据库和现有 API 四方只读对照。

**预计范围：** S，只读探索与合同确认，不修改代码、数据库或业务数据。

**2026-08-31 门禁结论：** `INSUFFICIENT_FOR_3C_L1`。PostgreSQL 只读核验确认
现有历史/验收 Candidate 2.0.0 run、artifact 和 observation 可读，但当前正式两阶段
Candidate 尚未交付；现有合同也没有持久化 StageResult ID/hash，Admission metadata
缺少决定时间。不得在可视化层推断或补造。StageResult 缺口已回到
`invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` §4.2，按 P0-A/B 完成现有
parser 深化、摄取、只读 projection 和真实验收后再恢复本切片；Admission 时间先按
`unavailable` 展示，不与 lineage 实施捆绑。

##### Task 3C-L1：最小只读追溯投影

**说明：** 仅当 3C-L0 证明现有持久化事实足够时，在既有 Research Workspace
或一个有界只读查询 seam 中投影 Candidate lineage；复用 Reader，不直读共享目录，
不让 Web 拼接业务关系。

**验收标准：**

- Candidate 能追溯末阶段策略 key/version/hash 与上游 StageResult run/hash；
- Archive、Intake、Admission、Research 状态分别投影，缺失值明确为 unavailable；
- 响应拒绝宿主路径、artifact URI、原始 payload、凭据和未脱敏异常。

**验证：** Application/API 成功、空、部分、冲突、损坏引用和脱敏测试；OpenAPI
生成与 drift 检查；Ruff、架构边界检查。

**预计范围：** M；若需要新增数据库字段、迁移或改变 Stage 4D 写入语义，立即停止，
将缺口退回 P0 Stage 4D 主线单独规划和授权，不在可视化任务中顺带实现。

**当前状态：BLOCKED_BY_STAGE4D_P0_LINEAGE。** P0-B 验收通过前不得启动实现。

##### Task 3C-L2：Candidate 与 Timeline 展示

**说明：** 在现有 Candidate Pool / Research Case 页面上增加只读追溯区块，复用
Research Workspace 和 Timeline，不新建平行详情系统。

**验收标准：**

- 用户可从 Candidate 或 Research Case 看见来源、策略版本、StageResult、Admission
  与 Research 生命周期，且每个标识可复制核验；
- unavailable、partial、conflict、rejected 与合法空结果有不同且中性的视觉语义；
- 浏览器不计算投资结论、不推导哈希、不提供 Admission 或策略治理写操作。

**验证：** Web loading/empty/success/partial/conflict/failed focused tests、全量测试、
typecheck、production build和无障碍基本检查。

**预计范围：** 拆为两个 S/M 垂直任务：先 Research Case lineage，再按真实导航需求
决定是否给 Candidate Pool 增加入口；单个任务不超过约 5 个文件。

##### Task 3C-L3：真实链路验收

**说明：** 使用真实 WorkBuddy Candidate 2.0.0 完成一次只读 E2E，保存 Gate B
证据；fixture 只用于自动测试，不替代真实验收。

**验收标准：**

- 页面展示与 AgentOA、artifact、数据库、API 四方的 ID/version/hash/status/time 一致；
- 合法空结果、Admission 拒绝或部分 Research 链均能如实展示，不伪装为成功闭环；
- Stage 4D 历史 Observation、Candidate、Run 和 Result 未被修改或重置。

**验证：** Playwright E2E、API/Web 回归、OpenAPI drift、Web typecheck/build、
`git diff --check`，以及一份不含凭据和宿主绝对路径的真实验收记录。

**预计范围：** S，以 E2E、只读回读和验收记录为主。

##### Slice 3 增量停止条件

- 真实 Candidate 2.0.0 尚未交付时，不宣称 3C-L3 或 Gate B 完成；
- 需要新增业务表、迁移、Candidate/Admission 写入字段或改变 Stage 4D 状态机；
- 只能通过共享目录直读、文件名猜测、Markdown 解析或前端常量建立追溯关系；
- 需要把策略审批、激活、Admission 决策或 Research 写操作开放到浏览器；
- 追溯响应可能泄漏凭据、宿主机路径、内部 artifact URI 或原始异常。

### Slice 4：策略迭代只读窗口

前置条件：`strategy-iteration` 最小只读合同已冻结并有真实记录。

最小字段：稳定策略身份、版本、原始假设、变更内容、变更原因、适用环境、失效条件、来源材料、决定时间。

验收标准：

- 新旧版本差异可追溯，不覆盖历史版本；
- WorkBuddy 提案与人工接受状态分离；
- 不展示虚构收益或自动评分；
- 前置条件未满足时只交付明确空状态。

### Slice 5：持仓纪律只读窗口

前置条件：`position-discipline` 最小只读合同已冻结并确认持仓事实来源。

最小字段：标的身份、建仓理由、计划周期、仓位上限、加减仓/退出条件、最近检查时间、偏离状态、偏离说明。

验收标准：

- 持仓事实与 ETF 成分持仓 Exposure 明确区分；
- 系统只检查和展示纪律，不建议或执行交易；
- 纪律变更和偏离记录不可覆盖；
- 前置条件未满足时只交付明确空状态。

## 8. 实施顺序与 Gate

```text
Slice 0 合同冻结
→ Slice 1 市场状态
→ Gate A：真实数据可视化
→ Slice 2 研究与机会
→ Slice 3 交付链与可信度
→ Gate B：中心只读平台 MVP
→ 独立审核 Strategy Iteration 合同
→ Slice 4
→ 独立审核 Position Discipline 合同
→ Slice 5
```

Slice 4、5 不阻塞中心平台 MVP；不得为了页面完整度提前创建未经审核的业务模型。

## 9. 验证策略

每个垂直切片必须完成：

- Application Read Model 单元测试；
- API 成功、空、部分、错误和脱敏测试；
- Web loading、empty、success、stale、partial、failed 测试；
- OpenAPI client drift 检查；
- TypeScript typecheck 与 production build；
- 真实环境只读联调，记录 `as_of`、来源和空状态原因；
- 全量回归通过后才允许标记 Gate 完成。

人工验收重点不是视觉效果，而是每项事实能否回答“来自哪里、截至何时、为何是这个状态”。

## 10. 风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| Dashboard 聚合过多 | 首页变慢且难维护 | Read Model 限定摘要，详情复用现有页面 |
| 业务合同未冻结就开发 UI | 形成假数据与返工 | Slice 4/5 设置独立前置 Gate |
| 混淆外部观察与正式事实 | 误导研判 | 类型、来源和视觉状态分层 |
| 把纪律提示做成交易指令 | 越过系统定位 | 只读、无买卖动作、无自动执行 |
| 现有 Dashboard 继续堆叠 | 信息层级失控 | 先重组问题集，再迁移现有卡片 |
| 修改现有脏工作树 | 覆盖未提交工作 | 实施前逐文件确认归属，原子提交 |

## 11. 开放决策

以下事项不阻塞 Slice 0–3，但进入对应 Slice 前必须由用户确认：

- 策略迭代的人工决定记录由哪个正式对象承载；
- 实际持仓事实来自手工登记、券商导入还是其他权威源；
- 持仓纪律是否只记录偏离，还是同时记录每次正常检查；
- 中心平台首期是否保留“ETF”作为主标签，或统一改为“投研”。

## 12. Definition of Done

- Gate A、Gate B 的验收项全部完成；
- 所有展示值均有来源、时间和状态语义；
- 浏览器保持只读且不访问共享目录；
- 不包含回测、自动交易和自动策略批准；
- OpenAPI、Web、API 和全量回归通过；
- 真实环境验收记录可复现；
- 计划、代码和验收证据的范围与页面语义一致；
- 用户审核通过后，中心只读平台 MVP 才标记完成。
