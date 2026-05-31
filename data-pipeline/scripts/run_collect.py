#!/usr/bin/env python3
"""数据采集入口脚本

用法:
  # 股票采集（默认 akshare）
  uv run python scripts/run_collect.py --limit 10 --days 30

  # 股票采集（RssCast 数据源）
  uv run python scripts/run_collect.py --rsscast --limit 10 --days 30

  # ETF 采集
  uv run python scripts/run_collect.py --etf --limit 20 --days 30
"""

import argparse
import logging
import sys
sys.path.insert(0, ".")

from src.pipeline import run_all, run_etf_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

def main():
    parser = argparse.ArgumentParser(description="Phase 1 数据采集管线")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--code", type=str, default="")
    parser.add_argument("--rsscast", action="store_true", help="使用 RssCast MCP 数据源")
    parser.add_argument("--etf", action="store_true", help="仅运行 ETF 采集管线")
    args = parser.parse_args()

    if args.etf:
        result = run_etf_pipeline(days=args.days or 30, limit=args.limit)
        print(f"\n✅ ETF采集完成")
        return

    codes = [c.strip() for c in args.code.split(",")] if args.code else None
    source = "rsscast" if args.rsscast else "akshare"

    result = run_all(stock_codes=codes, days=args.days, limit=args.limit, source=source)
    print(f"\n✅ 采集完成 | source={source}")

if __name__ == "__main__":
    main()
