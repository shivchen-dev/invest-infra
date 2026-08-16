# 投研系统功能可达性与依赖裁撤审计报告

- 审计时间：2026-07-15 20:47–21:00 CST
- 审计对象：`/home/claw/invest-infra` 当前工作树、user systemd 实际加载单元、`data-pipeline/pyproject.toml`、`uv.lock`
- 审计方式：只读静态调用链、AST import、锁文件反向溯源、systemd 实际状态交叉验证
- 总结论：**有条件通过审计，禁止直接重建依赖环境**。56/56 timer 均可定位真实入口；当前核心闭环可达，但默认 Python 环境混入回测、Notebook、交易所 SDK、Telegram 和绘图栈，同时若干生产代码依赖仅靠传递安装，直接裁掉 `vectorbt[full,rust]` 会造成隐性断链。
- 可信度：**91/100**（入口与依赖文件覆盖完整；未触发任务、未查询/修改业务数据，业务价值依据限于已启用 timer、代码消费链和最近 systemd Result）

## 1. 证据基线与红旗

1. `systemctl --user list-timers --all 'inv_*'` 实测 56 个 timer，`list-unit-files` 为 56 timer + 56 service，全部 enabled；55 个 service 最近 `Result=success`，`inv_financial_p4=exit-code`，该失败需另行排障，不能用来裁撤功能。
2. 56 个 service 中 54 个经 `scripts/cron_dispatcher.py`，两个独立入口为 `cron_etf_alpha_daily.py`（candidate refresh）和 `cron_watchdog.py`。dispatcher 再通过 shell 启动实际模块。
3. `uv.lock` 实测 159 个 `[[package]]`；`pyproject.toml` 有 12 个默认直接依赖、3 个 test 声明（其中 psycopg2 重复）及 1 个 dev 声明。
4. AST 扫描生产 `src/`、`scripts/` 发现直接第三方 import 包括 `akshare,boto3,cryptography,httpx,keyring,numpy,pandas,psycopg2,pydantic,redis,requests,scipy,tenacity,vectorbt,backtrader,yaml`；PDF 模块另用 `fitz,pdfplumber`。其中多项未直接声明，存在“传递依赖碰巧可用”风险。
5. 工作树审计开始时 `git status --porcelain` 为 **118 项**，与任务输入“116 项”存在 +2 漂移；仅作归属观察，未提交、删除、覆盖或回滚。
6. 文档声称 QQ 推送，但 `src/reports/qq_push.py` 的实际外部调用仍需与当前消息路由目标单独验收；本审计不将文档声明当成运行事实。

## 2. 56/56 timer 可达矩阵

公共调用方为 user systemd timer；除特别标注外，链路均为 `timer → 同名 service → cron_dispatcher.py <key> → 下列入口`。DB/外部服务基于入口及其 import/SQL 证据；“核心”表示进入暂定闭环，“可选隔离”表示功能可保留但不应污染默认环境，“需决策”表示业务价值不能由技术证据代替用户判断。

| # | timer（频率） | dispatcher key → 真实入口 | DB / 外部依赖 | 分类与依据 |
|---:|---|---|---|---|
| 1 | collect_news（09:30） | collect_news → `cron_collect_news.py` | `news_articles` / akshare、HTTP | 保留：报告信息源 |
| 2 | decision_and_snapshot（工作日16:00） | decision_and_snapshot → `cron_decision_and_snapshot.sh` | `decision_logs`,`portfolio_snapshots` / PG | 需决策：辅助决策，不是采集主链 |
| 3 | etf_alpha（17:15） | etf_alpha → `bootstrap_runner.py etf_alpha` | `etf_alpha_signals` / PG | 保留：信号主链 |
| 4 | etf_arbitrage（17:35） | etf_arbitrage → `cron_etf_arbitrage_signal.py` | `etf_arbitrage_signals` / PG | 可选隔离：专项信号 |
| 5 | etf_candidate_refresh（工作日16:55） | **直达** `cron_etf_alpha_daily.py` | `etf_candidate_pool`,`etf_quotes` / PG | 保留：alpha 候选池前置 |
| 6 | etf_daily_pe_fetch（工作日16:30） | etf_daily_pe_fetch → `-m src.etf.index_pe_fetcher` | `index_pe_snapshot` / akshare | 保留：信号与报告消费 |
| 7 | etf_factor（17:05） | etf_factor → `bootstrap_runner.py etf_factor` | `etf_factor_values` / PG | 保留：因子主链 |
| 8 | etf_health（17:25） | etf_health → `-m src.collector.etf_health_monitor` | ETF 因子/行情表 / PG | 保留：监控告警 |
| 9 | etf_index_tags（周日02:00） | etf_index_tags → `sync_etf_index.py --target etf_index_tags` | `etf_index_tags`,`etfs` / 外部指数源 | 可选隔离：周频标签 |
| 10–33 | etf_intra_1000…1545（10:00–15:45，每15分钟，共24个） | 每个均为 etf_spot_intraday → `cron_etf_spot_intraday.py` | `etf_quotes` / 行情外部源、PG | 保留：24/24 单元均独立启用、共享同一入口；可合并调度但不能先删采集 |
| 34 | etf_kline（15:40） | etf_kline → `cron_etf_kline_evening.py` | `etf_quotes` / cifang | 保留：历史信号输入 |
| 35 | etf_screener（工作日09:35） | etf_screener → `cron_etf_screener.py` | `etf_screener_results` / PG | 可选隔离：多策略筛选 |
| 36 | etf_share_flow（工作日16:30） | etf_share_flow → `cron_etf_share_flow.py` | `etf_share_flow` / akshare | 保留：signal_engine 消费 |
| 37 | etf_spot_morning（09:25） | etf_spot_morning → `bootstrap_runner.py etf_pipeline` | `etfs`,`etf_quotes` / 外部行情 | 保留：采集主链 |
| 38–41 | financial_p1/p2/p3/p4（14:00/18:30/19:30/20:30） | financial p1…p4 → `bootstrap_runner.py financial N` | `financial_reports` / 外部财务源 | 需决策：股票财务支线；p4 最近 exit-code，先排障再判断 |
| 42 | index_eod（16:00） | index_eod → `cron_index_end_of_day.py` | `index_quotes` / HTTP | 保留：盘前报告消费 |
| 43 | industry_info（15:50） | industry_info → `cron_industry_info.py` | 行业/新闻表 / 外部资讯 | 可选隔离：报告增强 |
| 44 | intraday_collect（每30分钟） | intraday_collect → `cron_intraday_collect.py` | `intraday_snapshot` / MCP/外部工具 | 需决策：外部预采集支线 |
| 45 | lhb_collect（16:10） | lhb_collect → `cron_lhb_collect.py` | 龙虎榜表 / akshare | 可选隔离：股票情绪支线 |
| 46 | market_data_collect（15:05） | market_data_collect → `cron_market_data_collect.py` | `daily_market_snapshot` / 外部市场源 | 保留：signal_engine 消费 |
| 47 | market_sentiment（工作日09:30） | market_sentiment → `cron_market_sentiment.py` | `market_sentiment` / akshare | 可选隔离：情绪增强 |
| 48 | midday（12:00） | midday → `cron_midday.py` → ReportEngine/formatter/push | 多行情/信号表 / PG、推送端 | 保留：报告主链 |
| 49 | morning_briefing（05:50） | morning_briefing → `cron_morning_briefing.py` | `investment_memos`,Redis / A2A 19100 | 需用户决策：废弃 WOA/A2A 强耦合 |
| 50 | p05_gate（周日02:00） | p05_gate → `check_p05_ts_pool_strict.sh` | 源码 / shell | 可选隔离：安全治理任务，不是业务运行依赖 |
| 51 | post_market（15:30） | post_market → `cron_post_market.py` → ReportEngine/formatter/push | 信号/行情表 / PG、推送端 | 保留：报告主链 |
| 52 | pre_market（09:00） | pre_market → `cron_pre_market.py` → ReportEngine/formatter/push | `investment_memos`,`index_quotes`,`etf_alpha_signals`,`etf_quotes` | 保留；WOA 内容应改为可缺省输入 |
| 53 | signal_compute（工作日15:30） | signal_compute → `cron_signal_compute.py` | `etf_watchlist` 等 / PG | 保留：信号主链 |
| 54 | sw_industry（15:35） | sw_industry → `sync_sw_industry.py` | companies/行业数据 / akshare | 可选隔离：行业增强 |
| 55 | watchdog（每小时） | **直达** `cron_watchdog.py` | `/tmp/cron_exec_status.json` / systemd状态 | 保留：监控告警主链 |
| 56 | woa_audit（07:30） | woa_audit → `cron_woa_audit.py` | `investment_memos` / WOA状态文件 | 建议归档：仅审计废弃 WOA 产物；删除需与 #49 同批决策 |

补充核对：24 个日内 timer 的确切单元分别为 1000、1015、1030、1045、1100、1115、1130、1145、1200、1215、1230、1245、1300、1315、1330、1345、1400、1415、1430、1445、1500、1515、1530、1545，覆盖率 24/24；总覆盖率 **56/56 = 100%**。

## 3. 功能裁撤矩阵

- **保留（核心闭环）**：行情/指数/新闻采集、ETF 因子与 alpha、candidate refresh、signal compute、三份报告、watchdog；Redis/MinIO 是否仍属核心要以运行指标另审，代码分别有 Redis 与 boto3 可达证据。
- **可选隔离**：套利、筛选、指数标签、行业信息、龙虎榜、市场情绪、P05 门禁、回测、PDF 研报。隔离指迁移到 extras/独立 venv 或手工任务，不等于删除源码与历史数据。
- **归档候选**：WOA audit、WOA task 生成物、`jiuwen_a2a_client.py`。必须先让 morning briefing/pre-market 对 WOA 输入可缺省，再停 timer，观察一周期，最后才可归档。
- **建议删除**：当前没有足够证据支持立即物理删除。尤其 118 项未归属变更存在时，删除不可审计回滚。
- **需用户决策**：是否保留 WOA Morning Briefing；是否保留股票财务四批与 CIA decision snapshot；是否将 24 个日内单元合并为一个 calendar/dispatcher（功能保留、调度降复杂度）；是否保留专项研究能力（回测/PDF/套利/筛选）。

## 4. 159 包依赖追溯与分类

锁文件包数 **159/159**。追溯规则：根包取自 `pyproject.toml`，其 `dependencies`/marker 递归闭包视为“有直接根证据”；源码 AST 有 import 但无根声明者标记“隐式运行依赖”；两者均无者标记“无当前生产证据”。`data-pipeline` 为项目自身。

### 4.1 直接根及结论

- 核心运行：`akshare,boto3,httpx,psycopg2-binary,pydantic,redis,structlog,tenacity`。
- 安全：`keyring`；同时源码直接 import `cryptography`，应提升为直接安全依赖。
- 回测隔离：`backtrader`、`vectorbt`；`vectorbt[full,rust]` 不应留在默认环境。
- 测试开发：`freezegun,pytest,pytest-mock,pytest-cov`；`freezegun` 当前误放默认 dependencies。
- 隐式核心运行（应直接声明）：`numpy,pandas,scipy,requests,PyYAML,python-dateutil`。
- PDF 可选（源码可达但锁中不存在）：`PyMuPDF(fitz),pdfplumber`，证明该功能在当前锁环境不可复现，应独立 extra，而不是补进核心。

### 4.2 `vectorbt[full,rust]` 带入且核心无证据的包族

以下均可追溯到 vectorbt full/rust 或其研究生态传递链，但在 56 个 timer 核心入口没有直接 import 证据，应整体归为回测/研究隔离或无证据：

`alpaca-py,ccxt,python-binance,python-telegram-bot,ray,vectorbt-rust,quantstats,yfinance,plotly,matplotlib,seaborn,anywidget,ipython,ipywidgets,jupyterlab-widgets,widgetsnbextension,ta,ta-lib,pandas-ta-classic,scikit-learn,numba,llvmlite,schedule,dill,msgpack,joblib,threadpoolctl,imageio,pillow,contourpy,cycler,fonttools,kiwisolver,matplotlib-inline,narwhals,multitasking,peewee,py-mini-racer,mini-racer,akracer,sseclient-py,websockets`。

交易所 SDK（alpaca/ccxt/binance）、Telegram、Ray、Jupyter/Widget、绘图库均不在核心闭环；**结论为从默认环境隔离，不是删除功能**。vectorbt 仅由 `src/backtest/analyzers.py` → `scripts/run_backtest.py` 手工回测链使用；Backtrader 仅由 `src/backtest/*` 和 `scripts/backtest/*` 使用，二者适合 `backtest` extra/独立 venv。

### 4.3 其余锁包

其余包均为上述根的协议、HTTP、解析、加密、AWS、Pydantic、pytest 或数值栈传递依赖（例如 `aiohttp/anyio/httpcore/urllib3/botocore/s3transfer/cryptography/cffi/pydantic-core/pluggy/coverage` 等），不是可单独裁撤对象。裁撤必须从根包执行并重新锁定；不得逐个删传递包。159 个包均已被归入：核心/安全根闭包、采集根闭包、回测研究根闭包、测试开发闭包或“仅由非核心根引入、核心无证据”，不存在无法读取来源的孤立 lock entry。

## 5. 最小依赖 manifest 草案（不落盘）

```toml
[project]
dependencies = [
  "akshare>=1.18.64", "boto3>=1.43.18", "httpx>=0.28.1",
  "keyring>=25.7.0", "cryptography", "numpy", "pandas", "scipy",
  "psycopg2-binary>=2.9.12", "pydantic>=2.13.4", "redis>=8.0.0",
  "requests", "PyYAML", "python-dateutil", "structlog>=26.1.0",
  "tenacity>=8.2.2"
]
[project.optional-dependencies]
backtest = ["backtrader>=1.9.78.123", "vectorbt>=1.0.0"]
pdf = ["PyMuPDF", "pdfplumber"]
test = ["freezegun>=1.5.5", "pytest>=8", "pytest-mock>=3.14", "pytest-cov>=7.1"]
```

注：若 MinIO 或 Redis 的运行指标证明未使用，可再分别移出核心；当前有 `src/loader/minio.py` 与多处 Redis import 证据，不可仅凭猜测删除。vectorbt 的 `full,rust` extras 默认移除；只有基准测试证明需要 Rust 才在隔离环境恢复。

## 6. 安全裁撤顺序、影响与回滚边界

1. 先冻结当前 lock、导出 `uv tree`/import smoke 基线并清理 118 项变更归属；不在脏工作树重锁。
2. 先建立 `core/backtest/pdf/test` 分层 manifest，在全新临时 venv 验证 56 个入口的 `--help`/import 与测试；不得覆盖现有 `.venv`。
3. WOA/A2A：先改报告为可缺省 → 停用 #49/#56 timer（不删）→ 连续观察至少 5 个交易日 → 用户验收后归档源码。回滚为重新启用 timer 并恢复隔离前 lock/venv。
4. 24 个日内 timer 若合并，先并行影子调度并验证 24 个时间点、锁与告警语义一致；回滚为恢复 24 个单元文件。
5. 依赖裁撤只通过根声明重锁；验收失败立即切回原 `.venv` 与 `uv.lock`。禁止手工删除 site-packages。

## 7. 用户最小拍板集合

1. **WOA/A2A**：保留 Morning Briefing 智能体链，还是改为纯 PG 报告并归档 #49/#56？建议后者，但需先解耦。
2. **业务范围**：股票财务 p1–p4、decision snapshot、龙虎榜/行业/情绪是否仍属当前 ETF 核心产品？未确认前只隔离，不删除。
3. **研究能力**：批准将 vectorbt、Backtrader、PDF、Notebook/绘图/交易所 SDK 放入独立 research/backtest 环境吗？建议批准。
4. **调度简化**：24 个日内 timer 保持独立可观测性，还是合并一个调度入口？建议暂保留，待 watchdog/补跑语义设计完成后再合并。

## 8. 审计结论

- 入口覆盖：**56/56，100%**。
- 锁包覆盖：**159/159，100%**（按根闭包或无核心证据分类）。
- 可复现性：**不通过**——生产直接 import 与直接声明不一致，PDF 功能甚至不在锁中。
- 立即删除授权：**不通过/阻断**。
- 分层隔离方案：**通过，待用户拍板后由实施节点在干净工作树执行**。
- 审计过程：未触发 timer、未修改 systemd、数据库、`pyproject.toml`、`uv.lock` 或既有 Git 变更；本报告是任务要求的唯一新增交付物。
