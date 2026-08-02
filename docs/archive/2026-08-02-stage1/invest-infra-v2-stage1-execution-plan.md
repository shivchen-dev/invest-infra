# invest-infra V2 分阶段建设建议与第一阶段执行计划

> 仓库：`shivchen-dev/invest-infra`
> 基线提交：`a917c041a35b8e378d07d6968e396d3cadb06e25`
> 第一阶段主题：真实数据驱动的手动每日闭环
> 通知通道：Matrix（第二阶段接入）
> 建设原则：复用现有代码、缩小范围、先跑通再自动化。

---

## 1. 建议分为四个阶段

### 第一阶段：真实每日闭环

目标：

```text
CifangQuant
→ 个人 ETF 池
→ 主数据
→ 日行情
→ Input Snapshot
→ Candidate Pool
→ Published Result
→ API 查询
```

运行方式：

- 手动指定交易日执行；
- 不依赖定时 Schedule；
- 不发送 Matrix；
- 重点验证真实数据和候选池结果。

完成标志：

> 执行一条命令后，可以在 API 查询到该交易日已发布的真实候选池。

---

### 第二阶段：自动运行与 Matrix 通知

目标：

```text
Dagster Schedule
→ 每日自动运行
→ Candidate Pool Diff
→ Matrix 摘要
→ 失败通知
```

主要内容：

- 收盘后 Schedule；
- 新增、保留、移出比较；
- Matrix 通知；
- 通知幂等；
- 手动重发。

---

### 第三阶段：稳定性与个人使用体验

目标：

- 日期区间回补；
- 数据新鲜度；
- 运行状态查询；
- 失败日期补跑；
- 简单结果页；
- 连续 10～20 个交易日运行；
- T+5 / T+20 信号回看。

---

### 第四阶段：策略与 AI 增强

目标：

- 大盘择时；
- 流动性、波动率和回撤规则；
- 候选池参数迭代；
- AI 研究解释；
- 新闻和行情综合分析。

本阶段不承诺：

- AI 生成并执行 Python 策略；
- 自动交易；
- 多用户 SaaS；
- 分钟级盯盘。

---

# 2. 第一阶段定位

第一阶段不是继续开发底层框架，而是把已经存在的组件接成一条真实链路。

当前已有：

- CifangQuant HTTP Adapter；
- CifangQuant Smoke；
- Provider Request / Attempt / Batch；
- ETF Instrument Pipeline；
- ETF DailyBar Pipeline；
- DailyBar revision；
- Input Snapshot；
- Candidate Pool 纯函数；
- Candidate Pool 数据表；
- Candidate Pool 查询 API。

当前主要缺口：

1. Assets 仍直接使用 `FixtureDevInstrumentProvider`。
2. 主数据 Asset 使用 `date.today()`。
3. 日行情 Asset 使用固定日期区间。
4. 日行情 symbol 来自 fixture，而不是个人 ETF 池。
5. Input Snapshot 当前包含所有 ETF，不是个人 ETF 池。
6. Candidate Pool Calculator 尚未接入 Dagster 完整运行链。
7. 尚未形成单条每日执行命令。
8. 尚未完成真实 PostgreSQL 端到端验证。

---

# 3. 第一阶段最终链路

```text
make personal-daily-run TRADE_DATE=2026-07-31
        │
        ▼
加载个人 ETF 池
        │
        ▼
构造 CifangQuant Provider
        │
        ▼
同步 ETF 主数据
        │
        ▼
采集指定交易日日行情
        │
        ▼
写入 Provider evidence
        │
        ▼
写入 core.daily_bars
        │
        ▼
创建个人池 Input Snapshot
        │
        ▼
计算最小 Candidate Pool
        │
        ▼
保存 CandidatePoolRun / Items
        │
        ▼
calculated → validated → published
        │
        ▼
GET /api/v1/candidate-pool/latest
```

---

# 4. 第一阶段范围

## 4.1 必须完成

1. 实现统一 Provider Factory。
2. Assets 不再直接构造 fixture Provider。
3. 加入个人 ETF 池 YAML 配置。
4. 所有运行使用显式 `trade_date`。
5. 日行情只采集个人 ETF 池。
6. Input Snapshot 只绑定个人 ETF 池。
7. 实现 Candidate Pool 计算服务。
8. 实现 Candidate Pool 发布流程。
9. 建立 Dagster Job。
10. 增加单条手动执行命令。
11. 完成真实 PostgreSQL E2E。
12. 使用真实 CifangQuant 运行一次。

## 4.2 明确不做

- Matrix 通知；
- Dagster Schedule；
- 多 Provider fallback；
- 完整交易日历；
- 并发 Backfill；
- 新的 Web 页面；
- 数据质量平台；
- 完整 FQIR；
- AI 分析；
- 新闻；
- 分钟行情；
- Redis、Kafka、Celery；
- 微服务拆分。

---

# 5. PR 拆分

第一阶段建议分为四个 PR：

```text
PR-1 Provider 运行时接线
PR-2 个人标的池与日期驱动采集
PR-3 Candidate Pool 计算与发布
PR-4 每日 Job、命令与端到端验收
```

---

# 6. PR-1：Provider 运行时接线

## 6.1 目标

让现有 Assets 根据配置选择：

```text
fixture_dev
cifangquant
```

不再直接构造：

```python
FixtureDevInstrumentProvider()
```

## 6.2 新增或调整文件

建议：

```text
apps/pipeline/src/invest_pipeline/provider_factory.py
apps/pipeline/src/invest_pipeline/resources.py
apps/pipeline/src/invest_pipeline/config.py
apps/pipeline/tests/test_provider_factory_runtime.py
```

如果现有模块已有等价职责，直接扩展，不重复创建。

## 6.3 Provider Factory

建议接口：

```python
def build_etf_provider(settings: PipelineSettings) -> EtfMarketDataProvider:
    if settings.provider_key == "fixture_dev":
        return FixtureDevInstrumentProvider()

    if settings.provider_key == "cifangquant":
        return CifangQuantInstrumentProvider(
            settings=settings.cifang
        )

    raise ValueError(
        f"Unsupported ETF provider: {settings.provider_key}"
    )
```

## 6.4 环境配置

```env
INVEST_ENVIRONMENT=personal
INVEST_PIPELINE_PROVIDER_KEY=cifangquant
INVEST_PIPELINE_CIFANG_ENABLED=true
INVEST_PIPELINE_CIFANG_API_KEY=***
```

规则：

- 测试默认使用 `fixture_dev`；
- personal 环境默认要求真实 Provider；
- Cifang 未启用时拒绝构造；
- API Key 缺失时立即失败；
- 不自动切回 fixture。

## 6.5 Dagster Resource

可以采用简单 ConfigurableResource：

```python
class EtfProviderResource(dg.ConfigurableResource):
    provider_key: str

    def build(self) -> EtfMarketDataProvider:
        return build_etf_provider(get_settings())
```

也可以直接在 Asset 内调用 Factory。

第一阶段不需要复杂 Resource 生命周期管理，只需确保：

- Provider 可关闭；
- 测试可以注入 fixture；
- Asset 不依赖具体 Provider 类型。

## 6.6 修改 Assets

替换：

```python
provider = FixtureDevInstrumentProvider()
```

为：

```python
provider = build_etf_provider(get_settings())
```

涉及：

```text
etf_instruments_raw
etf_daily_bars_raw
```

下游 Asset 不应再次创建 Provider，只读取已保存的 Request / Attempt / Batch。

## 6.7 Provider Key 修正

当前下游逻辑存在硬编码：

```text
provider_key="fixture_dev"
```

必须改为从：

- 上游 Asset metadata；
- 运行配置；
- 或统一 Settings；

获取真实 Provider Key。

第一阶段推荐使用统一 Settings，避免开发复杂 Asset 输出对象。

## 6.8 测试

覆盖：

- fixture 构造；
- Cifang 构造；
- 未启用 Cifang；
- 缺少 API Key；
- 未知 Provider；
- Token 不出现在 repr 和错误消息；
- Asset 测试仍使用 fixture，不访问网络。

## 6.9 验收

- [ ] Assets 中不再直接构造 fixture。
- [ ] `fixture_dev` 测试链路通过。
- [ ] `cifangquant` 可显式选择。
- [ ] 未启用时不访问网络。
- [ ] API Key 不泄漏。
- [ ] Architecture Check 通过。

---

# 7. PR-2：个人标的池与日期驱动采集

## 7.1 目标

使数据采集围绕：

```text
个人 ETF 池 + 指定交易日
```

运行，而不是：

```text
fixture 全量列表 + date.today() + 固定日期窗口
```

## 7.2 个人 ETF 池配置

新增：

```text
config/personal-universe.yaml
```

示例：

```yaml
version: 1

groups:
  broad_market:
    - "510300"
    - "510500"
    - "159915"

  technology:
    - "588000"
    - "588080"

  overseas:
    - "513050"
    - "513100"

enabled_groups:
  - broad_market
  - technology
  - overseas
```

建议所有代码使用字符串，避免前导零问题。

## 7.3 PersonalUniverse

建议新增：

```text
apps/pipeline/src/invest_pipeline/personal_universe.py
```

接口：

```python
@dataclass(frozen=True, slots=True)
class PersonalUniverse:
    version: int
    symbols: tuple[str, ...]
    content_hash: str


def load_personal_universe(path: Path) -> PersonalUniverse:
    ...
```

校验：

- version 必须为正整数；
- enabled group 必须存在；
- symbol 必须是六位数字；
- 自动去重；
- 保持稳定排序；
- 至少一个 symbol；
- 计算稳定 SHA-256。

## 7.4 与 Instrument 对齐

新增查询：

```python
resolve_universe_instruments(
    uow,
    symbols,
) -> list[Instrument]
```

必须检查：

- 每个 symbol 在 `core.instruments` 中存在；
- exchange 是 SSE 或 SZSE；
- instrument_type 是 ETF；
- 不允许静默忽略缺失标的。

如存在缺失：

```text
510300: found
510500: found
999999: missing
```

整个运行失败，并给出缺失列表。

## 7.5 显式交易日

新增运行配置：

```python
class PersonalDailyRunConfig(dg.Config):
    trade_date: str
    universe_path: str = "config/personal-universe.yaml"
```

解析：

```python
trade_date = date.fromisoformat(config.trade_date)
```

禁止使用：

```python
date.today()
```

决定业务日期。

`date.today()` 只可用于：

- 校验未来日期；
- 日志；
- 默认 CLI 展示；

不能作为业务输入。

## 7.6 主数据日期

主数据调用：

```python
provider.fetch_instruments(as_of=trade_date)
```

主数据不是每天都必须变化，但第一阶段每日运行可以同步一次，简化流程。

后续再优化为每周或按需同步。

## 7.7 日行情窗口

日行情必须调用：

```python
provider.fetch_daily_bars(
    symbols=universe.symbols,
    start_date=trade_date,
    end_date=trade_date,
)
```

删除固定默认：

```text
2026-07-23 → 2026-07-30
```

## 7.8 Request Key

Request Key 应包含：

```text
provider
dataset
trade_date
sorted symbols
```

例如：

```text
daily-bars:2026-07-31:159915,510300,510500
```

不要依赖原始 YAML 顺序。

## 7.9 Input Snapshot

当前 Snapshot 只保存 ETF ID 集合。

第一阶段要求：

- Snapshot 日期等于 trade_date；
- Snapshot instrument IDs 来自个人 ETF 池；
- 不是数据库中全部 ETF；
- row_count 等于个人池有效标的数；
- content_hash 反映个人池变化。

第一阶段暂不修改 Snapshot 结构以绑定 DailyBar revision，沿用当前实现。

## 7.10 测试

覆盖：

- YAML 正常加载；
- enabled group 缺失；
- 重复 symbol；
- 非六位 symbol；
- 空标的池；
- hash 稳定；
- 数据库缺失标的；
- 非 ETF 标的；
- 显式 trade_date；
- 日行情 start=end=trade_date；
- 相同日期重跑幂等。

## 7.11 验收

- [ ] 不再使用 fixture 列表决定 symbols。
- [ ] 不再使用固定日期窗口。
- [ ] 不再使用 `date.today()` 作为交易日。
- [ ] Snapshot 只包含个人 ETF 池。
- [ ] 缺失标的导致明确失败。
- [ ] 日行情只拉取单交易日。
- [ ] 相同输入生成相同 request key。
- [ ] Pipeline 测试通过。

---

# 8. PR-3：Candidate Pool 计算与发布

## 8.1 目标

把已经存在的最小 Candidate Pool Calculator 接入真实 Snapshot 和 DailyBar。

## 8.2 现有规则

第一阶段沿用现有规则：

```text
no_data
suspended
invalid_price
low_volume
low_amount
```

排序：

```text
close × volume 降序
```

不增加新规则。

## 8.3 参数配置

新增：

```text
config/candidate-pool-personal.yaml
```

示例：

```yaml
algorithm_key: personal_etf_candidate_pool
algorithm_version: "1.0.0"
parameter_set_key: personal-default

eligibility:
  min_volume: 100000
  min_amount: 10000000

selection:
  max_candidates: 10
```

如果当前 CandidatePoolPolicy 还需要其他结构字段，使用最小合法默认值，不新增业务规则。

## 8.4 计算服务

建议新增：

```text
apps/pipeline/src/invest_pipeline/candidate_pool_service.py
```

入口：

```python
def calculate_and_publish_candidate_pool(
    *,
    uow_factory,
    trade_date: date,
    snapshot_id: UUID,
    policy: CandidatePoolPolicy,
) -> CandidatePoolRun:
    ...
```

## 8.5 读取输入

服务读取：

1. 指定日期的 Input Snapshot；
2. Snapshot 中的 instrument IDs；
3. 指定日期 `core.latest_daily_bars`；
4. 对应 Instrument 信息；
5. CandidatePoolPolicy。

不得读取其他日期的 Bar 作为“最新替代”。

如果某标的无当日 Bar：

```text
保留在输入中
→ Calculator 输出 no_data
```

不能静默删除。

## 8.6 计算

调用：

```python
calculator.calculate(
    snapshot=snapshot,
    bars=bars,
    policy=policy,
)
```

结果必须满足：

- 每个 Snapshot instrument 出现一次；
- included + excluded = input_count；
- rank 从 1 连续；
- 排除项有原因；
- 结果确定性。

## 8.7 持久化

写入：

```text
analytics.candidate_pool_runs
analytics.candidate_pool_items
```

流程：

```text
创建 calculated Run
→ 批量保存 Items
→ 校验保存数量
→ 转 validated
→ 转 published
```

## 8.8 发布语义

第一阶段个人使用，可采用：

```text
同一 trade_date
+ algorithm_key
+ parameter_set_key
```

只允许一个当前 published 结果。

如果当前表尚无 publication pointer：

- `latest` API 使用最新 `published_at`；
- 同一日重算时保留历史 Run；
- 仅最新成功 Run 标记 published；
- 旧 published Run 可以保留，不在第一阶段引入复杂 superseded 状态。

不要为了第一阶段新增大型发布系统。

## 8.9 Dagster Asset

新增：

```text
personal_candidate_pool
```

依赖：

```text
etf_input_snapshot
etf_daily_bars
```

分区：

```text
DailyPartitionsDefinition
```

使用相同 partition key。

## 8.10 测试

覆盖：

- 正常计算；
- 无日行情；
- 停牌；
- 低成交量；
- 低成交额；
- 全部排除；
- 相同输入确定性；
- 保存 items 数量；
- 状态迁移；
- latest API 返回 published；
- 未发布结果不出现在 latest API。

## 8.11 验收

- [ ] 使用真实 Snapshot 和 Bar。
- [ ] 每个 ETF 有判断结果。
- [ ] Run 和 Items 成功保存。
- [ ] 状态到达 published。
- [ ] API 可以读取结果。
- [ ] 相同输入重复执行结果一致。
- [ ] 无数据 ETF 显示 no_data，而不是消失。

---

# 9. PR-4：每日 Job、命令与 E2E

## 9.1 目标

把第一阶段所有 Asset 组成一个可手动运行的 Job。

## 9.2 Asset 顺序

```text
etf_instruments_raw
→ etf_instruments
→ etf_daily_bars_raw
→ etf_daily_bars
→ etf_input_snapshot
→ personal_candidate_pool
```

## 9.3 Definitions

更新：

```text
apps/pipeline/src/invest_pipeline/definitions.py
```

注册：

- Assets；
- `personal_etf_daily_job`；
- 必要 Resources。

第一阶段不注册 Schedule 和 Sensor。

## 9.4 Job

```python
personal_etf_daily_job = dg.define_asset_job(
    name="personal_etf_daily_job",
    selection=[
        "etf_instruments_raw",
        "etf_instruments",
        "etf_daily_bars_raw",
        "etf_daily_bars",
        "etf_input_snapshot",
        "personal_candidate_pool",
    ],
)
```

实际写法按当前 Dagster 版本调整。

## 9.5 CLI / Makefile

新增：

```bash
make personal-daily-run TRADE_DATE=2026-07-31
```

底层可以使用：

```text
dagster job execute
```

或一个小型 Python CLI。

建议小型 CLI：

```text
apps/pipeline/src/invest_pipeline/personal_daily_cli.py
```

参数：

```text
--trade-date
--universe
--policy
--confirm-network
```

真实网络仍需显式：

```text
--confirm-network
```

环境变量仍需：

```text
INVEST_PIPELINE_CIFANG_ENABLED=true
```

## 9.6 输出摘要

成功后输出一行 JSON：

```json
{
  "trade_date": "2026-07-31",
  "provider": "cifangquant",
  "universe_count": 7,
  "daily_bar_count": 7,
  "snapshot_id": "...",
  "candidate_pool_run_id": "...",
  "included_count": 4,
  "excluded_count": 3,
  "status": "published"
}
```

不得输出：

- API Key；
- Raw Payload；
- 完整请求头。

## 9.7 PostgreSQL E2E

测试链路：

```text
空 PostgreSQL
→ alembic upgrade head
→ fixture personal daily run
→ 检查 raw 请求证据
→ 检查 instruments
→ 检查 daily bars
→ 检查 snapshot
→ 检查 candidate pool run/items
→ 调用 latest API
```

Fixture E2E 进入 CI。

真实 Cifang E2E 只作为显式 Smoke，不进入普通 CI。

## 9.8 真实验收

选择：

- 3～5 只 ETF；
- 一个已完成交易日；
- CifangQuant 真实 API。

执行：

```bash
export INVEST_PIPELINE_PROVIDER_KEY=cifangquant
export INVEST_PIPELINE_CIFANG_ENABLED=true
export INVEST_PIPELINE_CIFANG_API_KEY=***

make personal-daily-run \
  TRADE_DATE=2026-07-31 \
  CONFIRM_NETWORK=1
```

检查：

```text
raw.provider_requests
raw.provider_attempts
raw.provider_batches
core.instruments
core.daily_bars
analytics.input_snapshots
analytics.candidate_pool_runs
analytics.candidate_pool_items
```

最后调用：

```text
GET /api/v1/candidate-pool/latest
```

## 9.9 验收

- [ ] 单条命令完成全部步骤。
- [ ] Fixture E2E 进入 CI。
- [ ] 真实 Cifang 运行成功。
- [ ] API 返回 published 结果。
- [ ] 相同日期重跑不重复 DailyBar。
- [ ] 相同数据不新增 revision。
- [ ] 失败时输出明确阶段和 Run ID。
- [ ] 不发送 Matrix 消息。
- [ ] 不注册 Schedule。

---

# 10. 第一阶段 Issue 拆分

建议控制为 10 个 Issue：

1. 实现 ETF Provider Factory。
2. 替换 Assets 中的 fixture 硬编码。
3. 增加 personal-universe.yaml。
4. 实现 PersonalUniverse Loader。
5. 将 Assets 改为显式 trade_date。
6. 使用个人池采集日行情。
7. 使用个人池创建 Input Snapshot。
8. 实现 Candidate Pool 计算和发布服务。
9. 注册 personal_candidate_pool Asset 与 Job。
10. 增加 personal-daily-run CLI 和 E2E。

---

# 11. 第一阶段执行顺序

```text
第 1 步
Provider Factory
        ↓
第 2 步
个人池 Loader
        ↓
第 3 步
日期驱动主数据和日行情
        ↓
第 4 步
个人池 Snapshot
        ↓
第 5 步
Candidate Pool 计算和发布
        ↓
第 6 步
每日 Job 和 CLI
        ↓
第 7 步
Fixture E2E
        ↓
第 8 步
真实 Cifang 验收
```

---

# 12. 测试要求

## 12.1 Domain

不新增复杂 Domain。

只在必要时增加：

- PersonalUniverse 值对象测试；
- Policy 加载测试；
- Candidate Pool 现有测试补充。

## 12.2 Pipeline

必须覆盖：

- Provider 选择；
- 个人池加载；
- 显式日期；
- Asset 依赖；
- Cifang 关闭状态；
- Fixture 完整 Job。

## 12.3 Storage

复用现有测试。

补充：

- Candidate Pool published 查询；
- 同一日期重跑；
- DailyBar revision 不重复。

## 12.4 API

验证：

```text
GET /api/v1/candidate-pool/latest
```

只返回：

```text
published
```

## 12.5 网络测试

普通 CI：

```text
禁止真实网络
```

真实 Cifang：

```text
必须显式 confirm-network
```

---

# 13. Definition of Done

## Provider

- [ ] Assets 不再硬编码 fixture。
- [ ] personal 环境可选择 Cifang。
- [ ] Cifang 默认关闭。
- [ ] 凭据不泄漏。

## Personal Universe

- [ ] YAML 可加载。
- [ ] 标的去重。
- [ ] 标的与 Instrument 对齐。
- [ ] Snapshot 只包含个人池。
- [ ] Universe hash 稳定。

## 日期

- [ ] 所有业务流程使用显式 trade_date。
- [ ] 日行情 start=end=trade_date。
- [ ] 不使用固定日期窗口。
- [ ] 不用 date.today() 作为业务交易日。

## Candidate Pool

- [ ] 使用真实日行情。
- [ ] 每个标的有结果。
- [ ] 状态到达 published。
- [ ] API 可查询。
- [ ] 结果确定性。

## 运行

- [ ] 一条命令完成每日链路。
- [ ] Fixture E2E 通过。
- [ ] 真实 Cifang 验收通过。
- [ ] 同日重跑幂等。
- [ ] 输出脱敏摘要。

---

# 14. 第一阶段停止条件

满足以下条件立即结束第一阶段，不继续扩展：

```text
一个真实交易日
+ 一个真实 CifangQuant Provider
+ 一个个人 ETF 池
+ 一条手动运行命令
+ 一个 published Candidate Pool
+ 一个可查询 API
```

第一阶段完成后再进入第二阶段：

```text
Schedule
+ Candidate Pool Diff
+ Matrix 通知
```

---

# 15. 防止过度工程化

第一阶段禁止：

1. 新增第二 Provider。
2. 新增 Matrix 通知。
3. 新增 Schedule。
4. 新增 Redis 或消息队列。
5. 新增复杂交易日历服务。
6. 新增新的顶级 Package。
7. 重写现有 Repository。
8. 重新设计 Candidate Pool Domain。
9. 新增复杂数据质量框架。
10. 新增前端页面。
11. 新增 AI。
12. 新增完整 Backfill 平台。
13. 为未来多用户设计权限系统。
14. 为未来规模设计分库分表。

---

# 16. 第一阶段交付物

代码：

```text
Provider Factory
PersonalUniverse Loader
日期驱动 Assets
personal_candidate_pool Asset
personal_etf_daily_job
personal-daily-run CLI
```

配置：

```text
config/personal-universe.yaml
config/candidate-pool-personal.yaml
.env.example 更新
```

测试：

```text
Provider Factory tests
Universe tests
Asset tests
Candidate Pool service tests
Fixture E2E
```

文档：

```text
docs/runbooks/personal-manual-daily-run.md
```

---

# 17. 完成后的使用方式

```bash
export INVEST_PIPELINE_PROVIDER_KEY=cifangquant
export INVEST_PIPELINE_CIFANG_ENABLED=true
export INVEST_PIPELINE_CIFANG_API_KEY=***

make personal-daily-run \
  TRADE_DATE=2026-07-31 \
  CONFIRM_NETWORK=1
```

然后查询：

```text
GET /api/v1/candidate-pool/latest
```

第一阶段的最终成果：

> 使用者可以手动指定一个交易日，以真实 CifangQuant 数据运行个人 ETF 池，并得到一个已发布、可查询、可重复执行的候选池结果。
