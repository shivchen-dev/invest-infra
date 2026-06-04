#!/usr/bin/env python3
"""
cron_watchdog.py — CIA 定时任务看门狗
========================================

监控策略：
  1. 读取 /tmp/cron_exec_status.json（cron_dispatcher.py 写入的执行状态）
  2. 检查各任务距上次成功执行的时间
  3. 超过阈值 → 告警 + 尝试补发
  4. 尝试补发后再次超时 → 升级告警（OpenClaw 心跳通知用户）

触发方式：
  • 独立 systemd timer（每小时）— 主要巡检
  • OpenClaw 心跳（每30min）— 轻量兜底

注册方式：
  systemd-run --user --on-calendar="*-*-* *:00:00" --unit=cia_watchdog \
    /home/claw/invest-infra/data-pipeline/.venv/bin/python \
    /home/claw/invest-infra/data-pipeline/scripts/cron_watchdog.py
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "scripts" / "cron_dispatcher.py"
STATUS_FILE = Path("/tmp/cron_exec_status.json")
LOG_FILE = ROOT / "logs" / "cron_watchdog.log"
LOCK_DIR = Path("/tmp/cron_lock")
SETUP_SCRIPT = ROOT.parent / "setup_systemd_timers.py"

# ── 日志 ──────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cron_watchdog")

# ── 任务阈值配置 ────────────────────────────────────────────
# 每个任务定义：
#   expected_interval_s : 期望执行间隔（秒）
#   alert_threshold_s   : 超过这个时间未执行则告警（秒）
#   retry_threshold_s   : 超过这个时间未执行则尝试补发（秒）
#   critical            : 是否关键任务（影响大盘分析）
#   retry_max           : 最大补发次数（单次巡检内）
#   retry_interval_s    : 补发后等待重检时间（秒）

TASK_THRESHOLDS = {
    # ── 关键任务（failure_count 清零慢）────────────────
    "morning_briefing": {
        "expected_interval_s": 86400,    # 每天一次
        "alert_threshold_s": 3600,       # 超1h告警（正常应在07:30前）
        "retry_threshold_s": 3900,       # 超65min补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    "woa_audit": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,       # 超1.5h告警（正常应在07:30前）
        "retry_threshold_s": 5700,        # 超95min补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    "briefing_dispatch": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 7200,        # 超2h告警（正常应在07:40前）
        "retry_threshold_s": 7500,        # 超2h5min补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    "etf_spot_morning": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,        # 超45min（09:25正常应在09:30前）
        "retry_threshold_s": 3000,        # 超50min补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    # ── 日内高频任务 ─────────────────────────────────
    "etf_spot_intraday": {
        "expected_interval_s": 900,      # 每15分钟
        "alert_threshold_s": 1200,        # 超20min告警
        "retry_threshold_s": 1500,        # 超25min补发
        "critical": False,
        "retry_max": 3,
        "retry_interval_s": 180,
    },
    # ── 盘后任务 ──────────────────────────────────
    "etf_factor": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,       # 超45min（17:05正常应在17:10前）
        "retry_threshold_s": 3000,        # 超50min补发
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "etf_alpha": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,
        "retry_threshold_s": 3000,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "etf_health": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,
        "retry_threshold_s": 3000,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "etf_arbitrage": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,
        "retry_threshold_s": 3000,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "financial_p1": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,        # 超1.5h（14:00正常应在14:30前）
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "sw_industry": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,        # 超1.5h（15:35正常应16:05前）
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "etf_kline": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "industry_info": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "index_eod": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "financial_p2": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "financial_p3": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
    "financial_p4": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 5400,
        "retry_threshold_s": 5700,
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 300,
    },
}

# 夜间 23:00-08:00 不告警（静音窗口）
QUIET_START_HOUR = 23
QUIET_END_HOUR = 8


def is_quiet_hour() -> bool:
    h = datetime.now().hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            return {}
    return {}


def get_last_run(data: dict, task: str) -> datetime | None:
    """获取任务上次成功执行的时间"""
    entry = data.get(task)
    if not entry or entry.get("status") != "ok":
        return None
    try:
        return datetime.fromisoformat(entry["ts"])
    except Exception:
        return None


def get_seconds_since_last_run(task: str) -> int | None:
    """返回距上次成功执行的秒数，未知返回 None"""
    data = load_status()
    last = get_last_run(data, task)
    if last is None:
        return None
    return int((datetime.now() - last).total_seconds())


def is_task_running(task: str) -> bool:
    """检查任务是否正在执行中（lock 文件存在且进程存活）"""
    lock_file = LOCK_DIR / f"{task}.lock"
    if not lock_file.exists():
        return False
    try:
        pid = int(lock_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def rerun_task(task: str) -> bool:
    """通过 cron_dispatcher.py 补发任务，返回是否成功"""
    logger.warning(f"[{task}] 尝试补发...")
    try:
        result = subprocess.run(
            [sys.executable, str(DISPATCHER), task],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            logger.info(f"[{task}] 补发成功")
            return True
        else:
            logger.error(f"[{task}] 补发失败，退出码 {result.returncode}: {result.stderr[:100]}")
            return False
    except Exception as e:
        logger.error(f"[{task}] 补发异常: {e}")
        return False


def check_and_reregister_systemd_timers() -> dict:
    """检查 systemd timers 是否存在，缺失则尝试重新注册"""
    import subprocess
    result = subprocess.run(
        ["systemctl", "--user", "list-timers", "--all"],
        capture_output=True, text=True,
    )
    missing = []
    if result.returncode == 0:
        output = result.stdout
        for task in TASK_THRESHOLDS:
            unit = f"cia_{task}" if task != "etf_spot_intraday" else None
            # 检查是否有对应的 timer
            if unit and unit not in output:
                missing.append(task)
                logger.warning(f"[systemd] timer 缺失: {unit}")
    else:
        logger.error(f"读取 systemd timers 失败: {result.stderr[:100]}")

    # 尝试重新注册缺失的 timers
    re_reg_count = 0
    if missing and SETUP_SCRIPT.exists():
        logger.warning(f"尝试重新注册 {len(missing)} 个缺失的 timers...")
        r = subprocess.run([sys.executable, str(SETUP_SCRIPT)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            re_reg_count = len(missing)
            logger.info(f"重新注册完成")
        else:
            logger.error(f"重新注册失败: {r.stderr[:100]}")

    return {"missing": missing, "re_registered": re_reg_count}


def run_watchdog() -> dict:
    """执行一次巡检，返回告警结果"""
    data = load_status()
    now = datetime.now()
    report = {
        "ts": now.isoformat(),
        "quiet_hours": is_quiet_hour(),
        "alerts": [],      # 需要告警的任务
        "reruns": [],      # 已补发的任务
        "running": [],     # 正在执行中的任务
        "stale": [],       # 超时的任务
        "systemd_missing": [],
        "summary": "",
    }

    if is_quiet_hour():
        logger.info("【静音窗口】跳过告警，仅记录状态")
        report["summary"] = "quiet_hours"
        return report

    for task, cfg in TASK_THRESHOLDS.items():
        # 跳过日内高频（告警太多，只记录）
        if task == "etf_spot_intraday":
            continue

        last = get_last_run(data, task)
        elapsed = int((now - last).total_seconds()) if last else None
        running = is_task_running(task)

        # 正在执行中
        if running:
            logger.info(f"[{task}] 正在执行中，跳过")
            report["running"].append(task)
            continue

        # 从未执行过
        if elapsed is None:
            logger.warning(f"[{task}] ⚠️ 从未执行过")
            report["alerts"].append({
                "task": task,
                "reason": "never_run",
                "elapsed_s": None,
                "level": "critical" if cfg["critical"] else "warning",
            })
            continue

        # 超过告警阈值
        if elapsed > cfg["alert_threshold_s"]:
            level = "critical" if cfg["critical"] else "warning"
            logger.warning(f"[{task}] ⚠️ 超过阈值（{elapsed}s > {cfg['alert_threshold_s']}s）{'🚨 CRITICAL' if cfg['critical'] else '⚠️'}")
            report["alerts"].append({
                "task": task,
                "reason": "timeout",
                "elapsed_s": elapsed,
                "level": level,
            })

        # 超过补发阈值 → 尝试补发
        if elapsed > cfg["retry_threshold_s"]:
            retry_count = 0
            for i in range(cfg["retry_max"]):
                ok = rerun_task(task)
                if ok:
                    report["reruns"].append(task)
                    break
                retry_count += 1
                time.sleep(cfg["retry_interval_s"])

    # 检查 systemd timers 是否缺失
    sys_result = check_and_reregister_systemd_timers()
    report["systemd_missing"] = sys_result.get("missing", [])
    if sys_result.get("missing"):
        report["alerts"].append({
            "task": "systemd_timers",
            "reason": "missing_timers",
            "detail": sys_result["missing"],
            "level": "critical",
        })

    # 生成摘要
    alert_count = len([a for a in report["alerts"] if a["level"] == "critical"])
    warn_count = len([a for a in report["alerts"] if a["level"] == "warning"])
    rerun_count = len(report["reruns"])
    report["summary"] = f"critical={alert_count} warning={warn_count} rerun={rerun_count}"

    return report


def send_alert(report: dict):
    """发送告警到 OpenClaw 心跳通知用户"""
    if not report["alerts"]:
        return

    lines = [f"🐕 Watchdog 巡检报告 {report['ts'][:19]}"]
    for alert in report["alerts"]:
        level_tag = "🚨" if alert["level"] == "critical" else "⚠️"
        if alert["reason"] == "never_run":
            lines.append(f"  {level_tag} [{alert['task']}] 从未执行过")
        elif alert["reason"] == "timeout":
            elapsed_min = alert["elapsed_s"] // 60
            lines.append(f"  {level_tag} [{alert['task']}] 超时 {elapsed_min}min 未执行")
        elif alert["reason"] == "missing_timers":
            lines.append(f"  {level_tag} systemd timers 缺失: {', '.join(alert['detail'])}")

    if report["reruns"]:
        lines.append(f"  🔄 已补发: {', '.join(report['reruns'])}")

    if report["systemd_missing"]:
        lines.append(f"  ⚠️ 缺失 timers: {', '.join(report['systemd_missing'])}")

    # 去重后发送
    msg = "\n".join(lines)
    if msg == send_alert._last_msg:
        logger.debug("告警内容相同，跳过重复发送")
        return
    send_alert._last_msg = msg

    # 通过 sessions_send 发给主 session
    try:
        import subprocess
        alert_file = Path("/tmp/cron_alert.json")
        alert_file.write_text(json.dumps({
            "ts": report["ts"],
            "msg": msg,
            "critical": sum(1 for a in report["alerts"] if a["level"] == "critical"),
        }, ensure_ascii=False))
        logger.info(f"告警已写入 {alert_file}\n{msg}")

        # 通过 OpenClaw announce webhook 推送 QQ（推送到心跳订阅的频道）
        # 格式: announce -> qqbot:c2c:<sender_id>
        gateway = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:19100")
        announce_url = f"{gateway}/api/v1/announce"
        payload = {
            "accountId": os.environ.get("OPENCLAW_ACCOUNT_ID", "1903628521"),
            "channel": "qqbot",
            "to": "c2c:43C77867478A33B101FA705AA70754E3",
            "text": msg,
        }
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", announce_url,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload), "--max-time", "10"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            logger.info("QQ 告警推送成功")
            # 推送成功后删除 alert 文件，避免下次重复告警
            alert_file.unlink(missing_ok=True)
            logger.info(f"已清除告警文件 {alert_file}")
        else:
            logger.warning(f"QQ 推送失败: {r.stderr.strip()}")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")


send_alert._last_msg = ""


def main():
    logger.info("=" * 60)
    logger.info(f"[Watchdog] 巡检开始 {datetime.now().isoformat()}")
    logger.info("=" * 60)

    report = run_watchdog()

    logger.info(f"[Watchdog] 巡检完成: {report['summary']}")
    for alert in report["alerts"]:
        lvl = alert["level"]
        reason = alert["reason"]
        task = alert.get("task", "")
        elapsed = alert.get("elapsed_s", 0) or 0
        logger.info(f"  {'🚨' if lvl=='critical' else '⚠️'} [{task}] {reason} elapsed={elapsed}s")

    if report["reruns"]:
        logger.info(f"  🔄 已补发: {report['reruns']}")

    # 非静音窗口才发告警
    if not report["quiet_hours"] and report["alerts"]:
        send_alert(report)

    # 写入巡检结果供心跳读取
    result_file = Path("/tmp/cron_watchdog_result.json")
    try:
        result_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"巡检结果写入失败: {e}")

    # 返回是否需要人工介入（critical alert 存在 = 1）
    has_critical = any(a["level"] == "critical" for a in report["alerts"])
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())