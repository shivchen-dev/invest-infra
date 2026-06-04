#!/usr/bin/env python3
"""补充缺失历史K线 — 从次方量化 API 回填 2025 年至今的历史行情

针对 LOF/次方量化新增的 ETF，补充 akshare 未覆盖的历史段。
仅补缺失的日期，不覆盖已有数据。
"""
import sys, os, time, logging
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
os.chdir("/home/claw/invest-infra/data-pipeline")

from datetime import date, datetime
from src.collector.cifang import fetch_fund_hist, backfill_hist
from src.config import pg
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/home/claw/invest-infra/data-pipeline/logs/cifang_backfill.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cifang_backfill")

BACKFILL_START = date(2025, 1, 2)    # 统一从 2025-01-02 开始补
BACKFILL_END   = date.today()
MIN_DAYS       = 30                  # 历史少于 30 天才补


def main():
    conn = psycopg2.connect(pg.uri)
    cur = conn.cursor()

    # 找出历史少于 MIN_DAYS 的 ETF
    cur.execute("""
        SELECT e.code, e.name, COUNT(eq.id) as days
        FROM etfs e
        LEFT JOIN etf_quotes eq ON eq.etf_id = e.id
        WHERE e.is_active = true
        GROUP BY e.id, e.code, e.name
        HAVING COUNT(eq.id) < %s
        ORDER BY COUNT(eq.id) ASC
        LIMIT 200
    """, (MIN_DAYS,))
    targets = cur.fetchall()
    conn.close()

    if not targets:
        logger.info("无需补充历史的 ETF（全部 >= %d 天）", MIN_DAYS)
        return

    logger.info("待补充 ETF: %d 只（历史 < %d 天）", len(targets), MIN_DAYS)

    total_written = 0
    skipped = 0
    for code, name, existing_days in targets:
        try:
            written = backfill_hist(code, BACKFILL_START, BACKFILL_END)
            if written > 0:
                total_written += written
                logger.info("  %s %s: 补 %d 条 -> 共 %d 天", code, name[:8], written, existing_days + written)
            else:
                skipped += 1
                logger.debug("  %s %s: 无历史数据可补", code, name[:8])
        except Exception as e:
            logger.warning("  %s %s: 失败 -> %s", code, name[:8], e)

    logger.info("补充完成: 写入 %d 条, 跳过 %d 只", total_written, skipped)


if __name__ == "__main__":
    main()