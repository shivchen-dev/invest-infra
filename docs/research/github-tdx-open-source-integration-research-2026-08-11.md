# GitHub 通达信开源项目集成调研

- 日期：2026-08-11
- 范围：本地文件解析、行情协议/API、财务/板块/除权、公式/选股、GUI 自动化
- 方法：仅使用 GitHub 仓库 README、LICENSE、源码和 GitHub commit/repository 元数据；星数与提交时间是 2026-08-11 快照
- 目标系统：`invest-infra` 现有 `InstrumentProvider` / `EtfMarketDataProvider`、`raw.provider_requests` / `attempts` / `batches` 和 `tdx_offline` 适配器

## 结论

**唯一适合优先复用的是 `mootdx/mootdx`，但应只复用现有系统尚缺的解析能力，不应替换当前 `.day` Provider。** 它以 MIT 发布，覆盖 `.day`、`.lc1/.lc5`、板块文件、线上行情、财务包和除权相关能力；不过最后提交停在 2024-07，网络协议和上游端点必须隔离为可降级 Provider。

`pytdx` 是重要的协议实现来源，但仓库已归档且 README 明确“个人学习、不得商业使用”，并且 GitHub 没有可识别许可证，不能直接并入。`node-tdx` 虽有 MIT 文件且 2026 年仍活跃，但 README 同时限定“协议研究与个人学习、请勿商业使用”；技术许可与数据/服务器使用声明存在冲突，只能参考。GUI 自动化方面没有找到同时具备明确许可证、稳定版本契约和通达信 7.64 实证的成熟专用项目；继续使用我们已经验证的 `xdotool + 导出文件` 薄适配层，比引入交易机器人或通用桌面框架更可控。

## 候选矩阵

| 项目 | 用途/语言 | 活跃度快照 | License/附加声明 | 与当前系统关系 | 分级 |
|---|---|---|---|---|---|
| [`mootdx/mootdx`](https://github.com/mootdx/mootdx) | Python；本地日线/分钟线、板块、自定义板块，线上行情，财务文件 | 2,187 stars；最后提交 [`e99ae34`](https://github.com/mootdx/mootdx/commit/e99ae34382d970c68654c6d17c45512e728f130d)，2024-07-16 | [MIT](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/LICENSE) | `.day` 与 `tdx_offline` 高度重叠；`.lc1/.lc5`、板块和财务解析能补缺 | **推荐有边界采用** |
| [`rainx/pytdx`](https://github.com/rainx/pytdx) | Python；TDX 行情协议基础实现 | 1,552 stars；已归档；最后提交 [`14b1ad3`](https://github.com/rainx/pytdx/commit/14b1ad3534593952d1d698ffa706f4f13a4ed156)，2020-04-15 | GitHub 无许可证；[归档 README](https://github.com/rainx/pytdx/blob/archive/README.md) 明示仅个人学习、不得商业使用 | 线上协议参考源；不适合作生产依赖 | **不建议采用** |
| [`interstellarmt/node-tdx`](https://github.com/interstellarmt/node-tdx) | TypeScript；7709/7727 行情、K 线、盘口、分时、分笔 | 7 stars；最后提交 [`5236368`](https://github.com/interstellarmt/node-tdx/commit/5236368eb11870135d3bdf66c665a215b99d49c1)，2026-06-22 | [MIT 文件](https://github.com/interstellarmt/node-tdx/blob/5236368eb11870135d3bdf66c665a215b99d49c1/LICENSE)，但 [README](https://github.com/interstellarmt/node-tdx/blob/5236368eb11870135d3bdf66c665a215b99d49c1/README.md) 限定协议研究/个人学习并提示勿商用 | 与 Python Provider 技术栈不一致；提供重连、测速和 ExHq 设计参考 | **参考实现** |
| [`finanalyzer/tdx`](https://github.com/finanalyzer/tdx) | Python；将官方 TdxQuant 接入 OpenBB | 13 stars；最后提交 [`61df29c`](https://github.com/finanalyzer/tdx/commit/61df29c9d47d8fb6ba5852c51114e63c9de066d6)，2026-05-08 | GitHub API 为 `NOASSERTION`，未确认清晰开源许可证 | 其 Provider 标准化思路可参考；TdxQuant 可能比私有协议/GUI 更稳，但需客户端能力与授权实测 | **参考实现，暂不引入** |
| [`corefan/TdxTradeServer`](https://github.com/corefan/TdxTradeServer) | C++；通达信交易客户端自动化/服务化 | 119 stars；最后提交 [`b91a16b`](https://github.com/corefan/TdxTradeServer/commit/b91a16b566411a17083614ed63fc8462137a3b13)，2017-08-23 | 无许可证 | 面向交易而非分析导出，年代久远、许可不明 | **不建议** |
| [`map-A/A-stock-level1-dump`](https://github.com/map-A/A-stock-level1-dump) | Rust；A 股 Level-1 数据采集/落盘 | 247 stars；最后提交 [`c173115`](https://github.com/map-A/A-stock-level1-dump/commit/c173115b55c39d439ff91566bd608992edd5b2c7)，2026-05-30 | 无许可证 | 可能补盘中数据，但无许可即默认不可复制/分发，且数据来源合规需单审 | **不建议采用** |

> 注意：没有许可证的 GitHub 公开仓库并不等于可自由复制、修改或集成。README 的“仅学习/勿商用”也可能约束实际使用场景；MIT 只解决代码版权许可，不自动授予第三方行情服务器、客户端数据或再分发权。

## 重点能力核验

### 1. 本地 `.day/.lc1/.lc5`

`mootdx` 的 [Reader 文档](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/docs/api/reader.md) 明确支持 `vipdoc` 日线，以及 `.1/.5`、`.lc1/.lc5` 两类分钟文件；源码在 [`reader.py`](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/mootdx/reader.py) 中按后缀自动定位。当前项目自己的 [`reader.py`](../../apps/pipeline/src/invest_pipeline/adapters/tdx_offline/reader.py) 已实现三市场 `.day` 解析，且已有 provenance、fail-closed 与 Provider 编排，因此：

- 不替换当前 `.day` reader，避免引入 pandas/第三方对象模型和重复解析链路；
- 可移植或封装 `mootdx` 的分钟记录解析，落到新的 `tdx_offline_minute` Provider；
- 使用本机样本做逐字节 golden test，不能只依赖上游测试。

### 2. 财务、板块、除权

`mootdx` [板块读取文档](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/docs/api/reader.md#04-%E8%AF%BB%E5%8F%96%E6%9D%BF%E5%9D%97%E4%BF%A1%E6%81%AF) 和源码支持 `block_*.dat`、`blocknew.cfg/.blk`；[`financial.py`](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/mootdx/financial/financial.py) 解析 `gpcw*.zip` 财务包；[`quotes.py`](https://github.com/mootdx/mootdx/blob/e99ae34382d970c68654c6d17c45512e728f130d/mootdx/quotes.py) 暴露 finance/block 等线上入口。可复用的是**格式解析知识**，不是直接把 DataFrame 写进事实表：板块必须带分类来源与 snapshot date，财务必须带报告期/公告期和原始文件 hash，除权必须保留未复权原始序列。

### 3. 行情网络协议/API

`pytdx` 是大量后继实现的来源，但已归档且明确非商业；`node-tdx` README 承认移植/参考 `injoyai/tdx` 和 `mootdx`，同时展示心跳、重连、服务器测速、7709/7727 分离。这些可用于审阅协议边界，但不应直接成为生产主源。即使代码为 MIT，也仍要解决：通达信服务协议、行情服务器授权、限频、端点漂移、数据再分发和无人值守账号风险。

较值得继续验证的是官方 **TdxQuant** 路径：`finanalyzer/tdx` 的 README 声称基于通达信官方 TdxQuant Python 接口，但该仓库许可证当前不清晰，而且本机 7.64 镜像此前未发现 TdxQuant 组件。因此它目前只是“官方接口存在性的线索”，不是已可接入能力。

### 4. 公式/选股与 GUI 自动化

本轮未找到能够直接执行通达信公式、且同时满足许可证明确、持续维护、支持麒麟/Wine 与 7.64 的成熟库。GitHub 上的自动化项目多面向 Windows 下单，不能等价为分析结果导出。

已经实测可控的路径仍是：固定窗口/菜单状态 → 执行通达信原生条件选股 → ASCII 文件名导出 → GB18030/Tab 解析。应把它作为独立的 `tdx_gui_analysis` Provider，而不是塞进 `tdx_offline`：

- request：公式标识、公式参数、证券范围、客户端版本；
- attempt：登录/刷新/执行/导出每阶段状态及截图或日志证据；
- batch：命中数、导出行数、schema 版本、文件 hash、分析时点；
- fail-closed：窗口标题、命中数和文件行数任一不一致即拒绝发布。

通用 GUI 库最多作为驱动工具，不应被视为数据源；核心稳定性来自状态机、导出契约和证据记录。

## 与现有 Provider 架构的落点

| 能力 | 建议 Provider | 上游利用方式 | 主/备定位 |
|---|---|---|---|
| 未复权日线 | 现有 `tdx_offline` | 保留自研 reader；仅用 `mootdx` 交叉测试 | Tushare 失败后的备用 |
| 1/5 分钟线 | 新 `tdx_offline_minute` | 有边界复用 `mootdx` 记录解析 | 本地候选源，先 Spike |
| 当前板块快照 | 新 `tdx_local_block` | 参考 `mootdx` block 解析 | 辅助/交叉验证，不当历史权威源 |
| 财务包 | 新 `tdx_local_financial` | 参考 `mootdx` gpcw parser | 备用源，按报告期治理 |
| 在线行情 | 独立 `tdx_quote`（若合规批准） | 只参考 `node-tdx/mootdx`；不继承旧 `pytdx` | 非默认、熔断、限频 |
| 原生公式/选股结果 | `tdx_gui_analysis` | 自建 GUI 状态机与受控文件导入 | 通达信特有派生结果源 |

## 最终分级

1. **推荐有边界采用**：`mootdx` 的 `.lc1/.lc5`、板块、财务格式解析；保留 MIT notice，先以 wrapper/移植小模块和 golden tests 验证。
2. **参考实现**：`node-tdx` 的连接管理、`finanalyzer/tdx` 的 Provider 映射；不直接纳入依赖。
3. **不建议采用**：`pytdx`、`TdxTradeServer`、`A-stock-level1-dump`；原因分别是明确非商业+归档、无许可+陈旧+偏交易、无许可+来源风险。
4. **GUI 方向**：未发现比当前已验证方案更合适的专用开源项目；自建薄状态机是当前证据下风险最低的实现边界。

本报告只评价技术与开源许可证证据，不构成对通达信数据授权或服务条款的法律意见。
