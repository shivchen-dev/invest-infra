# Stage 4C Phase 1.2：A 股价格限制规则核查

> 核查日期：2026-08-11（Asia/Shanghai）
>
> 范围：A 股主板、创业板、科创板、北交所、ST；作为 Stage 4C Phase 1.2 的规则依据与实现记录。
> 证据优先级：交易所现行规则/业务指南 > 证监会制度文件 > 交易所官方问答；未引用二手文章。

## 结论摘要

截至核查日，当前常规股票规则可归纳为：主板 10%（风险警示股票通常为 5%）、创业板 20%、科创板 20%、北交所 30%；创业板/科创板新股上市前 5 个交易日不设涨跌幅限制，主板新股自 2023-04-10 起上市前 5 个交易日不设限制，北交所新股仅上市首日不设限制。各交易所均以价格最小变动单位 0.01 元进行价格计算并按规则四舍五入；精确的上市状态、风险警示状态和前收盘/除权除息参考价必须作为输入，不能由代码猜测。

下表是“已证实”的当前规则摘要；历史回放必须按生效日期选择规则版本。

| 市场/板块 | 常规限制 | ST/风险警示 | 新股无涨跌幅边界 | 主要制度切换 |
|---|---:|---:|---|---|
| 沪深主板 | ±10% | 通常 ±5% | 2023-04-10 起，上市后前 5 个交易日；此前首日有 ±44% 等旧规则 | 主板注册制交易规则自 2023-04-10 配套生效 |
| 创业板 | ±20% | 创业板风险警示股票仍按 ±20% 口径 | 上市后前 5 个交易日 | 注册制交易特别规定自 2020-08-24 起实施 |
| 科创板 | ±20% | 科创板风险警示股票按板块 ±20% 口径处理 | 上市后前 5 个交易日 | 科创板开市交易 2019-07-22；相关特别规定随板块开市生效 |
| 北交所 | ±30% | 北交所风险警示/特别处理口径需以北交所挂牌状态及现行规则确认；不得套用主板 5% | 仅上市首日 | 北交所开市交易 2021-11-15 |

“ST”不是跨市场单一规则：主板的 ST 5% 不能自动外推到创业板、科创板或北交所。北交所特别处理股票的具体状态字段、是否存在单独限制比例，应由业务在接入北交所挂牌状态后确认；未知时必须返回 unknown/rejected。

## 一手来源与可定位依据

以下链接均为交易所/证监会官方来源，检索日期均为 2026-08-11。交易所网页会随规则修订更新，生产实现应保存下载文件或网页快照、发布日期、版本号和 hash。

1. 上海证券交易所，《上海证券交易所交易规则（2023 年修订）》：价格涨跌幅限制、价格最小变动单位及新股上市初期交易安排，重点核对“股票交易”“价格涨跌幅限制”“新股上市初期交易”条款。官方规则入口：[上交所法律规则—股票主板/科创板](https://www.sse.com.cn/lawandrules/sselawsrules/stocks/main/)。
2. 上海证券交易所，《上海证券交易所科创板股票交易特别规定》：科创板 ±20%、上市前 5 个交易日不设涨跌幅限制、价格最小变动单位等。官方规则入口：[上交所科创板法律规则](https://www.sse.com.cn/lawandrules/sselawsrules/stocks/star/)。开市日期可与上交所 2019-07-22 开市公告交叉核对：[科创板官方信息入口](https://star.sse.com.cn/)。
3. 深圳证券交易所，《深圳证券交易所交易规则（2023 年修订）》及《深圳证券交易所创业板交易特别规定》：主板 ±10%、风险警示股票 ±5%、创业板 ±20%、创业板新股前 5 个交易日无涨跌幅限制，以及按最小变动单位四舍五入。官方规则入口：[深交所法律规则—股票](https://www.szse.cn/lawrules/rule/stock/index.html)。创业板注册制切换日由深交所创业板改革配套规则及 2020-08-24 交易安排公告确认：[深交所创业板改革专栏](https://www.szse.cn/marketServices/technicalservice/)。
4. 中国证监会，《创业板首次公开发行股票注册管理办法（试行）》及创业板改革配套制度：注册制制度切换和交易特别规定的上位制度依据。官方法规入口：[中国证监会规章及规范性文件](https://www.csrc.gov.cn/csrc/c101864/common_list.shtml)。
5. 北京证券交易所，《北京证券交易所交易规则（试行）》及《北京证券交易所股票交易特别规定》：±30%、上市首日不设涨跌幅限制、最小变动单位 0.01 元及价格计算/四舍五入条款。官方规则入口：[北交所规则](https://www.bse.cn/rules.html)。北交所开市交易日由北交所开市公告确认：[北交所官方首页/公告](https://www.bse.cn/)。
6. 证监会、上交所、深交所 2023 年全面实行股票发行注册制配套规则及主板新股交易安排公告：主板新股上市前 5 个交易日无涨跌幅限制的生效边界为 2023-04-10。官方入口：[证监会全面注册制专栏](https://www.csrc.gov.cn/csrc/c100028/common_list.shtml)。

## 规则细节

### 1. 价格精度、最小变动单位和舍入

- 本切片涉及的沪深 A 股、科创板和北交所股票，报价精度按 0.01 元；不要使用二进制浮点数保存或计算限制价，应使用 `Decimal`/整数分。
- 计算模型是以前收盘价（或交易所认定的当日参考价）乘以 `1 ± limit_ratio`，结果按交易所规则四舍五入到价格最小变动单位。限制价不是简单把百分比截断到两位小数。
- 因四舍五入，展示的限制价反推百分比可能略高或略低于名义比例；比较应比较规范化后的价格，不应比较浮点百分比。
- 价格低于 0.01 元、复权价格、除权除息日参考价、停牌后恢复交易参考价等边界不在本次研究中形成实现规则，必须使用交易所/行情源给出的参考价和状态。

定位依据：上述交易规则中关于“价格最小变动单位”“涨跌幅限制价格计算结果按四舍五入原则取至价格最小变动单位”的条款；见上交所、深交所、北交所官方规则入口（检索日期 2026-08-11）。

### 2. 无涨跌幅限制的边界

- “上市前 5 个交易日”是交易日序号 1—5，不是自然日，也不是从发行公告日计算；第 6 个交易日起进入板块常规比例。
- 主板新股的 5 日无涨跌幅安排是全面注册制主板规则的生效结果，不能回填到 2023-04-10 以前的历史；旧主板首日 ±44% 等规则必须单独保留历史 regime。
- 创业板、科创板的 5 日无涨跌幅规则分别随 2020-08-24 创业板注册制交易安排、2019-07-22 科创板开市交易生效；不能只按当前板块字段回放更早历史。
- 北交所新股的当前边界是上市首日不设涨跌幅限制，第二个交易日起适用 ±30%；不能把北交所套成沪深科创板的 5 日规则。
- “无涨跌幅限制”不等于无价格约束：临时停牌、盘中交易公开信息、申报价格有效范围和异常交易监管仍可能适用；这些不属于本切片的涨跌幅字段。

## 项目内可版本化 Domain 合同（已落地）

建议把规则作为纯 Domain policy，而不是写入 Provider 或 Analytics：

```text
PriceLimitRegime {
  regime_id: str                 # immutable，例如 SSE_MAIN_2023_04_10
  market: SSE | SZSE | BSE
  board: MAIN | GEM | STAR | BSE
  effective_from: date           # inclusive
  effective_to: date | null      # exclusive
  normal_ratio: Decimal | null
  risk_warning_ratio: Decimal | null
  ipo_unlimited_sessions: int
  tick_size: Decimal              # current scope: 0.01
  rounding: HALF_UP               # exchange rule: 四舍五入
  source_refs: tuple[SourceRef, ...]
}

PriceLimitResult =
  Known(limit_up, limit_down, regime_id, reference_price, source_refs)
  | Unlimited(regime_id, session_no, source_refs)
  | Unknown(reason, required_fields, source_refs)
```

合同约束：

1. 输入必须包含 `instrument_id`、交易所/板块、`trade_date`、上市交易起始日、当日上市交易序号、风险警示/特别处理状态、交易所认可的前收盘或参考价；缺任一关键字段不得默认到 10%。
2. 先按 `effective_from <= trade_date < effective_to` 选择唯一 regime，再判定 IPO session 和风险警示；不能以“当前板块规则”覆盖历史。
3. 同一输入与同一 `regime_id` 必须确定性地产生结果；规则修订以新增 regime 处理，旧版本只读可回放。
4. 未知 market/board、重叠生效区间、缺少来源、上市序号无法确定、ST 状态与板块不相容时 fail-closed：返回 `Unknown` 或拒绝发布 `stock_price_limits`，不得生成猜测的限制价。
5. `stock_price_limits` 应保留 `rule_version/regime_id`、`reference_price`、`limit_up_price`、`limit_down_price`、`source_refs`；`hit_limit_*` 只能在限制价已知时计算，未知时为 unknown。

## 状态分类

### 已证实

- 当前常规比例、创业板/科创板/主板新股无涨跌幅边界、北交所首日边界、0.01 元最小变动单位和四舍五入模型，均有交易所规则依据。
- Stage 4C 已落地版本化价格限制 Domain policy，并通过 fixture provider 覆盖沪深主板、创业板、科创板和北交所的代表性规则场景；`stock_price_limits` 尚未进入正式路由发布。
- 当前仓库已有 `prev_close` 补齐工作和日线 Provider，但不能替代交易所规则版本、上市状态和风险警示状态。

### 需业务确认

- 北交所 ST/风险警示挂牌状态的字段来源、实际限制比例及历史生效版本；在官方状态字段接入前不应硬编码。
- 除权除息、停牌复牌、发行后首个交易日和历史 regime 的参考价来源与优先级。
- “前 5 个交易日”是否以项目的 `listed_trade_session_no` 为准，以及跨停牌/暂停上市情形如何计数。
- 本项目是否只支持普通股票；ETF、可转债、存托凭证、B 股、退市整理期和其他特殊证券应明确排除或另建 regime。

### 明确不在本切片

- 不实现数据库迁移、正式 Provider 路由、Analytics 或 UI。
- 不实现临时停牌/有效申报价格范围、开板/封板盘中判定、除权除息参考价生成、北交所特殊状态映射。
- 不把二手行情软件字段或当前行情标签当作规则权威来源。

## 仓库复用核查

- `docs/plan/invest-infra-stage4c-core-data-layer-integration-plan.md` §3.3、§4.3、§7：已有 `stock_price_limits` 候选 dataset、`prev_close`/限制价/命中字段和 `rule_version/source_refs` 设计。
- `tasks/stage4c-core-data-layer-integration-todo.md` “Phase 1：日频市场状态”：已有“冻结 A 股价格限制规则与版本”“建设 `stock_price_limits` Raw/Core 事实”。
- `docs/adr/0004-etf-market-calendar-timezone-range.md`、`docs/adr/0005-etf-daily-bars-adjustment-contract.md`、`docs/adr/0006-daily-bar-revision-latest-policy.md`：可复用交易日、Decimal/日线 revision/provenance 的治理方向，但没有价格限制规则。
- 已落地 `limit_up_price`、`limit_down_price`、`regime_id` 和 fail-closed 结果语义；Provider catalog/dataset 只冻结能力名称与映射，尚未声明可路由 Provider。

## 核查边界与证据保全

本报告记录的是 2026-08-11 检索到的官方规则入口和条款定位。正式编码前，应将每个规则文件的具体发布日期、修订号、PDF/网页快照和 SHA-256 纳入 `SourceRef`；若官方页面更新或链接迁移，不能仅凭本报告的摘要继续扩展历史规则。
