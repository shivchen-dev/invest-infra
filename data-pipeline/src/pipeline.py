"""Phase 1 数据采集管线主编排器"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from src.config import collector as cc, minio as mc, rsscast as rc
from src.collector import companies, quotes, financial, news
from src.collector import rsscast as rsscast_collector
from src.collector import etf as etf_collector
from src.loader import minio as minio_loader, pg as pg_loader

logger = logging.getLogger(__name__)

WIDE_INDEX_CODES = ["000001", "399001", "000300", "000016", "000688", "399006", "000905", "000852"]


def run_all(
    stock_codes: Optional[list[str]] = None,
    days: int = 0,
    limit: int = 50,
    source: str = "akshare",
) -> dict:
    if source == "rsscast":
        return run_all_via_rsscast(stock_codes=stock_codes, days=days, limit=limit)

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

    # Step 2: 股票行情
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


def run_all_via_rsscast(
    stock_codes: Optional[list[str]] = None,
    days: int = 0,
    limit: int = 50,
) -> dict:
    rsscast_collector.configure(rc.endpoint, rc.token)

    result = {"started_at": datetime.now().isoformat(), "source": "rsscast", "steps": {}}
    today = date.today()
    history_days = days if days > 0 else cc.quotes_history_days
    start_date = today - timedelta(days=history_days)

    minio_loader.ensure_buckets()

    # Step 1: 公司列表同步（akshare）
    t0 = time.time()
    all_companies = companies.fetch_all_companies()
    sync_result = companies.sync_to_db(all_companies)
    result["steps"]["companies"] = {"count": len(all_companies), **sync_result, "elapsed_s": round(time.time() - t0, 2)}

    codes = stock_codes or [c["code"] for c in all_companies]
    batch_codes = codes[:limit]

    # Step 2: 股票行情 → daily_quotes
    t0 = time.time()
    q_total = 0
    realtime = rsscast_collector.fetch_stock_quotes_normalized(batch_codes)
    if realtime:
        q_total += len(realtime)
        minio_loader.store_json(realtime, mc.bucket_bronze_quotes, "quotes/daily", today)
        pg_loader.batch_upsert_quotes(realtime)

    klines = rsscast_collector.fetch_stock_kline_normalized(batch_codes, start_date=start_date, end_date=today)
    if klines:
        q_total += len(klines)
        minio_loader.store_json(klines, mc.bucket_bronze_quotes, "quotes/kline", today)
        pg_loader.batch_upsert_quotes(klines)

    result["steps"]["quotes"] = {"stocks": len(batch_codes), "records": q_total, "elapsed_s": round(time.time() - t0, 2)}

    # Step 3: 指数行情 → index_quotes
    t0 = time.time()
    idx_realtime = rsscast_collector.fetch_index_quotes_normalized(WIDE_INDEX_CODES)
    idx_klines = rsscast_collector.fetch_index_kline_normalized(WIDE_INDEX_CODES, start_date=start_date, end_date=today)
    i_total = 0
    if idx_realtime:
        i_total += len(idx_realtime)
        minio_loader.store_json(idx_realtime, mc.bucket_bronze_quotes, "index/daily", today)
        pg_loader.batch_upsert_index_quotes(idx_realtime)
    if idx_klines:
        i_total += len(idx_klines)
        minio_loader.store_json(idx_klines, mc.bucket_bronze_quotes, "index/kline", today)
        pg_loader.batch_upsert_index_quotes(idx_klines)

    result["steps"]["indices"] = {"indices": len(WIDE_INDEX_CODES), "records": i_total, "elapsed_s": round(time.time() - t0, 2)}

    result["finished_at"] = datetime.now().isoformat()
    return result


def run_etf_pipeline(days: int = 30, limit: int = 1486) -> dict:
    """
    ETF 采集管线：
    1. 同步 ETF 列表（etfs 表）
    2. 实时行情快照写入 etf_quotes（含 IOPV/溢价率/换手率等全字段）
       - trade_date = today
       - 每只ETF仅写一条，不覆盖历史K线
    3. 历史K线追加（独立于实时行情，不清空 IOPV 字段）

    Args:
        days: 历史K线回溯天数
        limit: 最多采集的ETF数量（默认1486=全量）
    """
    result = {"started_at": datetime.now().isoformat(), "steps": {}}
    today = date.today()
    start_date = today - timedelta(days=days)

    minio_loader.ensure_buckets()

    # Step 1: 同步 ETF 列表（etfs 表）
    t0 = time.time()
    etf_spot = etf_collector.fetch_etf_spot()
    sync_result = etf_collector.sync_etfs_to_db(etf_spot)
    result["steps"]["etf_list"] = {"total": len(etf_spot), **sync_result, "elapsed_s": round(time.time() - t0, 2)}

    # Step 2: 实时行情快照 → etf_quotes（trade_date = today）
    # 全量采集，IOPV/溢价率/换手率等字段完整
    t0 = time.time()
    spot_records = []
    for etf in etf_spot[:limit]:
        spot_records.append({
            "etf_code": etf["code"],
            "trade_date": today.isoformat(),
            "open_price": etf.get("open_price"),
            "high_price": etf.get("high_price"),
            "low_price": etf.get("low_price"),
            "close_price": etf.get("latest_price"),
            "pre_close": etf.get("pre_close"),
            "iopv": etf.get("iopv"),
            "premium_rate": etf.get("premium_rate"),
            "discount_rate": etf.get("discount_rate"),
            "volume": etf.get("volume"),
            "amount": etf.get("amount"),
            "turnover_rate": etf.get("turnover_rate"),
            "amplitude": etf.get("amplitude"),
            "change_pct": etf.get("change_pct"),
            "change_amount": etf.get("change_amount"),
            "source": "akshare-spot",
        })
    if spot_records:
        minio_loader.store_json(spot_records, mc.bucket_bronze_quotes, "etf/spot", today)
        pg_loader.batch_upsert_etf_quotes(spot_records)
    result["steps"]["etf_spot"] = {"etfs": len(spot_records), "elapsed_s": round(time.time() - t0, 2)}

    # Step 3: 历史K线（独立追加，不影响今日的实时字段）
    # days=1 时跳过：今日已有实时快照，历史K线会导致 IOPV 等字段被 NULL 覆盖
    if days > 1:
        target_etfs = etf_spot[:limit]
        t0 = time.time()
        k_total = 0
        for etf in target_etfs:
            code = etf["code"]
            hist = etf_collector.fetch_etf_hist(code, start_date=start_date, end_date=today)
            if hist:
                normalized = []
                for r in hist:
                    rec = {
                        "etf_code": code,
                        "trade_date": r["date"],
                        "open_price": r["open"],
                        "high_price": r["high"],
                        "low_price": r["low"],
                        "close_price": r["close"],
                        "volume": r["volume"],
                        "amount": r["amount"],
                        "source": "akshare-hist",
                        "iopv": None,
                        "premium_rate": None,
                        "discount_rate": None,
                        "pre_close": None,
                        "change_pct": None,
                        "change_amount": None,
                        "amplitude": None,
                        "turnover_rate": None,
                    }
                    normalized.append(rec)
                minio_loader.store_json(normalized, mc.bucket_bronze_quotes, f"etf/kline/{code}", today)
                pg_loader.batch_upsert_etf_quotes(normalized)
                k_total += len(normalized)
            time.sleep(cc.request_interval)
        result["steps"]["etf_quotes"] = {"etfs": len(target_etfs), "records": k_total, "elapsed_s": round(time.time() - t0, 2)}
    else:
        result["steps"]["etf_quotes"] = {"etfs": 0, "records": 0, "note": "days=1, skipped (today already has real-time snapshot)"}

    result["finished_at"] = datetime.now().isoformat()
    return result


def run_etf_spot_only(limit: int = 1486) -> dict:
    """
    仅采集 ETF 实时行情（快速，不含历史K线）。
    用于日内定时刷新。
    """
    result = {"started_at": datetime.now().isoformat(), "steps": {}}
    today = date.today()

    t0 = time.time()
    etf_spot = etf_collector.fetch_etf_spot()
    spot_records = []
    for etf in etf_spot[:limit]:
        spot_records.append({
            "etf_code": etf["code"],
            "trade_date": today.isoformat(),
            "open_price": etf.get("open_price"),
            "high_price": etf.get("high_price"),
            "low_price": etf.get("low_price"),
            "close_price": etf.get("latest_price"),
            "pre_close": etf.get("pre_close"),
            "iopv": etf.get("iopv"),
            "premium_rate": etf.get("premium_rate"),
            "discount_rate": etf.get("discount_rate"),
            "volume": etf.get("volume"),
            "amount": etf.get("amount"),
            "turnover_rate": etf.get("turnover_rate"),
            "amplitude": etf.get("amplitude"),
            "change_pct": etf.get("change_pct"),
            "change_amount": etf.get("change_amount"),
            "source": "akshare-spot",
        })
    if spot_records:
        minio_loader.store_json(spot_records, mc.bucket_bronze_quotes, "etf/spot", today)
        pg_loader.batch_upsert_etf_quotes(spot_records)
    result["steps"]["etf_spot"] = {"etfs": len(spot_records), "elapsed_s": round(time.time() - t0, 2)}
    result["finished_at"] = datetime.now().isoformat()
    return result
