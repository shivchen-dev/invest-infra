#!/usr/bin/env python3
"""因子计算入口脚本

用法:
  uv run python scripts/run_factors.py                         # 计算全部因子
  uv run python scripts/run_factors.py --category fundamental  # 仅基本面
  uv run python scripts/run_factors.py --category technical    # 仅技术面
  uv run python scripts/run_factors.py --limit 10              # 全市场前10只股票
  uv run python scripts/run_factors.py --code 600519.SH,000858.SZ  # 指定个股
"""

import argparse
import logging
import sys
sys.path.insert(0, ".")

from src.factors.engine import compute_factors, sync_definitions_to_db, get_active_company_ids
from src.factors.registry import register_all, list_factors, FactorCategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

def main():
    parser = argparse.ArgumentParser(description="Phase 2 因子计算引擎")
    parser.add_argument("--category", type=str, default="", choices=["", "fundamental", "technical", "alternative"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--code", type=str, default="")
    args = parser.parse_args()

    # 先同步定义
    sync_definitions_to_db()

    # 确定因子列表
    register_all()
    if args.category:
        cat = FactorCategory(args.category)
        factor_keys = [f.key for f in list_factors(category=cat)]
    else:
        factor_keys = None

    # 确定公司列表
    company_ids = None
    if args.code:
        import psycopg2
        from src.config import pg
        codes = [c.strip() for c in args.code.split(",")]
        conn = psycopg2.connect(pg.uri)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE code = ANY(%s)", (codes,))
            company_ids = [row[0] for row in cur.fetchall()]
        conn.close()
        print(f"指定股票 {args.code}: {len(company_ids)} 只")
    elif args.limit > 0:
        company_ids = get_active_company_ids()[:args.limit]

    result = compute_factors(factor_keys=factor_keys, company_ids=company_ids)
    print(f"\n✅ 因子计算完成: {result['factors_computed']} 个因子, {result['values_written']} 条值写入")
    if result.get("errors"):
        print(f"⚠️ {len(result['errors'])} 个错误: {result['errors'][:5]}")

if __name__ == "__main__":
    main()
