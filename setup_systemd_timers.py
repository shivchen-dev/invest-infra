#!/usr/bin/env python3
"""
setup_systemd_timers.py — 将 cron_dispatcher.py 所有任务注册为 systemd user timers
==================================================================================

【当前方案】static unit files（重启后持久，重启前一直生效）
【旧方案】transient timers（重启后丢失）

注册后验证：
  systemctl --user list-timers --all
  systemctl --user status cron_<task>.timer

重新生成（覆盖）：
  python3 /home/claw/invest-infra/setup_systemd_timers.py

注意：
  ETF 日内（10:00-15:00 每15分钟）全部调用同一个 TASK_MAP key，
  文件名区分 cron_etf_intra_XXXX，service 名不同但都触发 etf_spot_intraday。
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
    ("briefing_dispatch",  "*-*-* 07:40:00"),
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


def write_unit(path, content):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o644)


def register_timers():
    total = 0

    # Single-task static units
    for name, cal in SINGLE_TASKS:
        write_unit(f"{USER_DIR}/cron_{name}.timer", TIMER_TPL.format(name=name, cal=cal))
        write_unit(f"{USER_DIR}/cron_{name}.service", SVC_TPL.format(name=name, task=name, dispatcher=DISPATCHER, log=LOG))
        total += 1

    # ETF intraday: 10:00-15:00 every 15 min → all call etf_spot_intraday task
    for h in range(10, 16):
        for m in ["00", "15", "30", "45"]:
            fname = f"etf_intra_{h}{m}"
            cal = f"*-*-* {h:02d}:{m}:00"
            write_unit(f"{USER_DIR}/cron_{fname}.timer", TIMER_TPL.format(name=fname, cal=cal))
            write_unit(f"{USER_DIR}/cron_{fname}.service", SVC_TPL.format(name=fname, task="etf_spot_intraday", dispatcher=DISPATCHER, log=LOG))
            total += 1

    # Watchdog
    write_unit(f"{USER_DIR}/cron_watchdog.timer", WATCHDOG_TIMER)
    write_unit(f"{USER_DIR}/cron_watchdog.service", WATCHDOG_SVC.format(dispatcher=DISPATCHER, log=LOG))
    total += 1

    # Reload + start
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    for name, _ in SINGLE_TASKS + [(f"etf_intra_{h}{m}", "") for h in range(10, 16) for m in ["00", "15", "30", "45"]] + [("watchdog", "")]:
        subprocess.run(["systemctl", "--user", "start", f"cron_{name}.timer"], capture_output=True)
    subprocess.run(["systemctl", "--user", "start", "cron_watchdog.timer"], capture_output=True)

    print(f"Registered {total} static systemd user units")
    print("Run: systemctl --user list-timers --all")


if __name__ == "__main__":
    register_timers()