#!/usr/bin/env python3
"""
cron_dispatcher.py — CIA 定时任务统一调度入口
==============================================

绕过 AI 模型，直接执行各类脚本。
系统 cron 调用方式：
  python3 /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py <task>

任务清单：
  etf_spot_morning    → bootstrap_runner.py etf_pipeline（09:25 ETF盘前同步）
  etf_spot_intraday   → cron_etf_spot_intraday.py（交易日ETF实时）
  etf_factor          → bootstrap_runner.py etf_factor（16:40 ETF因子计算）
  etf_alpha           → bootstrap_runner.py etf_alpha（16:45 ETF动量/风控）
  etf_health          → etf_health_monitor.py（16:50 ETF健康检查）
  etf_arbitrage       → cron_etf_arbitrage_signal.py（16:50 套利信号）
  sw_industry         → sync_sw_industry.py（15:35 申万行业涨跌）
  industry_info       → cron_industry_info.py（15:50 行业快讯密度）
  etf_kline           → cron_etf_kline_evening.py（15:40 ETF历史K线）
  index_eod           → cron_index_end_of_day.py（16:00 指数收盘数据）
  financial_p1        → bootstrap_runner.py financial 1（14:00 财务采集第1批）
  financial_p2        → bootstrap_runner.py financial 2（16:30 财务采集第2批）
  financial_p3        → bootstrap_runner.py financial 3（18:30 财务采集第3批）
  financial_p4        → bootstrap_runner.py financial 4（20:30 财务采集第4批）
  morning_briefing    → cron_morning_briefing.py（06:30 派发Morning Briefing）
  woa_audit           → cron_woa_audit.py（07:30 WOA输出审计）
  pre_market          → cron_pre_market.py（07:50 盘前报）
  midday              → cron_midday.py（12:00 午盘报）
  post_market         → cron_post_market.py（15:30 盘后报）
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 环境变量加载 ──────────────────────────────────────────────
# 优先级链（后加载的覆盖前加载的）：
#   1. .secrets/tokens.env   — RSSCAST / GITEE
#   2. .secrets/pg.env      — PG_PASSWORD
#   3. .secrets/minio.env   — MINIO_SECRET_KEY
#   4. .secrets/cifang.env  — CIFANG_TOKEN
#   5. .secrets/mcp.env     — MCP_TOKEN
#   6. .env                 — 非密钥 + 运行时覆盖（可空）
ROOT = Path(__file__).resolve().parent.parent
_SECRETS = ROOT / ".secrets"
_ENV = ROOT / ".env"


def _load_env(path: Path, *, override: bool = False) -> dict:
    vals = {}
    if not path.exists():
        return vals
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k:
            if override:
                os.environ[k] = v.strip()
            else:
                os.environ.setdefault(k, v.strip())
            vals[k] = v.strip()
    return vals


# .secrets/ 是真相源 — 覆盖（不是 setdefault），便于本地 .env 不慎写入空值时仍能恢复
for _secret_name in ("tokens.env", "pg.env", "minio.env", "cifang.env", "mcp.env"):
    _load_env(_SECRETS / _secret_name, override=True)
_load_env(_ENV)  # .env 是 setdefault（不覆盖 .secrets/）

# ── 日志配置 ──────────────────────────────────────────────
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "cron_dispatcher.log"

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cron_dispatcher")

# ── 任务映射 ──────────────────────────────────────────────
TASK_MAP = {
    # ETF 行情类
    "etf_spot_morning": {
        "desc": "ETF盘前同步（09:25）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py etf_pipeline",
        "timeout": 120,
    },
    "etf_spot_intraday": {
        "desc": "ETF日内刷新（每15分钟）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_etf_spot_intraday.py",
        "timeout": 120,
    },
    # ETF 因子类
    "etf_factor": {
        "desc": "ETF因子计算（溢价率/IOPV/流动性）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py etf_factor",
        "timeout": 120,
    },
    "etf_alpha": {
        "desc": "ETF Alpha信号（动量/风控/综合得分）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py etf_alpha",
        "timeout": 120,
    },
    "etf_health": {
        "desc": "ETF健康检查（折溢价/波动率/资金流）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python -m src.collector.etf_health_monitor",
        "timeout": 120,
    },
    "etf_arbitrage": {
        "desc": "ETF套利信号",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_etf_arbitrage_signal.py",
        "timeout": 120,
    },
    # 申万行业类
    "sw_industry": {
        "desc": "申万行业涨跌同步（15:35）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/sync_sw_industry.py",
        "timeout": 120,
    },
    "industry_info": {
        "desc": "申万行业快讯密度（15:50）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_industry_info.py",
        "timeout": 120,
    },
    # K线/指数类
    "etf_kline": {
        "desc": "ETF历史K线采集（15:40）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_etf_kline_evening.py",
        "timeout": 300,
    },
    "index_eod": {
        "desc": "指数收盘数据（16:00）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_index_end_of_day.py",
        "timeout": 300,
    },
    # 财务采集类
    "financial_p1": {
        "desc": "财务采集第1批（14:00）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py financial 1",
        "timeout": 3700,
    },
    "financial_p2": {
        "desc": "财务采集第2批（16:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py financial 2",
        "timeout": 3700,
    },
    "financial_p3": {
        "desc": "财务采集第3批（18:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py financial 3",
        "timeout": 3700,
    },
    "financial_p4": {
        "desc": "财务采集第4批（20:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/bootstrap/bootstrap_runner.py financial 4",
        "timeout": 3700,
    },
    # 市场数据采集类
    "market_data_collect": {
        "desc": "市场快照采集（15:05）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_market_data_collect.py",
        "timeout": 300,
    },

    # Morning Briefing 类
    "morning_briefing": {
        "desc": "Morning Briefing 任务派发（06:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_morning_briefing.py",
        "timeout": 90,
    },
    "woa_audit": {
        "desc": "WOA 输出审计（07:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_woa_audit.py",
        "timeout": 60,
    },
    # 汇报类（统一经 report_engine.py）
    "pre_market": {
        "desc": "盘前报（07:50）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_pre_market.py",
        "timeout": 300,
    },
    "midday": {
        "desc": "午盘报（12:00）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_midday.py",
        "timeout": 300,
    },
    "post_market": {
        "desc": "盘后报（15:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_post_market.py",
        "timeout": 300,
    },
    "intraday_collect": {
        "desc": "盘中异动预采集（每30分钟）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_intraday_collect.py",
        "timeout": 60,
    },
    # 新闻采集类
    "collect_news": {
        "desc": "个股新闻采集（09:30）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_collect_news.py",
        "timeout": 600,
    },
    # 龙虎榜采集
    "lhb_collect": {
        "desc": "龙虎榜采集（16:10）",
        "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_lhb_collect.py",
        "timeout": 180,
    },
}

# ── 监控状态 ──────────────────────────────────────────────
STATUS_FILE = Path("/tmp/cron_exec_status.json")
LOCK_DIR = Path("/tmp/cron_lock")
LOCK_DIR.mkdir(exist_ok=True)


def _load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_status(data: dict):
    try:
        STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"状态写入失败 {STATUS_FILE}: {e}")


def write_status(task: str, status: str, duration_ms: int = 0, pid: int = 0, error: str = ""):
    """更新任务状态到共享文件"""
    data = _load_status()
    data[task] = {
        "task": task,
        "ts": datetime.now().isoformat(),
        "status": status,
        "duration_ms": duration_ms,
        "pid": pid,
        "error": error,
    }
    _save_status(data)


def acquire_lock(task: str, ttl_seconds: int = 3600) -> bool:
    """尝试获取任务锁，返回 True 表示获得锁"""
    lock_file = LOCK_DIR / f"{task}.lock"
    pid = os.getpid()
    try:
        if lock_file.exists():
            old_pid = int(lock_file.read_text().strip())
            # 检查旧进程是否还活着
            try:
                os.kill(old_pid, 0)
                # 进程还活着，检查是否超时
                mtime = lock_file.stat().st_mtime
                if time.time() - mtime < ttl_seconds:
                    return False  # 还在 TTL 内，不抢锁
                logger.warning(f"[{task}] 旧锁进程 {old_pid} 已超时，强制替换")
            except OSError:
                pass  # 进程不存在，可以抢锁
        lock_file.write_text(str(pid))
        return True
    except Exception as e:
        logger.warning(f"[{task}] 抢锁失败: {e}")
        return False


def release_lock(task: str):
    lock_file = LOCK_DIR / f"{task}.lock"
    try:
        if lock_file.exists() and int(lock_file.read_text().strip()) == os.getpid():
            lock_file.unlink()
    except Exception:
        pass


# ── 执行核心 ──────────────────────────────────────────────
def run_task(task_name: str) -> int:
    """执行单个任务，返回退出码"""
    if task_name not in TASK_MAP:
        logger.error(f"未知任务: {task_name}")
        logger.info(f"可用任务: {', '.join(sorted(TASK_MAP.keys()))}")
        return 1

    if not acquire_lock(task_name):
        logger.warning(f"[{task_name}] 任务正在执行中，跳过")
        return 99  # 99 = 跳过

    try:
        cfg = TASK_MAP[task_name]
        logger.info(f"▶ 开始执行 [{task_name}] {cfg['desc']}")
        write_status(task_name, "running", pid=os.getpid())

        start = datetime.now()
        try:
            result = subprocess.run(
                ["bash", "-c", cfg["shell"]],
                capture_output=True,
                text=True,
                timeout=cfg["timeout"],
                cwd=str(ROOT),
                env={**os.environ},
            )
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)

            if result.returncode == 0:
                write_status(task_name, "ok", elapsed_ms)
                logger.info(f"✅ [{task_name}] 完成，耗时 {elapsed_ms/1000:.1f}s，退出码 0")
                if result.stdout:
                    for line in result.stdout.splitlines()[:5]:
                        logger.info(f"  {line}")
                return 0
            else:
                write_status(task_name, "error", elapsed_ms, error=result.stderr[:200])
                logger.error(f"❌ [{task_name}] 失败，耗时 {elapsed_ms/1000:.1f}s，退出码 {result.returncode}")
                if result.stderr:
                    for line in result.stderr.splitlines()[:5]:
                        logger.error(f"  {line}")
                return result.returncode

        except subprocess.TimeoutExpired:
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
            write_status(task_name, "timeout", elapsed_ms)
            logger.error(f"⏰ [{task_name}] 超时（{elapsed_ms/1000:.0f}s > {cfg['timeout']}s）")
            return 124
        except Exception as e:
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
            write_status(task_name, "exception", elapsed_ms, error=str(e)[:200])
            logger.error(f"💥 [{task_name}] 异常（{elapsed_ms/1000:.1f}s）: {e}")
            return 1
    finally:
        release_lock(task_name)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python cron_dispatcher.py <task>")
        print(f"可用任务: {', '.join(sorted(TASK_MAP.keys()))}")
        return 0

    task = sys.argv[1]
    logger.info(f"{'='*60}")
    logger.info(f"[Cron Dispatcher] 任务={task} 时间={datetime.now().isoformat()}")
    logger.info(f"{'='*60}")

    exit_code = run_task(task)

    logger.info(f"[Cron Dispatcher] 退出码={exit_code}")
    return exit_code


if __name__ == "__main__":
    import time

    sys.exit(main())