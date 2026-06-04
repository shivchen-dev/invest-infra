#!/usr/bin/env python3
"""
cron_health_check.py — CIA 定时任务健康检查
============================================

检查 cron_dispatcher.py 所有任务的注册状态 + 最后执行状态。
用于人工核查或定时巡检。

用法：
  python3 scripts/cron_health_check.py
  python3 scripts/cron_health_check.py --status-file /tmp/cron_exec_status.json
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = Path("/tmp/cron_exec_status.json")


def load_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}


def check_registration() -> list:
    """通过 openclaw tasks list 获取注册状态"""
    try:
        r = subprocess.run(
            ["openclaw", "tasks", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return [], r.stderr
        data = json.loads(r.stdout)
        jobs = {}
        for item in (data if isinstance(data, list) else []):
            name = item.get("name", "")
            if name.startswith("cia-"):
                jobs[name] = item
        return jobs, ""
    except Exception as e:
        return [], str(e)


def format_ts(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str)
        diff = (datetime.now() - dt).total_seconds()
        if diff < 60:
            return f"{diff:.0f}s 前"
        elif diff < 3600:
            return f"{diff/60:.0f}min 前"
        else:
            return f"{diff/3600:.1f}h 前"
    except Exception:
        return ts_str


def main():
    print(f"{'='*70}")
    print(f"CIA 定时任务健康检查  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    # 1. OpenClaw 注册状态
    print("\n▸ OpenClaw Cron 注册状态")
    jobs, err = check_registration()
    if err:
        print(f"  ⚠️  无法获取注册状态: {err}")
    elif not jobs:
        print("  ⚠️  未找到 cia-* 命名的定时任务")
    else:
        print(f"  共 {len(jobs)} 个任务注册")
        for name, info in sorted(jobs.items()):
            schedule = info.get("schedule", {})
            expr = schedule.get("expr", "?")
            enabled = info.get("enabled", True)
            status = "✅" if enabled else "⛔"
            next_run = info.get("state", {}).get("nextRunAtMs", 0)
            next_str = ""
            if next_run:
                try:
                    from datetime import timezone, timedelta
                    tz = datetime.now().astimezone().tzinfo
                    next_dt = datetime.fromtimestamp(next_run / 1000, tz=tz)
                    next_str = f" | 下次: {next_dt.strftime('%m-%d %H:%M')}"
                except Exception:
                    pass
            print(f"  {status} {name:30s} cron={expr:15s}{next_str}")

    # 2. 执行状态
    print("\n▸ 最近执行状态")
    status = load_status()
    if not status:
        print("  ⚠️  无执行状态记录（/tmp/cron_exec_status.json 不存在或为空）")
    else:
        print(f"  共 {len(status)} 个任务有记录")
        for task, info in sorted(status.items()):
            st = info.get("status", "?")
            ts = info.get("ts", "?")
            dur = info.get("duration_ms", 0)
            error = info.get("error", "")
            icon = {"ok": "✅", "error": "❌", "timeout": "⏰",
                    "running": "🔄", "exception": "💥"}.get(st, f"❓{st}")
            dur_str = f"{dur/1000:.1f}s" if dur else "-"
            error_str = f" | {error[:40]}" if error else ""
            print(f"  {icon} {task:25s} {format_ts(ts):15s} dur={dur_str:8s}{error_str}")

    print(f"\n{'='*70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())