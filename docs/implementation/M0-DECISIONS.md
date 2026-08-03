# M0-DECISIONS

> 适用于 `invest-infra-v2` 仓库；版本 v1.0；日期 2026-07-30。
> 仅在 `docs/adr/` 中相关 ADR 基础上汇总已冻结决策、未决事项和影响范围；不引入新决策。

## 1. 已冻结决策（来自 M0 ADR）

| 主题 | 决策要点 | 引用 |
|---|---|---|
| Provider Adapter 边界 | 端口在 `packages/domain`；Adapter 只放 `apps/pipeline/src/invest_pipeline/adapters/<provider_key>/`，不写库、不筛候选池 | ADR-0003 |
| Provider 选型 | **未冻结**；推荐正式 API；事实清单已列；真实接入前阻塞 | ADR-0003 |
| Adapter 与存储职责 | `raw.provider_batches` 由 storage Repository/Pipeline application service 持久化；Adapter 不接收 Session | ADR-0003 |
| 市场范围 | 仅 SSE/SZSE 场内 ETF；Phase 1 不含港股、北交所、场外 | ADR-0004 |
| 时区 | `Asia/Shanghai`；`trade_date` 是本地交易日；`timestamptz` 存 UTC | ADR-0004 |
| 交易日历 | 版本化日历 + 头表；不能用 Provider 返回隐含决定 | ADR-0004 |
| 复权口径 | 仅 `none`；`qfq/hfq` 保留扩展；切换需要新 ADR | ADR-0005 |
| 单位与数值 | 价格 `Decimal`、币种 CNY、volume 份、amount CNY；`numeric(20,6)` 等精度由存储落库 | ADR-0005 |
| 缺失/停牌 | 停牌行不得伪造 OHLC；Provider 以前收盘填充必须在 fixture 识别 | ADR-0005 |
| DailyBar 主键 | `(instrument_id, trade_date, adjustment, revision)`，附 `CHECK revision>=1` | ADR-0006 |
| revision 行为 | 锁键 + Unit of Work 内比较 `row_hash`；`row_hash` 同则 no-op；不同则 `latest+1` | ADR-0006 |
| latest view | `core.latest_daily_bars` 只读 view；app 不得用其重放历史 | ADR-0006 |
| 历史修订 | 永不 update/delete；新输入快照和候选池新 run 才能引用新版本 | ADR-0006 |
| Snapshot 头 | 不可变；含 schema_version、query_hash、content_sha256、as_of_trade_date 等 | ADR-0007 |
| Snapshot rows | 新表 `analytics.input_snapshot_rows` 精确绑定 revision+row_hash | ADR-0007 |
| Snapshot 哈希 | SHA-256 + canonical JSON Lines；key 字典序；十进制规范化 | ADR-0007 |
| Candidate Pool 状态 | 仅 `calculated/validated/published/rejected`；合法转换已列；终态不可逆 | ADR-0008 |
| 发布指针 | `(trade_date, algorithm_key, parameter_set_key)`；新发布原子替换；旧 `published` 仍记录 `superseded_at` | ADR-0008 |
| 业务唯一性 | `(trade_date, algorithm_key, algorithm_version, parameter_hash, input_snapshot_id)` | ADR-0008 |
| 算法形态 | 纯函数；显式 snapshot/参数/上下文；不访问 IO/时间/环境 | ADR-0008 |
| Python 基线 | CPython 3.12.x；目标 `<3.13`；CI/Ruff/Pyright/Docker runtime 保持 3.12 | ADR-0009 |
| 核心依赖 | 沿用现有声明版本系列；`httpx/tenacity/structlog` 必须先做最小依赖变更再写代码 | ADR-0009 |
| 生产拓扑 | PostgreSQL 16 + 独立 migration job + API + Pipeline + 静态 Web + 既有入口；不引 K8s/Redis/Kafka | ADR-0010 |
| 部署顺序 | 备份点 → 迁移 → Pipeline → API → Web → smoke | ADR-0010 |
| 密钥 | Provider 凭据只注入 Pipeline；非 Git/日志/镜像；可无重建轮换 | ADR-0010 |
| 数据库分权 | `migration_owner/pipeline_writer/api_reader` + 独立备份身份 | ADR-0010 |
| 备份恢复 | 加密异地、完整性校验、WAL/PITR 能力；具体 RPO/RTO 待用户确认 | ADR-0010 |

## 2. 状态机速查

```text
provider_batches.status: requested | succeeded | partial | failed
   ∧
candidate_pool_runs.status: calculated -> validated -> published (终态)
                                       \\-> rejected  (终态)
```

`calculated -> validated` 与 `validated -> published` 必须各自在单一事务中完成并写入状态事件；并发更新失败时不得盲目重试。

## 3. 跨文档不变量

- 交易所以 `SSE`/`SZSE` 为唯一允许值；任何新 exchange 必须先修订 ADR-0004。
- `adjustment` 在生产代码和已发布行中只能出现 `none`；任何出现 `qfq/hfq` 的代码路径必须显式标 `not_production`。
- 候选池状态、snapshot revision、Provider batch 三类证据可相互索引，但不互相替代。
- `raw/core/analytics/ops` 四 schema 是事实基线；`ops.pipeline_runs` 已升级完成（原 `app.pipeline_runs` 已废弃），禁止新逻辑写入 `app` schema。

## 4. 未决事项（需用户确认）

| 编号 | 主题 | 阻塞范围 | 最小确认项 |
|---|---|---|---|
| O-1 | Provider 选型与授权 | M2 Adapter 编码、真实采集 smoke | 法定名称、合同/许可、ETF 字段覆盖、限频/并发、`none` 语义、停牌/缺失规则、历史起点、凭据注入方式 |
| O-2 | 复权算法选择 | M4 算法版本化字段 | 何时引入 `qfq/hfq` 及其公司行动/因子数据源 |
| O-3 | 全历史回补起点 | M3 backfill 默认参数 | `configured_backfill_start` 具体日期与原因 |
| O-4 | 收盘后可用 cutoff | M3 日常 job 调度 | 截止时间、是否节后补数 |
| O-5 | 候选池业务阈值 | M4 黄金样例、生产参数集 | 上市天数、流动性金额、波动、回撤、入选上下限、评分权重、Jaccard 漂移阈值 |
| O-6 | 数据质量数值阈值 | M3 质量规则实现 | 覆盖率、零成交天数、价格跳变、OHLC 浮动容差 |
| O-7 | RPO/RTO 与备份保留 | M6 部署清单 | 时间目标和保留期；首次恢复演练时间窗 |
| O-8 | 告警通道与责任人 | M6 监控配置 | P0/P1 路由与值班安排 |
| O-9 | Dagster 生产运行形态 | M3 job 部署 | daemon vs Kubernetes vs 计划任务、long-running service vs on-demand |
| O-10 | 域名前缀/API URL 边界 | M5 API 设计 | 是否采用 `/v1` 前缀、CORS、运维触发接口鉴权方式 |

## 5. 关键假设

- A1：当前示例阈值仅做架构验证用，不进入生产参数集。
- A2：M1 起 `core.instruments` 主键改为 UUID 不会影响下游，因为 domain 仍以 `Instrument` 实体（稳定 ID）为概念主键。
- A3：M1 已将 `app.pipeline_runs` 迁移/升级为 `ops.pipeline_runs`；迁移完成后禁止再写入 `app` schema。
- A4：候选池业务唯一性在并发插入时由 PostgreSQL `ON CONFLICT` 唯一约束保护；事务级 advisory lock 用于避免无意义的失败/重试。
- A5：日常发布的 publication pointer 替换采用 `INSERT ... ON CONFLICT DO UPDATE` 原子事务；旧 `published` run 保留并标记 `superseded_at`，历史结果仍可查询。

## 6. 影响范围（按 module）

- `apps/pipeline`
  - 新增 `adapters/fixture_dev/`（确定性 fixture，仅 dev/test）；不允许在 production 资产路径下默认启用。Phase 1 运行时仅保留 `fixture_dev`，真实 Provider 待 O-1 确认后接入。
- `apps/api`
  - 新增候选池、freshness、pipeline runs、运维触发接口；只读 publication pointer；不持有 Provider 凭据。
- `apps/web`
  - 调整现有 React 页面，新增候选池、freshness、runs 页；通过 OpenAPI 客户端消费 API。
- `packages/domain`
  - 扩展 `Instrument`/`DailyBar`/`ProviderBatch`/`CandidatePool*` 值对象；新增 `Adjust`/`TradingStatus` 枚举；新增 `CalculationContext`；不引入任何持久化或外部依赖。
- `packages/storage`
  - 新增/迁移模型 `raw.*`, `core.*`（含 `core.latest_daily_bars` view）, `analytics.*`（含 `input_snapshots`, `input_snapshot_rows`, `candidate_pool_runs/items`, `candidate_pool_publications`, 状态事件）, `ops.*`（升级 `pipeline_runs`，新增 `data_quality_results`）。
  - 新增 Unit of Work、Repository 抽象及 SQLAlchemy 2 实现；为 raw/core/analytics 提供事务边界。
- Migrations
  - 新增 `2026MMDD_0002_schemas_raw_analytics_ops.py` 等；每个 schema 一个或一组表，分步上线；不可在一个迁移中混 schema。
- CI/脚本
  - `scripts/check_architecture.py` 增加候选池/状态模型导入边界（domain 不得 import alembic/sqlalchemy.orm Session 等），并把 ruff/pyright/unittest/PostgreSQL 集成测试纳入门禁。
- 部署
  - 引入独立 migration job、Provider Secret 注入位置、生产 `pipeline_writer/api_reader/migration_owner` SQL 角色、备份与恢复 runbook 模板。

## 7. 后续编码代理前置条件

1. 必须已通过用户确认 O-1；否则禁止引入 Provider SDK。
2. 必须已有冻结的 M1 迁移方案（schema 拆 `raw/core/analytics/ops`，并升级 `app.pipeline_runs` 为 `ops.pipeline_runs`）。**状态：已完成**（commit 77a156c）。
3. 必须先有版本化日历与 instrument 主数据；禁止用 Provider 数据替代日历。
4. Provider contract 必须先以 fixture 编写并通过契约测试，再接入真实 HTTP。
5. 候选池算法不得引用计划文档中的示例数字作为生产参数；阈值必须来自用户确认的版本化参数集。
6. 任何 README、CHANGELOG 或 PR 描述不得宣称“生产就绪”，直到 M6 部署演练与 O-7 完成。

## 8. 不可逾越的红线

- 不得修改归档计划 `docs/archive/2026-08-02-stage1/invest-infra-v2-etf-vertical-slice-plan.md` 作为 M0 决策依据；本文件为基线。
- 不得宣称已选定或接入真实 Provider。
- 不得把 `app.pipeline_runs` 当作已完成运行审计（已废弃，请使用 `ops.pipeline_runs`）。
- 不得让 Adapter 提交数据库事务或写 `raw.provider_batches`。
- 不得把 `qfq/hfq` 行作为生产数据。
- 不得在 M0 文档阶段安装依赖、运行迁移、提交或发布。
