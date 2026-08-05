# invest-infra 架构治理基线

状态：Draft for implementation，适用于 `91929c9` 及后续收敛提交。

本文件是 Domain ownership、Data ownership 和 Repository 准入规则的权威入口。它补充 `docs/ARCHITECTURE.md`，不改变 Provider 的业务选型，也不授权新增数据源。

## 1. Runtime layers

```text
Provider Adapter
      ↓
Raw Provider Evidence
      ↓
Core Canonical Data
      ↓
Analytics Observations
      ↓
Research Evidence Pack
      ↓
AI Research
```

每一层只能通过明确的接口消费上一层结果。下游不得回写上游事实。

## 2. Domain ownership

### Core

拥有：

- `Instrument`
- `DailyBar`
- `EtfProfile`

职责：保存稳定、可复用的 canonical 业务对象及其来源追踪。

禁止拥有：

- 因子计算结果的业务解释；
- 候选池排序；
- Research Case、Evidence Pack；
- AI Thesis、Confidence、Report。

### Analytics

拥有：

- Factor calculation and observations；
- Risk metrics；
- Market state；
- Candidate Pool、Ranking、Quality Gate。

Analytics 只对输入的 Core 数据和版本化参数做确定性计算。计算结果必须携带算法版本、参数版本、观察日期和数据质量信息。

禁止拥有：

- 研究问题和 Research Case 生命周期；
- Provider 原始 payload；
- 投资结论和 AI 输出。

### Research

拥有：

- Research Case；
- Evidence Item；
- Evidence Pack；
- 面向 AI 的只读 Context projection。

Research 负责按一次研究任务组织证据，不重新计算行情、因子或风险指标。因子结果只能作为带 provenance 的 Evidence Item 被引用。

### AI

拥有：

- Agent execution；
- Playbook；
- Thesis；
- Risk interpretation；
- Confidence and Report。

AI 只能消费 Evidence Pack/Context projection。AI 不得修改 Evidence、Core 或 Analytics 事实。

## 3. Data ownership

| Data | Owner | Storage intent |
|---|---|---|
| Provider request/attempt/batch | Provider/Pipeline infrastructure | `raw`，保留 payload、时间、hash、错误和 provenance |
| Instrument/DailyBar/ETF Profile | Core | `core`，canonical 当前视图及修订历史 |
| Input Snapshot/Candidate Pool/Factor output | Analytics | `analytics`，版本化计算结果 |
| Evidence Pack | Research | 当前实现暂存于 `analytics`，逻辑所有权仍属于 Research |
| Context Pack | Research projection | 可重建、可替换，不是新的事实源 |
| AI result | AI | 暂不建设持久化模型 |

一张业务表只能有一个逻辑 owner。数据库 schema 位置不能替代领域 ownership。

## 4. Evidence rules

```text
Raw Provider Evidence
        ↓
Canonical Core / Analytics Observation
        ↓
EvidenceItem
        ↓
EvidencePack (one Research Case)
        ↓
Context projection
        ↓
AI Research
```

### EvidenceItem

每个 Evidence Item 必须能回答：

- 它支持哪一个 Research Case 或研究问题；
- 来源 Provider、Dataset、Batch/Revision 是什么；
- 何时观察到；
- 数据质量和 confidence 是什么；
- 内容 hash 如何计算。

### EvidencePack

- 一次 Research Case 一个证据集合；
- 只组织证据，不作为通用金融数据仓库；
- 内容不可变，修订必须生成新 hash/新版本；
- 可以引用 Core/Analytics 对象，但不复制其全部生命周期；
- 不承担 AI 结果存储。

### Context Pack

`ResearchContextPack` 是 Evidence Pack 的面向消费方的只读投影。它可以为检索和 Agent 输入提供扁平化字段，但必须能够由上游 Evidence 重建。

它不是第二套 Evidence source of truth，也不能独立产生与 Evidence Pack 冲突的事实。

### ETF profile field evidence

`EtfProfileField` 是 ETF Profile canonical 字段的来源证据。它属于 Core canonicalization 的 provenance，不是通用 Research Evidence 表。

外部新闻、机构观点和评论在没有稳定查询需求与生命周期前，优先作为 Raw/Evidence JSON 保存，不新增专用 Repository。

## 5. Repository admission

只有同时满足以下条件才新增 Repository：

1. 数据具有独立生命周期；
2. 存在稳定查询接口；
3. 需要事务、一致性或并发控制；
4. owner 和唯一写入路径已明确。

优先保留的 Repository：

- `Instrument`
- `DailyBar`
- `EtfProfile`
- `CandidatePoolRun`
- `ResearchCase`

暂不为以下内容建立专用 Repository：

- 新闻；
- 机构评论；
- 未冻结 schema 的 Context Item；
- AI 中间状态；
- 仅用于一次构建的临时 projection。

## 6. Current implementation mapping

| Rule | Current implementation | Governance disposition |
|---|---|---|
| Analytics factor calculation | `invest_domain.analytics.factor_calculators` | Analytics owns calculation; Research path is compatibility-only |
| Evidence Pack | `invest_domain.research.models.EvidencePack` | 保留 Research ownership |
| Context Pack | `invest_domain.research.context` + storage repository | 限定为可重建 projection |
| ETF field evidence | `invest_domain.etf_profile` + `etf_profile_fields` | 保留为 canonical provenance |
| Provider declarations | `invest_pipeline.provider_catalog` | 作为声明权威；Factory/Router 只消费 |
| API use cases | API routers 直接调用 Repository | 记录为后续独立收敛项，不与本轮 Evidence 变更混合 |

## 7. Explicit non-goals

本基线不批准：

- 新 Provider；
- 新策略通道；
- Factor Store、Feature Store、回测或自动交易；
- Agent/Thesis/Report 数据库；
- 把 Context Pack 扩展为全量金融数据仓库。
