# 通达信离线数据源调研

日期：2026-08-10

## 结论

通达信离线 `.day` 文件可以提供全 A 股股票日线，适合作为 Stage 4B
Market Breadth 的本地数据输入源。它不需要 API 令牌，数据由通达信客户端的
“盘后数据下载”维护，系统只读取本地文件。

推荐优先评估 `easy_tdx` 的离线读取能力；若需要高吞吐批量解析，再评估
`tdxrs`。`tdx_ext` 的数据格式解析清晰，但当前构建约束偏重，不适合作为第一
个集成点。

## GitHub 候选

| 项目 | 主要能力 | 对本项目的适配判断 |
|---|---|---|
| [handsomejustin/easy_tdx](https://github.com/handsomejustin/easy_tdx) | 读取 `vipdoc/sh/lday`、`vipdoc/sz/lday` 的 `.day` 文件；支持检测通达信目录、查找日线文件、批量/全市场读取；README/Wiki 还描述了本地日线同步 | 最适合先做离线 Spike。纯 Python，接口容易包进 Provider Adapter；需独立核验全市场扫描、停牌/缺失和同步稳定性 |
| [jiangtaovan/tdxrs](https://github.com/jiangtaovan/tdxrs) | Rust + PyO3；支持 `.day`、`.lc1`、`.lc5`；提供日 K、全市场证券列表、批量下载和增量更新；PyPI 版本为 `0.6.7`，标记为 Beta | 性能和功能最完整，适合后续大批量导入；但引入原生扩展、平台 wheel 和 Rust 构建链，集成成本高于 Python 方案 |
| [donge/tdx_ext](https://github.com/donge/tdx_ext) | DuckDB 扩展 `read_tdx(path)`；解析 `.day/.lc1/.lc5`，输出标准 OHLCV；`.day` 为 32 字节小端记录 | 适合离线分析/临时查询，不建议第一阶段直接引入 DuckDB 扩展：当前 README 的构建环境偏向 macOS Apple Silicon，且存在 unsigned extension / C++ ABI 运维面 |
| [kay-ou/SimTradeData](https://github.com/kay-ou/SimTradeData) | 提供 TDX `.day` 导入脚本、Parquet 导出和数据源路由 | 更像完整数据工程参考/工具箱；应复用其思路，不直接把脚本当作本项目 Provider |

## 数据格式与字段可行性

`tdx_ext` 的 README 明确记录 `.day` 每条 32 字节、小端序：

- 日期：`uint32`，格式 `YYYYMMDD`
- OHLC：`uint32 / 100`
- 成交额：`float32`，元
- 成交量：`uint32`，股
- 尾部 4 字节：未知字段，忽略

这些字段可以映射到现有 `DailyBar`：`trade_date/open/high/low/close/volume/amount`。
但仍需在 Adapter 层补齐并验证：交易所、股票标的主数据、停牌/缺失日期、原始
数据 hash、`observed_at`、revision，以及是否存在文件截断或写入中的半条记录。

通达信 `.day` 是未复权原始行情，符合当前项目禁止直接写入 `qfq/hfq` 的边界；
Market Breadth 的 MA20 应基于同一口径的原始收盘价计算。不要把通达信客户端
显示的前复权结果混入 `core.daily_bars`。

## 适合投研系统的接入方式

不要让 Domain 或 API 直接访问通达信目录。建议新增本地文件 Provider：

1. `tdx_offline` Provider 读取固定配置目录，不读取任意客户端传入路径。
2. `Instrument` 扫描层从 `sh/sz` 日线文件名生成候选代码，并通过 `.tnf/.tni`
   或现有主数据源补齐名称、交易所和状态；无法确定交易所或标的身份时 fail closed。
3. `.day` Reader 只负责解析文件；Mapper 负责构造 `DailyBar` 和稳定的
   `source_ref` / `raw_payload_hash`。
4. Pipeline application service 复用现有
   `ProviderRequest -> ProviderAttempt -> ProviderBatch` 证据链，再写入
   `core.instruments` / `core.daily_bars`。
5. 文件扫描采用快照 + 文件大小/mtime/hash 校验，避开通达信正在写入的文件；
   全 A 股首批导入后做代码数量、日期覆盖、重复记录和 OHLC 一致性验收。
6. 先生成 Market Breadth 所需的 20 日窗口，再开放 Breadth 持久化/API；不先
   把未经验证的本地文件直接接到消费层。

## 风险与限制

- “通达信客户端已下载”不是系统级数据 SLA；需要明确本地目录由谁维护、最后
  成功同步时间和缺失告警。
- `.day` 文件通常提供价格、量额，但不天然提供完整股票主数据、上市/退市历史、
  行业分类和复权事件；这些应由独立主数据合同处理。
- 文件可能被客户端并发更新；读取前必须做稳定性检查，不能假设一次 `read()`
  就是完整快照。
- TDX 数据许可和再分发边界需要按组织实际使用方式确认。GitHub 项目的 MIT
  许可证只覆盖项目代码，不自动授予通达信行情文件的再分发权。
- `tdxrs` README 自身标记为 Beta；原生扩展需验证 Linux/Python 3.12 部署链。

## 建议决策

建议采用“双层方案”：

- **第一阶段**：以通达信本地 `.day` + `easy_tdx`/自有小型 Reader 做只读 Spike，
  先验证当前机器是否有完整 `sh/sz` 文件、全 A 股覆盖数量和 60 个交易日连续性。
- **第二阶段**：把稳定的 `.day` 解析逻辑固化为本项目 `tdx_offline` Adapter，
  不把第三方 CLI/脚本作为核心依赖；若性能不足，再替换为 `tdxrs` Reader。
- **AkShare**：保留为外部补数/交叉校验候选，不作为本地 TDX 数据的前置依赖。

## 一手资料

- `easy_tdx` 离线数据 Wiki：<https://github.com/handsomejustin/easy_tdx/wiki/%E7%A6%BB%E7%BA%BF%E6%95%B0%E6%8D%AE%E8%AF%BB%E5%8F%96>
- `easy_tdx` 项目配置与依赖：<https://raw.githubusercontent.com/handsomejustin/easy_tdx/main/pyproject.toml>
- `tdxrs` README：<https://github.com/jiangtaovan/tdxrs>
- `tdxrs` 项目配置（版本、Python 要求、MIT）：<https://raw.githubusercontent.com/jiangtaovan/tdxrs/main/pyproject.toml>
- `tdxrs` License：<https://raw.githubusercontent.com/jiangtaovan/tdxrs/main/LICENSE>
- `tdx_ext` README（格式、字段、DuckDB 接口）：<https://raw.githubusercontent.com/donge/tdx_ext/main/README.md>
- `SimTradeData` README：<https://github.com/kay-ou/SimTradeData/blob/main/README_zh.md>

