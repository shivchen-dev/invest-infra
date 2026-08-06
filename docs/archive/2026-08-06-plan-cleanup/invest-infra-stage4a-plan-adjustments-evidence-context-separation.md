# invest-infra 早期实施计划调整建议

> 调整主题：Research Evidence Pack 与 ETF Profile / Research Context
> 解耦\
> 适用方案：Stage 4A --- Research Evidence Foundation\
> 调整原因：避免 Research Evidence Pack 固定契约被动态研究上下文污染

------------------------------------------------------------------------

## 1. 调整结论

当前 Stage 4A 的核心设计：

    Research Case
        ↓
    Research Evidence Pack
        ↓
    Evidence Items
        ↓
    Factor Observations

应继续保留。

但是：

**ETF Profile 不应直接接入 Research Evidence Pack。**

原因：

-   Evidence Pack 是不可变事实快照；
-   固定 factor_set 需要保证 hash 稳定；
-   ETF Profile 生命周期和因子不同；
-   Profile 更新不应导致行情因子 Evidence Pack 整体 revision。

建议新增：

    Research Context Pack

形成：

    Research Case
          |
          +----------------+
          |                |
          ↓                ↓
    Evidence Pack     Research Context Pack
    (事实证据)          (研究上下文)
          |
          +-------+
                  ↓
            JiuwenSwarm
                  ↓
            Research Result

------------------------------------------------------------------------

# 2. 新增 ADR：Evidence Pack 与 Research Context Pack 分离

## ADR-06：Evidence Pack 与 Research Context Pack 分离

### 决策

Research Evidence Pack 只保存确定性、可复现、版本化的数据证据。

ETF Profile、行业分类、主题标签、指数描述、外部研究资料等内容进入
Research Context Pack。

### 原因

Evidence Pack 用于回答：

> 当前这个 ETF 发生了什么？

例如：

-   收益变化；
-   趋势状态；
-   波动率；
-   最大回撤；
-   流动性；
-   数据质量。

Research Context Pack 用于回答：

> 这个 ETF 是什么，以及如何理解它？

例如：

-   ETF Profile；
-   跟踪指数；
-   行业分类；
-   主题标签；
-   基金属性；
-   外部研究材料。

二者生命周期不同，不能共享同一个 immutable hash。

------------------------------------------------------------------------

# 3. Research Evidence Pack 调整

## 保留内容

Evidence Pack v1.0：

-   instrument identity；
-   Candidate Pool Context；
-   price snapshot；
-   return factors；
-   trend factors；
-   volatility factors；
-   drawdown factors；
-   liquidity factors；
-   data quality；
-   freshness status。

------------------------------------------------------------------------

## 移除或禁止内容

以下内容不得进入 Evidence Pack：

-   ETF 投资主题；
-   行业标签；
-   基准指数描述；
-   基金管理策略说明；
-   外部研究观点；
-   新闻事件；
-   宏观解释。

这些内容属于 Research Context。

------------------------------------------------------------------------

# 4. 新增 Research Context Pack

## 数据模型

建议新增：

``` python
ResearchContextPack:
    id
    instrument_id
    schema_version
    context_version
    content_hash
    context_items
    created_at
```

------------------------------------------------------------------------

## Context Item 示例

``` json
{
  "context_type": "etf_profile",
  "key": "investment_theme",
  "value": "AI Infrastructure",
  "source": "fund_profile",
  "observed_at": "2026-08-03"
}
```

------------------------------------------------------------------------

## 第一阶段不实现完整 Context Pack

Stage 4A：

只冻结接口。

Stage 4B：

正式实现：

-   ETF Profile；
-   Index Profile；
-   Industry Exposure；
-   Market Context；
-   External Evidence。

------------------------------------------------------------------------

# 5. Research Case 调整

原：

    ResearchCase
     |
     └── EvidencePack

调整：

    ResearchCase

    inputs:

    - evidence_pack_id
    - context_pack_id
    - playbook_version

Research Case 不直接拥有所有研究资料。

------------------------------------------------------------------------

# 6. JiuwenSwarm 输入调整

原：

    evidence.json

调整为：

    research_bundle.json

结构：

``` json
{
  "evidence_pack": {
    "id": "...",
    "content_hash": "..."
  },
  "context_pack": {
    "id": "...",
    "content_hash": "..."
  },
  "playbook": {
    "key": "etf_medium_term_assessment",
    "version": "1.0.0"
  }
}
```

Agent 输入由：

    Evidence

升级为：

    Research Bundle

    =
    Evidence Pack
    +
    Context Pack
    +
    Playbook

------------------------------------------------------------------------

# 7. Stage 路线调整

## Stage 4A

保持：

    Research Evidence Foundation

目标：

冻结事实层。

交付：

-   Research Case；
-   Evidence Pack；
-   Factor Observation；
-   Research Run；
-   API Contract。

------------------------------------------------------------------------

## Stage 4B

调整名称：

    Research Context & Playbooks

新增：

-   ETF Profile；
-   Index Profile；
-   Industry Context；
-   Market Context；
-   External Evidence。

------------------------------------------------------------------------

## Stage 4C

JiuwenSwarm Investment Team

输入：

    Evidence Pack
    +
    Context Pack
    +
    Playbook

------------------------------------------------------------------------

# 8. 数据契约调整

## Evidence Pack Hash

保持：

    hash(
        evidence_items
    )

禁止：

    hash(
        evidence_items
        +
        ETF Profile
        +
        external context
    )

原因：

避免非行情变化导致 Evidence revision。

------------------------------------------------------------------------

# 9. 实施计划修改点

需要修改：

## 文件：

    docs/plan/invest-infra-v2-stage4a-ai-research-evidence-foundation-plan.md

    docs/plan/invest-infra-stage4a-merged-implementation-plan.md

------------------------------------------------------------------------

## 修改章节

### 1. Domain Model

新增：

-   Research Context Pack。

------------------------------------------------------------------------

### 2. Evidence Contract

增加：

-   Evidence 与 Context 边界。

------------------------------------------------------------------------

### 3. Stage 4B 范围

增加：

-   ETF Profile；
-   Research Context Layer。

------------------------------------------------------------------------

### 4. JiuwenSwarm 输入协议

从：

    Evidence Pack

调整：

    Research Bundle

------------------------------------------------------------------------

# 10. 最终架构

    Provider
       |
       ↓
    PostgreSQL
       |
       +----------------+
       |                |
       ↓                ↓
    Evidence Builder   Context Builder
       |                |
       ↓                ↓
    Evidence Pack    Context Pack
       |                |
       +-------+--------+
               |
               ↓
        JiuwenSwarm
               |
               ↓
        Research Result

------------------------------------------------------------------------

# 11. 最终建议

不要删除 ETF Profile。

但不要让 ETF Profile 污染 Evidence Foundation。

正确方向：

    Evidence Pack
    =
    事实

    Context Pack
    =
    解释背景

    Research Result
    =
    AI判断

三层分离后，Stage 4A、4B、4C 可以自然演进，避免后续返工。
