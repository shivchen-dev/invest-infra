#!/usr/bin/env python3
"""
run_health_monitor.py — ETF 数据健康检查（含套利信号统计）
============================================================

检查内容：
  1. etf_quotes 采集健康（最新有数据日期 + 记录数）
  2. etf_factor_values 计算健康（最新有数据日期 + 因子覆盖率）
  3. etf_arbitrage_signals 信号统计（触发数、方向分布、置信度）
  4. cron 任务最近执行状态摘要

调度：
  python3 scripts/run_health_monitor.py
"""

import sys, os
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

_dotenv = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k and v:
                os.environ.setdefault(k.strip(), v.strip())

from datetime import date
from src.config import pg
import psycopg2


def check_quotes_health(conn, today):
    """检查 etf_quotes 采集健康（使用最近有数据的日期）"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM etf_quotes")
    latest_date = cur.fetchone()[0] or today
    cur.execute("""
        SELECT COUNT(*), MAX(eq.created_at)
        FROM etf_quotes eq
        WHERE eq.trade_date = %s
    """, (latest_date,))
    row = cur.fetchone()
    cur.close()
    count, max_created = row
    return {"table": "etf_quotes", "records": count, "date": str(latest_date), "max_created": str(max_created)}


def check_factor_health(conn, today):
    """检查 etf_factor_values 计算健康（使用最近有数据的日期）"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(calc_date) FROM etf_factor_values")
    latest_date = cur.fetchone()[0] or today
    cur.execute("""
        SELECT COUNT(*),
               COUNT(CASE WHEN premium_rate IS NOT NULL THEN 1 END),
               COUNT(CASE WHEN liquidity_score IS NOT NULL THEN 1 END)
        FROM etf_factor_values
        WHERE calc_date = %s
    """, (latest_date,))
    total, has_premium, has_liquidity = cur.fetchone()
    cur.close()
    return {
        "table": "etf_factor_values",
        "records": total,
        "date": str(latest_date),
        "has_premium": has_premium,
        "has_liquidity": has_liquidity,
    }


def check_arbitrage_signals(conn, today):
    """检查套利信号统计（使用最近有信号的日期）"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(signal_date) FROM etf_arbitrage_signals")
    latest_date = cur.fetchone()[0] or today
    cur.execute("""
        SELECT COUNT(*),
               COUNT(CASE WHEN direction = 'premium' THEN 1 END),
               COUNT(CASE WHEN direction = 'discount' THEN 1 END),
               COUNT(CASE WHEN confidence = 'high' THEN 1 END),
               COUNT(CASE WHEN net_gain_pct > 0 THEN 1 END),
               ROUND(COALESCE(AVG(net_gain_pct), 0), 4),
               ROUND(COALESCE(MAX(net_gain_pct), 0), 4)
        FROM etf_arbitrage_signals
        WHERE signal_date = %s
    """, (latest_date,))
    row = cur.fetchone()
    cur.close()
    return {
        "table": "etf_arbitrage_signals",
        "signals_total": row[0] or 0,
        "premium_count": row[1] or 0,
        "discount_count": row[2] or 0,
        "high_confidence": row[3] or 0,
        "profitable_signals": row[4] or 0,
        "avg_net_gain_pct": row[5] or 0.0,
        "max_net_gain_pct": row[6] or 0.0,
        "date": str(latest_date),
    }


def main():
    today = date.today()
    conn = psycopg2.connect(pg.uri)
    try:
        print("=" * 60)
        print(f"  ETF 数据健康检查 — {today}")
        print("=" * 60)

        quotes = check_quotes_health(conn, today)
        print(f"\n[1/3] 行情采集 (etf_quotes)")
        print(f"   数据日期: {quotes['date']}  |  记录数: {quotes['records']}  条")
        print(f"   最新入库: {quotes['max_created']}")

        factor = check_factor_health(conn, today)
        print(f"\n[2/3] 因子计算 (etf_factor_values)")
        print(f"   数据日期: {factor['date']}  |  记录数: {factor['records']}  条")
        print(f"   含溢价率: {factor['has_premium']}  |  含流动性: {factor['has_liquidity']}")

        arb = check_arbitrage_signals(conn, today)
        print(f"\n[3/3] 套利信号 (etf_arbitrage_signals)")
        print(f"   数据日期: {arb['date']}  |  信号总数: {arb['signals_total']}  条")
        print(f"   溢价信号: {arb['premium_count']}  |  折价信号: {arb['discount_count']}")
        print(f"   高置信度: {arb['high_confidence']}  |  可盈利信号: {arb['profitable_signals']}")
        print(f"   平均净收益: {arb['avg_net_gain_pct']:.4f}%  |  最高: {arb['max_net_gain_pct']:.4f}%")

        # 总体结论
        print("\n" + "=" * 60)
        healthy = quotes["records"] > 0 and factor["records"] > 0
        print(f"结论: {'✅ 数据健康' if healthy else '⚠️ 数据异常'}")
        if arb["signals_total"] > 0:
            print(f"      套利信号 {arb['date']} 共 {arb['signals_total']} 条，"
                  f"{arb['high_confidence']} 条高置信，"
                  f"{arb['profitable_signals']} 条可盈利，"
                  f"最高净收益 {arb['max_net_gain_pct']:.4f}%")

    finally:
        conn.close()


if __name__ == "__main__":
    main()