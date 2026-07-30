# ADR-0003：Provider 选型与 Adapter 边界

- Status：Proposed（Adapter 边界已冻结；具体 Provider 待用户确认）
- Date：2026-07-30
- Owners：M0 架构基线

## Context

当前生产代码只有 `apps/pipeline/src/invest_pipeline/providers.py` 中的 `MockInstrumentProvider`，且 `packages/domain/src/invest_domain/ports.py` 只定义了简化的主数据端口；仓库没有真实 Provider SDK、凭据、契约 fixture 或授权证明。`apps/pipeline/pyproject.toml` 也尚未声明 `httpx`、重试库或供应商 SDK。因此不能声称真实 Provider 已选定或已接入。

现有边界要求见 `docs/ARCHITECTURE.md`：领域层不得依赖具体 SDK；`docs/plan/invest-infra-v2-etf-vertical-slice-plan.md` 要求真实 ETF 主数据、日行情、错误分类和原始批次证据。现有 `seed_instruments` asset 在 `apps/pipeline/src/invest_pipeline/assets.py` 内同时创建 Provider、Repository 和事务，仅是骨架，不是生产采集边界。

候选方向仅作事实核验清单，不代表仓库已有授权：

| 候选 | 适用判断 | 当前阻塞 |
|---|---|---|
| 经采购批准、提供正式 API 的直接数据供应商 | 推荐方向；应能明确 ETF 覆盖、字段、复权、限频、历史修订和使用权 | 供应商名称、合同、账户能力、端点和 SLA 均未知 |
| Tushare Pro 或类似直接 API | 可作为低复杂度候选进行契约验证 | 权限、积分/额度、ETF 主数据完整性、历史范围和生产使用权待确认 |
| Wind、Choice 等商业终端/API | 可作为组织已有许可时的候选 | 是否已有机器接口许可、部署方式和再分发边界待确认 |
| AkShare 等聚合库 | 仅研究、fixture 或经风险接受的补数候选 | 上游稳定性、授权链、错误契约和生产 SLA 未在仓库中得到证明 |

不得在确认前编造任何候选的价格、授权、额度或 SLA。

## Decision

1. **Provider 最终选型暂不冻结。** 推荐选择“经用户或组织确认授权、能直接提供中国场内 ETF 主数据与未复权日行情的正式 API”。Phase 1 的真实网络接入在用户完成最小确认前阻塞。
2. 用户需最少确认：
   - Provider 法定/产品名称及首选接入方式；
   - 账户是否允许生产自动化调用及系统所需的数据使用方式；
   - 可用的 ETF 主数据、SSE/SZSE 日行情端点和历史范围；
   - `none` 未复权语义、成交量/成交额单位、停牌/缺失规则；
   - 鉴权方式、限频/并发规则和凭据注入渠道。
3. 领域端口放在 `packages/domain`，使用标准领域类型，不暴露 SDK 类型、HTTP response 或数据库 row。端口至少提供主数据查询和按闭区间 `[start_date, end_date]` 获取日行情，返回包含请求元数据、标准化 records、原始 payload 字节或受控证据句柄的 `ProviderBatch`。
4. 具体 client/mapper/adapter 只能位于 `apps/pipeline/src/invest_pipeline/adapters/<provider_key>/`。Adapter 负责鉴权、请求、供应商限流、有限重试、响应解析、字段/错误映射和构造批次结果；不得筛选候选池、开启/提交数据库事务、直接更新发布状态或依赖 API/Web。
5. **`raw.provider_batches` 的持久化归 `packages/storage` Repository 和 Pipeline application service/Unit of Work 所有。** Adapter 只返回 payload 与元数据；application service 在一个明确事务中先登记请求/结果证据，再写标准化数据或失败状态。Dagster asset 仅编排该服务。Adapter 不接收 SQLAlchemy Session。
6. 原始响应采用 PostgreSQL `jsonb` 或 `bytea` 的受控持久化策略；第一阶段不引入对象存储。无论是否保存完整 payload，都必须保存脱敏请求参数、供应商请求 ID（如有）、接收时间、状态、字节级 SHA-256 和错误分类。大响应超出配置上限时必须失败并告警，不能只写一个无法恢复的 URI。
7. `request_key` 标识一次规范化请求意图，不等同于响应版本。失败重试和供应商修订必须可形成不同 attempt/batch 记录；不得以计划文档中的单一唯一键覆盖失败证据。
8. 普通 CI 仅使用脱敏 fixture 和 fake transport；真实 smoke test 显式启用、使用 Secret、默认不在 PR 中执行。

## Consequences

- 真实 Provider 编码被用户确认门禁阻挡，但端口、错误模型、Repository 和 fixture 结构可先实现。
- 原始证据和标准化写入由 application service 协调，可保证事务、幂等和失败审计，而不会污染 Adapter。
- 若后续更换 Provider，仅替换 adapter 和映射；领域契约、修订模型及候选池保持稳定。
- PostgreSQL 需要承担首期原始证据容量，必须设置 payload 上限并监测增长。

## Alternatives

- **直接在 Dagster asset 中调用 SDK 并写库：Rejected。** 当前骨架这样做仅适合 mock，会混合供应商、事务和编排职责。
- **让 Adapter 自己提交 `raw.provider_batches`：Rejected。** 无法由 Unit of Work 原子协调批次状态与标准化写入。
- **立即指定 AkShare 为生产 Provider：Rejected。** 仓库没有授权、上游契约或 SLA 证据。
- **首期同时接入多个 Provider：Rejected。** 增加对账和来源优先级复杂度，且当前没有第二来源需求证据。
