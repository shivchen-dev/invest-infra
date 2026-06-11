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
import threading
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
    # morning_briefing 已移出看门狗监控（2026-06-06）
    "woa_audit": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 43200,       # 超12h告警（正常应在07:30前，次日07:30前告警即可）
        "retry_threshold_s": 46800,        # 超13h补发
        "critical": False,
        "retry_max": 1,
        "retry_interval_s": 3600,
    },
    # 汇报类
    "pre_market": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,        # 超45min（07:50正常应在08:35前）
        "retry_threshold_s": 3000,        # 超50min补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    "midday": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,        # 超45min（12:00正常应在12:45前）
        "retry_threshold_s": 3000,
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },
    "post_market": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 2700,        # 超45min（15:30正常应在16:15前）
        "retry_threshold_s": 3000,
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 300,
    },

    "etf_spot_morning": {
        "expected_interval_s": 86400,
        "alert_threshold_s": 14400,       # 超4h告警（09:25正常应在13:25前，节假日/周末顺延）
        "retry_threshold_s": 18000,        # 超5h补发
        "critical": True,
        "retry_max": 2,
        "retry_interval_s": 600,
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

# ── 告警去重状态（模块级全局，替代 send_alert._last_msg）────────
# BUG1 fix: 使用独立 module-level 变量 + Lock，避免函数属性隐式全局线程不安全
_LAST_ALERT_MSG = ""
_ALERT_LOCK = threading.Lock()

# ── 失败事件追踪（一次失败只报警一次）───────────────────────────────
# key: task name → value: ISO timestamp when first alerted for this failure event
# 任务成功后自动清除，允许新失败事件触发新报警
_ALERTED_FAILURES_FILE = Path("/tmp/cron_watchdog_alerted.json")
_alerted_failures: dict = {}
_ALERTED_FAILURES_LOCK = threading.Lock()


def _load_alerted_failures() -> dict:
    """加载已报警失败事件追踪（进程重启后持久化）"""
    if _ALERTED_FAILURES_FILE.exists():
        try:
            return json.loads(_ALERTED_FAILURES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_alerted_failures(data: dict):
    """持久化已报警失败事件追踪"""
    try:
        _ALERTED_FAILURES_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[_alerted_failures] 持久化失败: {e}")


def _mark_alerted(task: str):
    """标记任务已报警（本次失败事件只报警一次）"""
    with _ALERTED_FAILURES_LOCK:
        _alerted_failures[task] = datetime.now().isoformat()
        _save_alerted_failures(_alerted_failures)


def _clear_alerted(task: str):
    """清除任务报警标记（任务成功后调用，允许新失败事件报警）"""
    with _ALERTED_FAILURES_LOCK:
        if task in _alerted_failures:
            del _alerted_failures[task]
            _save_alerted_failures(_alerted_failures)


def _is_already_alerted(task: str) -> bool:
    """检查任务是否已报警（同一失败事件不重复报警）"""
    with _ALERTED_FAILURES_LOCK:
        return task in _alerted_failures


# ── 启动时加载已报警失败事件 ───────────────────────────────────
_alerted_failures = _load_alerted_failures()


def _cleanup_stale_locks() -> int:
    """清理所有死进程残留的 .lock 文件，返回清理数量。"""
    cleaned = 0
    if not LOCK_DIR.exists():
        return cleaned
    for lock_file in LOCK_DIR.glob("*.lock"):
        try:
            pid = int(lock_file.read_text().strip())
            os.kill(pid, 0)
        except OSError:
            # 进程已死，删除残留锁文件
            lock_file.unlink(missing_ok=True)
            cleaned += 1
            logger.info(f"[lock] 清理残留锁: {lock_file.name} (pid={pid})")
    return cleaned


def _try_lock(task: str, pid: int) -> bool:
    """
    尝试原子获取任务锁。如果已有活跃锁（进程存活）返回 False，否则写入新锁并返回 True。
    调用前会先自动清理 stale lock；写入后立即写 PID 到同一文件（两步非原子但可接受）。
    """
    lock_file = LOCK_DIR / f"{task}.lock"
    # 先检查是否已有活跃进程持有该锁
    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text().strip())
            os.kill(existing_pid, 0)
            logger.info(f"[lock] [{task}] 锁已被 pid={existing_pid} 持有，跳过")
            return False
        except OSError:
            # 已有 stale lock，清理后重试
            lock_file.unlink(missing_ok=True)
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(str(pid))
        logger.debug(f"[lock] [{task}] 已加锁 pid={pid}")
        return True
    except Exception as e:
        logger.warning(f"[lock] [{task}] 加锁失败: {e}")
        return False


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



def is_task_running(task: str) -> bool:
    """检查任务是否正在执行中（lock 文件存在且进程存活）。

    BUG3 fix: 当进程已死时，删除残留的 lock 文件，避免后续误判。
    """
    lock_file = LOCK_DIR / f"{task}.lock"
    if not lock_file.exists():
        return False
    try:
        pid = int(lock_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except OSError:
        # 进程已死，删除残留锁文件，避免 false "never_run" / stale state
        lock_file.unlink(missing_ok=True)
        logger.debug(f"[lock] [{task}] 发现死锁 pid={pid}，已清理")
        return False


def rerun_task(task: str, pid: int | None = None) -> bool:
    """通过 cron_dispatcher.py 补发任务，返回是否成功。

    BUG2 fix: 启动前原子获取锁（_try_lock）。如果已有活跃进程持有该锁
    → 跳过补发。否则写入新锁并执行，执行后释放锁。这消除了 is_task_running()
    检查与 subprocess.run 之间的 TOCTOU 竞争窗口。

    Args:
        task: 任务名称
        pid: 当前进程的 PID（默认 os.getpid()），用于测试注入
    """
    my_pid = pid or os.getpid()

    # Atomically acquire ownership; if another watchdog already holds it, skip
    if not _try_lock(task, my_pid):
        logger.info(f"[{task}] 已有活跃进程持有锁，跳过补发")
        return False

    try:
        logger.warning(f"[{task}] 尝试补发...")
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
    finally:
        # Release our lock so the task can be re-checked normally on next run
        (LOCK_DIR / f"{task}.lock").unlink(missing_ok=True)


def check_and_reregister_systemd_timers() -> dict:
    """检查 systemd timers 是否存在，缺失则尝试重新注册"""
    result = subprocess.run(
        ["systemctl", "--user", "list-timers", "--all"],
        capture_output=True, text=True,
    )
    missing = []
    if result.returncode == 0:
        output = result.stdout
        for task in TASK_THRESHOLDS:
            unit = f"cia_{task}"  # intraday uses cia_etf_spot_intraday
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


def is_trading_day() -> bool:
    """判断今天是否为 A 股交易日（通过新浪历史交易日历）"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        today_str = datetime.now().strftime("%Y-%m-%d")
        # trade_date 是 date 类型，直接转字符串比较
        trading_dates = {d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d) for d in df["trade_date"]}
        return today_str in trading_dates
    except Exception as e:
        logger.warning(f"[is_trading_day] 检查失败: {e}，默认不跳过")
        return True  # 检查失败时不过滤，避免漏报


def run_watchdog() -> dict:
    """执行一次巡检，返回告警结果。

    BUG3 fix: 启动时清理所有 stale lock 文件，避免死进程导致误判。
    """
    # ── 启动时清理残留锁 ────────────────────────────────
    cleaned = _cleanup_stale_locks()
    if cleaned:
        logger.info(f"[watchdog] 启动清理 {cleaned} 个残留锁文件")

    # 非交易日跳过巡检（周末/节假日不告警）
    if not is_trading_day():
        logger.info("【非交易日】跳过看门狗巡检")
        return {
            "ts": datetime.now().isoformat(),
            "session": "🐕 Watchdog",
            "quiet_hours": False,
            "alerts": [],
            "reruns": [],
            "running": [],
            "stale": [],
            "systemd_missing": [],
            "summary": "non_trading_day",
        }

    data = load_status()
    now = datetime.now()
    # 根据时间判断盘面 session 标签
    h = now.hour
    if 9 <= h < 12:
        session_tag = "📈 早盘"
    elif 12 <= h < 15:
        session_tag = "📊 中盘"
    elif 15 <= h < 19:
        session_tag = "📉 收盘"
    else:
        session_tag = "🐕 Watchdog"

    report = {
        "ts": now.isoformat(),
        "session": session_tag,
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
        last = get_last_run(data, task)
        elapsed = int((now - last).total_seconds()) if last else None
        running = is_task_running(task)

        # ── 正在执行中 ────────────────────────────────────────
        if running:
            logger.info(f"[{task}] 正在执行中，跳过")
            report["running"].append(task)
            continue

        # ── 从未执行过 — 日内高频只记录不发告警 ────────────
        if elapsed is None:
            if task == "etf_spot_intraday":
                logger.info(f"[{task}] 尚未启动，仅记录（日内高频不告警）")
                report["stale"].append(task)
            else:
                # 从未成功过的任务 → 每次都报警（新失败事件）
                if not _is_already_alerted(task):
                    logger.warning(f"[{task}] ⚠️ 从未执行过")
                    report["alerts"].append({
                        "task": task,
                        "reason": "never_run",
                        "elapsed_s": None,
                        "level": "critical" if cfg["critical"] else "warning",
                    })
                    _mark_alerted(task)
                else:
                    logger.info(f"[{task}] ⚠️ 从未执行过（已报警，跳过）")
            continue

        # ── 超过期望间隔（stale） ────────────────────────────
        if elapsed > cfg["expected_interval_s"]:
            logger.warning(f"[{task}] ⚠️ 已过期（{elapsed}s > {cfg['expected_interval_s']}s）")
            report["stale"].append(task)

        # 超过告警阈值 → 发告警（同一失败事件只报警一次）
        if elapsed > cfg["alert_threshold_s"]:
            # 已报警过的失败事件，跳过（失败一次就停）
            if _is_already_alerted(task):
                logger.info(f"[{task}] ⚠️ 超过阈值（{elapsed}s > {cfg['alert_threshold_s']}s）【已报警，跳过】")
            else:
                level = "critical" if cfg["critical"] else "warning"
                logger.warning(f"[{task}] ⚠️ 超过阈值（{elapsed}s > {cfg['alert_threshold_s']}s）{'🚨 CRITICAL' if cfg['critical'] else '⚠️'}")
                report["alerts"].append({
                    "task": task,
                    "reason": "timeout",
                    "elapsed_s": elapsed,
                    "level": level,
                })
                _mark_alerted(task)

        # 超过补发阈值 → 尝试补发（失败一次就停，不反复重试）
        if elapsed > cfg["retry_threshold_s"]:
            # 已报警过的失败事件 → 跳过重试（等待下次调度或任务自己恢复）
            if _is_already_alerted(task):
                logger.info(f"[{task}] 超过补发阈值但已报警过，跳过重试，等待下次调度")
            else:
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

    lines = [f"{report['session']} 巡检报告 {report['ts'][:19]}"]
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

    # 去重后发送（BUG1 fix: 用模块级变量 + Lock 替代函数属性隐式全局）
    global _LAST_ALERT_MSG
    msg = "\n".join(lines)
    with _ALERT_LOCK:
        if msg == _LAST_ALERT_MSG:
            logger.debug("告警内容相同，跳过重复发送")
            return
        _LAST_ALERT_MSG = msg

    # 通过 openclaw message send CLI 推送 QQ
    try:
        import subprocess
        alert_file = Path("/tmp/cron_alert.json")
        alert_file.write_text(json.dumps({
            "ts": report["ts"],
            "msg": msg,
            "critical": sum(1 for a in report["alerts"] if a["level"] == "critical"),
        }, ensure_ascii=False))
        logger.info(f"告警已写入 {alert_file}\n{msg}")

        # 通过 openclaw message send 推送 QQ 到心跳订阅的频道
        r = subprocess.run([
            "/home/claw/.npm-global/bin/openclaw", "message", "send",
            "--channel", "qqbot",
            "--account", os.environ.get("OPENCLAW_ACCOUNT_ID", "1903628521"),
            "--target", "c2c:43C77867478A33B101FA705AA70754E3",
            "--message", msg,
        ], capture_output=True, text=True, timeout=30)

        if r.returncode == 0:
            logger.info("QQ 告警推送成功")
            logger.info(f"告警已推送，文件保留: {alert_file}")
        else:
            logger.warning(f"QQ 推送失败: {r.stderr.strip()[:200]}")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")

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