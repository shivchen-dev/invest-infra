# invest-infra 数据采集层增强实施计划 v1.0

> 目标：将 invest-infra 从 ETF 行情基础设施升级为 AI 投资研判数据底座

## 1. 背景

当前 invest-infra 已具备：

- Provider Catalog
- 多 Provider Adapter
- ETF Universe
- ETF 主数据
- 日行情与 revision
- Input Snapshot
- Candidate Pool
- Evidence Pack 基础能力

当前主要不足：

> 数据更偏向量化行情层，缺少支撑 AI 投资研判的 Investment Context Layer。

目标：

建立：

```
Raw Data
 ↓
Canonical Data
 ↓
Investment Context
 ↓
Research Evidence Pack
 ↓
AI Investment Research
```

---

# 2. 数据分层目标

## Raw Data Layer

负责：

- Provider
- Request
- Response
- Revision
- Provenance

## Quant Data Layer

负责：

- Price
- Volume
- Turnover
- Factor
- Risk

## Investment Context Layer

新增：

- ETF Profile
- Index Exposure
- Holdings
- Valuation
- Market Regime
- Events
- Institution Views

---

# 3. 实施阶段

## Stage DC-1 Provider 与数据质量增强

目标：

建立统一数据采集治理。

新增：

Provider Registry：

```
provider_key
dataset
priority
reliability_score
freshness_sla
supported_fields
```

增加：

- Provider 优先级
- 数据新鲜度
- 字段覆盖率
- 多源一致性检查

---

## Stage DC-2 ETF 基础研究数据

优先级：最高

新增：

## ETF Profile

```
etf_profile

symbol
name
manager
benchmark_index
category
inception_date
fund_type
management_fee
custody_fee
aum
shares
```

AI 用途：

- 产品成熟度
- 规模风险
- 长期研究价值

---

## Stage DC-3 指数与成分暴露

目标：

回答：

> ETF 为什么涨跌？

新增：

## Index

```
index_profile

index_code
index_name
category
```

## ETF Index Mapping

```
etf_index_mapping

etf_id
index_id
effective_date
weight
```

## Holdings

```
etf_holdings

etf_id
stock_code
industry
weight
date
```

支持：

- 行业暴露
- 龙头集中度
- 风险分析

---

## Stage DC-4 估值上下文

新增：

```
valuation_snapshot

target
date
pe
pb
dividend_yield
roe
percentile
```

AI 可判断：

- 当前是否高估
- 是否处于历史极端区域

---

## Stage DC-5 市场环境

新增：

```
market_regime_snapshot

date
trend_state
volatility_state
liquidity_state
risk_state
style_state
```

覆盖：

- 沪深300
- 中证500
- 中证1000
- 创业板
- 科创50

---

## Stage DC-6 风格与行业轮动

新增：

```
style_factor_snapshot

date
style
relative_strength
trend
```

覆盖：

- 成长
- 价值
- 红利
- 小盘
- 大盘
- 科技
- 消费
- 周期

---

## Stage DC-7 外部事件

新增：

```
research_event
event_id
date
source
title
summary
related_etf
related_sector
sentiment
importance
```

来源：

- 新闻
- 公告
- 政策
- 行业事件

原则：

保存结构化摘要，不保存大量全文。

---

## Stage DC-8 机构观点

新增：

```
institution_view

source
date
target
rating
horizon
summary
confidence
```

注意：

机构观点属于 External Evidence。

必须区分：

事实：

```
ETF规模100亿
```

观点：

```
机构看好该ETF
```

---

# 4. 数据质量体系

新增：

## Data Quality Score

组成：

```
freshness
completeness
consistency
source_reliability
```

输出：

0-100

## Cross Provider Validation

例如：

```
EastMoney
AkShare
Sina
```

比较：

- price
- volume
- amount

状态：

```
verified
warning
conflict
```

AI 不读取 conflict 数据。

---

# 5. Evidence Pack 增强

从：

```
Price Evidence
```

升级为：

```
Investment Evidence
```

增加：

```json
{
 "etf_profile": {},
 "index_exposure": {},
 "holdings": {},
 "valuation": {},
 "market_context": {},
 "events": {},
 "institution_views": {}
}
```

---

# 6. Provider 设计原则

统一 Adapter：

```
ResearchDataProvider

fetch_etf_profile()

fetch_index()

fetch_holdings()

fetch_valuation()

fetch_events()
```

所有输出必须包含：

```
source
retrieved_at
dataset_version
content_hash
quality
```

---

# 7. Github 项目参考

## AkShare

用途：

- 国内金融数据覆盖

借鉴：

- Provider Adapter

不要：

- 业务层直接调用

## OpenBB Platform

重点参考：

```
Provider
 ↓
Data Model
 ↓
Research Tools
 ↓
AI Analyst
```

与 invest-infra 长期方向最接近。

## QuantConnect Lean

参考：

- Security Master
- Universe Selection
- Data Subscription

不要引入：

- 回测体系

## Financial Modeling Prep

参考：

- Profile
- Financial Data
- News
- Ratios 数据组织方式

---

# 8. 实施顺序

推荐：

```
PR-DATA-01
Provider Registry + Quality

 ↓

PR-DATA-02
ETF Profile

 ↓

PR-DATA-03
Index + Holdings

 ↓

PR-DATA-04
Valuation

 ↓

PR-DATA-05
Market Regime

 ↓

PR-DATA-06
Events + Institution Views
```

---

# 9. 暂缓建设

暂不做：

- 分钟行情
- 高频数据
- 完整财务数据库
- 回测平台
- 自动交易
- 大型 RAG 知识库

原因：

当前 AI 研判最大的瓶颈不是数据量，而是：

- 数据可信度
- 投资上下文完整性
- 证据可追溯

---

# 10. 与 AI 投研路线关系

调整后：

```
Stage 4A-0
动态 ETF Candidate Routing

 ↓

Data Collection Enhancement
投资上下文数据层

 ↓

Stage 4A
Evidence Pack Foundation

 ↓

Stage 4B
Market Intelligence Foundation

 ↓

Research Evidence Bundle / Context Projection

 ↓

JiuwenSwarm Investment Research

 ↓

Research Workbench
```

---

# 11. 最终目标

建设：

> 一个能够向 AI 投资研判团队持续提供可信、完整、可追溯投资证据的数据基础设施。

核心能力：

```
数据可信
+
上下文完整
+
证据可追溯
+
AI 可解释
```
