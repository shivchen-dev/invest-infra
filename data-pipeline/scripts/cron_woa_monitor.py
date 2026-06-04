#!/usr/bin/env python3
"""
cron_woa_monitor.py — CIA 主动监控 WOA Morning Briefing 状态

触发时间：06:31（cia_morning_briefing 发任务后 1 分钟）
触发方式：isolated agent cron → CIA 被唤醒执行此脚本

职责：
  1. 检查 team.log / jiuwen.log / investment_memos，综合判断 WOA 状态
  2. 根据状态变化，动态 QQ 通知你
  3. 完成后写入 STATUS_TAG，供 cron_briefing_dispatch 参考
"""

import sys, os
from datetime import datetime, date, time as dtime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── .env 加载 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass

from src.config import pg


# ── 路径常量 ──────────────────────────────────────────────
LOG_DIR      = Path.home() / ".jiuwenswarm" / "logs" / "logs"
TEAM_LOG     = LOG_DIR / "team.log"
JIUWEN_LOG   = LOG_DIR / "run" / "jiuwen.log"
STATUS_TAG   = Path("/tmp/woa_morning_briefing_status.json")
BRIEFING_OUT = Path("/tmp/briefing_for_qq.txt")

OPENCLAW_BIN  = "/home/claw/.npm-global/bin/openclaw"
QQ_ACCOUNT    = "1903628521"
QQ_TARGET     = "43C77867478A33B101FA705AA70754E3"
STREAM        = "task_queue"
WINDOW_START  = dtime(6, 31)
WINDOW_END    = dtime(7, 40)
WINDOW_TOTAL  = 60  # 分钟，超时认为失败


# ── 工具函数 ──────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now()


def _qq_send(text: str) -> bool:
    import subprocess
    try:
        cp = subprocess.run(
            [OPENCLAW_BIN, "message", "send",
             "--channel", "qqbot",
             "--account", QQ_ACCOUNT,
             "--target", QQ_TARGET,
             "--message", text],
            capture_output=True, text=True, timeout=10
        )
        return cp.returncode == 0
    except Exception:
        return False


def _read_status_tag() -> dict:
    if not STATUS_TAG.exists():
        return {}
    import json
    try:
        return json.loads(STATUS_TAG.read_text())
    except Exception:
        return {}


def _write_status_tag(data: dict) -> None:
    import json
    STATUS_TAG.parent.mkdir(parents=True, exist_ok=True)
    STATUS_TAG.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _scan_log(log_path: Path, keywords: list, before_dt: Optional[datetime] = None,
              after_dt: Optional[datetime] = None) -> list:
    """扫描日志关键词，支持时间过滤。返回匹配的日志行。"""
    if not log_path.exists():
        return []
    now_ts = _now().timestamp()
    # 如果没传 after_dt，默认取最近 24 小时内
    if after_dt is None:
        after_dt = datetime.fromtimestamp(now_ts - 86400)
    results = []
    try:
        for line in log_path.read_text().splitlines():
            # 时间过滤（格式：2026-06-03 06:31:45 或类似）
            dt_part = line[:19]
            try:
                line_dt = datetime.strptime(dt_part, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if line_dt < after_dt:
                continue
            if before_dt and line_dt > before_dt:
                continue
            for kw in keywords:
                if kw.lower() in line.lower():
                    results.append(line.strip())
                    break
    except Exception:
        pass
    return results


# ── WOA 状态判断 ──────────────────────────────────────────
@dataclass
class WOAStatus:
    phase: str           # idle | enqueued | running | completed | timeout | error
    task_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    memo_count: int = 0
    confidence: Optional[str] = None
    risk_note: Optional[str] = None
    elapsed_min: Optional[float] = None
    error: Optional[str] = None
    new_info: list = field(default_factory=list)  # 新发现的信息（用于通知）


def _check_memos() -> tuple[int, str]:
    """检查 investment_memos，返回 (memo数量, 置信度)。"""
    import psycopg2
    try:
        conn = psycopg2.connect(pg.uri)
        cur = conn.cursor()
        today = date.today().isoformat()
        cur.execute("""
            SELECT COUNT(*), COALESCE(MAX(confidence_level), 'MEDIUM')
            FROM investment_memos
            WHERE company_id = 5233 AND memo_date = %s
        """, (today,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return (row[0] or 0, row[1] or "MEDIUM")
    except Exception:
        return (0, "MEDIUM")


def check_woa_status() -> WOAStatus:
    """
    1. 读取 STATUS_TAG（phase=enqueued 由 cron_morning_briefing 写入）
    2. 扫描 team.log / jiuwen.log / investment_memos
    3. 综合判断 WOA 当前状态
    """
    today_iso = date.today().isoformat()

    # ── 读取 phase（判断是否已进入监控） ──
    status_tag = _read_status_tag()
    phase = status_tag.get("phase", "enqueued")
    task_id = status_tag.get("task_id", "unknown")
    started_at_str = status_tag.get("started_at")

    if phase == "completed":
        return WOAStatus(phase="completed", task_id=task_id,
                         risk_note="WOA 已完成 Morning Briefing")

    if phase == "timeout":
        return WOAStatus(phase="timeout", task_id=task_id,
                         error="WOA 超过 60 分钟未完成")

    # 时间窗口检查
    now_local = datetime.now().time()
    in_window = WINDOW_START <= now_local <= WINDOW_END
    if not in_window:
        # 窗口外只读取，不写入 STATUS_TAG（避免覆盖 enqueued 状态）
        return WOAStatus(phase="idle", task_id=task_id,
                         risk_note=f"不在监控窗口（{WINDOW_START}~{WINDOW_END}）")

    # ── 计算已运行时间 ──
    started_at = None
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str)
        except ValueError:
            pass

    elapsed_min = None
    if started_at:
        elapsed_min = (_now() - started_at).total_seconds() / 60
        if elapsed_min > WINDOW_TOTAL:
            return WOAStatus(phase="timeout", task_id=task_id,
                             started_at=started_at,
                             elapsed_min=elapsed_min,
                             error=f"WOA 未在 {WINDOW_TOTAL} 分钟内完成 Morning Briefing")

    # ── 检查 memo（最权威的完成信号）──
    memo_count, confidence = _check_memos()
    if memo_count > 0:
        return WOAStatus(
            phase="completed", task_id=task_id,
            started_at=started_at,
            completed_at=_now(),
            memo_count=memo_count,
            confidence=confidence,
            risk_note=f"Found {memo_count} memos in PG",
        )

    # ── 检查 team.log / jiuwen.log ──
    new_info = []

    # team.log 完成标记
    team_lines = _scan_log(TEAM_LOG, ["all tasks completed", "succeeded", "failed"],
                           after_dt=started_at)
    if team_lines:
        new_info.extend(team_lines[:5])

    # jiuwen.log 错误标记
    error_lines = _scan_log(JIUWEN_LOG, ["error", "exception", "failed"],
                            after_dt=started_at)
    if error_lines:
        new_info.extend(error_lines[:3])

    # jiuwen.log 完成标记
    done_lines = _scan_log(JIUWEN_LOG, ["completed", "done", "finished"],
                            after_dt=started_at)
    if done_lines:
        new_info.extend(done_lines[:3])

    return WOAStatus(
        phase="running" if phase == "enqueued" else phase,
        task_id=task_id,
        started_at=started_at,
        elapsed_min=elapsed_min,
        memo_count=memo_count,
        confidence=confidence,
        risk_note=f"Elapsed: {elapsed_min:.0f}min, memos: {memo_count}" if elapsed_min else None,
        new_info=new_info,
    )


# ── QQ 通知消息生成 ──────────────────────────────────────
def _build_notification(status: WOAStatus) -> list[str]:
    """根据 WOAStatus 动态生成 QQ 通知列表。"""
    messages = []

    if status.phase == "enqueued":
        messages.append(
            f"⏳ WOA Morning Briefing 任务已接单\n"
            f"   task_id: {status.task_id[:8]}\n"
            f"   状态: 等待 WOA 开始执行..."
        )
        return messages

    if status.phase == "running":
        msgs = []
        if status.elapsed_min is not None:
            msgs.append(f"已运行 {status.elapsed_min:.0f} 分钟")
        if status.new_info:
            for line in status.new_info[:2]:
                clean = line.strip()
                if len(clean) > 80:
                    clean = clean[:80] + "..."
                msgs.append(clean)
        msg = "🔄 WOA Morning Briefing 进行中\n" + "\n".join(f"   {m}" for m in msgs)
        messages.append(msg)
        return messages

    if status.phase == "completed":
        msg = (
            f"✅ WOA Morning Briefing 已完成\n"
            f"   memo_count: {status.memo_count}\n"
            f"   confidence: {status.confidence or 'N/A'}\n"
            f"   → 07:40 cron_briefing_dispatch 将生成盘前洞察"
        )
        messages.append(msg)
        return messages

    if status.phase == "timeout":
        messages.append(
            f"⚠️ WOA Morning Briefing 超时（>{WINDOW_TOTAL}min）\n"
            f"   task_id: {status.task_id[:8]}\n"
            f"   → 07:40 将使用本地 fallback 数据"
        )
        return messages

    if status.phase == "idle":
        if status.risk_note:
            messages.append(f"ℹ️ {status.risk_note}")
        return messages

    return messages


# ── 主逻辑 ──────────────────────────────────────────────
def main() -> int:
    print(f"[{_now():%H:%M:%S}] CIA WOA Monitor 启动", file=sys.stderr)

    status = check_woa_status()
    messages = _build_notification(status)

    # 发送 QQ 通知
    for msg in messages:
        ok = _qq_send(msg)
        print(f"[{_now():%H:%M:%S}] QQ notify → {'✓' if ok else '✗'}: {msg[:60]}",
              file=sys.stderr)

    # 更新 STATUS_TAG（供 cron_briefing_dispatch 参考）
    tag_update = {
        "phase": status.phase,
        "task_id": status.task_id,
        "started_at": status.started_at.isoformat() if status.started_at else None,
        "completed_at": status.completed_at.isoformat() if status.completed_at else None,
        "memo_count": status.memo_count,
        "confidence": status.confidence,
        "elapsed_min": status.elapsed_min,
        "checked_at": _now().isoformat(),
    }
    _write_status_tag(tag_update)

    # 汇总输出文件（WOA 完成时写入，供 heartbeat 读取并推送最终报告）
    if status.phase == "completed" and not BRIEFING_OUT.exists():
        BRIEFING_OUT.parent.mkdir(parents=True, exist_ok=True)
        BRIEFING_OUT.write_text(
            f"✅ WOA Morning Briefing 已完成（{status.memo_count} 条 memo）\n"
            f"置信度: {status.confidence or 'N/A'}\n"
            f"详细报告将于 07:40 由 cron_briefing_dispatch 生成"
        )
        print(f"[{_now():%H:%M:%S}] 写入 {BRIEFING_OUT}", file=sys.stderr)

    print(f"[{_now():%H:%M:%S}] CIA WOA Monitor 完成 phase={status.phase}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())