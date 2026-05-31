"""Phase 1 数据采集管线主编排器"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from src.config import collector as cc, minio as mc
from src.collector import companies, quotes, financial, news
from src.loader import minio as minio_loader, pg as pg_loader

logger = logging.getLogger(__name__)


def run_all(stock_codes: Optional[list[str]] = None, days: int = 0, limit: int = 50) -> dict:
    result = {"started_at": datetime.now().isoformat(), "steps": {}}
    today = date.today()
    if days > 0:
        cc.quotes_history_days = days

    minio_loader.ensure_buckets()

    # Step 1: 公司列表同步
    t0 = time.time()
    all_companies = companies.fetch_all_companies()
    sync_result = companies.sync_to_db(all_companies)
    result["steps"]["companies"] = {"count": len(all_companies), **sync_result, "elapsed_s": round(time.time() - t0, 2)}

    codes = stock_codes or [c["code"] for c in all_companies]
    batch_codes = codes[:limit]
    start_date = today - timedelta(days=cc.quotes_history_days)

    # Step 2: 行情
    t0 = time.time()
    q_total = 0
    for code in batch_codes:
        batch = quotes.fetch_quotes(code, start_date=start_date, end_date=today)
        if batch:
            q_total += len(batch)
            minio_loader.store_json(batch, mc.bucket_bronze_quotes, "quotes/daily", today)
            pg_loader.batch_upsert_quotes(batch)
        time.sleep(cc.request_interval)
    result["steps"]["quotes"] = {"stocks": len(batch_codes), "records": q_total, "elapsed_s": round(time.time() - t0, 2)}

    # Step 3: 财报
    t0 = time.time()
    fr_total = 0
    for code in batch_codes:
        batch = financial.fetch_financial_report(code)
        if batch:
            fr_total += len(batch)
            minio_loader.store_json(batch, mc.bucket_bronze_financial, "financial/reports", today)
            pg_loader.batch_upsert_financial(batch)
        time.sleep(cc.request_interval)
    result["steps"]["financial"] = {"stocks": len(batch_codes), "records": fr_total, "elapsed_s": round(time.time() - t0, 2)}

    # Step 4: 新闻
    t0 = time.time()
    n_total = 0
    for code in batch_codes:
        batch = news.fetch_stock_news(code)
        if batch:
            n_total += len(batch)
            minio_loader.store_json(batch, mc.bucket_bronze_news, "news/stock", today)
            pg_loader.batch_upsert_news(batch)
        time.sleep(cc.request_interval)
    result["steps"]["news"] = {"stocks": len(batch_codes), "records": n_total, "elapsed_s": round(time.time() - t0, 2)}

    result["finished_at"] = datetime.now().isoformat()
    return result
