#!/usr/bin/env python3
"""
setup_systemd_timers.py — 将 cia_dispatcher.py 所有任务注册为 systemd user timers
==================================================================================

【当前方案】static unit files（重启后持久，重启前一直生效）
【旧方案】transient timers（重启后丢失）

注册后验证：
  systemctl --user list-timers --all
  systemctl --user status cia_<task>.timer

重新生成（覆盖）：
  python3 /home/claw/invest-infra/setup_systemd_timers.py

注意：
  ETF 日内（10:00-15:00 每15分钟）全部调用同一个 TASK_MAP key，
  文件名区分 cia_etf_intra_XXXX，service 名不同但都触发 etf_spot_intraday。
  所有时间都是 weekday-aware（systemd 自动在非工作日跳过）。
"""

import os
import subprocess

DISPATCHER = "/home/claw/invest-infra/data-pipeline/.venv/bin/python /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py"
LOG = "/home/claw/invest-infra/data-pipeline/logs/cron_cia.log"
USER_DIR = os.path.expanduser("~/.config/systemd/user")

# Fixed-time single tasks (all map to TASK_MAP key = task name)
SINGLE_TASKS = [
    ("morning_briefing",   "*-*-* 05:50:00"),
    ("woa_audit",         "*-*-* 07:30:00"),
    # briefing_dispatch removed 2026-06-12: 已合并到 morning_briefing(06:30 派发),任务在 dispatcher.py TASK_MAP 中不存在
    ("etf_spot_morning",   "*-*-* 09:25:00"),
    ("etf_spot_intraday",  "*-*-* 09:35:00"),
    ("financial_p1",      "*-*-* 14:00:00"),
    ("sw_industry",        "*-*-* 15:35:00"),
    ("etf_kline",          "*-*-* 15:40:00"),
    ("industry_info",      "*-*-* 15:50:00"),
    ("index_eod",          "*-*-* 16:00:00"),
    ("etf_factor",         "*-*-* 17:05:00"),
    ("etf_alpha",          "*-*-* 17:15:00"),
    ("etf_health",         "*-*-* 17:25:00"),
    ("etf_arbitrage",      "*-*-* 17:35:00"),
    ("financial_p2",      "*-*-* 18:30:00"),
    ("financial_p3",      "*-*-* 19:30:00"),
    ("financial_p4",      "*-*-* 20:30:00"),
    # ── 汇报类（之前为 orphan timers，统一纳入）────────────────────────
    ("pre_market",       "*-*-* 09:00:00"),   # 盘前报
    ("midday",           "*-*-* 12:00:00"),   # 午盘报
    ("post_market",      "*-*-* 15:30:00"),   # 盘后报
    ("collect_news",     "*-*-* 09:30:00"),   # 个股新闻采集（ARCH-4修复）
    ("market_collect",   "*-*-* 15:05:00"),   # 收盘快照采集
    ("lhb_collect",      "*-*-* 16:10:00"),   # 龙虎榜采集（ARCH-3修复）
    # ── intraday_collect 每30min × 盘后时段（10:00-15:00）──────────
    # 注意：intraday_collect 由 cia_intraday_collect.timer 统一轮询
    # 以下为 OnUnitActiveSec 循环定时，非 OnCalendar
]

TIMER_TPL = """[Unit]
Description=CIA {name} timer

[Timer]
OnCalendar={cal}
Persistent=true

[Install]
WantedBy=timer.target
"""

SVC_TPL = """[Unit]
Description=CIA {name} service

[Service]
Type=oneshot
ExecStart={dispatcher} {task}
StandardOutput=append:{log}
StandardError=append:{log}
"""

WATCHDOG_TIMER = """[Unit]
Description=CIA cron watchdog — hourly health check

[Timer]
OnCalendar=*-*-* *:00:00
Persistent=true

[Install]
WantedBy=timer.target
"""

WATCHDOG_SVC = """[Unit]
Description=CIA cron watchdog service

[Service]
Type=oneshot
ExecStart={dispatcher}
WorkingDirectory=/home/claw/invest-infra/data-pipeline
StandardOutput=append:{log}
StandardError=append:{log}
"""

# ── Recurring (OnUnitActiveSec) timer templates ─────────────────────────────
INTRADAY_TIMER_TPL = """[Unit]
Description=CIA {name} timer (recurring)

[Timer]
OnUnitActiveSec={interval}
Persistent=true

[Install]
WantedBy=timer.target
"""


def write_unit(path, content):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o644)


def register_timers():
    total = 0

    # Single-task static units
    for name, cal in SINGLE_TASKS:
        write_unit(f"{USER_DIR}/cia_{name}.timer", TIMER_TPL.format(name=name, cal=cal))
        write_unit(f"{USER_DIR}/cia_{name}.service", SVC_TPL.format(name=name, task=name, dispatcher=DISPATCHER, log=LOG))
        total += 1

    # ETF intraday: 10:00-15:00 every 15 min → all call etf_spot_intraday task
    for h in range(10, 16):
        for m in ["00", "15", "30", "45"]:
            fname = f"etf_intra_{h}{m}"
            cal = f"*-*-* {h:02d}:{m}:00"
            write_unit(f"{USER_DIR}/cia_{fname}.timer", TIMER_TPL.format(name=fname, cal=cal))
            write_unit(f"{USER_DIR}/cia_{fname}.service", SVC_TPL.format(name=fname, task="etf_spot_intraday", dispatcher=DISPATCHER, log=LOG))
            total += 1

    # Watchdog
    write_unit(f"{USER_DIR}/cia_watchdog.timer", WATCHDOG_TIMER)
    write_unit(f"{USER_DIR}/cia_watchdog.service", WATCHDOG_SVC.format(dispatcher=DISPATCHER, log=LOG))
    total += 1

    # ── Recurring timers ──────────────────────────────────────────────────────
    # intraday_collect: every 30 min during trading hours
    write_unit(
        f"{USER_DIR}/cia_intraday_collect.timer",
        INTRADAY_TIMER_TPL.format(name="intraday_collect", interval="30min")
    )
    write_unit(
        f"{USER_DIR}/cia_intraday_collect.service",
        SVC_TPL.format(name="intraday_collect", task="intraday_collect", dispatcher=DISPATCHER, log=LOG)
    )
    total += 1

    # Reload + start
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    for name, _ in SINGLE_TASKS + [(f"etf_intra_{h}{m}", "") for h in range(10, 16) for m in ["00", "15", "30", "45"]] + [("watchdog", "")]:
        subprocess.run(["systemctl", "--user", "start", f"cia_{name}.timer"], capture_output=True)
    subprocess.run(["systemctl", "--user", "start", "cia_watchdog.timer"], capture_output=True)

    print(f"Registered {total} static systemd user units")
    print("Run: systemctl --user list-timers --all")


if __name__ == "__main__":
    register_timers()