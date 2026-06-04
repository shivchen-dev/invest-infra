"""Phase 1 数据采集管线主编排器"""

import logging

logger = logging.getLogger(__name__)

import time
from datetime import date, datetime, timedelta
from typing import Optional

from src.config import collector as cc, minio as mc, rsscast as rc, pg as pg_cfg
from src.collector import companies, quotes, financial, news
from src.collector import rsscast as rsscast_collector
from src.collector import etf as etf_collector
from src.collector import cifang as cifang_collector
from src.loader import minio as minio_loader, pg as pg_loader
from src.loader.pg import backfill_financial_assets

from src.pipeline.error_isolation import safe_step


def run_cifang_etf_spot(limit: int = 1486) -> dict:
    """
    用次方量化 API 采集 ETF 实时行情，写入 PG etf_quotes 表。
    不依赖 boto3/minio，独立运行。
    """
    import time
    result = {"started_at": datetime.now().isoformat(), "steps": {}, "source": "cifang"}
    today = date.today()

    t0 = time.time()
    spot_data = cifang_collector.fetch_fund_spot()
    if not spot_data:
        logger.warning("次方量化实时行情为空，跳过写入")
        result["steps"]["cifang_spot"] = {"etfs": 0, "elapsed_s": 0, "note": "empty response"}
        result["finished_at"] = datetime.now().isoformat()
        return result

    written = cifang_collector.write_spot_to_etf_quotes(spot_data, today)
    result["steps"]["cifang_spot"] = {"etfs": written, "elapsed_s": round(time.time() - t0, 2)}
    result["finished_at"] = datetime.now().isoformat()
    return result

WIDE_INDEX_CODES = ["000001", "399001", "000300", "000016", "000688", "399006", "000905", "000852"]


def _build_etf_spot_records(etf_spot: list[dict], today: date, limit: int) -> list[dict]:
    """构建 ETF 实时行情记录，供 run_etf_pipeline 和 run_etf_spot_only 共用"""
    records = []
    for etf in etf_spot[:limit]:
        records.append({
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
    return records


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
    step_result = {"count": 0, "synced": 0, "elapsed_s": 0}
    try:
        all_companies = companies.fetch_all_companies()
        sync_result = companies.sync_to_db(all_companies)
        step_result = {"count": len(all_companies), **sync_result}
    except Exception as e:
        logger.error(f"[run_all] companies 步骤异常: {e}")
        step_result["error"] = str(e)[:200]
        all_companies = []
    result["steps"]["companies"] = {**step_result, "elapsed_s": round(time.time() - t0, 2)}

    codes = stock_codes or [c["code"] for c in all_companies]
    batch_codes = codes[:limit]
    start_date = today - timedelta(days=cc.quotes_history_days)

    # Step 2: 股票行情
    t0 = time.time()
    q_total = 0
    q_errors = 0
    for code in batch_codes:
        try:
            batch = quotes.fetch_quotes(code, start_date=start_date, end_date=today)
            if batch:
                q_total += len(batch)
                minio_loader.store_json(batch, mc.bucket_bronze_quotes, "quotes/daily", today)
                pg_loader.batch_upsert_quotes(batch)
        except Exception as e:
            q_errors += 1
            logger.warning(f"[run_all] quotes.fetch_quotes({code}) 失败: {e}")
        time.sleep(cc.request_interval)
    result["steps"]["quotes"] = {"stocks": len(batch_codes), "records": q_total, "errors": q_errors, "elapsed_s": round(time.time() - t0, 2)}

    # Step 3: 财报
    t0 = time.time()
    fr_total = 0
    fr_errors = 0
    for code in batch_codes:
        try:
            batch = financial.fetch_financial_report(code)
            if batch:
                fr_total += len(batch)
                minio_loader.store_json(batch, mc.bucket_bronze_financial, "financial/reports", today)
                pg_loader.batch_upsert_financial(batch)
        except Exception as e:
            fr_errors += 1
            logger.warning(f"[run_all] financial.fetch_financial_report({code}) 失败: {e}")
        time.sleep(cc.request_interval)
    result["steps"]["financial"] = {"stocks": len(batch_codes), "records": fr_total, "errors": fr_errors, "elapsed_s": round(time.time() - t0, 2)}

    # Step 3b: 财务指标补录
    t0 = time.time()
    fi_total = 0
    fi_errors = 0
    for code in batch_codes:
        try:
            indicator_batch = financial.fetch_financial_indicator(code, start_year=2020)
            if indicator_batch:
                fi_total += len(indicator_batch)
                minio_loader.store_json(indicator_batch, mc.bucket_bronze_financial, "financial/indicator", today)
                backfill_financial_assets(indicator_batch)
        except Exception as e:
            fi_errors += 1
            logger.warning(f"[run_all] financial.fetch_financial_indicator({code}) 失败: {e}")
        time.sleep(cc.request_interval)
    result["steps"]["financial_indicator"] = {"stocks": len(batch_codes), "records": fi_total, "errors": fi_errors, "elapsed_s": round(time.time() - t0, 2)}

    # Step 4: 新闻
    t0 = time.time()
    n_total = 0
    n_errors = 0
    for code in batch_codes:
        try:
            batch = news.fetch_stock_news(code)
            if batch:
                n_total += len(batch)
                minio_loader.store_json(batch, mc.bucket_bronze_news, "news/stock", today)
                pg_loader.batch_upsert_news(batch)
        except Exception as e:
            n_errors += 1
            logger.warning(f"[run_all] news.fetch_stock_news({code}) 失败: {e}")
        time.sleep(cc.request_interval)
    result["steps"]["news"] = {"stocks": len(batch_codes), "records": n_total, "errors": n_errors, "elapsed_s": round(time.time() - t0, 2)}

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
    step_result = {"count": 0, "synced": 0, "elapsed_s": 0}
    try:
        all_companies = companies.fetch_all_companies()
        sync_result = companies.sync_to_db(all_companies)
        step_result = {"count": len(all_companies), **sync_result}
    except Exception as e:
        logger.error(f"[run_all_via_rsscast] companies 步骤异常: {e}")
        step_result["error"] = str(e)[:200]
        all_companies = []
    result["steps"]["companies"] = {**step_result, "elapsed_s": round(time.time() - t0, 2)}

    codes = stock_codes or [c["code"] for c in all_companies]
    batch_codes = codes[:limit]

    # Step 2: 股票行情 → daily_quotes
    t0 = time.time()
    q_total = 0
    q_errors = 0
    try:
        realtime = rsscast_collector.fetch_stock_quotes_normalized(batch_codes)
        if realtime:
            q_total += len(realtime)
            minio_loader.store_json(realtime, mc.bucket_bronze_quotes, "quotes/daily", today)
            pg_loader.batch_upsert_quotes(realtime)
    except Exception as e:
        q_errors += 1
        logger.warning(f"[run_all_via_rsscast] fetch_stock_quotes_normalized 失败: {e}")
    try:
        klines = rsscast_collector.fetch_stock_kline_normalized(batch_codes, start_date=start_date, end_date=today)
        if klines:
            q_total += len(klines)
            minio_loader.store_json(klines, mc.bucket_bronze_quotes, "quotes/kline", today)
            pg_loader.batch_upsert_quotes(klines)
    except Exception as e:
        q_errors += 1
        logger.warning(f"[run_all_via_rsscast] fetch_stock_kline_normalized 失败: {e}")
    result["steps"]["quotes"] = {"stocks": len(batch_codes), "records": q_total, "errors": q_errors, "elapsed_s": round(time.time() - t0, 2)}

    # Step 3: 指数行情 → index_quotes
    t0 = time.time()
    i_total = 0
    i_errors = 0
    try:
        idx_realtime = rsscast_collector.fetch_index_quotes_normalized(WIDE_INDEX_CODES)
        if idx_realtime:
            i_total += len(idx_realtime)
            minio_loader.store_json(idx_realtime, mc.bucket_bronze_quotes, "index/daily", today)
            pg_loader.batch_upsert_index_quotes(idx_realtime)
    except Exception as e:
        i_errors += 1
        logger.warning(f"[run_all_via_rsscast] fetch_index_quotes_normalized 失败: {e}")
    try:
        idx_klines = rsscast_collector.fetch_index_kline_normalized(WIDE_INDEX_CODES, start_date=start_date, end_date=today)
        if idx_klines:
            i_total += len(idx_klines)
            minio_loader.store_json(idx_klines, mc.bucket_bronze_quotes, "index/kline", today)
            pg_loader.batch_upsert_index_quotes(idx_klines)
    except Exception as e:
        i_errors += 1
        logger.warning(f"[run_all_via_rsscast] fetch_index_kline_normalized 失败: {e}")
    result["steps"]["indices"] = {"indices": len(WIDE_INDEX_CODES), "records": i_total, "errors": i_errors, "elapsed_s": round(time.time() - t0, 2)}

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
    step_result = {"total": 0, "synced": 0, "elapsed_s": 0}
    try:
        etf_spot = etf_collector.fetch_etf_spot()
        sync_result = etf_collector.sync_etfs_to_db(etf_spot)
        step_result = {"total": len(etf_spot), **sync_result}
    except Exception as e:
        logger.error(f"[run_etf_pipeline] etf_list 步骤异常: {e}")
        step_result["error"] = str(e)[:200]
        etf_spot = []
    result["steps"]["etf_list"] = {**step_result, "elapsed_s": round(time.time() - t0, 2)}

    # Step 2: 实时行情快照 → etf_quotes（trade_date = today）
    t0 = time.time()
    spot_errors = 0
    try:
        spot_records = _build_etf_spot_records(etf_spot, today, limit)
        if spot_records:
            minio_loader.store_json(spot_records, mc.bucket_bronze_quotes, "etf/spot", today)
            pg_loader.batch_upsert_etf_quotes(spot_records)
    except Exception as e:
        spot_errors += 1
        logger.warning(f"[run_etf_pipeline] etf_spot 写入失败: {e}")
    result["steps"]["etf_spot"] = {"etfs": len(spot_records) if etf_spot else 0, "errors": spot_errors, "elapsed_s": round(time.time() - t0, 2)}

    if days > 1:
        target_etfs = etf_spot[:limit]
        t0 = time.time()
        k_total = 0
        k_errors = 0
        for etf in target_etfs:
            try:
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
                            "iopv": -1, "premium_rate": -1, "discount_rate": -1,
                            "pre_close": -1, "change_pct": -1, "change_amount": -1,
                            "amplitude": -1, "turnover_rate": -1,
                        }
                        normalized.append(rec)
                    minio_loader.store_json(normalized, mc.bucket_bronze_quotes, f"etf/kline/{code}", today)
                    pg_loader.batch_upsert_etf_quotes(normalized)
                    k_total += len(normalized)
            except Exception as e:
                k_errors += 1
                logger.warning(f"[run_etf_pipeline] fetch_etf_hist({etf.get('code')}) 失败: {e}")
            time.sleep(cc.request_interval)
        result["steps"]["etf_quotes"] = {"etfs": len(target_etfs), "records": k_total, "errors": k_errors, "elapsed_s": round(time.time() - t0, 2)}
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
    spot_records = _build_etf_spot_records(etf_spot, today, limit)
    if spot_records:
        minio_loader.store_json(spot_records, mc.bucket_bronze_quotes, "etf/spot", today)
        pg_loader.batch_upsert_etf_quotes(spot_records)
    result["steps"]["etf_spot"] = {"etfs": len(spot_records), "elapsed_s": round(time.time() - t0, 2)}
    result["finished_at"] = datetime.now().isoformat()
    return result