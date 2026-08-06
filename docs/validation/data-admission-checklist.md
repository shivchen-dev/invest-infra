# 新数据准入评审清单

状态：治理流程基线。任何新增 Provider Dataset、Canonical Data 或 Research
Evidence 类型，进入实现前必须完成本清单；未通过的提案只能保留为实验性
原始证据，不得进入生产链或新增 Repository。

## 1. 登记表

| 字段 | 必填内容 |
|---|---|
| `proposal_key` | 稳定、唯一的提案标识 |
| `dataset_key` | Provider Catalog 中的 dataset 标识；不得复用语义不同的旧 key |
| `research_question` | 它支持的明确 AI/研究问题 |
| `owner` | Core / Analytics / Research / AI 之一 |
| `source_tier` | Primary / Secondary / Experimental |
| `source_ref` | Provider、dataset、payload 或 evidence 来源 |
| `maturity_level` | L0 Raw / L1 Evidence / L2 Canonical / L3 Research capability |
| `retention` | 保存周期、hash、provenance 和修订策略 |
| `query_need` | 是否有稳定、可复用的查询需求 |
| `repository_need` | 若需要 Repository，说明生命周期、事务和唯一写入路径 |
| `canonical_target` | 若进入 Canonical，说明唯一 owner、schema 和冲突处理 |
| `evidence_target` | 若进入 Evidence，说明 Research Case 绑定和重建路径 |
| `decision` | reject / raw-only / evidence-only / canonical |

## 2. 阻断式评审

按顺序回答；任何一项为“否”都不得升级为 Canonical 或新增 Repository。

1. 是否支持一个具体、可验证的研究问题？否则 `reject`。
2. 是否已有可消费的 Core/Analytics owner？没有则先补 ownership，不新建平行模型。
3. 是否能保留 provider、dataset、观察时间、payload/hash 和 provenance？不能则 `raw-only`。
4. 是否需要稳定查询、独立生命周期和事务一致性？不需要则不建 Repository。
5. 是否有明确的唯一写入路径、版本/修订策略和冲突处理？没有则不得进入 Canonical。
6. 是否能由上游事实重建 Evidence/Context projection？不能则不得进入 Research Evidence。
7. Provider 是否为 Experimental？是则只能 `raw-only` 或隔离实验，不得进入生产链。

## 3. 决策规则

- `reject`：不支持当前研究问题，或会制造重复模型。
- `raw-only`：保留原始 payload 和 provenance，暂不建稳定业务模型。
- `evidence-only`：绑定具体 Research Case/Evidence Pack，不建立通用数据表。
- `canonical`：只有 owner、schema、查询、生命周期和写入路径全部冻结后才允许。
- 任何 `canonical` 决策必须同时更新 Provider Catalog、Data Ownership 映射、
  Repository admission 记录和测试/校验入口。

## 4. 最小审计记录

每个已决策提案至少保留：提案文件或 PR 链接、评审人、决策日期、决策结果、
拒绝/降级原因、关联 Provider/Dataset、验证命令和后续复审日期。该记录是
治理证据，不等同于业务数据表。

## 5. 当前执行状态

- 流程：已冻结。
- 已批准新增数据：无；本清单不授权新增 Provider。
- 下一步：`data_freshness` API/Application 边界收敛；新数据提案必须先引用本清单。
