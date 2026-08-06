# DC-3 AkShare Exposure 数据契约核实

> 核实日期：2026-08-06
> 源码基线：AKShare `e977951ef2cb384eccffa35424c75a51bb5fa1c9`
> 范围：仅使用 AKShare 官方文档和 `akfamily/akshare` 官方源码。

## 结论

AkShare 当前没有一个能直接产出仓库 `exposure_bundle` 的单一接口。DC-3 必须编排多个端点，并将“上游明示披露”与“本地补全”分开。建议首个真实数据切片只支持中证指数 + 东方财富公募 ETF，并允许 `industry=null`。

因此，当前可从 AkShare 可靠构建的只是 provider-independent **profile/constituents/reported holdings 子集**；无法不经外部规则就构建完整 fixture 形状。

## 官方接口与实际能力

| 需求 | AkShare 函数 | 输入 | 可用输出列 | 限制 |
|---|---|---|---|---|
| 指数名称/概要 | `index_csindex_all()` | 无 | 上游 Excel 原始列；源码只显式依赖 `指数代码`、`基日`、`发布时间` | 函数自身注明“不知道数据更新时间”；其他列未在代码中固化，不应当成稳定契约。[Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/index/index_csindex.py#L16-L58) |
| 指数成分/权重 | `index_stock_cons_weight_csindex(symbol)` | 中证 6 位指数代码 | `日期`, `指数代码`, `指数名称`, `指数英文名称`, `成分券代码`, `成分券名称`, `成分券英文名称`, `交易所`, `交易所英文名称`, `权重` | 只是“最新”关闭权重文件；无行业列；权重单位为 `%`，入域前必须除以 100。[Docs](https://akshare.akfamily.xyz/data/index/index.html#index-stock-cons-weight-csindex) [Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/index/index_cons.py#L160-L193) |
| ETF → 跟踪标的 | `fund_overview_em(symbol)` | 公募基金/ETF 代码 | 基金基本概况，包含 `基金代码`, `基金简称`, `基金类型`, `跟踪标的` 等 | `跟踪标的` 是页面文本，不保证提供中证指数代码；无 `effective_from/to`。需本地受控解析/人工映射，不可仅按名称静默猜测。[Docs](https://akshare.akfamily.xyz/data/fund/fund_public.html#fund-overview-em) [Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/fund/fund_overview_em.py#L15-L38) |
| ETF 持仓/权重 | `fund_portfolio_hold_em(symbol, date)` | 基金代码，年份；`date=""` 返回最新可用年份 | `序号`, `股票代码`, `股票名称`, `占净值比例`, `持股数`, `持仓市值`, `季度` | 是定期报告持仓，不是当日 PCF/实时组合；同一返回中可包含多个季度，必须按 `季度` 分组；`占净值比例` 单位为 `%`；无逐券行业。[Docs](https://akshare.akfamily.xyz/data/fund/fund_public.html#fund-portfolio-hold-em) [Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/fund/fund_portfolio_em.py#L84-L163) |
| ETF 行业暴露 | `fund_portfolio_industry_allocation_em(symbol, date)` | 基金代码，年份 | `行业类别`, `占净值比例`, `市值`, `截止时间` | 仅行业聚合，无股票代码，不能可靠地回填每个 `holding.industry`。[Docs](https://akshare.akfamily.xyz/data/fund/fund_public.html#fund-portfolio-industry-allocation-em) [Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/fund/fund_portfolio_em.py#L217-L284) |

`fund_info_index_em()` 不能代替 ETF 跟踪映射：其返回的 `跟踪标的` 是调用者传入的筛选类别（例如“沪深指数”），源码直接执行 `temp_df["跟踪标的"] = symbol`，并非每只基金的真实跟踪指数。[Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/akshare/fund/fund_em.py#L234-L369)

## 建议的最小真实数据契约

1. `IndexProfile`：以 `index_stock_cons_weight_csindex` 中的 `指数代码/指数名称` 为最小权威字段；`category=null`，`as_of_date=日期`。`index_csindex_all` 只做可选富化，列名须运行时校验。
2. `IndexConstituentSnapshot`：一个不为空的 `日期` 分组对应一个快照；`stock_code=成分券代码`，`weight=权重/100`，`industry=null`。
3. `EtfIndexMapping`：`etf_id` 必须由仓库 Instrument 业务键解析；`index_id` 必须来自本地稳定指数身份。只有 `fund_overview_em.跟踪标的` 能经显式规则解析到唯一指数代码时才发布；第一次观测日只能作为 `observed_at`，不得伪造真实 `effective_from`，`effective_to=null`。
4. `EtfHoldingSnapshot`：选取单个最新 `季度`，从季度文本解析报告期为 `as_of_date`；`weight=占净值比例/100`，`industry=null`。必须显式标记这是 `reported_portfolio_holdings`，不得标记为实时或完整 PCF。
5. 每个上游端点应有自己的 raw payload/hash/observed time；当前四段共用一个 `dataset_key`/`observed_at` 的 bundle 可作为应用层组装物，不应掩盖多源、多披露日期。

## 明确不支持/缺口

- **逐券行业**：上述官方函数不提供；当前 fixture 中的 `constituent.industry` 和 `holding.industry` 不能由这些端点直接产生。
- **ETF 跟踪指数的稳定代码与生效区间**：未提供；需受控解析表或更强的第一方数据源。
- **当前域契约的必填 `effective_from`**：AkShare 无对应字段。在未定义“本地规则生效日”及其 provenance 之前，真实 adapter 应跳过 `EtfIndexMapping` 发布，而不是拿爬取日顶替。
- **ETF 当日全量申购赎回清单/PCF**：`fund_portfolio_hold_em` 不是该数据。
- **任意指数提供商**：`index_stock_cons_weight_csindex` 只覆盖中证网站可用的代码；国证、上证等不能默认具有相同契约。
- **历史修订号**：端点未返回 provider revision；仓库 `revision` 应是本地内容变化序号，不能声称是上游版本。

## 依赖与运行边界

AKShare 是一个非轻量依赖：官方包直接依赖 `pandas`, `requests`, `beautifulsoup4`, `lxml`, `xlrd`, `openpyxl` 等。[Source](https://github.com/akfamily/akshare/blob/e977951ef2cb384eccffa35424c75a51bb5fa1c9/pyproject.toml#L42-L59) 当前 `apps/pipeline` 未将 `akshare` 列为默认依赖，且现有 client 采用延迟导入；建议保持此边界，将真实采集放入显式 optional dependency/worker image，fixture 与单元测路径继续不安装 SDK。

## DC-3 下一步建议

先实现三个延迟调用的 client 方法：`index_stock_cons_weight_csindex(index_code)`、`fund_overview_em(etf_code)`、`fund_portfolio_hold_em(etf_code, year="")`。首个手工验证用一只跟踪中证指数、且本地 Instrument 已存在的 ETF。遇到无法唯一解析的跟踪标的、空权重、混合报告期或非中证指数时应 fail closed，不用推测值补齐 bundle。
