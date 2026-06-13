#!/usr/bin/env python3
"""
cron_collect_news.py — 个股新闻采集（轻量独立版）

数据流：
  akshare stock_news_em(全A股 5525只) → 逐只采集 → 去重入库 news_articles
  → etf_info_flow.py 的 I 维度因子（行业聚合）有数据可用

触发时间：每日 09:30（etf_pipeline 之后5分钟）
历史追溯：采集全量历史新闻（不限日期，akshare 每次返回近期记录）
          由 ON CONFLICT DO NOTHING 去重

设计原则：
  - 独立脚本，不依赖 run_all() 的其他步骤（quotes/financial）
  - 分批采集，每批暂停 0.15s（akshare 友好）
  - 超时 8 分钟强制退出（不阻塞后续任务）
"""

import sys
import os
import time
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

# ─── 路径 & env ──────────────────────────────────────────────────────────────
_PIPELINE_DIR = Path("/home/claw/invest-infra/data-pipeline")
_SECRETS_DIR  = _PIPELINE_DIR.parent / ".secrets"

def _load_env(filepath):
    if filepath and filepath.exists():
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)

_load_env(_SECRETS_DIR / "tokens.env")
_load_env(_PIPELINE_DIR / ".env")

# ─── 超时控制 ────────────────────────────────────────────────────────────────
_MAX_RUNTIME = 480  # 8 分钟

# ─── 日志 ────────────────────────────────────────────────────────────────────
LOG_DIR = Path("/home/claw/invest-infra/data-pipeline/logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "news_collector.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("news_collector")

# ─── 导入 ─────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(_PIPELINE_DIR))
sys.path.insert(0, str(_PIPELINE_DIR / "src"))

from src.collector import news
from src.loader.pg import batch_upsert_news

# ─── 主逻辑 ─────────────────────────────────────────────────────────────────
def main():
    start_time = time.time()
    logger.info("[news_collector] 开始采集")

    import psycopg2
    conn = psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("PG_DB", "investdb"),
        user=os.environ.get("PG_USER", "invest"),
        password=os.environ.get("PG_PASSWORD", ""),
    )

    try:
        # 从 companies 表获取所有 A 股股票代码（akshare 只支持个股）
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM companies ORDER BY code")
            codes = [r[0] for r in cur.fetchall()]

        logger.info(f"[news_collector] 待采集股票数: {len(codes)}")

        total_written = 0
        total_errors = 0
        today = date.today()

        BATCH_SIZE = 200
        BATCH_DELAY = 0.15  # akshare 友好

        for i in range(0, len(codes), BATCH_SIZE):
            # 超时检查
            if time.time() - start_time > _MAX_RUNTIME:
                logger.warning(f"[news_collector] 超时({_MAX_RUNTIME}s)，强制退出，已采集至第{i}只")
                break

            batch_codes = codes[i:i + BATCH_SIZE]
            batch_records = []

            for code in batch_codes:
                try:
                    records = news.fetch_stock_news(code)
                    if records:
                        # 全部写入，ON CONFLICT DO NOTHING 自动去重
                        batch_records.extend(records)
                except Exception:
                    # 静默跳过（ETF代码/无数据/接口异常）
                    pass

                time.sleep(BATCH_DELAY)

            if batch_records:
                try:
                    result = batch_upsert_news(batch_records)
                    written = result.get("written", 0)
                    total_written += written
                    logger.info(f"[news_collector] 批次 {i//BATCH_SIZE + 1}: 写入 {written} 条")
                except Exception as e:
                    logger.error(f"[news_collector] 批次写入失败: {e}")

        elapsed = round(time.time() - start_time, 1)
        logger.info(f"[news_collector] 完成: 写入 {total_written} 条, 耗时 {elapsed}s")

    finally:
        conn.close()

if __name__ == "__main__":
    main()