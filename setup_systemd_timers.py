#!/usr/bin/env python3
"""
setup_systemd_timers.py — 将 cron_dispatcher.py 所有任务注册为 systemd user timers
==================================================================================

所有任务统一通过 cron_dispatcher.py 执行，确保：
  1. 任务状态写入 /tmp/cron_exec_status.json（Watchdog 巡检依据）
  2. 超时/异常处理统一在 dispatcher 侧
  3. 锁机制避免重复并发

注册方式：
  python3 /home/claw/invest-infra/setup_systemd_timers.py

验证：
  systemctl --user list-timers --all
  systemctl --user status cia_<task>.timer
"""

import subprocess
import sys

# 统一入口：所有任务走 cron_dispatcher.py
DISPATCHER = "/home/claw/invest-infra/data-pipeline/.venv/bin/python /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py"
LOG_DIR = "/home/claw/invest-infra/data-pipeline/logs"
SHELL_LOG = f"{LOG_DIR}/cron_cia.log"

# (task_name, calendar_expression)
TASKS = [
    # 早盘
    ("morning_briefing",   "*-*-* 05:50:00"),
    ("woa_audit",          "*-*-* 07:30:00"),
    ("briefing_dispatch",   "*-*-* 07:40:00"),
    ("etf_spot_morning",    "*-*-* 09:25:00"),
    ("etf_spot_intraday",   "*-*-* 09:35:00"),
    # 午盘/盘后
    ("financial_p1",       "*-*-* 14:00:00"),
    ("sw_industry",         "*-*-* 15:35:00"),
    ("etf_kline",           "*-*-* 15:40:00"),
    ("industry_info",       "*-*-* 15:50:00"),
    ("index_eod",           "*-*-* 16:00:00"),
    ("etf_factor",           "*-*-* 17:05:00"),
    ("etf_alpha",           "*-*-* 17:15:00"),
    ("etf_health",          "*-*-* 17:25:00"),
    ("etf_arbitrage",       "*-*-* 17:35:00"),
    # 夜盘
    ("financial_p2",       "*-*-* 18:30:00"),
    ("financial_p3",       "*-*-* 19:30:00"),
    ("financial_p4",       "*-*-* 20:30:00"),
]

# ETF日内刷新：10:00-15:00 每15分钟（排除09:35首跳，由 morning 处理）
for h in range(10, 16):
    for m in ["00", "15", "30", "45"]:
        TASKS.append(("etf_spot_intraday", f"*-*-* {h:02d}:{m}:00"))


def run_cmd(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️  {' '.join(cmd)} → {r.stderr.strip()}")
    else:
        print(f"  ✓ {r.stdout.strip() if r.stdout.strip() else 'ok'}")
    return r.returncode


def register_timers():
    print(f"注册 {len(TASKS)} 个 systemd user timers（统一走 cron_dispatcher.py）...")

    for task_name, calendar in TASKS:
        unit = f"cia_{task_name}"
        # 统一调用 cron_dispatcher.py，由它负责 write_status
        cmd = [
            "systemd-run",
            "--user",
            "--no-block",
            f"--on-calendar={calendar}",
            f"--unit={unit}",
            "/bin/bash", "-c",
            f"{DISPATCHER} {task_name} >> {SHELL_LOG} 2>&1"
        ]
        r = run_cmd(cmd, check=False)
        status = "✓" if r == 0 else "✗"
        print(f"  {status} {task_name:25s} @ {calendar}")

    print(f"\n=== 验证已注册的 timers ===")
    run_cmd(["systemctl", "--user", "list-timers", "--all"])

    print("\n下次触发（部分）：")
    for task_name, _ in TASKS[:6]:
        run_cmd(["systemctl", "--user", "status", f"cia_{task_name}.timer"])


if __name__ == "__main__":
    register_timers()