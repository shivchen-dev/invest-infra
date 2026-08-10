# invest-infra Investment Context Provider 接入实施计划 v1.0

## 目标

将中证指数、巨潮资讯、集思录、天天基金、理杏仁、Go-Goal 等数据源接入 invest-infra，形成 AI 投资研判所需的 Investment Context Layer。

核心原则：

外部数据不直接产生投资结论，而是形成可追溯 Evidence。

---

# 1. 架构目标

```
External Sources

↓

Provider Adapter

↓

Raw Evidence

↓

Canonical Investment Context

↓

Research Evidence Pack

↓

AI Research
```

---

# 2. 数据层扩展

新增：

## ETF Profile

来源：

- 巨潮
- 天天基金
- 官方资料

字段：

- manager
- benchmark
- category
- inception_date
- aum
- shares
- fees


---

## Stock Daily Market Context

来源：

- 通达信本地离线 `.day` 文件
- AkShare 股票历史行情（外部补数/交叉校验候选）
- Tushare Pro 股票日线（需单独确认 Token、权限和使用条款）

新增/复用：

```
core.instruments
core.daily_bars
market_breadth_snapshot
```

用途：

- 全 A 股 Universe
- 上涨/下跌占比
- 站上 MA20 占比
- Market Breadth 的可追溯原始行情输入

约束：

- 通达信文件通过独立 `tdx_offline` Provider Adapter 接入，不允许
  Domain、API 或 Web 直接读取本地路径；
- 日线统一使用未复权原始口径，禁止把 `qfq/hfq` 结果直接写入生产
  `core.daily_bars`；
- 先完成本地文件 Spike（文件完整性、全 A 覆盖、60 个交易日连续性），
  再进入批量导入和 Market Breadth 持久化；
- 该 Provider 不自动取得通达信数据许可，也不承诺本地文件维护 SLA。


---

## Index Exposure

来源：

中证指数等。

新增：

```
index_profile

index_constituents

etf_index_mapping
```

支持：

- 跟踪指数
- 成分股
- 行业权重


---

## Valuation Context

来源：

理杏仁等。

新增：

```
valuation_snapshot

PE

PB

Dividend Yield

ROE

Percentile
```


---

## ETF Trading Context

来源：

集思录。

新增：

```
premium_discount_snapshot

nav

market_price

premium_rate

turnover
```


---

## Fund Event Evidence

来源：

巨潮。

新增：

```
fund_event

event_type

date

summary

source
```

包括：

- 分红
- 公告
- 定期报告


---

## Flow Evidence

来源：

Go-Goal。

新增：

```
flow_snapshot

date

net_flow

institution_activity
```


---

# 3. Provider 分类

## MarketDataProvider

当前代码已存在或已有适配基础：

- AkShare
- Cifang
- Tushare（当前实现仍是 ETF 路径）

规划新增：

- `tdx_offline`：本地通达信 `.day` 股票日线 Provider

说明：EastMoney、Sina 等公开行情源目前是 AkShare 的内部上游候选，
不是本项目当前独立 runtime Provider。


## IndexProvider

负责：

- 指数
- 成分
- 估值


## FundInfoProvider

负责：

- ETF Profile
- 公告


## ResearchDataProvider

负责：

- 理杏仁
- 集思录
- Go-Goal


---

# 4. 数据源可行性与开源项目评估

总体判断：本计划的数据大部分可以获取，但“GitHub 项目可用”不等于“数据源具备稳定授权、完整历史数据和生产 SLA”。Provider 必须保持可替换，并将原始响应和来源信息持久化。

## 4.1 推荐数据源

| 数据类别 | 可获取性 | 首选项目或数据源 | 生产使用结论 |
|---|---|---|---|
| ETF 基本信息、净值、行情、折溢价 | 高 | [AKShare](https://github.com/akfamily/akshare)、[efinance](https://github.com/Micro-sheep/efinance) | AKShare 作为首选采集层，efinance 作为东方财富/天天基金备用源 |
| A 股股票日线 | 高（前提是本地 TDX 文件完整） | 通达信离线 `.day` + `tdx_offline` Adapter；AkShare/Tushare 作为外部候选 | 首选本地文件 Spike；完成覆盖、连续性、许可和维护责任确认后再进入生产数据链路 |
| 指数列表、成分股、权重 | 高 | AKShare 中证公开文件适配、Tushare Pro | 可落地；必须区分当前快照与历史成分/权重 |
| ETF 与指数映射 | 高 | AKShare、Tushare Pro、基金公告及招募说明书 | 通过多来源交叉确认，不依赖单个名称字段 |
| 基金公告、分红、定期报告 | 高 | 巨潮资讯、AKShare CNINFO 接口 | 保留原文 URL、发布日期、下载内容和哈希 |
| PE、PB、股息率、历史分位 | 中高 | Tushare Pro、理杏仁官方开放平台 | 理杏仁优先使用官方 API，非官方 SDK 仅作参考 |
| 集思录折溢价及交易上下文 | 中高 | 集思录受控采集、AKShare 等公开行情源 | Cookie、限流和接口变化风险较高，作为补充源 |
| 市场资金流 | 中 | AKShare、qstock 等公开接口 | 可作为市场辅助指标，不等同于 ETF 净流入 |
| ETF 份额变化、净申购赎回 | 中 | 基金公告、交易所/基金公司数据、商业数据 | 需单独建模，不能由普通资金流接口推导 |
| Go-Goal 研报、一致预期、机构观点 | 低（开源）/高（授权） | Go-Goal 官方商业 API 或数据服务 | GitHub 无成熟可替代项目，需按商业授权接入 |

## 4.2 开源项目定位

- **AKShare**：覆盖面最大，适合作为首期免费采集适配层；其本质是对中证、巨潮、东方财富等公开网页/API 的封装，不是这些平台的稳定授权 API。
- **通达信离线 `.day`**：适合作为本地股票日线输入；字段可映射到 `DailyBar`，但完整性取决于客户端盘后下载和本地目录维护，不能直接视为生产 SLA。
- **`tdx_offline`**：应作为本项目自己的 Provider Adapter；第三方 `easy_tdx`/`tdxrs` 只作为 Reader 或 Spike 依赖，不应让 Domain/API 直接依赖其文件路径或 CLI。
- **Tushare Pro**：适合作为接口较规范的补充，但必须核验 Token、积分、接口权限、字段历史和商用条款；GitHub SDK 的活跃度不能代表 Pro 数据服务的 SLA。
- **efinance**：适合作为东方财富/天天基金的备用实现和交叉验证源，不作为唯一生产数据源。
- **理杏仁**：使用官方开放平台；GitHub 上的非官方封装较旧，不应作为核心依赖。
- **集思录**：目前未发现可视为成熟基础设施的开源 SDK，应预期登录、反爬和接口变动风险。
- **巨潮资讯**：适合公告、基金报告和披露证据，不是 ETF 实时估值、折溢价或资金流的主源。
- **Go-Goal**：涉及研报、机构观点和一致预期等商业数据，不能按普通开源爬虫规划。

## 4.3 数据口径与生产风险

1. **实时接口不代表历史数据完整**：公开接口可能只提供近期分钟数据或当前成分快照。需要的历史快照必须自行持续归档，不能事后补齐。
2. **资金流必须明确口径**：个股、行业或市场资金流不能直接代表 ETF 净申购、赎回、份额变化或资产净流入。`Flow Evidence` 需要区分 `market_fund_flow`、`etf_share_change` 和 `etf_net_subscription`。
3. **多来源字段不可直接拼接**：PE、PB、股息率和 ROE 需要记录计算口径、基准日、样本范围和是否前复权/滚动口径。
4. **网页采集必须可降级**：Cookie 失效、限流、字段变更和反爬均属于预期故障，Provider 需要健康检查、限流、重试、备用源和字段契约测试。
5. **授权边界必须显式化**：研报全文、机构观点、一致预期等内容只有在授权范围内才能落库和进入 Evidence Pack。

## 4.4 分阶段接入建议

### 第一阶段：公开数据基础链路

先接入：

```text
TDX offline Spike + AKShare + Tushare Pro + CNINFO
```

其中 TDX offline 先只验证股票日线和 Market Breadth 所需 20 日窗口；
不直接承诺完整历史成分、历史估值分位或 ETF 净申购赎回。

TDX Spike 的通过条件：

- `sh/sz` 日线目录可定位且文件快照稳定；
- 全 A 股票代码覆盖数量可解释；
- 至少 60 个交易日连续性通过；
- OHLC、成交量、成交额和未复权口径通过契约测试；
- 缺失、停牌、半写入文件和重复记录有明确 fail-closed 规则；
- 本地数据维护责任和使用/再分发边界已确认。

### 第二阶段：特色数据源

单独实现：

```text
Lixinger Provider
Jisilu Provider
```

分别处理官方 Token、Cookie、限流和数据口径，不将其隐藏在通用 MarketDataProvider 中。

### 第三阶段：商业研究数据

实现可插拔的：

```text
GoGoal Licensed Provider
```

只有完成授权、字段清单和保存范围确认后，才接入研报、机构观点、一致预期和机构活动数据。


---

# 5. Evidence 规则

所有数据：

```
Raw Evidence

↓

Field Evidence

↓

Canonical View

↓

Research Evidence Pack
```

字段必须包含：

- value
- source
- observed_at
- quality
- confidence
- content_hash


---

# 6. Provider 质量体系

新增：

```
provider_quality

provider

dataset

freshness_score

coverage_score

reliability_score
```

区分：

- Primary
- Secondary
- Experimental


---

# 7. 实施 PR

## PR-DATA-01

Provider Framework

内容：

- Dataset Registry
- Provider Type
- Quality Score


## PR-DATA-02

中证指数接入

内容：

- Index Profile
- ETF Index Mapping
- Constituents


## PR-DATA-03

ETF Profile Evidence

内容：

- Field Evidence
- Resolver
- Source Priority


## PR-DATA-04

ETF Trading Context

内容：

- NAV
- Premium Discount


## PR-DATA-05

Valuation Context

内容：

- PE
- PB
- Dividend Yield


## PR-DATA-06

External Evidence

内容：

- Fund Events
- Institution View
- Flow Evidence


---

# 8. AI 投研集成

最终 Evidence Pack：

```
ETF Profile

+

Index Exposure

+

Holdings

+

Valuation

+

Market Context

+

Events

+

External Views
```


AI 可以回答：

- ETF是什么？
- 跟踪什么？
- 为什么涨跌？
- 是否高估？
- 风险在哪里？
- 是否有催化因素？


---

# 9. 不建议当前建设

暂缓：

- 高频行情
- 自动交易
- 重型回测
- 大型知识图谱
- 通用 RAG 平台


原因：

当前重点：

可信数据 + 投资上下文 + 证据追踪。


---

# 10. 完成标准

- ETF Profile 多来源覆盖
- 指数和成分可追踪
- 估值进入 Evidence
- 折溢价可分析
- 基金事件可追踪
- 外部观点可引用
- 所有字段有来源
- AI 可以区分事实和观点


---

# 11. 最终路线

```
Dynamic Candidate Pool

↓

Investment Context Layer

↓

Research Evidence Pack

↓

JiuwenSwarm Research Team

↓

AI Investment Report
```
