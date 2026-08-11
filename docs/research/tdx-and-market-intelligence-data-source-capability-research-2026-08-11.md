# TDX 与 Market Intelligence 数据源能力调研

- 日期：2026-08-11
- 范围：`invest-infra` 当前实现、本机通达信客户端及离线资产、Tushare 官方接口
- 目标：判断现有数据源能否支撑 Stage 4C 市场研判指标；不把“客户端能显示”误判为“系统已可生产使用”
- 状态词：**已验证可用**＝仓库已有可执行链路且本机存在相应输入；**理论可用但未验证**＝数据或官方接口存在，但尚无本项目生产契约/质量验收；**不可用/高风险**＝关键字段缺失、没有稳定入口，或许可与维护风险不可接受

## 1. 执行摘要

结论：**当前组合足以建设 Stage 4C 的日频 MVP，但通达信不能独立支撑整个 Market Intelligence 系统。**

1. 本机 `/home/claw/tdx-data/vipdoc` 约 5.3 GiB，实测存在沪、深、北三市场的 `.day`、`.lc1`、`.lc5` 文件。日线文件 9,260 个，按 A 股代码前缀筛得约 5,542 只股票；所有被抽检/扫描的股票 `.day` 文件长度均为 32 字节整数倍。绝大多数文件最新记录为 2026-08-10，少量为 2026-08-11，说明当前交易时段不能把“目录存在”当作已完成收盘同步。
2. 仓库已完成 Tushare 股票主数据和日线主源、TDX `.day` 失败后备用、A 股市场宽度、ETF 因子市场温度、Observation/Evidence/Context 链路。
3. **现有 TDX 适配器不能单独产出现有市场宽度**：`.day` 映射明确写入 `prev_close=None`，而宽度服务要求最新记录必须有正数 `prev_close`。这是 Stage 4C 开始前必须收口的真实阻断，不是 UI 问题。
4. TDX 本地数据适合承担：未复权日线 OHLCVA、由相邻交易日推导的昨收/涨跌、MA20/MA60、成交额、波动率、回撤，以及在明确交易规则和证券状态后推导的“触及涨跌停”。它不能从 `.day` 恢复封单、炸板过程、连板过程中的盘中状态、主力资金或历史板块归属。
5. `.lc1/.lc5` 数量充足，理论上可重建盘中触板/开板轨迹；但仓库未实现解析、缺少完整性与时间口径验收，而且历史通常受客户端下载窗口约束，故仅列为候选 Spike，不进入首个生产范围。
6. 客户端在线协议、内存/交互数据抓取列为**高风险并排除**。本机随客户端提供的《通达信用户服务协议》第 10 条明确限制逆向工程、对运行时/交互数据使用未经授权第三方工具接入等行为。[本机协议](file:///home/claw/.wine-tdx/drive_c/new_tdx64/service.html)
7. 推荐路由不是“TDX 替代一切”，而是：**TDX 日线作低成本本地事实源，Tushare 作主数据、官方结构化指标和交叉校验源；交易所规则作涨跌停口径权威；行业/概念、资金流等按独立数据合同接入。**
8. 本轮对当前 Tushare Token 做了最小只读权限验证：`daily_basic` 可用（2026-08-10 返回 5,538 行）；`tdx_index`、`kpl_list`、`dc_index`、`limit_list_d`、`index_classify`、`index_member`、`moneyflow` 均无权限。因此估值/换手输入已具备候选能力，而板块、涨跌停、行业成员和资金流接口不能写入 Stage 4C 的“已具备”基线，只能作为未来权限变化后的候选。

## 2. 调研方法与本机证据

本次只读检查包括：仓库源码/任务文档、TDX 文件树和文件头尾记录、文件数量/大小/更新时间、客户端自带服务协议，以及 Tushare 官方文档页面。未读取或输出任何凭证。

### 2.1 本机 TDX 资产盘点

数据根：`/home/claw/tdx-data/vipdoc`（约 5.3 GiB）。客户端安装树位于 `/home/claw/.wine-tdx/drive_c/new_tdx64`，其自身 `vipdoc` 只有约 88 KiB；生产配置必须明确指向前者，不能靠客户端安装目录猜测。

| 市场 | `.day` 总文件 | 按股票前缀筛选 | 股票文件非 32 倍数 | 股票最早首记录 | 主流最新记录 |
|---|---:|---:|---:|---:|---:|
| 上海 | 4,673 | 2,312 | 0 | 2020-01-02 | 4,659 个文件为 2026-08-10 |
| 深圳 | 4,252 | 2,895 | 0 | 2020-01-02 | 4,167 个文件为 2026-08-10；59 个为 2026-08-11 |
| 北京 | 335 | 335 | 0 | 2020-07-27 | 334 个文件为 2026-08-10 |

分钟文件现状：`.lc5` 为上海 4,612、深圳 4,144、北京 315；`.lc1` 为上海 4,677、深圳 4,265、北京 335。`vipdoc/cw` 当前为空，因此未发现可直接验证的财务文件输入。

说明：上表“按股票前缀筛选”只是盘点口径，不是证券主数据。退市、ETF、债券、指数、特殊证券身份必须由权威主数据确认；TDX 文件名不能承担上市状态与证券类型合同。

### 2.2 已有仓库能力

- Reader 只解析 `vipdoc/{sh,sz,bj}/lday/{market}{symbol}.day`，每条 32 字节，支持三交易所映射和文件枚举；它明确不处理复权、ETF 协议和持久化。[reader.py](../../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/reader.py#L1)
- TDX provider 能独立发现本地 symbol，并用显式 market/symbol 读取北京市场，失败时 fail-closed。[stock_adapter.py](../../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/stock_adapter.py#L503)
- 编排策略仍是 Tushare 主源，只有 Tushare `failed` 且显式启用 TDX 时才调用离线备用；`partial` 不会被 TDX 覆盖。[stock_daily_bars.py](../../apps/pipeline/src/invest_pipeline/stock_daily_bars.py#L474)
- Tushare 客户端当前只实现 `stock_basic` 和未复权 `daily`。`daily` 已请求 `pre_close`、OHLC、成交量和成交额；`stock_basic` 包括行业、市场、上市/退市日期和状态。[client.py](../../apps/pipeline/src/invest_pipeline/adapters/tushare/client.py#L54)
- 当前市场宽度只有上涨占比、下跌占比、站上 MA20 占比；输入必须含 `close/prev_close/ma20/trading_status`。[market_breadth.py](../../packages/domain/src/invest_domain/analytics/market_breadth.py#L148)
- 当前温度使用 `return_20d`、20 日波动率、20 日平均成交额、60 日最大回撤四个因子，输出 0–1 score/state，不是截图式全 A 股情绪温度。[market_temperature.py](../../packages/domain/src/invest_domain/analytics/market_temperature.py#L15)
- 研究 Dashboard 主读模型仍固定声明市场源未注册，UI 产品闭环尚未形成。[research.py](../../apps/api/src/invest_api/application/research.py#L23)

## 3. 通达信四层能力判断

### 3.1 已接入离线文件：`.day`

定级：**有条件可用**。

可直接提供未复权日线日期、OHLC、成交量、成交额；可计算收益、均线、量能、波动率、回撤和市场宽度。本地历史从 2020 年起，足够做近六年日频回放，但不是完整 A 股长历史。

现有缺陷：映射器把每条 TDX bar 的 `prev_close` 固定为 `None`，且把存在的每条记录都标为 `TradingStatus.NORMAL`；缺失记录只是“无行”，不能区分停牌、漏数或未上市。[stock_adapter.py](../../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/stock_adapter.py#L215) 宽度服务又会过滤掉缺少 `prev_close` 的股票，因此当前 TDX-only fallback 和宽度消费契约不闭合。[market_breadth_service.py](../../apps/pipeline/src/invest_pipeline/market_breadth_service.py#L377)

### 3.2 其他本地缓存：`.lc1/.lc5`、板块/客户端缓存

定级：**理论可用但未验证**。

- `.lc1/.lc5`：文件广泛存在，理论上可以重建分钟 K、盘中触板和开板轨迹；仓库 reader 明确忽略这两类文件，没有 schema、时区、集合竞价、复牌和缺口质量合同。
- `T0002/blocknew/zxg.blk` 是用户自选板块，不是行业/概念权威分类。
- 客户端存在 `BlockMap/*.dat`、`base.dbf`、`hq_cache/base.dbf` 等资产，但本次没有一手 schema 或稳定导出合同，不能据文件名推断为可生产的板块、财务或证券主数据。
- `vipdoc/cw` 当前为空，财务/估值不能宣称由本机 TDX 提供。

### 3.3 客户端导出

定级：**理论可用但未验证，不作为自动生产主链**。

客户端人工导出可用于小样本口径核对，但本次未发现仓库中稳定的无交互导出合同、固定 schema、增量游标和失败重试机制。人工导出还缺少 provider request/batch、原始 hash 和同步 SLA。若未来验证，只应作为受控导入文件，而不是驱动自动化驾驶舱。

### 3.4 在线协议或运行时抓取

定级：**不可用/高风险，Stage 4C 排除**。

原因包括：非官方稳定 API、协议/字段可能随客户端升级变化、账号/限频/封禁风险、无法承诺 SLA。更重要的是客户端自带服务协议限制逆向工程，以及通过未经授权第三方工具接入软件和交互数据；在获得通达信书面授权前，不应做协议抓取或运行时注入。[本机 service.html 第 10 条](file:///home/claw/.wine-tdx/drive_c/new_tdx64/service.html)

## 4. 指标能力矩阵

| 研判能力 | 需要的事实 | TDX 本地 | Tushare 官方接口 | 当前系统定级 | 结论 |
|---|---|---|---|---|---|
| 涨跌家数/平盘 | 当日与前一有效交易日收盘 | `.day` 可推导 | `daily.pre_close` 原生提供 | Tushare 已接；TDX 缺昨收映射 | **近期可落地** |
| MA20/MA60 宽度 | 连续日线、证券池、停牌口径 | `.day` 可算 | `daily` + `stock_basic` | MA20 已实现，MA60 未实现 | **近期可落地** |
| 成交额/量能 | amount/volume 历史 | `.day` 原生 | `daily` 原生 | 已持久化基础字段 | **已具备输入** |
| 波动率/回撤 | 连续收盘历史 | `.day` 可算 | `daily` 可算 | ETF 温度已有同类算法 | **近期可落地** |
| 收盘涨停/跌停 | 证券板块、ST 状态、上市日、当日价格限制 | 日线只能判断收盘/触及；无完整状态 | `limit_list_d` 提供每日涨跌停统计；`daily`/主数据可交叉核对 | 未接入 | **优先用官方结构化接口** |
| 炸板/封板时长 | 分钟或逐笔轨迹、涨停价、状态 | `.lc1/.lc5` 候选；日线仅能粗判 high=limit 且 close<limit | `limit_list_d` 可提供部分结构化字段，权限需验证 | 未接入 | **先用官方日频；分钟 Spike 后置** |
| 连板高度 | 多日涨停事件、复牌/ST/新股口径 | 可由可靠涨停事件派生 | `limit_list_d` 可作为事件源 | 未实现 | **可落地但先冻结规则** |
| 行业分类/行业强度 | 分类体系、成分、历史有效期、行情 | 本机缓存未证实稳定 schema | `index_classify`、`index_member` 提供申万分类/成员 | `stock_basic.industry` 只有当前粗字段 | **以 Tushare 分类接口为主** |
| 概念/题材扩散 | 概念清单、成分、变更历史 | 客户端可见不等于可抽取 | Tushare 有同花顺指数/成分等候选接口，权限与历史需实测 | 未接入 | **候选，不能承诺历史回放** |
| 风格轮动 | 宽基/风格指数、成分/权重、收益 | TDX 指数 `.day` 文件存在但尚未分类接入 | 指数日线、成分/权重相关接口 | ETF/指数暴露已有部分模型 | **可做价格轮动；历史成分需另验** |
| 个股资金流 | 买卖方向分档口径 | `.day` 无法提供 | `moneyflow` 官方接口候选 | 未接入 | **Tushare 候选，口径不可与“主力净流入”混用** |
| 北向资金 | 交易机制与官方可得性 | `.day` 不提供 | 需按当前互联互通披露和 Tushare可用接口单独确认 | 未接入 | **不纳入首期承诺** |
| 估值/基本面 | PE/PB/换手/财务快照 | 本机 `cw` 为空 | `daily_basic` 等官方接口 | 未接入股票日频估值 | **Tushare 可候选** |
| 盘中盘口/逐笔 | 委托、成交、撤单 | 普通本地文件未验证，在线抓取高风险 | 当前仓库无对应官方源 | 未实现 | **Stage 4C 排除** |

Tushare 一手接口页面：[`daily`](https://tushare.pro/document/2?doc_id=27)、[`stock_basic`](https://tushare.pro/document/2?doc_id=25)、[`limit_list_d`](https://tushare.pro/document/2?doc_id=298)、[`daily_basic`](https://tushare.pro/document/2?doc_id=97)、[`moneyflow`](https://tushare.pro/document/2?doc_id=170)、[`index_classify`](https://tushare.pro/document/2?doc_id=259)、[`index_member`](https://tushare.pro/document/2?doc_id=260)。这些页面可访问不代表当前 Token 已具备积分/权限；必须以真实最小请求验收。

当前账户实测补充：`daily_basic` 的 2026-08-10 最小只读请求成功返回 5,538 行；`tdx_index`、`kpl_list`、`dc_index`、`limit_list_d`、`index_classify`、`index_member`、`moneyflow` 的最小只读请求均返回无权限。这个结果只证明当前账户当前时点的权限状态，不代表 Tushare 平台没有相应产品；计划中必须把不可访问接口标为 blocked/candidate，而不是现成数据源。

## 5. 历史、时效、口径、合规和维护风险

| 风险 | 实证 | 控制要求 |
|---|---|---|
| 收盘时效 | 2026-08-11 盘中，绝大多数 `.day` 仍止于 2026-08-10，少量文件已有 2026-08-11 | 按交易日设置“收盘完成”水位；以全市场覆盖率而非最大日期判断 freshness |
| 历史截断 | 本机股票日线最早普遍为 2020-01-02 | 回测报告必须声明可用区间；不将其称为全历史 |
| 停牌与缺数混淆 | TDX 映射只对存在记录标 NORMAL，缺日无 row | 使用交易日历+上市状态+第二源区分停牌/未上市/缺失；未知项不得进入分母 |
| 昨收缺失 | TDX 映射 `prev_close=None`，宽度要求非空 | 从同口径前一有效 bar 推导并留 lineage，或改变宽度输入合同；两者必须选一并测试 |
| 复权口径 | `.day` 当前按 `Adjust.NONE` 入库 | 涨跌、宽度、限价使用未复权一致口径；长期收益另建复权序列，不覆盖原始行情 |
| 涨跌停规则 | 不同板块、ST、上市初期和规则变更不能用固定 10% 代替 | 以交易所规则和每日证券状态冻结算法版本；优先用结构化涨跌停事件交叉验证 |
| 行业历史漂移 | `stock_basic.industry` 是当前主数据字段，不是历史成分事实 | 行业/概念成员必须带 `effective_from/to` 或 snapshot date；缺历史时禁止回填未来分类 |
| 数据许可 | Tushare 权限/积分与使用条款待账户实测；TDX 协议对逆向/第三方接入有明确限制 | 仅内部使用也应做条款审查；禁止再分发；在线协议抓取排除 |
| 文件并发更新 | 客户端可能正在写文件 | 读取前后校验 size/mtime/hash，非 32 倍数或水位变化 fail-closed |
| Provider 漂移 | Tushare 字段和权限、客户端版本/文件可能变化 | 原始 payload/file hash、schema version、provider attempt、跨源抽样一致性告警 |

交易制度的最终口径应引用上交所、深交所、北交所现行交易规则及其修订公告，而不是博客或硬编码经验值：<https://www.sse.com.cn/lawandrules/sselawsrules/trade/>、<https://www.szse.cn/lawrules/rule/trade/>、<https://www.bse.cn/rule/rule_detail.html>。具体实现前要冻结“规则版本—生效日期—证券板块/ST/上市阶段”表。

## 6. 主备源路由建议

| 数据合同 | 主源 | 备用/校验 | 原因 |
|---|---|---|---|
| 股票身份、上市状态、行业粗字段 | Tushare `stock_basic` | 交易所证券列表；TDX 仅发现候选代码 | 文件名不能证明证券身份或 active 状态 |
| 未复权股票日线 | Tushare `daily` | TDX `.day` | 当前链路已如此实现；TDX 本地成本低、适合故障降级 |
| 日频宽度/量价/风险 | 系统从归一化 daily bars 计算 | Tushare/TDX 跨源抽检 | 派生指标不应绑定单一 provider |
| 涨跌停事件 | Tushare `limit_list_d` 或交易所可验证事实 | 归一化日线+规则引擎复核 | 避免单靠百分比猜 ST/新股/规则变更 |
| 行业分类与成分 | Tushare `index_classify/index_member` | 交易所/指数公司公开资料 | 需要明确分类版本和快照日期 |
| 概念/题材 | 单独受治理的结构化 provider | TDX 仅人工抽样核对 | 概念口径供应商依赖强，历史漂移大 |
| 分钟行情 | 暂不设生产主源 | TDX `.lc1/.lc5` 只做受控 Spike | 当前无 reader、质量合同和许可结论 |
| 资金流/估值 | Tushare 对应官方接口候选 | 第二独立源抽检 | TDX `.day` 不具备这些语义 |

## 7. Stage 4C 可落地边界

### 可进入首期的确定范围

1. 数据质量收口：TDX/Tushare 收盘水位、覆盖率、文件稳定性、跨源抽样差异、证券池完整率。
2. 修通同口径 `prev_close` 与停牌/未知状态，保证 TDX fallback 真能供给宽度。
3. 日频研判：涨跌/平盘、MA20/MA60 宽度、成交额与量能分位、20 日波动率、60 日回撤。
4. 接入日频涨跌停事件，派生涨停/跌停家数、连板高度；每项都带规则/数据版本。
5. 接入一套有版本的行业分类和当前/历史成员快照，计算行业强度、扩散度和持续性。
6. 所有结果沿用 `Observation → Evidence Bundle → Context Projection`，先提供最小验证视图，不把 UI 当数据事实源。

### 仅做 Spike 或后置

- `.lc1/.lc5` 解析、盘中触板/炸板时刻和封板时长。
- 概念题材历史、资金流、估值、历史指数成分；先验证权限、字段、历史和口径。
- 正式驾驶舱视觉设计；应等指标与数据质量状态稳定。

### 明确排除

- TDX 私有在线协议、内存/交互数据抓取、插件注入。
- L2 盘口、逐笔委托撤单等当前没有合规稳定源的数据。
- 用当前行业标签回填历史、用固定 10% 推断所有涨跌停、把缺 bar 一律当停牌。
- 对外再分发 TDX/Tushare 原始数据。

## 8. 计划入口门槛

Stage 4C 计划可按上述边界制定，但实施前应把以下验收项写成硬门槛：

- TDX 单日收盘覆盖率按沪深北和证券状态分层统计，不能只看文件总数或最大日期。
- `prev_close` 方案对停牌、上市首日、退市整理和跨长假有明确测试样例。
- Tushare `limit_list_d/index_classify/index_member` 当前账户均已确认无权限；计划必须把权限获取或替代数据源列为前置决策，并在权限变化后重新验证行数、历史起点、限频和字段。
- 涨跌停规则版本得到交易所规则逐项映射；行业成员有 snapshot/effective date。
- 任何 `.lc1/.lc5` 工作先做独立 reader Spike 和许可复核，不直接进入生产资产。

最终判断：**优先加强数据与指标层是正确方向；TDX 是强力的本地日线底座和候选分钟数据源，但不是行业、概念、资金、主数据和合规实时协议的一站式答案。Stage 4C 应以“日频可信事实闭环”为边界，而不是以“客户端界面能看到多少内容”为边界。**
