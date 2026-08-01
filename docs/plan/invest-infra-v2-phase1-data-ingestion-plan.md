# invest-infra V2 第一阶段实施方案：ETF 数据采集层

> 仓库：`shivchen-dev/invest-infra`  
> 当前基线：`e09ceaf615179c2b8b64c9b3fd95fc802d1921d9`  
> 阶段目标：在现有 V2 骨架上完成一条真实、稳定、可重跑的 ETF 数据采集链路。  
> 建设原则：尽量复用现有代码，不扩展无关能力，不提前建设策略、AI、报告和复杂平台组件。

---

## 1. 阶段结论

当前 V2 已经具备：

- `packages/domain` 纯领域模型；
- `packages/storage` SQLAlchemy Repository 和 Unit of Work；
- `apps/pipeline` Dagster 骨架；
- `apps/api` FastAPI 骨架；
- `core.instruments`；
- `raw.provider_batches`；
- `app.pipeline_runs`；
- Provider Registry、配置和 fixture；
- AkShare、Cifang Provider 占位实现；
- 一批领域和存储测试。

当前缺少：

- 可用的真实 ETF Provider；
- 真实 ETF 主数据采集；
- 真实 ETF 日行情采集；
- `core.daily_bars`；
- Dagster 日行情资产和回补任务；
- 基础数据质量检查；
- 真实数据库端到端验证。

因此第一阶段只建设：

```text
一个真实 ETF Provider
        ↓
ETF 主数据采集
        ↓
ETF 日行情采集
        ↓
标准化与基础质量校验
        ↓
PostgreSQL 持久化
        ↓
Dagster 单日运行与区间回补
```

---

## 2. 本阶段范围

### 2.1 必须完成

1. 从现有候选数据源中确定一个主 Provider。
2. 实现主 Provider 的真实 Adapter。
3. 采集 SSE、SZSE 场内 ETF 主数据。
4. 采集未复权 ETF 日行情。
5. 保存 Provider 请求结果和失败信息。
6. 建立 `core.daily_bars`。
7. 实现行情幂等写入和简单 revision。
8. 建立 Dagster 主数据和日行情资产。
9. 支持指定交易日运行。
10. 支持日期区间回补。
11. 增加基础数据质量校验。
12. 使用 PostgreSQL 完成端到端测试。

### 2.2 明确不做

本阶段不建设：

- 候选池算法；
- FQIR；
- 因子体系；
- AI 模型分析；
- 新闻和财报；
- 股票、指数和分钟行情；
- 多 Provider 自动切换；
- Redis、Kafka、Celery、MinIO；
- Kubernetes；
- 完整数据湖；
- 独立微服务；
- 复杂权限系统；
- 新前端页面；
- 完整 Input Snapshot；
- 回测；
- 报告生成。

---

## 3. 简化后的第一阶段架构

```text
真实 ETF Provider
        │
        ▼
Provider Adapter
  - 请求
  - 字段映射
  - 错误转换
        │
        ▼
Ingestion Service
  - 保存请求结果
  - 标准化
  - 质量校验
  - 事务写入
        │
        ▼
PostgreSQL
  raw.provider_batches
  core.instruments
  core.daily_bars
  app.pipeline_runs
        ▲
        │
Dagster Assets / Jobs
```

第一阶段继续使用现有：

```text
apps/pipeline
packages/domain
packages/storage
apps/api/migrations
```

暂不为了“理想分层”增加新的顶级工程或微服务。

---

## 4. 现有代码的处理原则

### 4.1 保留

保留并继续使用：

```text
packages/domain/src/invest_domain/instruments/
packages/domain/src/invest_domain/market_data/
packages/storage/src/invest_storage/
apps/pipeline/src/invest_pipeline/providers/
apps/pipeline/src/invest_pipeline/definitions.py
apps/api/migrations/
```

保留：

- `Instrument`；
- `DailyBar`；
- `ProviderBatch`；
- `EtfMarketDataProvider`；
- `SqlAlchemyUnitOfWork`；
- `SqlAlchemyInstrumentRepository`；
- `SqlAlchemyProviderBatchRepository`；
- `SqlAlchemyPipelineRunRepository`。

### 4.2 暂停扩展

本阶段不继续扩展：

```text
candidate_pool
rsscast
quicktiny_mcp
股票和指数 Provider 能力
AI Domain
报告 Domain
复杂 Provider 插件系统
```

现有相关代码可以保留，但不要继续增加功能。

`quicktiny_mcp` 的“research_only / 显式排除 ETF 主数据与日线”决策已
通过 `invest_pipeline.provider_catalog.QUICKTINY_MCP` 在代码目录中以纯
声明形式落地（仅 ``ProviderDeclaration`` dataclass + stdlib enum，无
HTTP / MCP transport、无 API key 处理、无 Dagster asset / 数据库迁移
变更）；该声明同步受
`apps/pipeline/tests/unit/test_provider_catalog.py` 守护，单元测试直
接断言 `provider_key="quicktiny_mcp"`、`role="research_only"`、能力集仅
含 `research` / `market_snapshot` 且 `enabled_by_default=False`，并断言
`ProviderCapability.ETF_DAILY_BARS` / `ETF_MASTER_DATA` /
`INDEX_DAILY_BARS` 不在能力集中，`lookup_provider()` 对未知 key 抛出
`KeyError`。第一阶段不在 Dagster / 数据持久化路径使用 quicktiny_mcp。

### 4.3 暂不重构

为控制范围，本阶段暂不执行：

- 将 Alembic 从 API 迁移到独立应用；
- 删除全部现有迁移并重建；
- 大规模重命名 Schema；
- 引入新的 Application Package；
- 重写现有 UoW；
- 拆分多个网络服务。

这些可以在真实采集链路稳定后单独处理。

---

## 5. Provider 选型

本阶段只能实现一个真实 Provider。

### 5.1 选择条件

主 Provider 必须满足：

- 能返回 SSE、SZSE ETF 列表；
- 能返回指定 ETF 的日行情；
- 支持未复权数据；
- 支持日期区间查询；
- 返回字段和单位可以确认；
- 有明确的鉴权方式；
- 能确认基本限频要求；
- 当前部署环境能够稳定访问。

### 5.2 选型动作

开发开始前完成一个简短决策文件：

```text
docs/adr/0011-primary-etf-provider.md
```

只记录：

- 选用哪个 Provider；
- 使用什么接口；
- 鉴权方式；
- ETF 主数据字段；
- 日行情字段；
- 复权口径；
- 限频和批量限制；
- 已知风险。

不需要编写复杂供应商评估报告。

### 5.3 运行时范围

第一阶段 Registry 只实际启用：

```text
fixture_dev
一个真实 Provider
```

`rsscast` 和 `quicktiny_mcp` 不参与第一阶段运行。

---

## 6. Provider Adapter 实现

### 6.1 推荐目录

沿用现有 Provider 目录，不再创建新的插件框架：

```text
apps/pipeline/src/invest_pipeline/providers/
└── <selected_provider>/
    ├── __init__.py
    ├── config.py
    ├── client.py
    ├── mapper.py
    └── adapter.py
```

### 6.2 Client 职责

`client.py` 只负责：

- 调用真实 HTTP API 或 SDK；
- 设置鉴权；
- 设置超时；
- 控制简单请求间隔；
- 返回原始响应；
- 将网络错误转换为 Provider 错误。

不要在 Client 中：

- 写数据库；
- 创建 Domain Repository；
- 计算候选池；
- 调用 Dagster；
- 直接决定数据是否发布。

### 6.3 Mapper 职责

`mapper.py` 负责：

- Provider symbol 转换；
- SSE/SZSE 交易所映射；
- 日期解析；
- `Decimal` 转换；
- 成交量和成交额单位统一；
- 停牌状态映射；
- 未复权口径检查；
- 构造 `Instrument` 和 `DailyBar`。

### 6.4 Adapter 接口

实现现有端口：

```python
class SelectedEtfMarketDataProvider:
    @property
    def provider_key(self) -> str:
        ...

    def fetch_instruments(
        self,
        as_of: date,
    ) -> ProviderBatch[Instrument]:
        ...

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> ProviderBatch[DailyBar]:
        ...
```

### 6.5 超时和重试

采用简单策略：

- 连接超时：10 秒；
- 读取超时：30 秒；
- 最多重试 3 次；
- 使用指数退避；
- HTTP 429 按 Provider 限频规则处理；
- HTTP 5xx 可以重试；
- 401、403 不重试；
- 数据字段错误不重试。

不要引入复杂熔断器、消息队列或分布式限流。

---

## 7. `raw.provider_batches` 最小修正

当前表已经存在，本阶段不拆成三张复杂审计表。

只做必要调整。

### 7.1 增加字段

建议新增：

```text
attempt_no integer NOT NULL DEFAULT 1
error_stage varchar(32)
```

`error_stage` 可选值：

```text
authentication
rate_limit
network
timeout
http
decode
contract
storage
```

### 7.2 调整唯一约束

当前：

```text
UNIQUE(provider_key, dataset_key, request_key)
```

调整为：

```text
UNIQUE(
  provider_key,
  dataset_key,
  request_key,
  attempt_no
)
```

这样可以保存同一逻辑请求的多次尝试。

### 7.3 调整 payload hash 约束

规则改为：

```text
succeeded / partial
    → payload_sha256 必须存在

failed
    → payload_sha256 可以为空
    → error_code 和 error_message 至少有一个
```

不要求超时、DNS 或鉴权失败具有响应哈希。

### 7.4 暂不拆表

第一阶段不新增：

```text
provider_requests
provider_attempts
provider_responses
```

等采集规模和审计需求明确后再决定是否拆分。

---

## 8. ETF 主数据采集

### 8.1 数据范围

只采集：

```text
SSE ETF
SZSE ETF
```

暂不采集：

- 港股 ETF；
- 北交所产品；
- 场外基金；
- LOF；
- 股票；
- 指数成分股。

### 8.2 主数据字段

本阶段至少保存：

```text
id
symbol
exchange
name
instrument_type
currency
list_date
status
underlying_index
category
provider_symbol_map
source_provider
source_updated_at
created_at
updated_at
```

### 8.3 Upsert 规则

业务键：

```text
symbol + exchange
```

相同业务键：

- 名称变化：更新；
- 分类变化：更新；
- 跟踪指数变化：更新；
- 状态变化：更新；
- Provider symbol 映射变化：更新。

Provider 某次未返回某只 ETF：

```text
不能自动判定退市
```

### 8.4 主数据质量检查

只做必要检查：

- symbol 非空；
- exchange 必须为 SSE 或 SZSE；
- name 非空；
- 同一批次不能重复；
- 返回数量不能为 0；
- 返回数量相对上一次成功结果大幅下降时失败。

“大幅下降”的阈值使用配置，初始可设置为 30%。

---

## 9. ETF 日行情存储

### 9.1 新增表

新增迁移：

```text
core.daily_bars
```

建议字段：

```sql
CREATE TABLE core.daily_bars (
    instrument_id uuid NOT NULL,
    trade_date date NOT NULL,
    adjustment varchar(8) NOT NULL DEFAULT 'none',
    revision integer NOT NULL DEFAULT 1,

    open numeric(20,6),
    high numeric(20,6),
    low numeric(20,6),
    close numeric(20,6),
    prev_close numeric(20,6),

    volume numeric(28,4),
    amount numeric(28,4),

    trading_status varchar(24) NOT NULL,
    currency varchar(8) NOT NULL DEFAULT 'CNY',

    source_provider varchar(64) NOT NULL,
    source_batch_id uuid NOT NULL,
    observed_at timestamptz NOT NULL,
    row_hash varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (
        instrument_id,
        trade_date,
        adjustment,
        revision
    )
);
```

### 9.2 必要约束

```text
adjustment = 'none'
revision >= 1
volume IS NULL OR volume >= 0
amount IS NULL OR amount >= 0
row_hash 长度为 64
```

正常交易行情：

```text
open > 0
high > 0
low > 0
close > 0
high >= open
high >= close
high >= low
low <= open
low <= close
```

停牌数据按现有 `DailyBar` Domain 规则处理。

### 9.3 简单 Revision

写入前查询当前最新记录：

```text
没有历史记录
→ 插入 revision=1

row_hash 相同
→ 不插入

row_hash 不同
→ 插入 revision=latest+1
```

第一阶段不实现复杂事件溯源。

为避免同一个标的、日期并发写入，可采用：

```text
事务内 SELECT ... FOR UPDATE
```

或对同一分区限制为单写入任务。

### 9.4 Latest View

新增：

```sql
core.latest_daily_bars
```

返回每个：

```text
instrument_id + trade_date + adjustment
```

最新 revision。

第一阶段 API 和运维查询可以使用该 View。

---

## 10. Ingestion Service

### 10.1 新增目录

```text
apps/pipeline/src/invest_pipeline/services/
├── instrument_ingestion.py
└── daily_bar_ingestion.py
```

### 10.2 主数据服务

```python
class InstrumentIngestionService:
    def run(
        self,
        as_of: date,
        pipeline_run_id: UUID,
    ) -> IngestionSummary:
        ...
```

执行：

```text
创建 pipeline run
→ 调用 Provider
→ 保存 provider batch
→ 校验主数据
→ upsert instruments
→ 标记 pipeline run
```

### 10.3 日行情服务

```python
class DailyBarIngestionService:
    def run(
        self,
        trade_date: date,
        pipeline_run_id: UUID,
    ) -> IngestionSummary:
        ...
```

执行：

```text
读取活跃 ETF
→ 分批调用 Provider
→ 保存 provider batch
→ 映射 DailyBar
→ 基础质量校验
→ 写入 daily_bars
→ 汇总结果
→ 标记 pipeline run
```

### 10.4 批量大小

默认配置：

```text
50～100 个 symbol / batch
```

具体值按 Provider 限制调整。

不开发动态批量算法。

---

## 11. Dagster Assets 和 Jobs

### 11.1 替换 Mock 主数据路径

当前：

```text
seed_instruments
```

保留作为开发测试 Asset，但增加明确命名：

```text
seed_fixture_instruments
```

真实生产 Asset：

```text
sync_etf_instruments
```

### 11.2 日行情 Asset

新增：

```text
sync_etf_daily_bars
```

使用日分区：

```text
YYYY-MM-DD
```

### 11.3 Job

只建立两个 Job：

```text
etf_daily_ingestion_job
etf_backfill_job
```

`etf_daily_ingestion_job`：

```text
sync_etf_instruments（可选）
→ sync_etf_daily_bars
```

`etf_backfill_job`：

```text
指定 start_date / end_date
→ 按日期分区运行 daily bars
```

### 11.4 暂不建立

不建立：

- 多市场 Job；
- AI Job；
- 候选池 Job；
- 报告 Job；
- 复杂 Sensor；
- 自动数据修复 Sensor；
- 动态分区；
- 自定义 Dagster IO Manager。

---

## 12. 基础数据质量

第一阶段只做能阻止明显错误的规则。

### 12.1 主数据

Error：

```text
返回为空
symbol 为空
exchange 非 SSE/SZSE
批次内业务键重复
总量相对上次成功批次下降超过阈值
```

### 12.2 日行情

Error：

```text
trade_date 与请求日期不一致
OHLC 关系错误
价格小于 0
成交量小于 0
成交额小于 0
同一批次业务键重复
返回了非 none 复权数据
```

Warn：

```text
零成交
prev_close 缺失
部分 ETF 无行情
价格单日变化异常
```

### 12.3 质量结果存储

第一阶段不急于建立通用规则引擎。

可以：

- 将错误直接抛出并标记 Pipeline Run 失败；
- 将汇总写入 Dagster MaterializeResult metadata；
- 将告警信息写入结构化日志。

如确实需要数据库记录，只新增一张简单表：

```text
ops.data_quality_results
```

不要提前设计复杂数据质量平台。

---

## 13. 配置

### 13.1 环境变量

只新增必要配置：

```text
INVEST_PIPELINE_PROVIDER_KEY
INVEST_PIPELINE_PROVIDER_ENABLED
INVEST_PIPELINE_PROVIDER_TOKEN
INVEST_PIPELINE_PROVIDER_BASE_URL
INVEST_PIPELINE_PROVIDER_TIMEOUT_SECONDS
INVEST_PIPELINE_PROVIDER_BATCH_SIZE
INVEST_PIPELINE_PROVIDER_MAX_ATTEMPTS
```

具体变量名可使用所选 Provider 前缀。

### 13.2 环境限制

```text
ENVIRONMENT=production
```

时：

- 禁止 `fixture_dev`；
- Provider 未启用时启动失败；
- 凭据缺失时启动失败。

### 13.3 敏感信息

- 不提交 `.env`；
- 不在日志打印 token；
- 不把完整请求头写入数据库；
- 错误消息必须脱敏。

---

## 14. 测试方案

### 14.1 Mapper 单元测试

使用脱敏 fixture 测试：

- ETF symbol 映射；
- 交易所映射；
- 日期转换；
- Decimal 转换；
- 成交量单位；
- 停牌数据；
- 错误 OHLC；
- 非法复权数据；
- 缺失字段。

### 14.2 Provider 契约测试

fixture：

```text
contracts/provider-fixtures/
├── instruments-success.json
├── instruments-empty.json
├── daily-bars-success.json
├── daily-bars-partial.json
├── authentication-error.json
├── rate-limit-error.json
└── malformed-response.json
```

普通 CI 不调用真实外部 Provider。

### 14.3 Storage 集成测试

使用 PostgreSQL 验证：

- Instrument upsert；
- Provider Batch 失败记录；
- 同一 request 多 attempt；
- DailyBar 首次写入；
- 相同 row_hash no-op；
- 不同 row_hash revision+1；
- Latest View 返回最新 revision。

### 14.4 Dagster 测试

验证：

- fixture 主数据 Asset；
- fixture 日行情 Asset；
- 单日分区；
- Provider 失败时 Run 失败；
- 同一日期重跑幂等；
- 区间回补顺序。

### 14.5 真实 Smoke Test

单独提供命令：

```bash
make provider-smoke
```

要求：

- 明确设置真实 Provider；
- 只采集少量 ETF；
- 只采集一个交易日；
- 不在普通 PR CI 自动执行；
- 输出记录数量和脱敏摘要。

---

## 15. CI 最小增强

现有 CI 基础上增加：

```text
domain tests
pipeline provider tests
storage PostgreSQL integration tests
Alembic upgrade head
```

第一阶段不要求立即建立复杂矩阵。

最低门禁：

```bash
python scripts/check_architecture.py
cd packages/domain && uv run pytest
cd apps/pipeline && uv run pytest
cd apps/api && uv run alembic upgrade head
pytest tests/storage/integration
```

前端没有新增功能，本阶段只保持现有 build 不被破坏。

---

## 16. 建议实施顺序

### PR 1：必要数据库修正

内容：

- 调整 `raw.provider_batches`；
- 增加 `attempt_no`；
- 放宽 failed payload hash；
- 新建 `core.daily_bars`；
- 新建 latest view；
- 增加 ORM Model；
- 增加 Repository 和集成测试。

完成标准：

```text
fixture DailyBar 可以可靠写入 PostgreSQL
```

### PR 2：实现一个真实 Provider

内容：

- 新增 Provider ADR；
- 实现 Client；
- 实现 Mapper；
- 实现 Adapter；
- 添加 fixture；
- 添加契约测试；
- 添加 smoke test。

完成标准：

```text
可以获取真实 ETF 列表和少量 ETF 日行情
```

### PR 3：实现采集服务

内容：

- InstrumentIngestionService；
- DailyBarIngestionService；
- Provider Batch 审计；
- 重试；
- 主数据 upsert；
- DailyBar revision；
- 基础质量校验。

完成标准：

```text
服务层可从真实 Provider 写入 PostgreSQL
```

### PR 4：接入 Dagster

内容：

- `sync_etf_instruments`；
- `sync_etf_daily_bars`；
- 日分区；
- daily ingestion job；
- backfill job；
- 运行 metadata；
- Dagster 测试。

完成标准：

```text
可以在 Dagster 执行单日采集和区间回补
```

### PR 5：端到端验收

内容：

- 修复 CI；
- 完整 fixture E2E；
- 真实 smoke；
- 更新 README；
- 增加简单运行手册。

完成标准：

```text
从 Provider 到 PostgreSQL 的完整链路稳定运行
```

---

## 17. 建议 Issue 拆分

第一阶段控制在以下 Issue：

1. 修正 Provider Batch 重试和失败约束。
2. 创建 `core.daily_bars` 和 latest view。
3. 实现 DailyBar Repository revision。
4. 确定第一阶段主 Provider。
5. 实现主 Provider Client。
6. 实现主 Provider Mapper。
7. 实现主 Provider Adapter。
8. 建立 Provider fixture 契约测试。
9. 实现 ETF 主数据采集服务。
10. 实现 ETF 日行情采集服务。
11. 实现主数据 Dagster Asset。
12. 实现日行情 Dagster 分区 Asset。
13. 实现区间回补 Job。
14. 补充 PostgreSQL 端到端测试。
15. 编写采集层运行手册。

不要在第一阶段建立 50 个以上 Issue。

---

## 18. 第一阶段验收场景

### 18.1 正常主数据同步

执行：

```text
sync_etf_instruments
```

结果：

- Provider 请求成功；
- `raw.provider_batches` 有成功记录；
- `core.instruments` 有 SSE/SZSE ETF；
- 重复执行不会产生重复标的；
- Pipeline Run 标记成功。

### 18.2 正常单日行情

执行：

```text
sync_etf_daily_bars partition=2026-07-31
```

结果：

- 读取活跃 ETF；
- 分批请求日行情；
- 保存 Provider Batch；
- 写入 `core.daily_bars`；
- 记录数量和缺失数量可见；
- Pipeline Run 标记成功。

### 18.3 重复运行

相同日期再次运行：

- 相同 row_hash 不新增 revision；
- 不产生重复业务记录；
- 运行可以正常完成。

### 18.4 历史修订

Provider 返回同一日期的修正数据：

- row_hash 变化；
- revision 从 1 增加到 2；
- revision 1 保留；
- latest view 返回 revision 2。

### 18.5 Provider 超时

第一次超时，第二次成功：

- 两次 attempt 均有记录；
- 失败 attempt 不要求 payload hash；
- 第二次成功数据正常写入。

### 18.6 鉴权失败

- 不进行无意义重试；
- Pipeline Run 失败；
- 错误类型明确；
- 日志中没有 token；
- 不写入错误行情。

### 18.7 区间回补

执行一段日期范围：

- 每个交易日独立运行；
- 某一天失败不破坏其他已成功日期；
- 失败日期可以单独重跑。

---

## 19. 第一阶段 Definition of Done

### Provider

- [ ] 已确定一个真实 ETF Provider。
- [ ] Adapter 不再是 placeholder。
- [ ] 能获取真实 ETF 主数据。
- [ ] 能获取真实未复权日行情。
- [ ] 有脱敏 fixture 和契约测试。
- [ ] 有独立 smoke test。

### 数据库

- [ ] `raw.provider_batches` 支持多 attempt。
- [ ] failed 记录允许无 payload hash。
- [ ] 已创建 `core.daily_bars`。
- [ ] 已创建 latest view。
- [ ] DailyBar revision 可用。
- [ ] 相同数据重跑幂等。

### Pipeline

- [ ] 已有真实主数据 Asset。
- [ ] 已有日行情分区 Asset。
- [ ] 支持单日运行。
- [ ] 支持区间回补。
- [ ] 运行成功和失败可追踪。
- [ ] production 禁止 fixture。

### 质量

- [ ] 主数据基本校验有效。
- [ ] OHLC 校验有效。
- [ ] 非法复权数据被拒绝。
- [ ] 缺失数据有汇总。
- [ ] Provider 错误能够分类。

### 测试

- [ ] Domain 测试通过。
- [ ] Mapper 测试通过。
- [ ] Provider 契约测试通过。
- [ ] PostgreSQL 集成测试通过。
- [ ] Dagster 测试通过。
- [ ] Fixture E2E 通过。
- [ ] 真实 Smoke 通过。

### 文档

- [ ] Provider ADR 已完成。
- [ ] README 包含采集启动方式。
- [ ] 有主数据同步命令。
- [ ] 有单日行情运行命令。
- [ ] 有区间回补命令。
- [ ] 有鉴权和超时故障处理说明。

---

## 20. 第一阶段完成后的系统状态

完成后，系统应达到：

```text
真实 ETF Provider
        ↓
可审计的 Provider Batch
        ↓
标准 ETF Instrument
        ↓
标准 DailyBar
        ↓
PostgreSQL revision
        ↓
Dagster 单日任务与回补
```

第一阶段结束时，系统还不会：

- 推荐 ETF；
- 生成候选池；
- 运行 AI；
- 输出投资结论。

这些属于后续阶段。

第二阶段可以在该数据底座上继续建设：

```text
数据质量结果持久化
→ Input Snapshot
→ 策略规则
→ 候选池
```

---

## 21. 控制过度工程化的规则

第一阶段执行以下限制：

1. 只接入一个真实 Provider。
2. 不建立多 Provider 路由算法。
3. 不引入队列和缓存。
4. 不创建微服务。
5. 不开发通用规则引擎。
6. 不开发通用数据目录。
7. 不实现复杂事件溯源。
8. 不为数据量假设提前分库分表。
9. 不创建新的前端管理后台。
10. 不为了目录理想化重写已有可用代码。
11. 每个抽象必须有当前生产调用方。
12. 每个表必须服务第一阶段真实链路。
13. 每个 PR 必须产生可运行增量。
14. 不以测试数量代替真实链路完成度。
15. 第一阶段完成前不开发候选池和 AI。

---

## 22. 最终执行主线

```text
先修正 Provider Batch 和 DailyBar 存储
        ↓
实现一个真实 Provider
        ↓
实现主数据和日行情采集服务
        ↓
接入 Dagster 单日任务
        ↓
实现区间回补
        ↓
完成 PostgreSQL E2E 和真实 Smoke
```

第一阶段的唯一核心成果是：

> **V2 能够稳定、可审计、可重跑地采集真实 ETF 主数据和日行情，并写入标准 PostgreSQL 数据表。**
