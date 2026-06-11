#!/usr/bin/env python3
"""
cron_woa_status.py — WOA 任务状态检查脚本
===========================================

替代 A2A 回调反馈的机制：
  1. cron_morning_briefing.py 写入 task_id → sys_operation.log
  2. 本脚本轮询 team.log + investment_memos 判断 WOA 是否完成
  3. 完成后读取 PG investment_memos 整合盘前洞察 → QQ 通知

调度：
  cron_woa_status.py 作为独立 cron，06:40 开始每 5 分钟检查一次
  最多检查 60 分钟（06:40 ~ 07:40），超时则告警
"""

import os
import re
import sys
import time
import json
import signal
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta, time as dtime
from pathlib import Path

# ── 时间窗口（必须与 cron_woa_status 调度一致）──
_WINDOW_START = dtime(6, 40)   # 06:40 开始轮询
_WINDOW_END   = dtime(7, 40)   # 07:40 结束轮询
_WINDOW_TOTAL_MIN = 60         # 任务最大运行时长（分钟）

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

_dotenv = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k and v:
                os.environ.setdefault(k.strip(), v.strip())

import psycopg2
from src.config import pg

# ── 日志路径 ──────────────────────────────────────────────────

TEAM_LOG   = "/home/claw/.jiuwenswarm/logs/logs/team.log"
JIUWEN_LOG = "/home/claw/.jiuwenswarm/logs/logs/run/jiuwen.log"
STATUS_TAG = "/tmp/woa_morning_briefing_status.json"
SYS_OP_LOG = "/home/claw/.jiuwenswarm/logs/logs/sys_operation.log"

# ── 状态 ──────────────────────────────────────────────────────

@dataclass
class WOAStatus:
    phase: str                    # idle / running / completed / timeout / error
    task_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    memo_count: int               # investment_memos 条目数量
    confidence: str | None       # HIGH / MEDIUM / LOW
    risk_note: str | None
    elapsed_min: float | None
    error: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_last_task_id() -> str | None:
    """从 STATUS_TAG 读取最后写入的 task_id。"""
    if not os.path.exists(STATUS_TAG):
        return None
    try:
        with open(STATUS_TAG) as f:
            data = json.load(f)
            return data.get("task_id")
    except Exception:
        return None


def _write_status_tag(task_id: str, phase: str = "idle"):
    """写入当前任务状态标记。"""
    with open(STATUS_TAG, "w") as f:
        json.dump({
            "task_id": task_id,
            "phase": phase,
            "updated_at": _now().isoformat(),
        }, f)


def _check_team_log_completion(task_id: str | None, since: datetime) -> tuple[bool, str]:
    """
    检查 team.log 中是否有 WOA 团队完成 morning_briefing 相关任务的痕迹。
    查找：investment_memos 写入成功的日志 或 明确的 completed 标记。
    """
    if task_id and os.path.exists(TEAM_LOG):
        # 查找包含 task_id 后8位的完成标记
        prefix = task_id[:8]
        try:
            # 读最后 500 行
            with open(TEAM_LOG) as f:
                lines = f.readlines()
            recent = lines[-500:] if len(lines) > 500 else lines
            for line in reversed(recent):
                if prefix in line and ("completed" in line.lower() or "success" in line.lower() or "memos" in line.lower()):
                    return True, "found completion marker in team.log"
                # 查找 investment_memos 写入成功
                if "investment_memos" in line and ("INSERT" in line or "success" in line.lower()):
                    return True, "investment_memos write confirmed"
        except Exception as e:
            return False, f"team.log read error: {e}"
    return False, ""


def _check_memos_completion(today: str) -> tuple[bool, int, str]:
    """
    检查 investment_memos 表是否有今日 Morning Briefing 的完成条目。
    """
    conn = psycopg2.connect(pg.uri)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*),
                   STRING_AGG(SUBSTRING(title, 1, 40), ' | ' ORDER BY created_at)
            FROM investment_memos
            WHERE company_id = 5233
              AND memo_date = %s
        """, (today,))
        row = cur.fetchone()
        count = row[0] if row else 0
        titles = row[1] if row and row[1] else ""
        cur.close()
        return count > 0, count, titles
    finally:
        conn.close()


def _assess_confidence_from_memos(conn, today: str) -> str | None:
    """从 memo 内容评估置信度。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT title, summary, confidence_level
        FROM investment_memos
        WHERE company_id = 5233 AND memo_date = %s
        LIMIT 5
    """, (today,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return None
    text = " ".join(r[0] + " " + (r[1] or "") for r in rows).lower()
    conf = rows[0][2] if rows and rows[0][2] else None
    if conf in ("HIGH", "high"):
        return "HIGH"
    if conf in ("MEDIUM", "medium"):
        return "MEDIUM"
    if conf in ("LOW", "low"):
        return "LOW"
    return "MEDIUM"


def _check_jiuwen_log_progress(since: datetime) -> str | None:
    """检查 jiuwen.log 中是否有活跃的工作痕迹。"""
    if not os.path.exists(JIUWEN_LOG):
        return None
    try:
        mtime = os.path.getmtime(JIUWEN_LOG)
        age_min = (_now().timestamp() - mtime) / 60
        if age_min > 30:
            return None  # 文件30分钟未更新，WOA 可能已停止
        with open(JIUWEN_LOG) as f:
            lines = f.readlines()
        recent = lines[-200:] if len(lines) > 200 else lines
        for line in reversed(recent):
            if "morning" in line.lower() or "晨" in line or "盘前" in line:
                return line.strip()
        return None
    except Exception:
        return None


def check_woa_status() -> WOAStatus:
    """
    主检查函数：
    1. 读取当前追踪的 task_id（从 STATUS_TAG）
    2. 检查 team.log / jiuwen.log / investment_memos
    3. 综合判断 WOA 完成状态
    """
    today = date.today().isoformat()
    task_id = _read_last_task_id()
    started_at = None

    # 时间窗口检查：只在 06:40~07:40 内轮询
    # 任务最大运行时长 = 60min（超时则标记 timeout）
    now = _now().astimezone().tzinfo.utcoffset(None)  # 本地时间
    now_local = datetime.now().time()
    if not (_WINDOW_START <= now_local <= _WINDOW_END):
        # 不在窗口期：不检查（返回 idle，避免误判）
        return WOAStatus(
            phase="idle",
            task_id=task_id,
            started_at=started_at,
            completed_at=None,
            memo_count=0,
            confidence=None,
            risk_note=f"不在时间窗口（{_WINDOW_START}~{_WINDOW_END}）",
            elapsed_min=None,
            error=None,
        )

    # 读取 task 开始时间（从 status tag）
    status_tag_mtime = None
    if os.path.exists(STATUS_TAG):
        try:
            with open(STATUS_TAG) as f:
                data = json.load(f)
                phase = data.get("phase", "enqueued")
                # 如果已完成或超时，不再重复检查（直接返回）
                if phase in ("completed", "timeout"):
                    conn2 = psycopg2.connect(pg.uri)
                    try:
                        memo_ok2, memo_count2, _ = _check_memos_completion(today)
                        confidence2 = _assess_confidence_from_memos(conn2, today) if memo_ok2 else None
                    finally:
                        conn2.close()
                    return WOAStatus(
                        phase=phase,
                        task_id=data.get("task_id"),
                        started_at=datetime.fromisoformat(data.get("updated_at", "")),
                        completed_at=_now() if phase == "completed" else None,
                        memo_count=memo_count2,
                        confidence=confidence2,
                        risk_note=f"WOA {phase}（根据状态标记）",
                        elapsed_min=None,
                        error=None,
                    )
                started_at_str = data.get("updated_at", "")
                if started_at_str:
                    started_at = datetime.fromisoformat(started_at_str)
        except Exception:
            pass

    # 检查 memo 完成度
    memo_ok, memo_count, memo_titles = _check_memos_completion(today)

    if memo_ok:
        conn = psycopg2.connect(pg.uri)
        try:
            confidence = _assess_confidence_from_memos(conn, today)
        finally:
            conn.close()
        # 回写完成状态到 tag（避免重复检查）
        if task_id:
            _write_status_tag(task_id, phase="completed")
        return WOAStatus(
            phase="completed",
            task_id=task_id,
            started_at=started_at,
            completed_at=_now(),
            memo_count=memo_count,
            confidence=confidence,
            risk_note=None,
            elapsed_min=round((_now() - started_at).total_seconds() / 60, 1) if started_at else None,
            error=None,
        )

    # 未完成：检查是否超时
    if started_at:
        elapsed = (_now() - started_at).total_seconds() / 60
        if elapsed > _WINDOW_TOTAL_MIN:
            return WOAStatus(
                phase="timeout",
                task_id=task_id,
                started_at=started_at,
                completed_at=None,
                memo_count=memo_count,
                confidence=None,
                risk_note=f"超时（>{60}min）",
                elapsed_min=round(elapsed, 1),
                error=f"WOA 未在 {_WINDOW_TOTAL_MIN} 分钟内完成 Morning Briefing",
            )

    # 检查 jiuwen.log 活跃度
    progress = _check_jiuwen_log_progress(started_at or _now())

    # 检查 team.log 完成标记
    team_complete, team_msg = _check_team_log_completion(task_id, started_at or _now())

    return WOAStatus(
        phase="running" if progress or team_complete else "idle",
        task_id=task_id,
        started_at=started_at,
        completed_at=None,
        memo_count=memo_count,
        confidence=None,
        risk_note=team_msg if team_complete else (progress if progress else None),
        elapsed_min=round((_now() - started_at).total_seconds() / 60, 1) if started_at else None,
        error=None,
    )


def main():
    status = check_woa_status()
    print(json.dumps({
        "phase": status.phase,
        "task_id": status.task_id[:8] if status.task_id else None,
        "memo_count": status.memo_count,
        "confidence": status.confidence,
        "risk_note": status.risk_note,
        "elapsed_min": status.elapsed_min,
        "error": status.error,
        "checked_at": _now().isoformat(),
    }, ensure_ascii=False, indent=2))
    return 0 if status.phase in ("completed", "idle") else 1


if __name__ == "__main__":
    raise SystemExit(main())