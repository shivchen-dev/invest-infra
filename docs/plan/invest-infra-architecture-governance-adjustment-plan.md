# invest-infra 架构收敛与治理调整实施计划 v1.0

## 目标

解决项目快速扩展后的：

- 架构漂移
- 领域膨胀
- 重复建设
- 代码规模失控风险

保持项目目标：

> AI 投资研判基础设施

而不是金融数据仓库。

---

# 1. 当前问题

当前项目已经具备：

- Provider Catalog
- 多 Provider Adapter
- ETF Universe
- Candidate Pool
- ETF Profile
- Evidence Pack

方向正确。

但风险：

1. Core、Analytics、Research 边界扩大；
2. 新增数据容易复制完整工程链；
3. Evidence Pack 可能成为第二数据仓库；
4. Repository 数量快速增长；
5. Provider 数量增加导致治理困难。

---

# 2. 架构边界冻结

最终：

```
Provider Layer

↓

Raw Data Layer

↓

Core Data Layer

↓

Analytics Layer

↓

Research Evidence Layer

↓

AI Research Layer
```

---

# 3. Domain 职责

## Core

负责：

- Instrument
- Daily Bars
- ETF Profile Canonical View

不负责：

- 投资观点
- AI结果


## Analytics

负责：

- Factor
- Risk Metrics
- Candidate Ranking
- Market State

不负责：

- 投资判断


## Research

负责：

- Research Case
- Evidence Pack
- Evidence Item
- Research Result

不重新计算行情。


## AI

负责：

- Agent
- Playbook
- Thesis
- Risk
- Confidence

不修改 Evidence。

---

# 4. 数据成熟度规则

## Level 0 Raw Evidence

保存：

- provider
- payload
- timestamp
- hash


## Level 1 Evidence

增加：

- source
- quality
- provenance
- confidence


## Level 2 Canonical Model

稳定业务对象：

- ETF Profile
- Index
- Holdings


## Level 3 Research Capability

用于：

- AI Research
- Playbook
- Report


不是所有数据立即进入 Canonical Model。

---

# 5. Repository 治理

## 必须 Repository

需要：

- 生命周期
- 查询
- 事务

例如：

- Instrument
- DailyBar
- CandidatePoolRun
- ResearchCase
- EvidencePack


## 暂不 Repository

证据型数据：

- 新闻
- 机构观点
- 外部评论

优先保存：

Evidence JSON

避免过度建模。

---

# 6. Evidence Pack 边界

错误：

```
所有金融数据
        ↓
Evidence Pack
```

正确：

```
Database

↓

Evidence Builder

↓

Research Evidence Pack

↓

AI Agent
```

Evidence Pack 是：

一次研究任务需要的证据集合。

不是数据仓库。

---

# 7. Provider 治理

增加分级：

## Primary

生产来源：

- 官方数据
- 主数据源


## Secondary

校验：

- AkShare
- 第三方数据


## Experimental

实验：

- MCP
- Scraper


实验 Provider 不直接进入生产链。

---

# 8. 新数据准入规则

新增数据必须回答：

## 是否支持 AI 研究问题？

例如：

问题：

为什么上涨？

需要：

- Index Exposure
- Holdings


---

## 是否需要 Canonical Model？

外部观点：

不要马上建表。


---

## 是否进入 Evidence Pack？

不能支持研究的数据暂缓。

---

# 9. 实施任务

## 当前收敛状态（2026-08-06）

- GOV-01～GOV-05：已完成并通过既有治理验收。
- GOV-06：已完成。`pipeline_runs`、`candidate_pool`、ETF/instrument
  只读 API 已通过 Application Query Service 组织，路由仅保留 HTTP
  校验、异常映射和响应映射。
- GOV-07：已完成。`data_freshness` 的 raw SQL 已移入 storage
  Infrastructure reader，Application service 负责编排和状态归约，Router
  仅保留 HTTP/Pydantic 映射。
- 新数据准入流程：已形成可执行登记/评审清单，见
  `docs/validation/data-admission-checklist.md`；不等于批准新增 Provider。
- 当前验证：API 全量测试 `174 passed`，API/storage ruff 通过，
  `scripts/check_architecture.py` 通过；存在 1 个 FastAPI/httpx 依赖弃用警告。

## PR-GOV-01 架构冻结

交付：

- Domain Boundary 文档
- Data Ownership
- Repository Rule


---

## PR-GOV-02 Evidence 治理

交付：

- Evidence Lifecycle
- Evidence Contract
- Provenance Rule


---

## PR-GOV-03 Provider 治理

交付：

- Provider Tier
- Reliability Score
- Dataset Ownership


---

## PR-GOV-04 模块清理

检查：

- 重复 Model
- 重复 Mapper
- 重复 Factor
- 重复 API


---

# 10. 暂缓建设

暂缓：

- 完整新闻系统
- 机构数据库
- Factor Store
- Feature Store
- 回测平台
- 自动交易

原因：

当前目标不是量化平台。

---

# 11. 后续路线

```
Dynamic Candidate Pool

↓

Investment Context

↓

Evidence Pack

↓

JiuwenSwarm Research

↓

AI Investment Report
```

---

# 12. Definition of Done

- [x] Core / Analytics / Research / AI 边界明确
- [x] Evidence Pack 定位冻结
- [x] Provider 分级完成
- [x] Repository 规则明确
- [x] 新数据准入流程完成（登记、阻断式评审和决策记录模板已冻结）
- [x] 无第二套数据模型
- [x] 文档和代码一致（API Application 收敛状态已同步）

---

最终目标：

构建：

```
可信数据
+
完整上下文
+
证据追踪
+
AI解释能力
```

而不是：

```
最大数据量
+
最大代码量
+
最多模型
```
