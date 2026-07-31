# invest-infra V2 偏移修复与垂直链路纠偏实施方案

> 适用仓库：`shivchen-dev/invest-infra`  
> 基线分支：`main`  
> 审查基线提交：`e09ceaf615179c2b8b64c9b3fd95fc802d1921d9`  
> 文档目标：纠正当前 V2 项目的实施节奏与局部架构偏移，并尽快完成  
> **真实 ETF Provider → ETF 日行情 → 数据质量 → 输入快照 → 候选池 → 发布 → API**  
> 的生产级闭环。

---

## 1. 结论

当前项目没有重新退化成 V1 的技术栈，但已出现两类偏移：

1. **实施节奏偏移**  
   代码主要集中在领域契约、Provider 注册框架、Repository、迁移兼容和大量测试，真实数据垂直链路尚未形成。

2. **局部决策偏移**  
   包括：
   - `app.pipeline_runs` 与已冻结的 `ops.pipeline_runs` 决策冲突；
   - greenfield 项目引入 `_instruments_legacy` 影子表迁移；
   - Provider 失败批次必须具备 payload hash；
   - Provider 请求重试证据与唯一约束冲突；
   - Candidate Pool 完整性校验存在漏洞；
   - Python 版本范围与 ADR 不一致；
   - CI 未真正执行完整测试和 PostgreSQL 迁移验证。

本修复方案不推倒现有 V2 架构，保留以下正确资产：

- `apps/api`、`apps/pipeline`、`apps/web` 独立运行单元；
- `packages/domain` 零第三方依赖；
- `packages/storage` 独立 SQLAlchemy 实现；
- PostgreSQL 作为首期唯一持久化基础设施；
- FastAPI、Dagster、React；
- Provider Adapter 边界；
- DailyBar revision、input snapshot、候选池版本化和可解释性设计；
- 不引入 Redis、Kafka、Celery、Kubernetes；
- 不迁移旧系统数据。

---

# 2. 修复目标

修复完成后，项目必须具备以下状态：

```text
一个已冻结的真实 ETF Provider
        ↓
真实 ETF 主数据
        ↓
真实未复权 ETF 日行情
        ↓
raw.provider_batches 审计证据
        ↓
core.instruments / core.daily_bars
        ↓
ops.data_quality_results
        ↓
analytics.input_snapshots
        ↓
纯函数 Candidate Pool
        ↓
analytics.candidate_pool_*
        ↓
validated / published
        ↓
FastAPI 查询接口
```

核心验收原则：

- 不再继续横向增加 Provider、领域抽象和 Repository，直到该链路跑通。
- 所有数据和计算结果可追溯到真实 Provider 请求。
- 所有失败请求可保存独立 attempt 证据。
- 所有候选池结果绑定不可变输入快照。
- 默认 API 只返回 `published` 结果。
- CI 在空 PostgreSQL 中执行真实迁移和集成测试。

---

# 3. 修复优先级

## P0：阻塞真实垂直链路

必须先修复：

1. 压平未上线迁移链。
2. 移除 `app.pipeline_runs`，改为 `ops.pipeline_runs`。
3. 删除 `_instruments_legacy` 兼容迁移。
4. 修正 Provider 失败批次模型。
5. 修正 Provider request/attempt 幂等模型。
6. 修正 Candidate Pool 完整性约束。
7. 冻结并实现一个真实 Provider。
8. 建立 `core.daily_bars` 和真实行情落库流程。

## P1：发布前修复

1. 将 Alembic 迁移从 API 运行单元中分离。
2. 统一 Python 3.12 版本范围。
3. 补齐 CI 的真实测试门禁。
4. 扩展架构边界检查。
5. 删除当前垂直链路无关的运行时 Provider 注册。
6. 建立 GitHub Issue、PR 和分支保护流程。

## P2：首个生产版本前完成

1. API 和数据新鲜度页面。
2. 候选池发布指针。
3. 告警和 Runbook。
4. 数据库最小权限账户。
5. 备份与恢复演练。

---

# 4. 总体执行原则

## 4.1 修复期间冻结范围

修复期间暂停以下开发：

- RSSCast Provider；
- Quicktiny MCP Provider；
- 新闻和报告；
- 股票和指数行情；
- 多 Provider 自动切换；
- 分钟行情；
- 完整 FQIR；
- 回测；
- 用户组合；
- 复杂前端页面；
- Redis、MinIO、消息队列；
- 新的通用插件框架；
- 新增 Candidate Pool 抽象层；
- 为当前未上线数据库继续编写兼容迁移。

允许开发范围：

```text
数据库基线
Provider 请求证据
真实 ETF 主数据
真实 ETF 日行情
数据质量
输入快照
候选池最小算法
发布
查询 API
```

## 4.2 每个 PR 必须形成增量闭环

禁止再出现：

```text
只增加接口
只增加数据类
只增加 Registry
只增加 Repository
只增加测试计划
```

每个 PR 至少包含：

```text
领域契约
+ 实现
+ 持久化或运行接线
+ 自动测试
+ 可执行验收命令
```

## 4.3 不以测试数量代替业务完成度

测试验收应回答：

- 真实请求是否成功；
- 失败请求是否保留证据；
- 日行情是否落库；
- 质量失败是否阻止发布；
- 相同输入是否幂等；
- 候选池是否可解释；
- API 是否能查询已发布结果。

不再以“新增多少个 Mock 测试”作为主要完成指标。

---

# 5. PR 1：压平数据库基线

## 5.1 目标

在首次正式部署前，删除当前 `0001～0004` 的演进兼容历史，生成一个干净的 greenfield 基线迁移。

## 5.2 前置条件

仅在以下条件成立时执行：

- 当前 V2 数据库没有需要保留的生产数据；
- 没有其他生产环境依赖当前 migration revision；
- 当前部署可以删除数据库并从空库重建。

若已经存在不可丢弃的生产数据，本 PR 不得压平迁移，应改为前向修复迁移，并单独制定数据保留方案。

## 5.3 删除内容

删除：

```text
apps/api/migrations/versions/20260730_0001_initial.py
apps/api/migrations/versions/20260730_0002_instruments_uuid_identity.py
apps/api/migrations/versions/20260730_0003_provider_batches_raw_evidence.py
apps/api/migrations/versions/20260730_0004_pipeline_runs_updated_at.py
tests/test_increment2_migrations_ast.py
```

删除数据库对象设计：

```text
core._instruments_legacy
app.pipeline_runs
app schema
```

## 5.4 新建迁移运行单元

推荐结构：

```text
apps/
  migrations/
    pyproject.toml
    alembic.ini
    migrations/
      env.py
      script.py.mako
      versions/
        20260731_0001_v2_baseline.py
```

`apps/migrations` 依赖：

```toml
[project]
name = "invest-migrations"
requires-python = ">=3.12,<3.13"
dependencies = [
  "invest-storage",
  "alembic>=1.18,<2",
  "sqlalchemy>=2.0.51,<2.1",
  "psycopg[binary]>=3.3.4,<4",
]
```

API 生产依赖中删除：

```text
alembic
```

## 5.5 新基线 Schema

```text
raw
core
analytics
ops
```

本 PR 首先创建：

```text
raw.provider_requests
raw.provider_attempts
raw.provider_batches
core.instruments
ops.pipeline_runs
```

可在 PR 3/4 增加：

```text
core.daily_bars
core.latest_daily_bars
ops.data_quality_results
```

也可以在基线迁移中直接一次性创建当前已冻结的最终最小结构，但必须避免创建尚未设计完成的大量未来表。

## 5.6 `core.instruments`

建议结构：

```sql
CREATE TABLE core.instruments (
    id uuid PRIMARY KEY,
    symbol varchar(32) NOT NULL,
    exchange varchar(16) NOT NULL,
    name varchar(160) NOT NULL,
    instrument_type varchar(24) NOT NULL,
    currency varchar(8) NOT NULL DEFAULT 'CNY',
    list_date date,
    delist_date date,
    status varchar(24) NOT NULL,
    underlying_index varchar(64),
    category varchar(80),
    provider_symbol_map jsonb NOT NULL DEFAULT '{}',
    valid_from date,
    valid_to date,
    source_provider varchar(64),
    source_updated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

约束：

```text
UNIQUE(symbol, exchange) WHERE valid_to IS NULL
exchange IN ('SSE', 'SZSE')
status IN ('active', 'suspended', 'delisted', 'unknown')
valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
delist_date IS NULL OR list_date IS NULL OR delist_date >= list_date
```

不再保留重复语义字段：

```text
is_active
status
```

建议只保留 `status`，并通过：

```text
status = active
```

判断活跃标的。

## 5.7 `ops.pipeline_runs`

结构建议：

```sql
CREATE TABLE ops.pipeline_runs (
    id uuid PRIMARY KEY,
    orchestrator_run_id varchar(128),
    job_key varchar(120) NOT NULL,
    partition_key varchar(64),
    trigger_type varchar(32) NOT NULL,
    status varchar(24) NOT NULL,
    algorithm_version varchar(80),
    config_snapshot jsonb NOT NULL DEFAULT '{}',
    started_at timestamptz,
    finished_at timestamptz,
    error_code varchar(64),
    error_summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

状态：

```text
queued
running
succeeded
partial
failed
cancelled
```

不要把业务候选池状态和流水线运行状态混在同一状态机中。

## 5.8 验收标准

- [ ] 从空数据库执行 `alembic upgrade head` 成功。
- [ ] 迁移后不存在 `app` Schema。
- [ ] 迁移后不存在 `_legacy` 表。
- [ ] 迁移只有一个 head。
- [ ] ORM metadata 与数据库无漂移。
- [ ] API 镜像不安装 Alembic。
- [ ] Migration Job 独立执行。
- [ ] PostgreSQL 集成测试真实运行。

---

# 6. PR 2：修正 Provider 请求、Attempt 和 Batch 模型

## 6.1 问题

当前模型将逻辑请求、请求尝试、Provider 响应批次混为一体。

导致：

- 同一请求重试时唯一键冲突；
- 失败 attempt 无响应体却被要求提供 payload hash；
- 无法区分网络失败、鉴权失败、HTTP 错误和数据契约失败；
- 更新同一行可能覆盖历史失败证据。

## 6.2 推荐三层模型

```text
ProviderRequest
    逻辑业务请求

ProviderAttempt
    一次真实网络或 SDK 尝试

ProviderBatch
    一次成功或部分成功解析出的标准化批次
```

## 6.3 `raw.provider_requests`

```sql
CREATE TABLE raw.provider_requests (
    id uuid PRIMARY KEY,
    provider_key varchar(64) NOT NULL,
    dataset_key varchar(64) NOT NULL,
    logical_request_key varchar(128) NOT NULL,
    request_params jsonb NOT NULL,
    requested_by_run_id uuid,
    status varchar(24) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(provider_key, dataset_key, logical_request_key)
);
```

状态：

```text
pending
running
succeeded
partial
failed
```

## 6.4 `raw.provider_attempts`

```sql
CREATE TABLE raw.provider_attempts (
    id uuid PRIMARY KEY,
    provider_request_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    provider_request_id_text varchar(128),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status varchar(32) NOT NULL,
    http_status integer,
    error_stage varchar(32),
    error_code varchar(64),
    error_message text,
    response_payload_sha256 varchar(64),
    response_payload_json jsonb,
    response_payload_uri text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(provider_request_id, attempt_no)
);
```

状态：

```text
running
succeeded
failed
```

`error_stage`：

```text
configuration
authentication
rate_limit
dns
connect
tls
timeout
http
provider
decode
contract
storage
```

约束：

```text
status = succeeded
    → response_payload_sha256 必须存在

status = failed
    → error_stage、error_code 必须存在
    → response_payload_sha256 可为空
```

## 6.5 `raw.provider_batches`

```sql
CREATE TABLE raw.provider_batches (
    id uuid PRIMARY KEY,
    provider_request_id uuid NOT NULL,
    provider_attempt_id uuid NOT NULL,
    provider_key varchar(64) NOT NULL,
    dataset_key varchar(64) NOT NULL,
    record_count integer NOT NULL,
    payload_sha256 varchar(64) NOT NULL,
    warnings jsonb NOT NULL DEFAULT '[]',
    status varchar(24) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

状态：

```text
succeeded
partial
```

失败不创建 `ProviderBatch`，失败证据只保存在 `ProviderAttempt`。

## 6.6 领域契约调整

将当前：

```python
ProviderBatchStatus.FAILED
```

删除，或仅用于兼容期但不进入持久化。

建议新增：

```python
class ProviderAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderFailureStage(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    DNS = "dns"
    CONNECT = "connect"
    TLS = "tls"
    TIMEOUT = "timeout"
    HTTP = "http"
    PROVIDER = "provider"
    DECODE = "decode"
    CONTRACT = "contract"
```

`ProviderBatch` 只表示成功或部分成功的数据批次：

```python
class ProviderBatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
```

## 6.7 重试策略

Application Service 控制重试，不由 Domain 或 Repository 控制。

伪代码：

```python
request = provider_requests.get_or_create(logical_request_key)

for attempt_no in range(1, max_attempts + 1):
    attempt = attempts.start(request.id, attempt_no)

    try:
        raw_response = provider_client.fetch(...)
        batch = adapter.map_response(raw_response)
        attempts.mark_succeeded(attempt.id, raw_response.hash)
        batches.add(batch)
        provider_requests.mark_succeeded(request.id)
        return batch

    except RetryableProviderError as exc:
        attempts.mark_failed(
            attempt.id,
            stage=exc.stage,
            code=exc.code,
            message=exc.safe_message,
        )
        if attempt_no == max_attempts:
            provider_requests.mark_failed(request.id)
            raise

    except PermanentProviderError:
        attempts.mark_failed(...)
        provider_requests.mark_failed(request.id)
        raise
```

## 6.8 验收标准

- [ ] 超时失败可以保存且不要求 payload hash。
- [ ] HTTP 401 可以保存独立失败证据。
- [ ] 同一逻辑请求可以有多个 attempt。
- [ ] 第三次成功不会覆盖前两次失败。
- [ ] 相同逻辑请求成功后可幂等复用。
- [ ] 日志不包含 token、Cookie 和完整敏感响应。
- [ ] Provider Adapter 不接收数据库 Session。
- [ ] Repository 不负责网络重试。

---

# 7. PR 3：修正 Candidate Pool 领域契约

## 7.1 完整性不变量

当前候选池结果必须改为强相等校验：

```python
len(items) == summary.input_count

summary.included_count + summary.excluded_count == summary.input_count

summary.included_count == sum(item.included for item in items)

summary.excluded_count == sum(not item.included for item in items)
```

入选排名：

```text
rank 必须唯一
rank 必须从 1 连续到 included_count
rank 不得超过 selection.max_candidates
```

每个输入标的：

```text
必须恰好出现一次
```

排除项：

```text
必须至少包含一个 exclusion reason
不得带 rank
total_score 可按算法策略选择保留或为空
```

建议保留排除项的 `total_score`，因为硬过滤未通过与综合分不足是两类不同结果。若保留为空，应在契约中明确。

## 7.2 补齐实际阈值字段

当前 Policy 只有窗口，没有足够业务阈值。

修正为：

```python
@dataclass(frozen=True, slots=True)
class LiquidityCriteria:
    lookback_days: int
    min_valid_days: int
    min_median_amount_cny: Decimal


@dataclass(frozen=True, slots=True)
class RiskCriteria:
    volatility_lookback_days: int
    max_annualized_volatility: Decimal
    drawdown_lookback_days: int
    max_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class PriceQualityCriteria:
    lookback_days: int
    max_missing_ratio: Decimal
    max_zero_volume_days: int
    max_stale_price_days: int
```

O-5 未确认时：

- 不提供生产默认值；
- 测试使用 fixture policy；
- 生产启动若没有版本化参数集则直接失败；
- 不把计划文档示例数字隐式作为生产参数。

## 7.3 Policy 哈希

参数哈希必须包含所有影响结果的字段：

```text
algorithm_key
algorithm_version
parameter_set_key
eligibility
liquidity
price_quality
risk
selection
score_weights
hash_schema_version
```

新增阈值后同步更新：

```text
compute_parameter_hash()
golden tests
数据库唯一约束
```

## 7.4 候选池状态

保留：

```text
calculated
validated
published
rejected
```

增加发布指针表：

```sql
CREATE TABLE analytics.candidate_pool_publications (
    trade_date date NOT NULL,
    algorithm_key varchar(64) NOT NULL,
    parameter_set_key varchar(64) NOT NULL,
    candidate_pool_run_id uuid NOT NULL,
    published_at timestamptz NOT NULL,
    PRIMARY KEY(trade_date, algorithm_key, parameter_set_key)
);
```

新的发布在单一事务中替换 pointer，不修改旧运行的业务结果。

## 7.5 验收标准

- [ ] `items` 数量必须等于输入数量。
- [ ] 汇总计数与 items 计算结果一致。
- [ ] rank 唯一且连续。
- [ ] 参数哈希覆盖全部阈值。
- [ ] 同一输入和参数重复计算结果完全一致。
- [ ] 终态不可逆。
- [ ] 默认查询只通过 publication pointer 获取结果。

---

# 8. PR 4：缩减 Provider 运行时范围并冻结主 Provider

## 8.1 删除当前无关运行时注册

从生产 Registry 和 Settings 中移除：

```text
rsscast
quicktiny_mcp
股票行情能力
指数行情能力
研究和报告能力
```

可以保留在：

```text
docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md
```

但不进入：

- ProviderFactory；
- 生产环境变量；
- 当前 CI 契约矩阵；
- Dagster Resources；
- 当前 API。

## 8.2 当前运行时只保留

```text
fixture_dev
primary_etf_provider
```

其中：

- `fixture_dev` 只能在 `dev/test` 环境启用；
- `production` 环境若选择 `fixture_dev` 必须启动失败；
- 主 Provider 通过明确配置启用；
- 不做自动多 Provider fallback。

## 8.3 冻结 Provider 所需决策

在编码真实请求前，建立新 ADR：

```text
docs/adr/0011-primary-etf-provider.md
```

必须确认：

- Provider 法定名称；
- 授权范围；
- ETF 主数据字段覆盖；
- 未复权日行情语义；
- SSE/SZSE 代码规范；
- 停牌返回规则；
- 缺失日期规则；
- 历史数据起点；
- API 限频；
- 并发限制；
- 鉴权方式；
- 凭据注入方式；
- 是否会修订历史数据；
- 真实 smoke test 是否允许在 CI 外执行。

## 8.4 AkShare 特别修正

当前代码把 AkShare 建模为带：

```text
token
base_url
```

但实际使用方式必须以所选库或服务的真实接口为准，不能为了统一配置而虚构 token/base URL。

若选择 AkShare Python 库：

```text
不应要求 AKSHARE_TOKEN
不应配置 example.invalid base_url
应在 pipeline pyproject 增加明确版本约束
应确认其上游数据接口稳定性和授权边界
```

若使用的是其他名为 AkShare 的代理服务，应在 ADR 中明确其真实服务身份，不能与开源 Python 库混淆。

## 8.5 验收标准

- [ ] 生产 Registry 只有 fixture 和一个真实 Provider。
- [ ] production 禁止 fixture。
- [ ] Provider 选择有正式 ADR。
- [ ] 配置字段对应真实接口，不存在伪造 token/base_url。
- [ ] Adapter 的 fixture 契约测试通过。
- [ ] 真实 smoke test能获得 ETF 主数据和一天日行情。
- [ ] smoke test 结果不提交敏感原始数据。

---

# 9. PR 5：实现真实 ETF 主数据链路

## 9.1 资产

新增 Dagster asset：

```text
etf_instruments_provider_request
etf_instruments_raw_batch
etf_instruments_normalized
etf_instruments_quality
```

也可简化为两个业务资产：

```text
etf_instruments_raw
etf_instruments
```

但内部必须记录 request、attempt 和 batch。

## 9.2 Application Service

建议：

```python
class SyncEtfInstruments:
    def __init__(
        self,
        provider: EtfMarketDataProvider,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        ...

    def execute(self, as_of: date, pipeline_run_id: UUID) -> SyncResult:
        ...
```

职责：

1. 创建逻辑 Provider Request。
2. 执行重试。
3. 保存 Attempt。
4. 保存 Batch。
5. 标准化 Instrument。
6. 执行主数据质量检查。
7. 在事务中 upsert。
8. 返回运行摘要。

## 9.3 主数据 upsert 规则

业务键：

```text
symbol + exchange
```

变化处理：

- 名称变化：更新当前版本并记录审计；
- category 变化：更新并记录来源；
- status 变化：更新；
- delist：设置 `status=delisted` 和 `delist_date`；
- Provider 本次未返回某 ETF：不能直接判定退市；
- Provider Symbol 映射保存在 `provider_symbol_map`。

## 9.4 质量规则

P0：

```text
symbol 为空
exchange 非 SSE/SZSE
同一批次业务键重复
活跃 ETF 总数低于最小保护值
总量较上次成功批次异常下降
```

P1：

```text
名称为空
上市日期缺失率异常
category 缺失率异常
```

## 9.5 验收标准

- [ ] 真实 Provider 返回 ETF 主数据。
- [ ] 数据写入 `core.instruments`。
- [ ] 重复执行不会生成重复标的。
- [ ] Provider Request、Attempt、Batch 可追踪。
- [ ] 异常数量下降会阻止数据发布。
- [ ] Pipeline Run 正确标记成功或失败。
- [ ] fixture E2E 和真实 smoke 均通过。

---

# 10. PR 6：实现真实 ETF 日行情链路

## 10.1 `core.daily_bars`

```sql
CREATE TABLE core.daily_bars (
    instrument_id uuid NOT NULL,
    trade_date date NOT NULL,
    adjustment varchar(8) NOT NULL,
    revision integer NOT NULL,
    open numeric(20,6),
    high numeric(20,6),
    low numeric(20,6),
    close numeric(20,6),
    prev_close numeric(20,6),
    volume numeric(28,4),
    amount numeric(28,4),
    trading_status varchar(24) NOT NULL,
    currency varchar(8) NOT NULL,
    source_provider varchar(64) NOT NULL,
    source_batch_id uuid NOT NULL,
    observed_at timestamptz NOT NULL,
    row_hash varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(instrument_id, trade_date, adjustment, revision)
);
```

约束：

```text
adjustment = 'none'
revision >= 1
价格非负或在停牌规则下为空
volume >= 0
amount >= 0
row_hash 是 64 位小写 hex
```

## 10.2 Latest View

```sql
CREATE VIEW core.latest_daily_bars AS
SELECT DISTINCT ON (instrument_id, trade_date, adjustment)
       *
FROM core.daily_bars
ORDER BY instrument_id, trade_date, adjustment, revision DESC;
```

业务计算若需要历史可重放，不得直接依赖 latest view；必须通过 input snapshot 固定 revision。

## 10.3 Revision 规则

事务内：

```text
查询当前最大 revision 和最新 row_hash
```

若：

```text
row_hash 相同
→ no-op
```

若：

```text
row_hash 不同
→ revision + 1
→ 插入新行
```

永不更新或删除旧 revision。

并发保护：

```text
PostgreSQL advisory lock
或
SELECT ... FOR UPDATE
```

## 10.4 Dagster 分区

使用交易日分区：

```text
YYYY-MM-DD
```

禁止以执行日期代替交易日期。

资产：

```text
etf_daily_bars_raw
etf_daily_bars
etf_daily_bars_quality
```

作业：

```text
daily_close_job
backfill_daily_bars_job
```

## 10.5 数据质量

Error：

```text
返回 trade_date 与分区不一致
OHLC 关系错误
价格为负
成交量或成交额为负
重复业务键
覆盖率低于 error 阈值
数据新鲜度超过 cutoff
Provider 返回不支持的复权口径
```

Warn：

```text
零成交
涨跌幅异常
价格跳变
部分标的缺失
```

## 10.6 验收标准

- [ ] 可采集指定交易日。
- [ ] 可回补日期范围。
- [ ] 日行情写入 `core.daily_bars`。
- [ ] 相同数据重跑 no-op。
- [ ] 历史修订生成新 revision。
- [ ] 质量 error 阻止后续计算。
- [ ] 单日失败不污染其他分区。
- [ ] Pipeline Run、Request、Attempt、Batch 可串联追踪。

---

# 11. PR 7：实现 Input Snapshot

## 11.1 表结构

```sql
CREATE TABLE analytics.input_snapshots (
    id uuid PRIMARY KEY,
    dataset_key varchar(64) NOT NULL,
    trade_date date NOT NULL,
    schema_version integer NOT NULL,
    query_definition jsonb NOT NULL,
    query_hash varchar(64) NOT NULL,
    row_count integer NOT NULL,
    content_sha256 varchar(64) NOT NULL,
    min_observed_at timestamptz,
    max_observed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

```sql
CREATE TABLE analytics.input_snapshot_rows (
    input_snapshot_id uuid NOT NULL,
    position integer NOT NULL,
    instrument_id uuid NOT NULL,
    trade_date date NOT NULL,
    adjustment varchar(8) NOT NULL,
    revision integer NOT NULL,
    row_hash varchar(64) NOT NULL,
    PRIMARY KEY(input_snapshot_id, position),
    UNIQUE(input_snapshot_id, instrument_id)
);
```

## 11.2 生成规则

1. 查询参与候选池的有效 ETF。
2. 读取需要的日行情窗口。
3. 固定每一行 revision。
4. 按稳定键排序：
   ```text
   exchange
   symbol
   trade_date
   revision
   ```
5. 生成 canonical JSON Lines。
6. 计算 SHA-256。
7. 保存 Snapshot Header 和 Rows。
8. Snapshot 一经创建不可修改。

## 11.3 幂等

唯一性建议：

```text
dataset_key
trade_date
query_hash
content_sha256
```

相同数据快照重复生成应复用已有 snapshot。

## 11.4 验收标准

- [ ] Snapshot 精确绑定每条 DailyBar revision。
- [ ] Snapshot 不依赖 latest view 动态变化。
- [ ] 相同输入生成相同 hash。
- [ ] 任一行修订会生成不同 Snapshot。
- [ ] Snapshot 不可更新。
- [ ] 可从 Snapshot 还原候选池输入。

---

# 12. PR 8：实现最小 Candidate Pool 算法

## 12.1 第一版范围

只实现 4～6 条规则：

```text
交易所资格
上市天数
当前交易日行情存在
流动性
价格数据质量
波动/回撤
```

不要迁移完整 FQIR。

## 12.2 纯函数

```python
def build_candidate_pool(
    instruments: Sequence[Instrument],
    histories: Mapping[InstrumentId, Sequence[DailyBar]],
    policy: CandidatePoolPolicy,
    context: CalculationContext,
) -> CandidatePoolResult:
    ...
```

禁止：

```text
数据库访问
Provider 调用
环境变量
datetime.now()
文件 IO
网络 IO
全局配置
```

## 12.3 输出要求

每个输入 ETF 都必须生成：

```text
included
rank
total_score
metrics
rule_results
exclusion_reasons
```

示例：

```json
{
  "instrument_id": "...",
  "included": false,
  "rank": null,
  "total_score": "41.32",
  "metrics": {
    "listing_days": 32,
    "median_amount_20d": "8200000",
    "annualized_volatility_20d": "0.51"
  },
  "rule_results": [
    {
      "rule_key": "min_listing_days",
      "passed": false,
      "value": "32",
      "threshold": "60"
    }
  ],
  "exclusion_reasons": [
    {
      "code": "min_listing_days",
      "message": "上市时间不足"
    }
  ]
}
```

## 12.4 存储

```text
analytics.candidate_pool_runs
analytics.candidate_pool_items
analytics.candidate_pool_state_events
analytics.candidate_pool_publications
```

## 12.5 质量门禁

发布前：

- 输入数量不低于保护值；
- 每个输入标的有唯一结果；
- 入选排名连续；
- 所有排除项有原因；
- 无 NaN、Infinity；
- 入选数量在参数范围；
- 数据质量无 Error；
- 与上一已发布结果差异超过阈值时要求人工批准或拒绝发布。

## 12.6 验收标准

- [ ] 算法使用真实日行情。
- [ ] 相同 Snapshot 和 Policy 结果稳定。
- [ ] 算法版本升级不覆盖旧结果。
- [ ] 所有输入 ETF 可解释。
- [ ] 质量失败不能发布。
- [ ] 发布指针原子切换。
- [ ] 可查询历史运行和当前发布版本。

---

# 13. PR 9：API 最小查询闭环

## 13.1 接口

```http
GET /v1/health
GET /v1/instruments
GET /v1/data-freshness
GET /v1/pipeline-runs
GET /v1/pipeline-runs/{run_id}
GET /v1/candidate-pools/latest
GET /v1/candidate-pools/{run_id}
GET /v1/candidate-pools/{run_id}/items
GET /v1/candidate-pools/{run_id}/items/{symbol}
```

## 13.2 默认规则

`latest` 必须读取：

```text
analytics.candidate_pool_publications
```

不能使用：

```text
ORDER BY created_at DESC LIMIT 1
```

否则未验证或已拒绝的结果可能被展示。

## 13.3 API 边界

API：

- 只读数据库；
- 不安装 Provider SDK；
- 不持有 Provider 凭据；
- 不执行候选池算法；
- 不触发 Shell；
- 不直接操作 Dagster 内部数据库；
- 不承担迁移。

## 13.4 验收标准

- [ ] API 只能读取 published 结果。
- [ ] 能查看某 ETF 入选或排除原因。
- [ ] 能追踪 Candidate Pool → Snapshot → DailyBar revision → Provider Batch。
- [ ] API 使用只读数据库账户。
- [ ] OpenAPI 可生成 TypeScript Client。
- [ ] API 集成测试使用真实 PostgreSQL。

---

# 14. PR 10：CI 与架构门禁修复

## 14.1 Python 版本统一

所有项目修改为：

```toml
requires-python = ">=3.12,<3.13"
```

CI、Docker 和本地文档全部固定：

```text
CPython 3.12.x
```

若需要支持 3.13，必须先修改 ADR 并验证依赖兼容性。

## 14.2 CI Job

```yaml
jobs:
  architecture:
  domain-tests:
  storage-unit-tests:
  storage-integration-tests:
  migration-tests:
  api-tests:
  pipeline-tests:
  web-tests:
  container-build:
  secret-scan:
```

## 14.3 真实迁移测试

CI 中启动 PostgreSQL 16：

```text
创建空库
alembic upgrade head
alembic current
alembic check
运行 storage integration tests
```

可以增加：

```text
upgrade head
downgrade base
upgrade head
```

但仅限迁移支持安全 downgrade 的阶段；生产迁移不应假设所有 destructive migration 可回滚。

## 14.4 删除过度静态迁移测试

删除或缩减依赖 AST 检查迁移实现细节的测试。

保留：

- migration chain 单 head；
- 禁止修改已发布迁移；
- 真实数据库 upgrade；
- 表、约束和 view 集成验证。

不要测试：

```text
某迁移必须使用 shadow rename
某函数必须调用 uuid.uuid4
某条 SQL 必须以特定代码形式出现
```

测试行为，不测试迁移源码写法。

## 14.5 架构检查扩展

新增规则：

```text
domain 不得导入 storage/api/pipeline
storage 不得导入 api/pipeline/dagster/provider SDK
api 不得导入 pipeline/provider SDK
Provider SDK 只能出现在 adapters/<provider>
生产代码禁止 subprocess 调用仓库 Python 脚本
FastAPI routes 禁止直接 import SQLAlchemy Session
生产 assets 禁止默认构造 fixture Provider
API pyproject 禁止 alembic、dagster、akshare、vectorbt
domain pyproject 必须保持 dependencies=[]
所有包 requires-python 必须一致
```

## 14.6 Makefile

建议：

```make
test:
	$(MAKE) test-domain
	$(MAKE) test-storage
	$(MAKE) test-api
	$(MAKE) test-pipeline
	$(MAKE) test-web

test-domain:
	cd packages/domain && uv run pytest

test-storage:
	cd packages/storage && uv run pytest ../../tests/storage

test-integration:
	docker compose up -d postgres
	cd apps/migrations && uv run alembic upgrade head
	cd packages/storage && uv run pytest ../../tests/storage/integration

check:
	$(MAKE) arch-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
```

## 14.7 验收标准

- [ ] CI 真实执行 domain pytest。
- [ ] CI 真实执行 Provider contract tests。
- [ ] CI 真实执行 PostgreSQL integration tests。
- [ ] CI 在空库执行迁移。
- [ ] 前端执行 typecheck 和 build。
- [ ] 所有 Python 包版本范围一致。
- [ ] main 分支设置 required checks。
- [ ] 直接 push main 被禁止。

---

# 15. GitHub 治理修复

## 15.1 分支策略

```text
main
feature/<issue>-<topic>
fix/<issue>-<topic>
```

禁止：

```text
智能体直接连续提交 main
无 Issue 开发
无 PR 验收
```

## 15.2 Issue 模板

每个 Issue 包含：

```text
背景
目标
范围
非目标
设计约束
数据库影响
安全影响
验收标准
验证命令
关联 ADR
```

## 15.3 PR 模板

```markdown
## 目标

## 修改内容

## 非目标

## 架构边界

## 数据库迁移

## 测试证据

## 风险

## 回滚

## 验收清单
```

## 15.4 分支保护

main：

- Require pull request；
- Require at least one approval；
- Require conversation resolution；
- Require status checks；
- Require branch up to date；
- Block force pushes；
- Block deletions。

即使当前只有一个开发者，也建议通过 PR 保留可审查记录。

---

# 16. 建议 Issue 拆分

## Epic 1：Baseline Correction

1. 压平未上线 Alembic 迁移链。
2. 新建独立 migration app。
3. 删除 app Schema。
4. 创建 ops.pipeline_runs。
5. 删除 Instrument legacy shadow table。
6. 统一 Python 3.12 范围。
7. 修正 ORM metadata 与迁移一致性。

## Epic 2：Provider Evidence Model

8. 创建 provider_requests。
9. 创建 provider_attempts。
10. 重构 provider_batches。
11. 实现失败 stage 和错误分类。
12. 实现 attempt 重试证据。
13. 修正 ProviderBatch 领域状态。
14. 增加 Provider 失败集成测试。

## Epic 3：Provider Scope

15. 删除 RSSCast 运行时注册。
16. 删除 Quicktiny 运行时注册。
17. 删除无关股票和指数 capabilities。
18. 增加 production fixture 禁用门禁。
19. 冻结主 Provider ADR。
20. 修正主 Provider 配置。
21. 实现真实 Provider fixture 契约测试。
22. 实现真实 smoke test。

## Epic 4：ETF Instruments

23. 实现 ETF 主数据 Application Service。
24. 实现 Provider Request/Attempt/Batch 写入。
25. 实现 Instrument 标准化。
26. 实现 Instrument upsert。
27. 实现主数据质量规则。
28. 实现 Dagster 主数据 asset。
29. 实现主数据 E2E。

## Epic 5：Daily Bars

30. 创建 core.daily_bars。
31. 创建 latest_daily_bars view。
32. 实现 DailyBar Repository。
33. 实现 revision 并发规则。
34. 实现日行情 Provider mapping。
35. 实现日行情质量规则。
36. 实现 Dagster 日分区。
37. 实现日常收盘 Job。
38. 实现 Backfill Job。
39. 实现真实日行情 E2E。

## Epic 6：Input Snapshot

40. 创建 input_snapshots。
41. 创建 input_snapshot_rows。
42. 实现 canonical snapshot hash。
43. 实现 snapshot Repository。
44. 实现 snapshot Dagster asset。
45. 实现 snapshot 重放测试。

## Epic 7：Candidate Pool

46. 修正 CandidatePoolResult 完整性。
47. 补齐 Policy 数值阈值。
48. 实现第一版 eligibility rules。
49. 实现 liquidity rule。
50. 实现 price quality rule。
51. 实现 volatility/drawdown rule。
52. 实现 score 和 rank。
53. 创建 candidate_pool_runs/items。
54. 创建 state events/publications。
55. 实现质量门禁。
56. 实现发布事务。
57. 建立黄金样例。

## Epic 8：Serving and Operations

58. 实现 Data Freshness API。
59. 实现 Pipeline Runs API。
60. 实现 Candidate Pool API。
61. 生成 TypeScript Client。
62. 实现候选池最小页面。
63. 建立 Provider 故障 Runbook。
64. 建立日行情缺失 Runbook。
65. 建立分区重跑 Runbook。
66. 建立候选池拒绝发布 Runbook。
67. 配置最小权限数据库账户。
68. 配置指标和告警。

## Epic 9：CI and Governance

69. 修复 CI domain tests。
70. 增加 PostgreSQL integration job。
71. 增加 Alembic empty DB test。
72. 增加 Web typecheck/build。
73. 扩展 architecture checker。
74. 删除实现细节型 AST migration tests。
75. 添加 Issue 模板。
76. 添加 PR 模板。
77. 开启 main branch protection。

---

# 17. 推荐 PR 顺序

```text
PR-01  Baseline migration reset
PR-02  Provider request/attempt/batch correction
PR-03  Candidate Pool contract correction
PR-04  Provider scope reduction and primary-provider ADR
PR-05  Real ETF instrument ingestion
PR-06  Real ETF daily-bar ingestion
PR-07  Data quality and input snapshot
PR-08  Minimal candidate-pool calculator and persistence
PR-09  Candidate-pool publication and API
PR-10  CI, governance, alerts and runbooks
```

依赖关系：

```text
PR-01
  ↓
PR-02 ─────────────┐
  ↓                │
PR-04              │
  ↓                │
PR-05              │
  ↓                │
PR-06              │
  ↓                │
PR-07 ← PR-03 ─────┘
  ↓
PR-08
  ↓
PR-09
  ↓
PR-10
```

PR-10 中的部分 CI 基础修复可以提前，但 branch protection 应在 required checks 稳定后开启。

---

# 18. 每个 PR 的通用 Definition of Done

## 代码

- [ ] 没有越过 Domain/Storage/Pipeline/API 边界。
- [ ] 没有新增当前垂直链路无关能力。
- [ ] 没有引入 Redis、Kafka、Celery、Kubernetes。
- [ ] 没有 `subprocess` 调用仓库内部 Python 脚本。
- [ ] 没有隐式读取全局时间或环境变量的领域逻辑。
- [ ] 没有手工 SQL 出现在 FastAPI route 中。

## 数据库

- [ ] 所有结构变化有 Alembic migration。
- [ ] migration 在空 PostgreSQL 16 上通过。
- [ ] ORM metadata 和数据库一致。
- [ ] 唯一约束和并发行为有集成测试。
- [ ] 不创建 legacy/shadow 表，除非存在真实生产数据迁移要求。
- [ ] 不在应用启动时自动建表。

## 测试

- [ ] 单元测试通过。
- [ ] Provider fixture 契约测试通过。
- [ ] PostgreSQL 集成测试通过。
- [ ] E2E 覆盖本 PR 的实际业务行为。
- [ ] 测试验证行为，不绑定实现细节。
- [ ] 失败路径有测试。

## 运维

- [ ] 日志包含 run/request/attempt/batch ID。
- [ ] 日志不泄漏凭据。
- [ ] 错误有稳定 machine-readable code。
- [ ] 有明确重跑或恢复方式。
- [ ] 对生产行为变化有 Runbook 或变更说明。

## 文档

- [ ] ADR 与代码一致。
- [ ] README 不宣称尚未达到的生产能力。
- [ ] Issue 验收项全部关闭。
- [ ] PR 包含验证命令和输出摘要。

---

# 19. 修复完成的最终验收场景

## 场景 1：正常收盘链路

输入：

```text
交易日 T
真实 Provider
全量活跃 ETF
```

预期：

```text
Provider Request succeeded
所有 Attempt 可追踪
ETF 主数据更新
T 日日行情落库
质量规则通过
Input Snapshot 创建
Candidate Pool calculated
Candidate Pool validated
Candidate Pool published
API latest 返回该运行
```

## 场景 2：Provider 超时后成功

```text
Attempt 1 timeout
Attempt 2 timeout
Attempt 3 succeeded
```

预期：

- 三次 attempt 都保留；
- 前两次不要求 payload hash；
- 第三次生成 batch；
- 逻辑 Request 成功；
- 下游只消费成功 Batch。

## 场景 3：鉴权失败

预期：

- 不自动重复大量重试；
- attempt 标记 authentication；
- Provider Request 失败；
- Pipeline Run 失败；
- 不写 DailyBar；
- 触发 P0 告警；
- 日志不包含 token。

## 场景 4：Provider 修订历史行情

预期：

- 相同 `instrument/date/adjustment`；
- row_hash 不同；
- 插入 revision+1；
- 旧 revision 保留；
- 旧 Candidate Pool 仍绑定旧 Snapshot；
- 新计算创建新 Snapshot 和新 Candidate Pool Run。

## 场景 5：质量不合格

输入：

```text
当日行情覆盖率低于阈值
```

预期：

- raw 和 core 数据可以保留；
- quality 记录 error；
- Candidate Pool 不发布；
- latest publication 指针不变；
- API 继续显示上一已发布版本，并标记数据延迟。

## 场景 6：候选池算法升级

输入：

```text
相同 Snapshot
algorithm_version 1.0.0 → 1.1.0
```

预期：

- 创建新 Run；
- 旧 Run 不覆盖；
- 可以比较结果差异；
- 只有通过质量和批准的新 Run 才替换 publication pointer。

---

# 20. 纠偏后的停止条件

在以下条件满足前，不进入更多业务模块：

- [ ] 一个真实 Provider 已冻结并接入。
- [ ] 真实 ETF 主数据成功落库。
- [ ] 真实 ETF 日行情成功落库。
- [ ] 请求失败和重试证据完整。
- [ ] DailyBar revision 生效。
- [ ] 数据质量门禁生效。
- [ ] Input Snapshot 可重放。
- [ ] Candidate Pool 纯函数运行真实数据。
- [ ] Candidate Pool 可以验证并发布。
- [ ] API 能查询 published 结果。
- [ ] CI 在 PostgreSQL 中执行完整链路测试。
- [ ] main 分支保护开启。

满足之后，才能评估：

```text
第二 Provider
新闻
报告
复杂因子
回测
组合
缓存
对象存储
消息队列
```

---

# 21. 最终原则

1. **先跑通一个真实垂直链路，再扩展横向能力。**
2. **Greenfield 项目不为不存在的数据编写兼容迁移。**
3. **逻辑请求、网络尝试和成功数据批次必须分离。**
4. **失败请求不应被强制要求不存在的响应哈希。**
5. **候选池必须对每个输入标的给出唯一、完整、可解释结果。**
6. **数据质量失败时保留证据，但不发布结果。**
7. **API 只读取发布指针，不猜测“最新结果”。**
8. **测试验证真实行为，不以 Mock 数量或 AST 细节代替系统验收。**
9. **文档、ADR、代码和 CI 必须采用同一事实基线。**
10. **任何新抽象都必须服务于当前真实链路，而不是未来假设。**
