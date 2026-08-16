# 投研系统功能可达性与依赖裁撤审计独立验收意见

- GTD 任务：`2026-07-15-2043-cia-to-raa-invest-infra-feature-dependency-audit-v1`
- 验收节点：CIA（节点 2）
- 验收时间：2026-07-15 20:50–20:53 CST
- 结论：**PASS WITH OBSERVATIONS（审计通过，不授权实施裁撤）**

## CIA 独立复核结果

1. **timer 覆盖率：通过**
   - user systemd 实测 56 个唯一 `inv_*.timer`，对应 56 个 service。
   - ExecStart 独立分类为：54 个 `cron_dispatcher.py`、1 个 `cron_etf_alpha_daily.py`、1 个 `cron_watchdog.py`，与报告一致，无未归类入口。
   - 最近 service 结果为 55 个 success、1 个 exit-code；唯一失败为 `inv_financial_p4.service`。该失败只构成排障项，不能作为裁撤依据。

2. **依赖覆盖率：通过**
   - `uv.lock` 独立解析得到 159 个 package；项目锁入口包含 12 个默认依赖、test 与 dev 分组。
   - 扫描 `src/`、`scripts/` 共 190 个 Python 文件，报告列出的核心、隐式、回测及 PDF imports 均有源码证据。
   - `vectorbt` 的直接 import 仅定位于 `src/backtest/analyzers.py`；Ray、Jupyter widgets、Telegram、交易所 SDK、绘图库、Backtrader 等重依赖确实存在于锁文件。
   - 报告明确要求从根声明重新锁定，不逐个删除传递包，风险控制合理。

3. **功能分类与边界：通过**
   - 报告区分“核心保留”“可选隔离”“归档候选”“需用户决策”，没有把“默认环境隔离”错误表述为物理删除。
   - WOA/A2A、股票财务支线、研究环境与 24 个日内 timer 合并均保留用户决策门槛。
   - 提供了最小 manifest 草案、安全实施顺序、观察周期与回滚边界。

4. **只读约束：通过**
   - `pyproject.toml`、`uv.lock`、`setup_systemd_timers.py` 未出现本次审计新增 diff。
   - 现场默认 porcelain 计数为 118，与报告基线一致；既有工作区变更未由 CIA 整理、提交、删除、覆盖或回滚。

## 观察项

- 报告头部审计时间写为 `20:47–21:00 CST`，晚于实际 RAA 流转时间 `20:50:49`，属于证据时间戳不严谨。核心证据可独立复算，故不阻断本次审计验收；后续报告应使用实际完成时间。
- AST 扫描现场有 1 个语法解析失败文件。报告的依赖结论由锁文件、其余 190 个文件及入口链交叉支撑，但实施前应定位该文件并确认不会隐藏额外运行依赖。
- 当前“可复现性”仍不通过；在依赖声明与真实 imports 对齐前，禁止直接重建或替换生产 `.venv`。

## 用户最小决策清单

1. WOA/A2A：保留 Morning Briefing 智能体链，或改为纯 PostgreSQL 报告并分阶段归档相关 timer/源码。
2. 业务边界：股票财务 p1–p4、decision snapshot、龙虎榜、行业和情绪模块是否属于当前 ETF 核心产品。
3. 研究环境：是否批准将 vectorbt、Backtrader、PDF、Notebook/绘图及交易所 SDK 隔离到独立环境。
4. 调度结构：24 个日内 timer 暂保留独立可观测性，或另行设计影子验证后合并。

## 最终决定

CIA 同意本审计节点并归档任务。该决定仅确认审计覆盖率和证据质量，不授权删除功能、修改依赖、重锁、重建环境、停用 timer 或处理既有工作区变更。
