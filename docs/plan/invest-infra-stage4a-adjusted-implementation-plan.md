# invest-infra Stage 4A 调整后实施计划方案

> 文档版本：v1.2\
> 文档状态：Draft for Review\
> 调整依据：Research Evidence Pack 与 Research Context Pack 分离建议\
> 适用仓库：`shivchen-dev/invest-infra`\
> 调整目标：在保持 Evidence Foundation 契约稳定的前提下，为 ETF
> Profile、行业上下文和未来 AI 研判扩展预留架构空间。

------------------------------------------------------------------------

# 1. 执行摘要

本实施方案基于原 Stage 4A：

> Research Evidence Foundation

进行架构调整。

核心调整：

**Research Evidence Pack 不再承载所有研究输入，而只负责确定性事实层。**

新增：

> Research Context Pack

作为研究背景上下文层。

最终形成：

    Research Case

        +----------------+
        |                |
        ↓                ↓

    Evidence Pack   Research Context Pack
    事实证据          研究上下文

        +----------------+
                 |
                 ↓

           JiuwenSwarm
                 |
                 ↓

           Research Result

调整后：

-   Evidence Pack 保持 immutable；
-   Factor Set 保持固定版本；
-   ETF Profile 不污染 Evidence hash；
-   Stage 4B 可以自然扩展 ETF Profile；
-   JiuwenSwarm 输入升级为 Research Bundle。

## 1.1 当前 V2 实施基线（2026-08-05）

本计划以仓库实际状态为准，不把“已有代码”重复规划为新工作：

| 能力 | 当前状态 | 事实依据 |
|---|---|---|
| Research Evidence Pack Domain、Factor Set、canonical hash | 已有 | `packages/domain/src/invest_domain/research/` |
| Research Evidence Pack storage migration/model | 已有 | migration `20260803_0007_research_evidence_packs` |
| ETF Profile Domain、Field Evidence、Resolver | 已有 | 已推送提交至 `911e8aa` 的前序提交 |
| ETF Profile → FieldEvidence → Resolver → canonical Profile | 已实现但未提交 | `apps/pipeline/src/invest_pipeline/etf_profiles.py` 当前工作树 |
| Provider Catalog / Factory 与集中凭据 | 已实现但未提交 | `.env.example`、`credentials.py`、Provider config/client |
| Tushare Adapter | 已实现但未提交 | `apps/pipeline/src/invest_pipeline/adapters/tushare/` |
| Research Context Pack | 未开始 | 本计划 Stage 4B |
| Research Bundle / JiuwenSwarm 接口 | 未开始 | 本计划 Stage 4C |

当前 `HEAD` 与 `origin/main` 均为 `911e8aa`；工作树中的未提交实现不得视为已发布能力。后续验收必须分别标记“代码存在”“测试通过”“已提交”“已推送”。

------------------------------------------------------------------------

# 2. 架构原则调整

## 2.1 三层研究模型

系统拆分为三个边界：

    确定性事实层
            |
            ↓
    Research Evidence Pack


    研究上下文层
            |
            ↓
    Research Context Pack


    概率性判断层
            |
            ↓
    Research Result

------------------------------------------------------------------------

## 2.2 职责划分

  模块              职责                          是否参与 Hash
  ----------------- ----------------------------- -----------------
  Evidence Pack     当前事实、因子、质量状态      是
  Context Pack      ETF Profile、行业、市场背景   是（独立 Hash）
  Research Result   AI 观点、风险、结论           否

------------------------------------------------------------------------

# 3. ADR 调整

## ADR-06：Evidence Pack 与 Research Context Pack 分离

### 决策

Research Evidence Pack 只保存：

-   可验证；
-   可复现；
-   时间冻结；
-   确定性计算生成的数据。

ETF Profile、行业分类、指数信息、外部研究资料进入 Research Context
Pack。

------------------------------------------------------------------------

### 原因

Evidence Pack 回答：

> 当前 ETF 发生了什么？

例如：

-   收益；
-   趋势；
-   波动；
-   回撤；
-   流动性；
-   数据质量。

Research Context Pack 回答：

> 当前 ETF 是什么？

例如：

-   投资主题；
-   跟踪指数；
-   管理策略；
-   行业暴露；
-   基金属性。

二者生命周期不同。

------------------------------------------------------------------------

# 4. Stage 4A 范围重新定义

## 4.1 Stage 4A 必须完成

目标：

> 建立可信 Evidence Foundation。

交付：

-   Research Case；
-   Research Evidence Pack；
-   Evidence Item；
-   Factor Observation；
-   Research Run；
-   Evidence API；
-   固定 Factor Set；
-   Golden Hash；
-   Revision 管理。

------------------------------------------------------------------------

## 4.2 Stage 4A 不包含

暂不建设：

-   ETF Profile；
-   行业知识；
-   市场环境模型；
-   新闻事件；
-   外部研究资料；
-   完整 Research Context。

这些进入 Stage 4B。

说明：本条表示 ETF Profile 不作为 Stage 4A Evidence Foundation 的输入或验收
条件，不表示删除当前已存在的 DC-2 ETF Profile Domain、Field Evidence、Resolver
和采集代码。Stage 4B 只需把这些已存在的 canonical 结果接入 Context Builder，
不应重新访问 Provider 或绕过 Resolver。

------------------------------------------------------------------------

# 5. 新增 Research Context Pack

## 5.1 目标

为未来 AI Agent 提供背景解释材料。

------------------------------------------------------------------------

## 5.2 数据模型

``` python
ResearchContextPack:

id
instrument_id
schema_version
context_version
content_hash
items
created_at
```

约束：

- `instrument_id` 必须与 Research Case、Evidence Pack 一致；
- `schema_version` 描述结构版本，`context_version` 描述同一上下文的业务修订；
- `content_hash` 只由规范化后的 `items` 和上下文版本参与计算，不包含 `id`、`created_at`；
- Context Pack 是不可变快照，更新必须生成新版本，不允许原地覆盖；
- Context Pack 可以为空，但必须显式返回 `missing_context`，不得伪造默认值。

------------------------------------------------------------------------

## 5.3 Context Item

示例：

``` json
{
  "context_type": "etf_profile",
  "key": "investment_theme",
  "value": "AI Infrastructure",
  "value_type": "text",
  "source_provider": "fund_profile",
  "source_dataset": "etf_profile",
  "source_batch_id": "...",
  "source_revision": 1,
  "observed_at": "2026-08-03T00:00:00Z",
  "quality_status": "complete",
  "confidence_score": "0.95",
  "evidence_refs": ["field-evidence-content-hash"],
  "item_hash": "..."
}
```

`ContextItem` 最小契约：

- `context_type`：`etf_profile`、`benchmark`、`industry`、`market`、`external_evidence`；
- `key`：稳定字段名，禁止把多个业务字段压成一段自由文本；
- `value` / `value_type`：按 `text`、`decimal`、`date`、`json` 显式编码；
- `source_provider`、`source_dataset`、`source_batch_id`、`source_revision`、`observed_at`：完整来源链；
- `quality_status`、`confidence_score`：保留缺失、冲突和可信度；
- `evidence_refs`：指向 `FieldEvidence.content_hash` 或外部 Evidence ID；
- `item_hash`：由上述业务字段规范化计算，排除运行时创建时间。

规范化规则：Context Item 按 `(context_type, key, item_hash)` 排序；JSON 使用
UTF-8、稳定键序、紧凑分隔符；`Decimal` 使用字符串编码；时间统一为带时区
ISO-8601。`ResearchContextPack.content_hash` 对排序后的 Item 列表计算 SHA-256。

------------------------------------------------------------------------

# 6. Domain Model 调整

## 6.1 ResearchCase

调整：

原：

    ResearchCase
     |
     EvidencePack

改为：

    ResearchCase

    inputs:

    - evidence_pack_id
    - context_pack_id
    - playbook_version

Research Case 不直接拥有所有研究材料。

------------------------------------------------------------------------

## 6.2 ResearchEvidencePack

保持：

``` python
ResearchEvidencePack:

schema_version
factor_set_key
factor_set_version
content_hash
quality_status
freshness_status
```

------------------------------------------------------------------------

## 6.3 EvidenceItem

允许：

-   instrument_snapshot；
-   market_data；
-   factor_observation；
-   candidate_pool_context；
-   data_quality。

禁止：

-   investment_theme；
-   industry_story；
-   external_opinion。

------------------------------------------------------------------------

# 7. Evidence Contract 调整

## 7.1 Hash 边界

保持：

    Evidence Pack Hash

    =
    Evidence Items
    +
    Factor Observations

禁止：

    Evidence Pack Hash

    =
    Evidence
    +
    ETF Profile
    +
    External Context

------------------------------------------------------------------------

## 7.2 Revision 规则

行情变化：

    Daily Bars Revision

    ↓

    新的 Evidence Pack

ETF Profile 更新：

    新的 Context Pack

    ↓

    不影响 Evidence Pack

------------------------------------------------------------------------

# 8. Factor Set 调整

保持：

    factor_set_key:

    etf_research_daily

    version:

    1.0.0

包含：

-   return_20d；
-   return_60d；
-   return_120d；
-   distance_ma20；
-   distance_ma60；
-   volatility；
-   max_drawdown；
-   liquidity；
-   completeness。

原则：

因子只描述状态。

禁止：

``` json
{
 "action":"buy"
}
```

Bundle 契约补充：

- 顶层增加 `schema_version` 和 `instrument_id`；
- `evidence_pack`、`context_pack` 只携带不可变 ID、版本和 hash，不内嵌未规范化原始数据；
- `context_pack` 允许为 `null`，但必须携带明确的 `missing_reason`；
- 两个 Pack 的 `instrument_id` 不一致时拒绝生成 Bundle；
- Playbook 必须包含稳定 `key` 和 `version`，不得使用未版本化提示词作为输入标识。

------------------------------------------------------------------------

# 9. Stage 4B 调整

原：

Research Context & Playbooks

强化为：

> Research Context Layer

目标：

建设：

    Context Builder

    ↓

    Research Context Pack

范围：

## ETF Context

-   ETF Profile；
-   Benchmark；
-   Expense Ratio；
-   Issuer；
-   Theme。

## Market Context

-   市场状态；
-   风险环境；
-   风格周期。

## Industry Context

-   行业分类；
-   主题暴露。

## External Evidence

后续支持：

-   新闻；
-   政策；
-   事件。

------------------------------------------------------------------------

# 10. JiuwenSwarm 输入调整

## 原：

    Evidence Pack

## 调整：

    Research Bundle

结构：

``` json
{
 "evidence_pack":{
    "id":"xxx",
    "hash":"xxx"
 },

 "context_pack":{
    "id":"xxx",
    "hash":"xxx"
 },

 "playbook":{
    "key":"etf_medium_term_assessment",
    "version":"1.0.0"
 }
}
```

------------------------------------------------------------------------

# 11. Research Run 调整

Research Run 保存：

-   Evidence Pack ID；
-   Context Pack ID；
-   Playbook Version；
-   Workspace；
-   Result Hash；
-   AI 输出状态。

示例：

    ResearchRun

    inputs:

    Evidence Pack
    Context Pack
    Playbook

    output:

    Research Result

------------------------------------------------------------------------

# 12. 实施阶段调整

## Phase A：契约冻结

交付：

-   ADR-06；
-   Evidence Contract v1.0；
-   Context Contract v0.1；
-   Factor Set v1.0；
-   Research Bundle Schema。

------------------------------------------------------------------------

## Phase B：Evidence Foundation

交付：

-   Research Case；
-   Evidence Pack；
-   Factor Observation；
-   Storage；
-   Hash；
-   API。

------------------------------------------------------------------------

## Checkpoint A

必须满足：

-   Evidence Pack 不依赖 Context；
-   Hash 稳定；
-   Revision 可追踪；
-   缺失数据明确。

------------------------------------------------------------------------

## Phase C：Research Context Layer

新增：

-   Context Pack；
-   ETF Profile Builder；
-   Context API。

------------------------------------------------------------------------

## Phase D：JiuwenSwarm Integration

输入：

    Research Bundle

实现：

-   Playbook；
-   Agent Team；
-   E2A；
-   Research Result。

------------------------------------------------------------------------

## Phase E：Research Workbench

展示：

-   Evidence；
-   Context；
-   Agent 分析；
-   Report；
-   历史变化。

------------------------------------------------------------------------

# 12.1 可执行任务清单与依赖

## Phase A：契约冻结

### Task A1：冻结 Evidence Pack 边界

**交付：** 保留现有固定 Factor Set、canonical hash 和 revision 语义；补充
Evidence Pack 不包含 Context 的负向测试。

**验收：** 既有 Research Evidence 测试和 Golden Hash 测试通过；增加 Context
数据变化不改变 Evidence Pack hash 的测试。

**依赖：** 无。

### Task A2：冻结 Context Contract v0.1

**交付：** `ResearchContextPack`、`ContextItem`、状态枚举、来源引用、规范化
JSON 和 hash 规则。

**验收：** 相同业务内容 hash 稳定；调整 `created_at`、数据库 ID 不改变 hash；
调整 value、source revision 或 quality status 会生成新 hash。

**依赖：** A1。

### Task A3：冻结 Research Bundle Schema v0.1

**交付：** Evidence Pack 引用、Context Pack 引用、Playbook 引用、instrument
一致性和缺失输入行为。

**验收：** Bundle 能表达“无 Context”状态；跨 instrument 的 Pack 被拒绝；Schema
版本可校验。

**依赖：** A1、A2。

## Phase B：Evidence Foundation 收口

### Task B1：核对现有 Evidence Foundation

**交付：** Research Case、Research Run、Evidence API、Storage 和 migration
的现状清单；只补缺口，不重写已存在的 Evidence Pack。

**验收：** Domain、Storage、API focused tests 通过；migration chain 可运行；
未引入 ETF Profile 依赖。

**依赖：** A1。

## Checkpoint B：事实层冻结

- [ ] Evidence Pack 不读取 Context Pack；
- [ ] Evidence Pack Golden Hash 未变化；
- [ ] Evidence revision 与 Context revision 可独立追踪；
- [ ] Stage 4A 代码、测试和文档状态一致。

## Phase C：Research Context Layer

### Task C1：Context Pack Domain 与 canonical 实现

**交付：** `ResearchContextPack`、`ContextItem`、item hash、pack hash、缺失和
冲突状态。

**验收：** Domain validation、canonical golden tests、empty/missing/conflict
tests 通过。

**依赖：** A2。

### Task C2：Context Pack Storage/API

**交付：** `analytics.research_context_packs`、`analytics.research_context_items`
migration、Repository、查询 API；保持与 Evidence 表分离。

**验收：** 同一 hash 幂等；不同 revision 可共存；按 instrument 和 context_version
可查询；来源引用可回溯。

**依赖：** C1、B1。

### Task C3：ETF Profile Context Builder

**交付：** `FieldEvidence → Resolver → canonical EtfProfile → ContextItem →
ResearchContextPack` 的单向构建链。

**验收：** 缺失字段保留 missing；冲突字段不输出 resolved value；AUM 不接受
market_value 替代；每个 ContextItem 都有 source/evidence reference。

**依赖：** C1、C2；当前 ETF Profile Evidence/Resolver 实现可复用。

## Phase D：Research Bundle 与 Agent 接入

### Task D1：Research Case / Research Run 增加 Context 引用

**交付：** `context_pack_id`、`context_version` 和输入一致性校验。

**验收：** Evidence Pack 更新不会修改 Context Pack；Context Pack 更新不会修改
Evidence Pack；Research Run 保存两者的不可变引用。

**依赖：** A3、B1、C2。

### Task D2：JiuwenSwarm Research Bundle Adapter

**交付：** 生成稳定的 `Research Bundle` JSON；旧的 Evidence-only 输入提供明确
兼容策略，不静默改变语义。

**验收：** Bundle Schema、跨 instrument 校验、无 Context 行为和脱敏测试通过。

**依赖：** A3、D1。

## Checkpoint D：研究输入闭环

- [ ] Evidence Pack + Context Pack + Playbook 能生成同一 instrument 的 Bundle；
- [ ] Bundle 可复现、可追溯、可版本化；
- [ ] JiuwenSwarm 不直接读取 Provider 或数据库原始表；
- [ ] 旧 Evidence-only 流程的兼容行为有测试。

------------------------------------------------------------------------

# 13. 数据库调整

新增：

保持：

    analytics.research_cases
    analytics.research_evidence_packs
    analytics.research_evidence_items
    analytics.factor_observations
    analytics.research_runs

后续新增：

    analytics.research_context_packs
    analytics.research_context_items

不合并。

建议最小字段：

`research_context_packs`：`id`、`instrument_id`、`schema_version`、
`context_version`、`content_hash`、`created_at`。

`research_context_items`：`id`、`pack_id`、`context_type`、`key`、`value_json`、
`value_type`、`source_provider`、`source_dataset`、`source_batch_id`、
`source_revision`、`observed_at`、`quality_status`、`confidence_score`、
`evidence_refs_json`、`item_hash`。

约束：Pack 按 `(instrument_id, context_version)` 保留历史版本；Item 按
`item_hash` 幂等；Pack 与 Item 不能复用 Evidence Pack 表；所有来源引用必须
可回溯到 Field Evidence 或 Provider Raw Batch。

------------------------------------------------------------------------

# 14. 测试调整

新增测试：

## Evidence

验证：

-   hash 不受 Context 影响；
-   revision 正确；
-   Golden Pack 稳定。

## Context

验证：

-   Context 更新不会修改 Evidence Pack；
-   Context hash 独立。

## Research Bundle

验证：

-   Evidence + Context + Playbook 可组合；
-   Agent 输入结构稳定。

------------------------------------------------------------------------

# 15. Definition of Done

Stage 4A 完成：

-   [ ] Evidence Pack 契约冻结；
-   [ ] Context Pack 边界明确；
-   [ ] Factor Set v1.0 完成；
-   [ ] Research Case 完成；
-   [ ] Evidence API 完成；
-   [ ] Hash Golden Test 完成；
-   [ ] Revision 测试完成；
-   [ ] 不依赖 ETF Profile。

进入 Stage 4B：

-   [ ] Context Pack Schema 完成；
-   [ ] ETF Profile 接入；
-   [ ] Context Builder 完成。

进入 Stage 4C：

-   [ ] Research Bundle Contract 冻结；
-   [ ] JiuwenSwarm 使用 Bundle 输入。

------------------------------------------------------------------------

# 16. 最终架构

    Provider
       |
       ↓
    PostgreSQL

       +----------------+
       |                |
       ↓                ↓

    Evidence Builder   Context Builder

       |                |
       ↓                ↓

    Evidence Pack    Context Pack

       +----------------+
                |
                ↓

         Research Bundle

                |
                ↓

          JiuwenSwarm

                |
                ↓

         Research Result

------------------------------------------------------------------------

# 17. 方案结论

本次调整不是扩大范围，而是修正边界。

最终原则：

    Evidence Pack
    =
    事实

    Context Pack
    =
    背景

    Research Result
    =
    AI判断

通过三层分离，可以保证：

-   当前 Stage 4A 不返工；
-   ETF Profile 可以持续扩展；
-   JiuwenSwarm 获得完整研究输入；
-   Evidence Contract 长期稳定。
