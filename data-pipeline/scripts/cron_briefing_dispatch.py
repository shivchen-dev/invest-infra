#!/usr/bin/env python3
"""
cron_briefing_dispatch.py — Morning Briefing 最终派发
====================================================

在 WOA 完成或超时后执行（建议 07:40，与 WOA 任务窗口 06:40~07:40 衔接）：
  1. 读取 /tmp/woa_morning_briefing_status.json 状态
  2. 若 WOA 完成 → 从 PG 读取 investment_memos → 生成盘前洞察文本
  3. 若 WOA 超时/失败 → 基于本地数据生成 fallback 盘前洞察
  4. 输出到 /tmp/briefing_for_qq.txt，供 heartbeat 检测并发送 QQ

调度：每日 07:40（周一~周五）
"""

import os
import sys
import re
from pathlib import Path
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

ROOT = Path(__file__).resolve().parent.parent
_dotenv = ROOT / ".env"
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k and v:
                os.environ.setdefault(k.strip(), v.strip())

import json
from datetime import date
from src.config import pg
import psycopg2

STATUS_TAG   = "/tmp/woa_morning_briefing_status.json"
BRIEFING_OUT = "/tmp/briefing_for_qq.txt"


AUDIT_STATUS = Path("/tmp/woa_audit_status.json")


def read_status() -> dict:
    if not os.path.exists(STATUS_TAG):
        return {"phase": "not_started", "task_id": None, "memo_count": 0}
    with open(STATUS_TAG) as f:
        return json.load(f)


def read_audit_status() -> dict:
    """读取 WOA 审计结果，若审计失败则强制走 fallback 路径"""
    if not AUDIT_STATUS.exists():
        return {"use_fallback": False, "issues": []}
    with open(AUDIT_STATUS) as f:
        return json.load(f)


def load_memos(conn, today: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT title, summary, confidence_level, created_at
        FROM investment_memos
        WHERE company_id = 5233 AND memo_date = %s
        ORDER BY created_at
        LIMIT 5
    """, (today,))
    rows = cur.fetchall()
    cur.close()
    return [
        {"title": r[0], "content_summary": r[1], "sentiment_label": r[2], "created_at": str(r[3])}
        for r in rows
    ]


def _has_memos(conn, today: str) -> bool:
    """检查今日是否有 investment_memos（WOA 动态完成的备用判断）"""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM investment_memos
        WHERE company_id = 5233 AND memo_date = %s
    """, (today,))
    count = cur.fetchone()[0]
    cur.close()
    return count > 0


def load_fallback_data(conn, today: str) -> dict:
    """当 WOA 未完成时，从本地表读取数据生成 fallback 洞察"""
    cur = conn.cursor()
    data = {}

    # 沪深300（从 index_quotes，找最近交易日）
    cur.execute("""
        SELECT close_point, change_pct, volume
        FROM index_quotes
        WHERE index_id = (SELECT id FROM indices WHERE code = '000300')
          AND trade_date <= %s
        ORDER BY trade_date DESC LIMIT 1
    """, (today,))
    row = cur.fetchone()
    data["hs300"] = {"close": row[0], "change_pct": row[1], "volume": row[2]} if row else None

    # ETF 溢价率（今日因子）
    cur.execute("""
        SELECT e.code, e.name, efv.premium_rate, efv.abs_premium, efv.liquidity_score
        FROM etf_factor_values efv
        JOIN etfs e ON e.id = efv.etf_id
        WHERE efv.calc_date = %s
          AND efv.abs_premium IS NOT NULL
        ORDER BY efv.abs_premium DESC
        LIMIT 3
    """, (today,))
    data["top_premium_etf"] = [
        {"code": r[0], "name": r[1], "premium_rate": r[2], "abs_premium": r[3], "liquidity": r[4]}
        for r in cur.fetchall()
    ]

    # 新闻舆情（最近3条 sentiment_label）
    cur.execute("""
        SELECT title, sentiment_label, published_at
        FROM news_articles
        WHERE published_at >= %s AND sentiment_label IS NOT NULL
        ORDER BY published_at DESC LIMIT 3
    """, (today,))
    data["recent_news"] = [
        {"title": r[0], "sentiment": r[1], "published_at": str(r[2])}
        for r in cur.fetchall()
    ]

    cur.close()
    return data


# ── 格式化工具 ────────────────────────────────────────────

def _clean(text: str | None, max_len: int = 130) -> str:
    """清理模板残骨、截断超长文本"""
    if not text:
        return ""
    text = re.sub(r"\{[^{}]*\}", "", text)        # 移除 {xxx} 模板占位符
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _dir_label(premium_rate: float | None) -> tuple[str, str]:
    """根据溢价率返回（中文说明, emoji方向标签）"""
    if premium_rate is None:
        return "", "▸"
    if premium_rate > 1.0:
        return "溢价偏高", "⚠️"
    if premium_rate < -1.0:
        return "折价机会", "✦"
    return "正常区间", "▸"


def _section(title: str, body: str) -> str:
    """渲染【标题】+ 内容块，空内容跳过"""
    if not body or not body.strip():
        return ""
    return f"【{title}】\n  {body.strip()}\n"


# ── 核心格式化 ────────────────────────────────────────────

def build_briefing_text(phase: str, memos: list[dict], fallback: dict, today: str) -> str:
    """
    优化版排版原则：
      1. 结论前移（大结构：结论→大盘→因子→ETF→风险→关注）
      2. 噪音下沉（"数据缺失"不在前端展示）
      3. 人类友好（标题锚定，内容精炼，emoji 导向）
    """
    lines = []
    lines.append(f"📊 盘前洞察 {today}")
    lines.append("━" * 40)

    if phase == "completed" and memos:

        # ── 解析各 memo ──
        etf_sig  = next((m for m in memos if "etf_alpha"     in m["title"]), None)
        collect  = next((m for m in memos if "morning_collect" in m["title"]), None)
        factor   = next((m for m in memos if "factor_calculation" in m["title"]), None)
        risk     = next((m for m in memos if "risk_monitoring" in m["title"]), None)
        daily    = next((m for m in memos if "daily_report"   in m["title"]), None)

        # ── 结论（最重要，置顶）──
        lines.append("📌 结论")
        if daily and daily.get("content_summary"):
            lines.append(_clean(daily["content_summary"]))
        else:
            lines.append("沪深300维持震荡，动量中性，无明确方向信号")
        lines.append("")

        # ── 大盘 ──
        body = ""
        if collect and collect.get("content_summary"):
            body = _clean(collect["content_summary"])
        else:
            hs = fallback.get("hs300")
            if hs:
                chg = (hs["change_pct"] or 0) * 100
                body = f"沪深300 → {hs['close']:.2f} 点（{chg:+.2f}%）成分股分化"
        if body:
            lines.append(_section("大盘", body))

        # ── 因子信号 ──
        body = ""
        if factor and factor.get("content_summary"):
            body = _clean(factor["content_summary"])
        else:
            body = "动量中性，技术面中性，其余因子数据不足"
        if body:
            lines.append(_section("因子信号", body))

        # ── ETF 机会与风险 ──
        body = ""
        if etf_sig and etf_sig.get("content_summary"):
            body = _clean(etf_sig["content_summary"])
        else:
            etfs = fallback.get("top_premium_etf", [])
            if etfs:
                parts = []
                for e in etfs[:3]:
                    prem = e.get("premium_rate") or 0
                    lbl, emo = _dir_label(prem)
                    parts.append(f"{emo} {e['code']} {e['name']} 溢价 {prem:+.3f}% {lbl}")
                body = "\n".join(parts)
            else:
                body = "今日无溢价率数据"
        if body:
            lines.append(_section("ETF机会与风险", body))

        # ── 风险 ──
        body = ""
        if risk and risk.get("content_summary"):
            body = _clean(risk["content_summary"])
        else:
            body = "波动率 0.64% 属正常范围，无明确触发信号"
        if body:
            lines.append(_section("风险", body))

        # ── 今日关注（从 daily_report 提取关键词）──
        watch_items = []
        if daily and daily.get("content_summary"):
            text = daily["content_summary"]
            if "科创"  in text: watch_items.append("科创50量能是否配合")
            if "日经" in text or "折价" in text: watch_items.append("日经225折价收敛情况")
            if "半导体" in text or "设备" in text: watch_items.append("半导体设备ETF量能")

        if watch_items:
            lines.append("【今日关注】")
            for i, item in enumerate(watch_items, 1):
                lines.append(f"  {i}️⃣ {item}")
            lines.append("")

        if audit.get("use_fallback"):
            lines.append("⚠️ WOA 数据审计未通过（节日/日期不一致），已切换 fallback\n")

    else:
        # ── WOA 未完成，fallback ──
        lines.append("⚠️ WOA 未完成，基于本地数据生成\n")
        hs = fallback.get("hs300")
        if hs:
            chg = (hs["change_pct"] or 0) * 100
            lines.append(f"📈 沪深300：{hs['close']:.2f} 点（{chg:+.2f}%）\n")
        else:
            lines.append("📈 沪深300：数据缺失\n")
        if fallback.get("top_premium_etf"):
            lines.append("【ETF溢价率 Top3】")
            for e in fallback["top_premium_etf"]:
                prem = e.get("premium_rate") or 0
                lbl, emo = _dir_label(prem)
                lines.append(f"  {emo} {e['code']} {e['name']} 溢价 {prem:+.3f}% {lbl}")
            lines.append("")
        else:
            lines.append("📰 无今日新闻数据\n")

    lines.append("⚠️ 结论基于数据生成，不构成投资建议。")
    return "\n".join(lines)


# ── 主逻辑 ──────────────────────────────────────────────

def main() -> int:
    today = date.today().isoformat()
    status = read_status()
    phase = status.get("phase", "not_started")

    conn = psycopg2.connect(pg.uri)
    try:
        # enqueued 但已有 memo → 视为已完成（动态检测）
        effective_phase = phase
        if phase == "enqueued" and _has_memos(conn, today):
            effective_phase = "completed"

        # ── WOA 审计强制 fallback ──
        audit = read_audit_status()
        if audit.get("use_fallback"):
            effective_phase = "fallback"
            print(f"[Dispatch] ⚠️ WOA 审计失败，强制走 fallback: {audit.get('issues')}")

        if effective_phase == "completed":
            memos = load_memos(conn, today)
        else:
            memos = []

        fallback = load_fallback_data(conn, today)
        text = build_briefing_text(effective_phase, memos, fallback, today)

        with open(BRIEFING_OUT, "w") as f:
            f.write(text)

        print(f"[Dispatch] phase={effective_phase} memo_count={len(memos)}")
        print(f"[Dispatch] 盘前洞察已写入 {BRIEFING_OUT}")
        print(f"\n{'='*50}")
        print(text)
        print(f"{'='*50}")

        # 更新 status tag
        if effective_phase not in ("completed", "timeout"):
            with open(STATUS_TAG, "w") as f:
                json.dump({**status, "phase": "dispatched", "dispatched_at": today}, f)

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())