# V2 全数据源接入清单

> 当前进度（2026-08-04）：DC-1 代码级契约已完成；AkShare 与 CifangQuant
> 近期真实取数均已恢复并通过 16 个 active ETF 覆盖复测。剩余工作属于
> 2016 年历史数据已按范围决策豁免；当前剩余工作为 DC1-C 跨源数值验收和
> Stage 2 Shadow Run。
>
> PR-05 收尾复测：覆盖计划已按 ETF 生命周期与探测窗口求交集。2018 窗口
> 生命周期有效的 14 个标的在 AkShare/CifangQuant 均为 14/14 完整；2020
> 窗口为 16/16 完整。2016 窗口仍有 `513050` 因 AkShare 上游代理失败，
> CifangQuant 对该窗口返回有效空数据。

- [x] PR-01：统一 Provider Contract / Catalog
- [x] PR-02：AkShare Adapter 与历史覆盖探测（首个 ETF master/OHLCV 切片）
  - [x] 惰性导入，可选依赖缺失时返回 typed failure
  - [x] ETF master data / daily bars 映射与三层证据契约
  - [x] Provider Factory 显式 enabled gate，默认关闭
  - [x] 58 个 AkShare 专项测试，ruff/架构检查通过
- [x] PR-03：QuickTiny ETF/指数只读 Adapter
  - [x] MCP initialize / tools-list / tools-call 只读客户端
  - [x] ETF/指数 market snapshot 结果模型与 SHA-256
  - [x] token 脱敏、错误分类、默认关闭与无触网构造
  - [x] 49 个 QuickTiny 专项测试，ruff/架构检查通过
- [x] PR-04：RssCast 研究 Adapter
  - [x] MCP initialize / tools-list / tools-call 只读客户端
  - [x] 研究响应、参数哈希、响应哈希与限流状态
  - [x] token 脱敏、错误分类、默认关闭与无触网构造
  - [x] 62 个 RssCast 专项测试，ruff/架构检查通过
- [x] PR-05：Provider Routing、覆盖矩阵与幂等回填（2016 历史窗口按范围豁免）
  - [x] Provider Routing：按 dataset / ProviderCapability 选择 declaration，默认 off + research_only 拒绝 ETF 日线
  - [x] 覆盖矩阵：source × symbol × date-range × field 的只读 / 确定性模型与计算器（无网络 / DB 写入）
  - [x] 聚焦离线测试：路由安全、能力不匹配、确定性覆盖、空 / 部分覆盖
  - [ ] 幂等回填：真实网络验收 + 各源真实覆盖率报告（不在本切片）
  - [x] Coverage CLI：fixture 离线验收 + Cifang 单 ETF 代表性真实探测
  - [x] 代表性结果记录：`docs/implementation/PROVIDER-COVERAGE-2026-08-04.md`
  - [x] Fixture active-universe matrix：7 symbols / 2026-07-23..2026-07-30 / 6 fields
  - [x] Fixture matrix result：`docs/implementation/PROVIDER-COVERAGE-FIXTURE-2026-08-04.md`
  - [x] Fixture full active-universe bridge：16 symbols / 2026-07-23..2026-07-30 / 6 fields
  - [x] 多 Provider CoverageReport 合并：重复 Provider / schema mismatch 拒绝，aggregate hash 确定性
  - [x] AkShare 真实近期全量覆盖探测（16 个 active ETF / 2026-07-30..2026-08-03 / 6 fields；无错误）
  - [x] 覆盖计划按 `list_date` / `delist_date` 与探测窗口求交集，排除窗口外标的
  - [x] AkShare 历史窗口复测：2018 生命周期有效标的 14/14，2020 为 16/16
  - [x] CifangQuant 历史窗口复测：2016 有效空数据，2018 生命周期有效标的 14/14，2020 为 16/16
  - [x] 2016 历史窗口豁免，不进入生产回填阻塞项
  - [x] 2026/2018/2020 有效窗口覆盖矩阵与回填排序
  - [x] 2026-01-01..2026-08-04 全范围回填：16 symbols / 2256 latest rows / 0 missing fields
  - [x] AkShare 完整字段 revision 2 回填；CifangQuant revision 1 原始证据保留
  - [x] PostgreSQL 验收：16 symbols、每标的 141 条、0 业务重复、OHLCV 跨源一致
  - [x] AkShare NAV/交易日历 Adapter：只读 fetch_nav + fetch_trading_calendar；mapper 不把 NAV 映射为 OHLCV；聚焦离线测试
  - [x] 覆盖率探针输入构造器：纯函数把成功 ProviderBatch/响应 metadata 转成 calculate_coverage 输入；无网络 / DB 写入

## 当前切片

- [x] 记录 V1 归档、官方文档和真实接口核验结果
- [x] 配置 QuickTiny OpenClaw MCP 令牌并验证 `tools/list`
- [x] 扩展 V2 Provider Contract / Catalog
- [x] 完成 AkShare/QuickTiny/RssCast 三个适配器首个切片
- [x] 补齐 AkShare NAV/交易日历 Adapter（只读 + 不映射为 OHLCV；真实网络验收仍待 O-1）
- [x] 提供纯函数覆盖率探针输入构造器（无网络 / DB 写入；真实覆盖率报告仍待 PR-05 后续切片）
- [x] 按 dataset/capability 建立 Provider Routing（真实近期覆盖报告已完成；历史覆盖与回填仍待 PR-05 后续切片）
