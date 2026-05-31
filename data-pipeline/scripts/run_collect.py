#!/usr/bin/env python3
"""数据采集入口脚本

用法:
  uv run python scripts/run_collect.py              # 默认采集前 50 只
  uv run python scripts/run_collect.py --limit 10   # 只采 10 只测试
  uv run python scripts/run_collect.py --days 30    # 回溯 30 天
  uv run python scripts/run_collect.py --code 000001.SZ,600519.SH
"""

import argparse
import logging
import sys
sys.path.insert(0, ".")

from src.pipeline import run_all

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
    args = parser.parse_args()
    codes = [c.strip() for c in args.code.split(",")] if args.code else None
    result = run_all(stock_codes=codes, days=args.days, limit=args.limit)
    print(f"\n✅ 采集完成")

if __name__ == "__main__":
    main()
