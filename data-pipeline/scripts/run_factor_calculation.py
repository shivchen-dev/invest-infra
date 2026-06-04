#!/usr/bin/env python3
"""
run_factor_calculation.py — FQIR 三维度因子统一调度脚本
============================================================

按顺序执行：
  1. etf_fundamental.py（F 维度：行业景气/成分股盈利/集中度）
  2. etf_info_flow.py（I 维度：新闻情绪/政策支持/舆情/研报覆盖）
  3. etf_risk.py（R 维度：政策风险/财务恶化/波动率异常/流动性风险）

执行方式：
  python3 scripts/run_factor_calculation.py              # 今日
  python3 scripts/run_factor_calculation.py --date 2026-06-01  # 指定日期
  python3 scripts/run_factor_calculation.py --dry-run    # 不写入DB
  python3 scripts/run_factor_calculation.py --step fund # 只跑某个维度

输出：
  - 各维度因子写入 etf_fundamental_scores / etf_info_scores / etf_risk_scores
  - 控制台打印统计（计算数量、写入数量、耗时）
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
from src.config import pg
import pandas as pd

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_factor")


def run_fundamental(conn, calc_date, dry_run):
    from src.factors.etf_fundamental import compute_etf_fundamental
    import psycopg2
    t0 = time.time()
    try:
        df = compute_etf_fundamental(conn, calc_date, dry_run=dry_run)
    except psycopg2.Error as e:
        logger.error("[fundamental] compute_etf_fundamental 失败 pgcode=%s: %s", e.pgcode, e)
        conn.rollback()
        raise
    elapsed = time.time() - t0
    logger.info(
        "[fundamental] F维度完成 | 计算%d只ETF | 耗时%.1fs | 写入=%s",
        len(df), elapsed, not dry_run
    )
    return df


def run_info_flow(conn, calc_date, dry_run):
    from src.factors.etf_info_flow import compute_etf_info_flow
    t0 = time.time()
    df = compute_etf_info_flow(conn, calc_date, dry_run=dry_run)
    elapsed = time.time() - t0
    logger.info(
        "[info_flow] I维度完成 | 计算%d只ETF | 耗时%.1fs | 写入=%s",
        len(df), elapsed, not dry_run
    )
    return df


def run_risk(conn, calc_date, dry_run):
    from src.factors.etf_risk import compute_etf_risk
    t0 = time.time()
    df = compute_etf_risk(conn, calc_date, dry_run=dry_run)
    elapsed = time.time() - t0
    logger.info(
        "[risk] R维度完成 | 计算%d只ETF | 耗时%.1fs | 写入=%s",
        len(df), elapsed, not dry_run
    )
    return df


def run_all(conn, calc_date, dry_run, steps):
    total_start = time.time()

    results = {}
    step_map = {
        "fund": ("fundamental", lambda: run_fundamental(conn, calc_date, dry_run)),
        "info": ("info_flow",    lambda: run_info_flow(conn, calc_date, dry_run)),
        "risk": ("risk",         lambda: run_risk(conn, calc_date, dry_run)),
    }

    for step in steps:
        if step in step_map:
            label, fn = step_map[step]
            try:
                results[step] = fn()
            except psycopg2.Error as e:
                logger.error("[run_all] %s 失败 pgcode=%s: %s", label, e.pgcode, e)
                conn.rollback()
                results[step] = pd.DataFrame()
            except Exception as e:
                logger.error("[run_all] %s 异常: %s", label, e)
                conn.rollback()
                results[step] = pd.DataFrame()

    total_elapsed = time.time() - total_start
    success = [s for s in results if not results[s].empty]

    logger.info("=" * 50)
    logger.info("因子计算完成  date=%s  dry=%s  耗时=%.1fs", calc_date, dry_run, total_elapsed)
    logger.info("成功维度: %s  |  总ETF数: %s", success, {s: len(r) for s, r in results.items()})
    logger.info("=" * 50)

    return results


def main():
    parser = argparse.ArgumentParser(description="ETF FQIR 三维度因子计算")
    parser.add_argument("--date", type=str, default=None,
                        help="计算日期（YYYY-MM-DD），默认今日")
    parser.add_argument("--dry-run", action="store_true",
                        help="只计算不写入数据库")
    parser.add_argument("--step", type=str, default="all",
                        help="只运行指定维度: fund | info | risk | all（默认all）")
    args = parser.parse_args()

    calc_date = date.fromisoformat(args.date) if args.date else date.today()

    steps_map = {
        "all": ["fund", "info", "risk"],
        "fund": ["fund"],
        "info": ["info"],
        "risk": ["risk"],
    }
    steps = steps_map.get(args.step, ["fund", "info", "risk"])

    logger.info("启动因子计算  date=%s  step=%s  dry=%s", calc_date, args.step, args.dry_run)

    conn = psycopg2.connect(pg.uri)
    try:
        run_all(conn, calc_date, args.dry_run, steps)
    finally:
        conn.close()


if __name__ == "__main__":
    main()