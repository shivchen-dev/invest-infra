# V2 全数据源接入清单

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
- [ ] PR-05：Provider Routing、覆盖矩阵与幂等回填
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
  - [ ] AkShare 真实全量覆盖探测（SDK 已通过 Clash 安装并完成导入验证；16 个 active ETF 请求均因 EastMoney 上游经代理返回 `ProxyError / RemoteDisconnected`，待网络链路恢复后重试）
  - [x] CifangQuant 全量 active-universe 探测：16 symbols / 2016、2020、2026-07 三窗口
  - [ ] 全量 active ETF 覆盖矩阵与回填排序
  - [x] AkShare NAV/交易日历 Adapter：只读 fetch_nav + fetch_trading_calendar；mapper 不把 NAV 映射为 OHLCV；聚焦离线测试
  - [x] 覆盖率探针输入构造器：纯函数把成功 ProviderBatch/响应 metadata 转成 calculate_coverage 输入；无网络 / DB 写入

## 当前切片

- [x] 记录 V1 归档、官方文档和真实接口核验结果
- [x] 配置 QuickTiny OpenClaw MCP 令牌并验证 `tools/list`
- [x] 扩展 V2 Provider Contract / Catalog
- [x] 完成 AkShare/QuickTiny/RssCast 三个适配器首个切片
- [x] 补齐 AkShare NAV/交易日历 Adapter（只读 + 不映射为 OHLCV；真实网络验收仍待 O-1）
- [x] 提供纯函数覆盖率探针输入构造器（无网络 / DB 写入；真实覆盖率报告仍待 PR-05 后续切片）
- [x] 按 dataset/capability 建立 Provider Routing（仅 routing + coverage 模型；真实覆盖率报告仍待 PR-05 后续切片）
