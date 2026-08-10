# invest-infra Stage 4B Market Intelligence Foundation

> 文档版本：v2.0
> 状态：Architecture and implementation plan
> 基线：GitHub/Gitee `main`，`8caff0225ff9443b251d31a2f80664e67061af85`
> 前置：Stage 4A 已完成代码级验收；环境级治理收口仍按 Final Acceptance 报告执行

## 1. 目标与范围

Stage 4B 为 AI Research 增加可复现、可追溯的市场上下文事实层。

本阶段不重建 Stage 4A，不修改现有 ETF `EvidencePack` 的固定 8 因子合同，
不新增微服务，不引入自动交易、回测、参数优化或市场智能 UI。

首个可交付切片只实现：

```text
现有 ETF Daily Bars / Factor Observations
            ↓
Analytics Market Observation
            ↓
Market Temperature Snapshot
            ↓
Research Evidence Bundle（按 Case 绑定）
            ↓
Context Projection
            ↓
ResearchRun / AI
```

Market Breadth、Market Style、Theme Intelligence、ETF Rotation 只保留为后续
切片边界，不进入首个实现切片。

## 2. 架构决策

### 2.1 所有权

| 对象 | Owner | 职责 |
|---|---|---|
| `MarketObservationSnapshot` | `Analytics / Market Intelligence` | 基于 Core/Analytics 输入生成可复用的确定性市场事实 |
| `EvidencePack` | `Research` | 按一个 Research Case 冻结现有 ETF/因子证据 |
| `ResearchEvidenceBundle` | `Research` | 绑定 ETF EvidencePack 与 Market Observation 快照，形成 AI 研究输入身份 |
| `ContextProjection` | `Research` | 从 Bundle 重建 AI 可消费的扁平上下文，不作为事实源 |
| `ResearchRun` | `AI Research` | 管理一次 AI 研究执行、重试和外部会话 |
| `ResearchResult` | `AI Research` | 保存观点、风险、报告和 Evidence 引用 |

依赖关系：

```text
Provider / Core
      ↓
Analytics Observation
      ↓
Research Evidence Bundle
      ↓
Context Projection
      ↓
AI Research Result
```

### 2.2 现有 EvidencePack 不变

当前 `EvidencePack` 继续满足以下约束：

- 一个 Research Case 一个不可变证据集合；
- 固定 `etf_market_state_daily / 1.0.0` 8 个因子；
- `pack_hash` 对业务内容确定性计算；
- Factor Observation 自动生成 `item_hash` 和 `evidence_id`；
- AI Result 不修改 EvidencePack。

Market Temperature 不作为第 9 个因子，也不直接追加到现有 `factors` 数组。

### 2.3 MarketObservationSnapshot

`MarketObservationSnapshot` 是 Analytics 所有的、可复用的确定性观察快照。
它不绑定 Research Case，也不包含 AI 观点。

最小合同：

```text
snapshot_id
scope_type              # etf_universe
scope_key               # etf_active_universe_v1
as_of_date
input_snapshot_id
algorithm_version
quality_status
freshness_status
content_hash
observations[]
```

单条 observation：

```text
observation_key
value
unit
observed_date
source_kind
source_ref
quality_status
item_hash
```

首期允许的 `observation_key`：

```text
market_temperature_score
market_temperature_state
market_temperature_breadth_score
market_temperature_momentum_score
market_temperature_liquidity_score
market_temperature_risk_score
```

`state` 是版本化确定性规则的输出，不是 AI stance；`confidence` 不作为投资观点
字段，数据质量使用 `quality_status` 和 `freshness_status` 表达。

### 2.4 ResearchEvidenceBundle

Bundle 是 Research Case 对上游不可变事实的绑定，不复制上游对象的完整生命周期。

最小合同：

```text
bundle_id
research_case_id
evidence_pack_id
market_snapshot_ids[]
schema_version
created_at
bundle_hash
```

`bundle_hash` 必须绑定：

- Research Case 身份和 as-of date；
- ETF EvidencePack 的 ID/hash；
- MarketObservationSnapshot 的 ID/hash；
- Bundle schema version。

运行身份必须能够追溯到 Bundle。为兼容现有 `ResearchRun.evidence_pack_id`，
实施时允许先增加 nullable `evidence_bundle_id`；旧 Run 保持原字段语义，新 Run
必须绑定 Bundle。不得用隐式约定把 Market Observation 拼进旧 Pack payload。

### 2.5 ContextProjection

ContextProjection 是 Bundle 的可重建视图：

- 由 Research/Application 层生成；
- 只读、可替换；
- 输出所有事实的 `evidence_id`、source、observed date、quality 和 hash；
- 不直接查询 Provider，不执行任意 SQL；
- 不拥有独立于 Bundle 的事实版本。

首期不新增 Context Projection Repository；先以应用层 DTO/序列化结果验证接口，
只有出现稳定查询和独立生命周期后才申请持久化 Repository。

## 3. 首期数据范围

### 3.1 Universe

首期市场范围固定为：

```text
etf_active_universe_v1
```

即当前可用的 active ETF Universe，不宣称代表全 A 股市场，不混入股票宽度结论。
Universe 必须通过现有 Input Snapshot/Universe 机制冻结，且每次计算绑定
`input_snapshot_id`。

### 3.2 输入

首期只消费本地已落库的：

- ETF Daily Bars；
- 现有 8 个确定性 ETF 因子；
- 日行情 revision 和质量状态；
- 既有交易日历/as-of 规则。

首期不新增 Provider，不依赖 Go-Goal、理杏仁、集思录 Cookie 或未授权商业数据。

### 3.3 计算合同

Market Temperature 由版本化算法计算。算法必须显式定义：

- eligible ETF 的资格条件；
- breadth、momentum、liquidity、risk 的输入因子和聚合方式；
- 缺失、partial、invalid、stale 的处理；
- Decimal 精度、边界裁剪和排序规则；
- 同日重跑、不同 revision 和不同 universe 的 hash 行为。

首期禁止写入：

```text
buy / sell / stance / thesis / investment_confidence
```

## 4. 存储与接口边界

### 4.1 Storage

只有在 `MarketObservationSnapshot` 具备独立生命周期、稳定查询和事务一致性
需求后，才增加 Analytics-owned migration/repository。首期建议采用：

```text
analytics.market_observation_snapshots
analytics.market_observations
```

要求：

- content hash 唯一；
- 相同输入幂等；
- 不同输入生成新 snapshot，不覆盖历史；
- child observation 不能脱离 snapshot 单独发布；
- upgrade/downgrade 和 PostgreSQL round-trip 有测试。

`ResearchEvidenceBundle` 独立于 Market Observation 生命周期，存储在 Research
所有权下；具体迁移必须在 Task 1 合同冻结后实现。

### 4.2 API

首期只新增一个只读资源接口：

```http
GET /api/v1/market-temperature/latest?as_of_date=YYYY-MM-DD
```

接口必须：

- 只读取已持久化的 Observation；
- 不计算因子、不访问 Provider、不执行外部 Agent；
- 返回 `as_of_date`、scope、algorithm version、quality/freshness、data、evidence_ids、content_hash；
- 数据不存在返回 404；非法日期返回 422；查询异常返回去敏错误；
- 不暴露 Provider key、连接信息、本地路径或任意文件内容。

以下接口暂不新增：

```text
/market-breadth/latest
/market-style/latest
/themes/ranking
/etf-rotation/latest
```

首期不新增 Agent Tool；待 HTTP contract 和 Context Projection 冻结后再决定
是否提供只读 Tool。

## 5. Pipeline 组织

建议新增深模块：

```text
apps/pipeline/src/invest_pipeline/market_intelligence/
    market_temperature.py
```

对外接口保持窄：

```python
build_market_temperature(
    *,
    input_snapshot,
    factor_observations,
    as_of_date,
    algorithm_version,
) -> MarketObservationSnapshot
```

Builder 接收已冻结输入并返回不可变结果；不在 Builder 内部创建数据库 Session、
读取环境变量、调用 Provider 或触发 AI。Storage、Dagster 和 API 通过各自 Adapter
接入该接口。

## 6. 实施阶段

### Phase 0：Contract and ownership freeze

交付：

- `MarketObservationSnapshot`、observation、Bundle、Projection 合同；
- ownership、hash、quality、revision 规则；
- 首期 ETF Universe 和算法版本；
- ADR/架构文档与本计划对齐。

验收：

- 不修改现有 EvidencePack 8 因子合同；
- 能画出唯一的 Observation → Bundle → Projection → Run 链路；
- 所有新增字段有 owner、source、observed date 和 hash 语义。

### Phase 1：Market Observation domain and deterministic builder

交付：

- Analytics-owned domain model；
- hash/canonical serialization；
- fixture ETF universe 的 Market Temperature builder；
- complete/partial/missing/failed 测试。

验收：

- 相同输入 hash、observation ID 完全一致；
- 缺失或 stale 输入 fail closed；
- 算法不产生投资结论；
- 不依赖数据库、Provider 或 AI。

### Phase 2：Persistence and daily orchestration

交付：

- migration、row model、repository、UoW；
- Pipeline/Dagster 显式编排；
- snapshot 幂等和历史保留。

验收：

- PostgreSQL round-trip；
- upgrade/downgrade；
- 相同输入不重复写入；
- revision 不覆盖旧 snapshot；
- 默认无网络副作用。

### Phase 3：Research Bundle and Context Projection

交付：

- Case 对 ETF EvidencePack 与 Market Snapshot 的绑定；
- Bundle hash 和 ResearchRun 新旧字段兼容；
- Context Projection 序列化；
- Evidence ID 校验。

验收：

- Run 能追溯到准确的 ETF Pack 和 Market Snapshot；
- Bundle 变更产生新身份；
- Result 不能修改任何上游事实；
- Fake Runner 能消费 Projection。

### Phase 4：Read-only API and acceptance

交付：

- Market Temperature API；
- OpenAPI 和契约测试；
- API/TestClient/Storage 集成验证；
- Stage 4B Phase 1 验收报告。

验收：

- 200/404/422/安全错误边界通过；
- API 不计算、不访问 Provider、不暴露内部路径；
- OpenAPI、Router、客户端和文档一致；
- 真实 seeded case 可从 Market Observation 追溯到 Research Result。

## 7. 后续切片边界

只有 Phase 0–4 完成后，才分别评估：

1. **Market Breadth**：需要独立股票 Universe、股票行情和市场范围合同；
2. **Market Style**：需要明确风格基准、相对强弱和状态算法；
3. **Theme Intelligence**：需要 Theme 实体、主题来源、行业/主题映射和授权边界；
4. **ETF Rotation**：需要 ETF-Theme 映射、轮动算法和历史可解释性合同。

这些切片不得提前修改首期 Market Temperature 的 Evidence/Bundle 语义。

### 7a. Slice 2：Market Breadth (Contract & Builder, 2026-08)

在 Stage 4B Phase 0–4 完成、Phase 1 验收报告封板后，启动
Slice 2 的 Market Breadth 垂直切片。Slice 2 不动 Market Temperature
Evidence/Bundle 语义，不新增 Provider，不接商业研究数据，不新增 UI
和 Agent Tool。

#### 7a.1 范围与默认值

| 项目 | 默认值 | 备注 |
|---|---|---|
| Universe | `ashare_active_universe_v1` | 全 A 股；不混入 ETF Universe |
| 输入 | `MarketBreadthInput`（逐只股票 close/prev_close/ma20/trading_status） | 由调用方注入；本切片不实现 A 股行情采集 |
| 输出指标（首期三项） | `advancing_ratio` / `declining_ratio` / `above_ma20_ratio` | 单位 `ratio`；clip 至 [0, 1]；8 位小数 `ROUND_HALF_EVEN` |
| Scope | `scope_type=ashare_universe` / `scope_key=ashare_active_universe_v1` | 冻结 |
| Algorithm version | `1.0.0` | 模块级常量；与 Market Temperature 的 `1.0.0` 不冲突 |
| 持久化 | 沿用 `analytics.market_observation_snapshots` / `analytics.market_observations` | 不新增表 |
| API | 本切片**不新增** `/market-breadth/latest` | 待 Slice 3 评估后冻结 OpenAPI 再开 Router |
| Agent Tool | 本切片**不新增** | 同上 |

#### 7a.2 已交付（当前 commit）

- `packages/domain/src/invest_domain/analytics/market_breadth.py`：
  纯函数 `build_market_breadth()` + `MarketBreadthInput` 值对象；deep
  module 边界，零数据库 / Provider / FastAPI / SQLAlchemy / Dagster
  依赖。
- `packages/domain/tests/test_market_breadth.py`：15 个 focused 测试
  覆盖 hash 稳定性、scope/algorithm pin、ratio 计算、clip/quantise、
  empty/stale/unknown/suspended fail-closed、输入校验、不可变性。

#### 7a.3 后续切片边界

1. **Slice 3 — Persistence & Orchestration**：等 A 股 daily bars 接入
   后，再行评估 Repository / 迁移 / Dagster 编排，沿用
   `SqlAlchemyMarketObservationSnapshotRepository` 路径。
2. **Slice 4 — API**：先冻结 OpenAPI contract，再实现 Router。
3. **Slice 5 — Bundle 注册**：在 `ResearchEvidenceBundle` 中
   评估是否把 Market Breadth snapshot 加入绑定候选。
4. **Slice 6 — Provider**：A 股日线 Provider 走现有 Provider Contract
   + Catalog + Data Admission 流程；本切片不得提前引入。

## 8. 安全与非目标

- Agent 不直连数据库；
- Web 不直连 PostgreSQL；
- Provider 凭据不进入 Domain、Evidence、API 响应或报告；
- 不保存任意 workspace 文件路径给客户端；
- 不建设通用 Feature Store、Factor Store、向量数据库或消息队列；
- 不新增微服务；
- 不生成自动交易、仓位或买卖入口。

## 9. Stage 4B 完成标准

首期 Phase 1 完成不等于完整 Stage 4B 完成。首期关闭条件：

- [ ] MarketObservationSnapshot 合同冻结；
- [ ] ETF Market Temperature 算法可复现；
- [ ] hash、quality、freshness、revision 有测试；
- [ ] Observation 持久化幂等并保留历史；
- [ ] ResearchEvidenceBundle 能绑定准确快照；
- [ ] Context Projection 可重建；
- [ ] Fake Runner/ResearchResult 引用链通过；
- [ ] Market Temperature API/OpenAPI 通过；
- [ ] 无 Provider Key、workspace 路径或任意文件泄漏；
- [ ] Stage 4B Phase 1 验收报告可复核。

完整 Market Intelligence（Breadth/Style/Theme/Rotation）另行验收，不作为首期
关闭条件。

## 10. 依赖与阻塞

- Stage 4A Final Acceptance 的环境级治理项完成前，不启动生产市场数据层写入；
  可以先完成 Phase 0 合同、测试夹具和架构文档；
- 任何新 Provider 先通过现有 Provider Contract、Catalog 和 Data Admission 流程；
- 任何新 Repository 先证明独立生命周期、稳定查询和事务需求；
- 任何新增 API 先冻结 OpenAPI，再实现 Router 和客户端。
