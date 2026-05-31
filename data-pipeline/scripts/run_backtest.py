#!/usr/bin/env python3
"""Phase 3 回测引擎 — CLI 入口

用法:
  uv run python scripts/run_backtest.py --list                     # 列出可用因子
  uv run python scripts/run_backtest.py --code 600519.SH           # 单股回测
  uv run python scripts/run_backtest.py --code 000001.SZ,000858.SZ # 多股
  uv run python scripts/run_backtest.py --limit 10                 # Top N 股票
  uv run python scripts/run_backtest.py --scan                     # 因子扫描
  uv run python scripts/run_backtest.py                           # 全市场
"""

import argparse
import logging
import sys
sys.path.insert(0, ".")

from datetime import date, timedelta
from src.backtest.engine import run_backtest
from src.backtest.strategies import make_signal_config, StrategyConfig, FactorSignalConfig
from src.backtest.report import render_single_report
from src.backtest.analyzers import vectorbt_quick_scan, compute_rank_ic, FactorICReport
from src.backtest.feeds import get_company_code_map
from src.factors.engine import get_active_company_ids
from src.factors.registry import register_all, list_factors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def list_available_factors():
    register_all()
    print("\n可用因子列表:")
    print(f"{'因子Key':<20} {'名称':<20} {'类别':<16}")
    print("-" * 56)
    for f in list_factors():
        print(f"{f.key:<20} {f.name:<20} {f.category.value:<16}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Phase 3 回测引擎")
    parser.add_argument("--code", type=str, default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--list", action="store_true", help="列出可用因子")
    parser.add_argument("--scan", action="store_true", help="Factor IC 扫描")
    parser.add_argument("--factor", type=str, default="",
                        help="逗号分隔的因子 key，默认使用全部因子")
    parser.add_argument("--days", type=int, default=180,
                        help="回测天数 (默认180)")
    parser.add_argument("--threshold", type=float, default=0.7,
                        help="因子信号入场阈值 (默认0.7)")
    parser.add_argument("--top-n", type=int, default=0,
                        help="Top-N 选股 (0=阈值模式)")
    parser.add_argument("--init-cash", type=float, default=1_000_000.0)
    parser.add_argument("--output", type=str, default="",
                        help="报告输出路径")
    args = parser.parse_args()

    if args.list:
        list_available_factors()
        return

    register_all()

    # 确定公司列表
    if args.code:
        codes = [c.strip() for c in args.code.split(",")]
        import psycopg2
        from src.config import pg
        conn = psycopg2.connect(pg.uri)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE code = ANY(%s)", (codes,))
            company_ids = [row[0] for row in cur.fetchall()]
        conn.close()
        print(f"指定股票 {args.code}: {len(company_ids)} 只")
    elif args.limit > 0:
        company_ids = get_active_company_ids()[:args.limit]
        print(f"全市场前 {args.limit} 只")
    else:
        company_ids = get_active_company_ids()
        print(f"全市场 {len(company_ids)} 只股票")

    if not company_ids:
        logger.error("无公司数据")
        return

    # 确定因子
    if args.factor:
        factor_keys = [f.strip() for f in args.factor.split(",")]
    else:
        factor_keys = [f.key for f in list_factors()]

    # 日期
    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)

    # 因子扫描模式
    if args.scan:
        print(f"\nVectorBT 因子快速扫描: {len(factor_keys)} 个因子 × {len(company_ids)} 只股票")
        print(f"区间: {start_date} ~ {end_date}\n")
        scan_result = vectorbt_quick_scan(company_ids, factor_keys, start_date, end_date)
        if scan_result:
            print(f"{'因子':<20} {'Top收益%':<12} {'Bottom收益%':<12} {'Spread%':<12} {'胜率%':<10}")
            print("-" * 66)
            for fk, data in sorted(scan_result.items(), key=lambda x: x[1].get("spread_return", 0), reverse=True):
                print(f"{fk:<20} {data['top_mean_return']*100:>+8.2f}%  "
                      f"{data['bot_mean_return']*100:>+8.2f}%  "
                      f"{data['spread_return']*100:>+8.2f}%  "
                      f"{data['top_win_rate']*100:>5.1f}%")
            print()
        return

    # 回测模式
    config = make_signal_config(
        factor_keys=factor_keys,
        threshold_entry=args.threshold,
        top_n=args.top_n,
        max_pos_pct=0.25,
        rebalance_days=5,
    )

    print(f"\n运行回测: {config.name}")
    print(f"区间: {start_date} ~ {end_date}")
    print(f"因子: {len(factor_keys)} 个")
    print(f"股票: {len(company_ids)} 只")
    print()

    result = run_backtest(
        config, company_ids, start_date, end_date,
        init_cash=args.init_cash,
    )

    # IC 分析
    ic_reports = []
    for fk in factor_keys:
        ic = compute_rank_ic(company_ids, fk, start_date, end_date)
        if ic.rank_ic_mean != 0:
            ic_reports.append(ic)

    # 输出报告
    report = render_single_report(result, ic_reports)
    print(report)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"报告已保存: {args.output}")


if __name__ == "__main__":
    main()
