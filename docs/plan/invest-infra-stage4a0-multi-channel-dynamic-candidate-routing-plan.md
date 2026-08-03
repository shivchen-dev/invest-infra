# invest-infra 动态 ETF 多渠道筛选实施计划

> 文档版本：v1.0  
> 文档状态：Draft for Review  
> 制定日期：2026-08-03  
> 适用仓库：`shivchen-dev/invest-infra`  
> 建议阶段名称：**Stage 4A-0 — Multi-Channel Dynamic Candidate Routing**  
> 后续依赖：完成后再实施 `invest-infra-stage4a-merged-implementation-plan-v1.1.md`  
> 建设原则：确定性筛选、多渠道输入、统一融合、可审计、轻量化、不做参数寻优  

---

## 1. 阶段结论

在 Evidence Pack 与 JiuwenSwarm 投资研判之前，先增加一个独立的动态 ETF 筛选阶段。

正式业务链路：

```text
ETF 基础标的池
        ↓
数据质量与资格门禁
        ↓
多个筛选渠道
├─ 基础因子策略
├─ 成熟机构推荐
├─ 自定义策略
└─ 人工关注渠道（可选）
        ↓
统一 Candidate Proposal
        ↓
融合、风险约束与稳定排名
        ↓
Dynamic Candidate Pool
        ↓
Top N / Watch
        ↓
Stage 4A v1.1
Evidence Pack → E2A → JiuwenSwarm → Research Result
```

本阶段不回答“应该买什么”，只回答：

> 哪些 ETF 值得进入下一轮 AI 深度研判，以及它们为什么被选中、观察或排除。

---

## 2. V1 成熟能力评估

V1 已经存在较成熟的动态选择基础，但不是完整的多渠道融合系统。

### 2.1 V1 已有能力

#### 统一动态选择契约

V1 已定义：

```python
@dataclass(frozen=True)
class TargetSelectionResult:
    as_of: date
    strategy: str
    codes: list[str]
    scores: dict[str, float]
    source: str
    is_fallback: bool
    generated_at: datetime
    fallback_reason: str | None = None
    data_age_days: int | None = None
```

其核心语义可以直接迁移：

- ETF 数量可变；
- 不允许固定 5、9、20 只的业务断言；
- Strategy 必须明确；
- 结果包含来源；
- 最近成功池必须标记 fallback；
- 无有效结果时 fail closed。

#### FQIR 动态候选池

V1 的 `cron_etf_alpha_daily.py` 已具备：

```text
Q/L/R 因子
→ F/I/R 因子
→ FQIR 综合评分
→ 候选过滤
→ Top N 排名
→ etf_candidate_pool 持久化
```

这是 V1 中最成熟的动态筛选主路径。

#### 二因子筛选

V1 的 `dynamic_pool_selector.py` 已实现：

```text
股息率
+ 近 20 日流动性
→ 归一化
→ 0.7 / 0.3 加权
→ 动态排名
```

但该策略在归档版本中被标记为 `frozen`，没有完整生产消费者和正式存储契约。

#### 多场景 ETF Screener

V1 的 ETF Screener 已存在以下场景：

```text
wide_base
sector_rotation
qdii_high
arbitrage_monitor
```

其价值主要是证明“同一 ETF Universe 可以由多个独立策略场景评估”。

#### 最近成功池与 Fail Closed

V1 已形成正确的降级语义：

```text
当日池不可用
→ 查询同策略最近成功池
→ 校验最大年龄
→ 未过期则显式 fallback
→ 过期或不存在则返回空池并告警
```

不得静默回退到固定 ETF 代码。

### 2.2 V1 不应直接搬回的部分

不迁移：

- Python 直接拼 SQL 的旧实现；
- 旧 PostgreSQL 表；
- `strategic_pool_log` 的历史 JSON 格式；
- systemd/cron 编排；
- 固定 `MAX_TARGETS`；
- 固定 ETF fallback；
- 实验策略的冻结状态和生产耦合；
- TypeScript API Gateway 和第二套数据模型。

### 2.3 V2 需要新增的能力

V1 没有形成成熟实现的部分：

- 成熟机构推荐渠道；
- 多机构来源、发布时间和有效期治理；
- 安全的声明式自定义策略；
- 统一 Proposal Contract；
- 多渠道冲突和融合；
- Included / Watch / Excluded；
- 渠道级贡献和解释；
- 与 AI Evidence Pack 的正式接口。

因此，本阶段的原则是：

> 迁移 V1 的成熟业务语义，使用 V2 的 Domain、Storage、UoW、Dagster、FastAPI 和 PostgreSQL 边界重新实现。

---

## 3. 当前 V2 基础

当前系统已经具备：

- `core.instruments`；
- `core.daily_bars` 与 revision；
- `analytics.input_snapshots`；
- `analytics.candidate_pool_runs`；
- `analytics.candidate_pool_items`；
- Candidate Pool 状态机；
- Pipeline Run 审计；
- Candidate Pool Latest/Diff API；
- 最小资格过滤和成交额排名。

当前 Candidate Pool 仍属于 MVP：

- 输入来自配置化个人 ETF 列表；
- 主要使用单日行情；
- 排除规则集中于：
  - `no_data`
  - `suspended`
  - `invalid_price`
  - `low_volume`
  - `low_amount`
- 排名主要使用 `close × volume`；
- 尚未使用滚动历史、趋势、风险和多渠道推荐。

本计划不建立第二套 Candidate Pool，继续复用现有 Run、Item、状态机、Repository 和 UoW。

---

## 4. 阶段目标

完成后系统应能够：

1. 从 `core.instruments` 构造动态 ETF Universe；
2. 对具备历史数据的 ETF 计算共享因子；
3. 同时执行多个独立策略渠道；
4. 将渠道结果统一为 `CandidateProposal`；
5. 使用固定、版本化的融合策略生成候选池；
6. 生成 `included / watch / excluded` 三类结果；
7. 记录每个渠道的支持、反对、理由和有效期；
8. 使用 Shadow 模式运行，不直接替换当前正式池；
9. 向 Stage 4A v1.1 输出 Candidate Pool Run 和 Top N；
10. 相同输入、配置和版本产生相同结果及排名。

---

## 5. 设计原则

### 5.1 筛选与 AI 研判分离

筛选层负责：

- 数据资格；
- 因子计算；
- 阈值判断；
- 渠道标准化；
- 评分融合；
- 稳定排序。

AI 层负责：

- 解释不同证据；
- 对候选横向比较；
- 反方质询；
- 风险和失效条件；
- 综合研判。

筛选层禁止输出：

- 最终投资观点；
- 仓位；
- 目标价；
- 买卖指令；
- 自动订单。

### 5.2 渠道独立

各渠道只能读取统一的 `ChannelEvaluationContext`，并输出统一 Proposal。

渠道之间：

- 不直接调用；
- 不读取其他渠道内部数据；
- 不修改 Universe；
- 不直接发布 Candidate Pool。

### 5.3 机构推荐是外部观点

机构推荐：

- 不能绕过停牌、无效价格和数据质量门禁；
- 不能单独形成最终投资结论；
- 必须保存来源、发布时间、有效期和引用标识；
- 后续进入 Evidence Pack 时标记为 `external_opinion`；
- 不得伪装为确定性事实。

### 5.4 自定义策略使用声明式配置

首版仅支持 YAML/JSON：

- Factor 白名单；
- Filter 条件；
- 人工权重；
- Top N；
- Watch N。

禁止：

- 任意 Python；
- SQL；
- Shell；
- 动态 import；
- 网络请求；
- 自定义函数。

### 5.5 不做参数寻优

所有阈值、权重和渠道权重均是人工策略假设。

本阶段不通过历史收益寻找最优参数。

---

## 6. 首版策略渠道

## Channel A：基础因子筛选

```text
channel_key: baseline_factor_screen
channel_type: deterministic_factor
```

基于：

- 数据完整性；
- 趋势；
- 动量；
- 流动性；
- 波动；
- 回撤。

这是系统基础渠道，其他外部渠道不可用时仍可运行。

## Channel B：成熟机构推荐

```text
channel_key: institutional_recommendation
channel_type: external_recommendation
```

第一版支持：

- 手工 JSON/CSV 导入；
- 来源标识；
- 发布时间；
- 有效期；
- 评级映射；
- 推荐摘要；
- 来源引用；
- 多机构独立权重。

暂不做网页抓取。

后续只有具备授权和稳定数据源时才接 API Provider。

## Channel C：自定义策略

```text
channel_key: custom_strategy
channel_type: declarative_strategy
```

支持多个策略实例：

```text
custom_trend
custom_low_vol
custom_liquidity
custom_defensive
```

首版通过 YAML 定义。

## Channel D：人工关注

```text
channel_key: manual_watchlist
channel_type: manual
```

可选。

人工指定的 ETF：

- 仍需通过基础数据资格门禁；
- 默认最高进入 `watch`；
- 不能直接进入最终 Included；
- 必须记录理由、时间和来源。

---

## 7. 统一渠道契约

建议新增：

```text
packages/domain/src/invest_domain/candidate_pool/channels.py
```

### CandidateChannel

```python
class CandidateChannel(Protocol):
    channel_key: str
    channel_version: str

    def evaluate(
        self,
        context: ChannelEvaluationContext,
    ) -> ChannelResult:
        ...
```

### ChannelEvaluationContext

```python
@dataclass(frozen=True)
class ChannelEvaluationContext:
    as_of_date: date
    instruments: tuple[Instrument, ...]
    factors: Mapping[UUID, Mapping[str, FactorObservation]]
    data_quality: Mapping[UUID, DataQualitySummary]
    candidate_policy_version: str
```

### CandidateProposal

```python
@dataclass(frozen=True)
class CandidateProposal:
    instrument_id: UUID
    channel_key: str
    channel_version: str
    decision: str
    normalized_score: Decimal | None
    confidence: Decimal | None
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    published_at: datetime | None
    valid_until: datetime | None
    metadata: Mapping[str, JsonValue]
```

`decision`：

```text
include
watch
exclude
no_opinion
```

注意：

- 渠道级 `exclude` 表示该渠道不支持；
- 最终硬排除只由基础资格门禁决定。

### ChannelResult

```python
@dataclass(frozen=True)
class ChannelResult:
    channel_key: str
    channel_version: str
    input_hash: str
    output_hash: str
    proposals: tuple[CandidateProposal, ...]
    warnings: tuple[str, ...]
```

---

## 8. 动态 ETF Universe

基础 Universe：

```text
instrument_type = ETF
exchange IN (SSE, SZSE)
status = active
未退市
```

再根据历史数据分类。

### Full Eligible

```text
有效交易日 >= 60
```

可参与全部渠道和最终排名。

### Partial Eligible

```text
20 <= 有效交易日 < 60
```

可参与：

- 20 日因子；
- 机构推荐；
- 人工关注；
- 部分自定义策略。

最高只能进入 `watch`。

### Ineligible

```text
有效交易日 < 20
无有效价格
停牌
严重过期
非法数据
```

进入 `excluded`。

首版建议先覆盖 30–100 只具备历史数据的 ETF，不强制一次扩展到全市场。

---

## 9. 共享因子

Stage 4A-0 与 Stage 4A v1.1 共用同一个因子包。

```text
factor_set_key: etf_market_state_daily
factor_set_version: 1.0.0
```

首版因子：

| Factor Key | 窗口 |
|---|---:|
| `return_20d` | 20 |
| `return_60d` | 60 |
| `distance_ma20` | 20 |
| `distance_ma60` | 60 |
| `realized_volatility_20d` | 20 |
| `max_drawdown_60d` | 60 |
| `avg_turnover_amount_20d` | 20 |
| `data_completeness_60d` | 60 |

建议目录：

```text
packages/domain/src/invest_domain/factors/
├── models.py
├── calculators.py
└── factor_set.py
```

Candidate Routing 和 Research Evidence 不得分别实现同一公式。

Stage 4A v1.1 中的历史行情准备和因子任务，完成本阶段后改为直接复用。

---

## 10. 基础因子渠道

### 10.1 硬资格门禁

- active ETF；
- latest price valid；
- not suspended；
- minimum history；
- data completeness；
- minimum average turnover；
- maximum stale days。

硬门禁失败后，任何机构推荐、人工指定或自定义策略都不能使标的进入 Included。

### 10.2 三维评分

```text
trend_score
liquidity_score
risk_adjustment
```

概念公式：

```text
baseline_score =
    trend_weight × trend_score
  + liquidity_weight × liquidity_score
  + risk_weight × risk_adjustment
```

所有子分数统一到 0–100。

权重通过配置确定，不做回测寻优。

---

## 11. 机构推荐渠道

### 11.1 输入 Schema

```json
{
  "source_key": "institution_x",
  "published_at": "2026-08-03T08:00:00+08:00",
  "valid_until": "2026-08-10T23:59:59+08:00",
  "recommendations": [
    {
      "symbol": "510300",
      "recommendation_level": "recommended",
      "original_score": 4,
      "original_scale": "1-5",
      "confidence": 0.8,
      "reason_summary": "宽基配置价值提升",
      "source_ref": "institution_x:report_20260803"
    }
  ]
}
```

### 11.2 导入命令

```bash
make recommendation-import \
  FILE=config/recommendations/institution-x-20260803.json
```

### 11.3 评级映射

```yaml
recommended: 80
positive: 70
neutral: 50
negative: 20
avoid: 0
```

### 11.4 约束

- 来源必须在白名单；
- 未知 Symbol 记录 warning；
- 过期推荐自动失效；
- 重复推荐按来源和引用去重；
- 不自动计算机构历史胜率；
- 不复制完整受版权保护报告正文；
- 只保存结构化摘要和引用标识。

---

## 12. 自定义策略渠道

配置目录：

```text
config/candidate-strategies/
├── custom-trend.yaml
├── custom-defensive.yaml
└── custom-liquidity.yaml
```

示例：

```yaml
strategy_key: custom_trend
version: 1.0.0
enabled: true

universe:
  minimum_history_days: 60

filters:
  all:
    - factor: data_completeness_60d
      op: gte
      value: 0.90
    - factor: avg_turnover_amount_20d
      op: gte
      value: 10000000
    - factor: distance_ma60
      op: gt
      value: 0

score:
  - factor: return_20d
    weight: 0.35
    direction: higher
  - factor: return_60d
    weight: 0.35
    direction: higher
  - factor: realized_volatility_20d
    weight: 0.15
    direction: lower
  - factor: max_drawdown_60d
    weight: 0.15
    direction: higher

output:
  include_top_n: 10
  watch_next_n: 10
```

首版操作符：

```text
gt
gte
lt
lte
eq
in
all
any
```

加载时验证：

- Strategy Key；
- Version；
- Factor 白名单；
- 操作符；
- 阈值类型；
- 权重和；
- Top N；
- 内容 Hash。

---

## 13. 多渠道融合

首版仅实现：

```text
fusion_policy_key: weighted_union_v1
fusion_policy_version: 1.0.0
```

执行流程：

```text
资格门禁
→ 各渠道独立运行
→ Proposal 标准化
→ 去除过期 Proposal
→ 应用渠道权重
→ 融合评分
→ 风险覆盖
→ 稳定排名
→ included / watch / excluded
```

渠道贡献：

```text
normalized_score
× channel_weight
× confidence_factor
× freshness_factor
```

同时记录：

```text
supporting_channel_count
opposing_channel_count
no_opinion_channel_count
```

建议首版规则：

```yaml
included:
  minimum_fusion_score: 65
  minimum_supporting_channels: 1

watch:
  minimum_fusion_score: 45
```

仅有机构推荐支持、而基础因子明显较弱时，只能进入 `watch`。

### 稳定排序

```text
-fusion_score
-supporting_channel_count
-risk_quality
instrument_id.bytes
```

不得使用随机排序或数据库未指定排序。

---

## 14. Candidate Pool 输出

每个 Candidate Item 至少包含：

```text
bucket
rank
fusion_score
trend_score
liquidity_score
risk_adjustment
channel_contributions
supporting_channel_count
opposing_channel_count
exclusion_reasons
warnings
```

Bucket：

```text
included
watch
excluded
```

现有 `included: bool` 可以兼容：

```text
included → true
watch / excluded → false
```

---

## 15. 存储设计

优先复用：

```text
analytics.input_snapshots
analytics.candidate_pool_runs
analytics.candidate_pool_items
ops.pipeline_runs
```

Candidate Pool Run 记录：

```text
strategy_set_key
strategy_set_version
fusion_policy_key
fusion_policy_version
factor_set_version
channel_keys
channel_input_hashes
channel_output_hashes
run_mode
```

Candidate Pool Item 的 JSON 字段记录：

```text
bucket
channel_contributions
supporting_channel_count
opposing_channel_count
exclusion_reasons
warnings
```

只有现有字段不能满足渠道审计时，才新增一张：

```text
analytics.candidate_channel_snapshots
```

本阶段不新增：

- Factor Store；
- 平行 Candidate Pool；
- 每因子一行的历史表；
- 多套策略结果表。

---

## 16. Pipeline 设计

建议新增：

```text
apps/pipeline/src/invest_pipeline/candidate_routing/
├── universe_builder.py
├── factor_snapshot.py
├── channel_registry.py
├── channel_runner.py
├── fusion.py
├── publisher.py
├── cli.py
└── channels/
    ├── baseline_factor.py
    ├── institutional.py
    ├── custom_strategy.py
    └── manual_watchlist.py
```

新增手工 Job：

```text
dynamic_candidate_pool_job
```

首版默认：

```text
MODE=shadow
```

Shadow 模式：

- 保存结果；
- 不覆盖当前正式池；
- 可与当前 Candidate Pool 比较；
- 可作为 Stage 4A v1.1 的测试输入。

---

## 17. CLI

```bash
make recommendation-import \
  FILE=config/recommendations/institution-x-20260803.json

make candidate-strategy-validate \
  FILE=config/candidate-strategies/custom-trend.yaml

make candidate-channel-run \
  CHANNEL=custom_trend \
  AS_OF=2026-08-03

make dynamic-candidate-pool-run \
  AS_OF=2026-08-03 \
  STRATEGY_SET=research_default \
  MODE=shadow

make candidate-pool-compare \
  BASE_RUN_ID=<current-run-id> \
  TARGET_RUN_ID=<dynamic-run-id>
```

---

## 18. 只读 API

首版增加三个接口：

```http
GET /api/v1/candidate-routing/latest
GET /api/v1/candidate-routing/{run_id}
GET /api/v1/candidate-routing/{run_id}/channels
```

返回：

- Strategy Set；
- Fusion Policy；
- Included / Watch / Excluded；
- 每只 ETF 的渠道贡献；
- 输入/输出 Hash；
- 警告和缺失。

Web 页面不作为阶段完成门禁。

---

## 19. 与 Stage 4A v1.1 的接口

正式研判入口：

```bash
make research-run-from-pool \
  CANDIDATE_POOL_RUN_ID=<uuid> \
  TOP_N=5
```

Evidence Pack 增加：

```text
candidate_pool_run_id
candidate_bucket
candidate_rank
fusion_score
channel_contributions
strategy_set_version
fusion_policy_version
```

单 ETF 命令：

```bash
make research-run \
  INSTRUMENT_ID=<uuid> \
  AS_OF=YYYY-MM-DD
```

继续保留，但仅作为：

- 调试入口；
- 人工指定入口；
- 候选池异常时的受控研究入口。

本阶段完成后，v1.1 中以下任务改为复用：

- 60 日历史行情准备；
- 8 个共享因子；
- Candidate Pool Context；
- 因子公式测试。

---

## 20. 实施任务

### Task 0：契约与边界

- Channel Contract；
- Candidate Proposal；
- Fusion Policy；
- 机构推荐 Schema；
- 自定义策略 Schema；
- 与 v1.1 的接口约定。

### Task 1：Universe 与历史数据

- 动态 ETF Universe；
- 至少一个 65 日 Fixture Universe；
- 历史补齐命令；
- Full / Partial / Ineligible。

### Task 2：共享因子

- 8 个共享因子；
- Factor Set；
- 质量状态；
- 无未来数据。

### Task 3：基础因子渠道

- 资格门禁；
- 三维评分；
- 稳定排名；
- Included / Watch / Excluded。

### Task 4：机构推荐渠道

- JSON/CSV；
- 导入 CLI；
- 来源、有效期和评级映射；
- 未知标的和过期处理。

### Task 5：自定义策略渠道

- YAML Loader；
- Factor 白名单；
- Filter / Score；
- 安全边界；
- 校验 CLI。

### Task 6：融合与发布

- `weighted_union_v1`；
- 渠道贡献；
- 风险覆盖；
- 现有 Candidate Pool 持久化；
- Shadow Mode。

### Task 7：API、E2E 与验收

- 三个 API；
- Fixture E2E；
- 幂等和稳定排名；
- 当前池与动态池对比；
- 验收记录。

---

## 21. PR 拆分

```text
PR-01 Channel Contract 与动态 Universe
PR-02 共享因子与基础渠道
PR-03 机构推荐渠道
PR-04 自定义策略渠道
PR-05 融合、发布、API 与验收
```

依赖：

```text
PR-01
  ↓
PR-02
  ├─→ PR-03
  └─→ PR-04
        ↓
      PR-05
```

PR-03 和 PR-04 可以并行。

---

## 22. 测试

### Domain

- Channel Contract；
- Proposal；
- Strategy Schema；
- Fusion；
- 稳定排序；
- 过期和冲突渠道。

### Factor

- 8 个因子；
- 窗口不足；
- 非法价格；
- amount 缺失；
- 无未来数据。

### Institution

- 正常导入；
- 未知 Symbol；
- 重复；
- 过期；
- 评级映射；
- 来源缺失；
- 版权敏感字段不进入存储。

### Custom Strategy

- 合法 YAML；
- 非法 Factor；
- 非法操作符；
- 权重错误；
- Top N 错误；
- 禁止任意代码。

### Fusion

- 单渠道；
- 多渠道同意；
- 渠道冲突；
- 只有机构推荐；
- 推荐过期；
- 基础风险门禁失败；
- 同分稳定排序。

### E2E

```text
Fixture Universe
→ 65 日行情
→ 基础因子渠道
→ 机构推荐渠道
→ 自定义策略渠道
→ Fusion
→ Dynamic Candidate Pool
→ API
→ 验证 Top N 与渠道解释
```

---

## 23. Shadow 验收

至少执行五个有效交易日或五组固定历史日期。

对比：

```text
当前 Candidate Pool
vs
Dynamic Candidate Routing Shadow Pool
```

检查：

- 候选数量；
- Included / Watch / Excluded；
- 排名；
- 因子值；
- 渠道贡献；
- 空池；
- 过期机构推荐；
- Candidate Pool Hash；
- 相同输入重跑。

Shadow 期间：

- 不覆盖正式池；
- 不触发正式 AI 日报；
- 不产生自动交易建议；
- 仅供人工检查和 Stage 4A v1.1 联调。

---

## 24. Definition of Done

- [ ] 动态 ETF Universe 可生成；
- [ ] 至少一个 Universe 有 60 日历史；
- [ ] 8 个共享因子稳定；
- [ ] 基础因子渠道可运行；
- [ ] 机构推荐可导入并记录来源、时间和有效期；
- [ ] 自定义 YAML 策略可运行；
- [ ] 自定义策略不能执行 Python、SQL 和网络调用；
- [ ] 多渠道统一为 Candidate Proposal；
- [ ] `weighted_union_v1` 可融合；
- [ ] 每只 ETF 有 Included / Watch / Excluded；
- [ ] 每只 ETF 有渠道贡献和理由；
- [ ] 相同输入结果和排名一致；
- [ ] 过期推荐不参与融合；
- [ ] 硬资格门禁不能被外部推荐绕过；
- [ ] Shadow Mode 不覆盖当前正式池；
- [ ] 三个 API 可查询；
- [ ] 可向 Stage 4A v1.1 输出 Candidate Pool Run；
- [ ] 未引入回测、参数寻优、任意代码执行或新微服务。

---

## 25. 风险控制

| 风险 | 控制 |
|---|---|
| 渠道框架过度通用 | 首版三类正式渠道和一个 Protocol |
| 机构推荐质量不稳定 | 人工来源权重、有效期控制、不能绕过资格门禁 |
| 机构内容版权问题 | 只保存结构化摘要和引用，不复制完整报告 |
| 自定义策略代码风险 | YAML DSL、Factor 白名单、禁止 Python/SQL/网络 |
| 权重被误认为最优 | 明确为人工假设，不做历史寻优 |
| 渠道冲突 | 保存支持和反对，进入 Watch 或交给 AI 质询 |
| 影响现有生产 | 默认 Shadow，不覆盖正式池 |
| 因子重复实现 | Candidate Routing 与 Research 共用 Factor 包 |
| 全市场数据成本高 | 首版 30–100 只，逐步扩大 |
| AI 将机构观点当事实 | 标记 `external_opinion`，报告区分事实和观点 |
| V1 旧实现被直接搬回 | 只迁移业务语义，按 V2 边界重写 |

---

## 26. 最终阶段顺序

```text
Stage 4A-0
Multi-Channel Dynamic Candidate Routing
        ↓
Stage 4A v1.1
Evidence + Integrated E2A + JiuwenSwarm Research
```

Stage 4A-0 的核心价值不是寻找历史最优策略，而是：

> 让不同来源和策略以统一、可审计的方式提出研究候选，再由确定性融合层控制候选范围，由 AI 投资研判团队负责深度解释、反方质询和风险判断。
