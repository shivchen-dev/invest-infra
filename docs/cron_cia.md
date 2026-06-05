# ════════════════════════════════════════════════════════════════════════════
#  CIA 定时任务系统 — 智能投研体系
# ════════════════════════════════════════════════════════════════════════════
#
#  【当前方案】systemd user timers（setup_systemd_timers.py 注册）
#  【备选方案】系统 crontab（兼容所有类 Unix 系统）
#
#  ┌─────────────────────────────────────────────────────────────────────┐
#  │  systemd timers 注册方式（已实现）                               │
#  │                                                                    │
#  │  python3 /home/claw/invest-infra/setup_systemd_timers.py        │
#  │                                                                    │
#  │  注册后可通过以下命令查看状态：                                    │
#  │    systemctl --user list-timers --all                             │
#  │    systemctl --user status cia_<task>.timer                       │
#  │                                                                    │
#  │  注意：当前注册为 transient（临时），重启后会丢失。               │
#  │  如需持久化，需改用 systemd-run --permanent 或创建 .service 文件  │
#  └─────────────────────────────────────────────────────────────────────┘
#
#  ┌─────────────────────────────────────────────────────────────────────┐
#  │  Watchdog 看门狗（每小时自动巡检）                                │
#  │                                                                    │
#  │  - 每整点触发，检查所有任务距上次成功执行的时间                  │
#  │  - 超阈值（alert_threshold_s）→ 尝试通过 cron_dispatcher.py 补发 │
#  │  - 补发后仍异常 → 推送 QQ 频道（c2c:43C77867478A33B101FA705AA70754E3）│
#  │  - 告警文件 /tmp/cron_alert.json 推送后保留，由我处理完后再手动删除 │
#  │  - 静音窗口：23:00-08:00（不告警）                              │
#  │                                                                    │
#  │  日志路径：/home/claw/invest-infra/data-pipeline/logs/          │
#  │            cron_watchdog.log                                      │
#  └─────────────────────────────────────────────────────────────────┘
#
#  执行状态文件：/tmp/cron_exec_status.json（JSON，各任务独立状态）
#  告警状态文件：/tmp/cron_alert.json（推送后保留，需手动删除）
#
#  ┌─────────────────────────────────────────────────────────────────────┐
#  │  架构说明                                                         │
#  │                                                                    │
#  │  systemd timers 触发 → cron_dispatcher.py <task>                  │
#  │      ↓                                                            │
#  │  cron_dispatcher.py 读取 TASK_MAP → 执行对应 shell 命令          │
#  │      ↓                                                            │
#  │  状态写入 /tmp/cron_exec_status.json                              │
#  │      ↓                                                            │
#  │  watchdog 读取状态文件 → 巡检 → 补发/推送 QQ                     │
#  │                                           ↓                       │
#  │                              /tmp/cron_alert.json 推送后保留       │
#  │                              → CIA 处理 → 手动删除 alert 文件     │
#  │                                                                    │
#  │  执行日志：/home/claw/invest-infra/data-pipeline/logs/            │
#  │            cron_dispatcher.log（所有任务统一日志）                 │
#  │  执行状态：/tmp/cron_exec_status.json                             │
#  │  告警推送：QQ c2c:43C77867478A33B101FA705AA70754E3                │
#  └─────────────────────────────────────────────────────────────────┘
#
# ════════════════════════════════════════════════════════════════════════════
#  任务清单（systemd timers 实际触发时间）
# ════════════════════════════════════════════════════════════════════════════
#
#  早盘  05:50-09:35
#  ─────────────────────────────────────────────────────────────────────
#  05:50  → morning_briefing        Morning Briefing 任务派发
#                               WOA claim → 生成盘前洞察 → 写入 investment_memos
#  07:30  → woa_audit               WOA 输出审计（节日/日期一致性校验）
#  07:40  → briefing_dispatch        最终盘前洞察派发（读 WOA memo 或 fallback）
#  09:25  → etf_spot_morning         ETF盘前同步（IOPV/溢价率/换手率/主力资金）
#  09:35  → etf_spot_intraday        ETF日内刷新首跳（09:25 后间隔 10min）
#
#  午盘/盘后  10:00-17:35
#  ─────────────────────────────────────────────────────────────────────
#  10:00-15:00 每15分钟 → etf_spot_intraday   ETF日内刷新（排除09:35首跳）
#  14:00  → financial_p1             财务采集第1批（500只，避开盘中交易）
#  15:35  → sw_industry              申万行业涨跌（早于指数收盘，采集行业情绪）
#  15:40  → etf_kline                ETF历史K线（次方量化，等比复权）
#  15:50  → industry_info            行业快讯密度（财联社快讯统计，窗口24h）
#  16:00  → index_eod                沪深300等8指数 + 成分股K线 + 北向资金
#  17:05  → etf_factor               ETF因子计算（溢价率/IOPV差值/流动性评分）
#  17:15  → etf_alpha                ETF动量/风控/综合得分
#  17:25  → etf_health               ETF健康检查（折溢价/波动率/资金流）
#  17:35  → etf_arbitrage            ETF套利信号
#
#  夜盘  18:30-20:30
#  ─────────────────────────────────────────────────────────────────────
#  18:30  → financial_p2             财务采集第2批（500只）
#  19:30  → financial_p3             财务采集第3批（500只）
#  20:30  → financial_p4             财务采集第4批（500只）
#
# ════════════════════════════════════════════════════════════════════════════
#  备选 crontab 安装方式（适用于无 systemd 的环境）
# ════════════════════════════════════════════════════════════════════════════
#  安装：crontab /home/claw/invest-infra/cron_cia.txt
#  卸载：crontab -r（注意：会清除所有 crontab 条目）
#
#  早盘
#  ─────────────────────────────────────────────────────────────────────
#  05:50 派发 Morning Briefing
#  50 5 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py morning_briefing >> logs/cron_cia.log 2>&1
#
#  07:30 WOA 输出审计
#  30 7 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py woa_audit >> logs/cron_cia.log 2>&1
#
#  07:40 最终盘前洞察派发
#  40 7 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py briefing_dispatch >> logs/cron_cia.log 2>&1
#
#  09:25 ETF盘前同步
#  25 9 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_spot_morning >> logs/cron_cia.log 2>&1
#
#  09:35 ETF日内刷新首跳
#  35 9 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_spot_intraday >> logs/cron_cia.log 2>&1
#
#  午盘/盘后
#  ─────────────────────────────────────────────────────────────────────
#  14:00 财务采集第1批
#  0 14 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py financial_p1 >> logs/cron_cia.log 2>&1
#
#  15:35 申万行业涨跌
#  35 15 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py sw_industry >> logs/cron_cia.log 2>&1
#
#  15:40 ETF历史K线
#  40 15 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_kline >> logs/cron_cia.log 2>&1
#
#  15:50 行业快讯密度
#  50 15 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py industry_info >> logs/cron_cia.log 2>&1
#
#  16:00 指数收盘数据
#  0 16 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py index_eod >> logs/cron_cia.log 2>&1
#
#  17:05 ETF因子计算
#  5 17 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_factor >> logs/cron_cia.log 2>&1
#
#  17:15 ETF动量/风控
#  15 17 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_alpha >> logs/cron_cia.log 2>&1
#
#  17:25 ETF健康检查
#  25 17 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_health >> logs/cron_cia.log 2>&1
#
#  17:35 ETF套利信号
#  35 17 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_arbitrage >> logs/cron_cia.log 2>&1
#
#  夜盘
#  ─────────────────────────────────────────────────────────────────────
#  18:30 财务采集第2批
#  30 18 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py financial_p2 >> logs/cron_cia.log 2>&1
#
#  19:30 财务采集第3批
#  30 19 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py financial_p3 >> logs/cron_cia.log 2>&1
#
#  20:30 财务采集第4批
#  30 20 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py financial_p4 >> logs/cron_cia.log 2>&1
#
#  日内 ETF 每15分钟
#  ─────────────────────────────────────────────────────────────────────
#  ETF日内刷新（10:00-15:00 每15分钟，排除 09:35 首跳）
#  */15 10-15 * * 1-5 cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_dispatcher.py etf_spot_intraday >> logs/cron_cia.log 2>&1
#
# ════════════════════════════════════════════════════════════════════════════
#  文件索引
# ════════════════════════════════════════════════════════════════════════════
#
#  cron_dispatcher.py    — 统一调度入口（读取 TASK_MAP，执行对应脚本）
#  cron_watchdog.py     — 看门狗（每小时巡检，超时补发，写告警）
#  setup_systemd_timers.py — systemd timers 注册脚本
#
#  日志目录：/home/claw/invest-infra/data-pipeline/logs/
#  状态文件：/tmp/cron_exec_status.json
#  告警文件：/tmp/cron_alert.json