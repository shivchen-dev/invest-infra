"""PostgreSQL 批量数据写入 — Silver 层入库"""

import logging
import math
import time
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_batch

from src.config import pg

logger = logging.getLogger(__name__)

# 模块级连接池，min=1 max=4 在单 pipeline 调用场景下足够
_cn_pool: Optional[pool.ThreadedConnectionPool] = None


def _get_pool() -> pool.ThreadedConnectionPool:
    global _cn_pool
    if _cn_pool is None:
        _cn_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=4,
            dsn=pg.uri,
            connection_factory=None,
        )
    return _cn_pool


def _release_pool():
    global _cn_pool
    if _cn_pool is not None:
        _cn_pool.closeall()
        _cn_pool = None


@contextmanager
def get_conn():
    """从池中获取连接，用完自动归还"""
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        p.putconn(conn)


def _nan_to_none(v):
    """过滤 NaN/Inf → None（BIGINT 字段不接受 NaN）；保留 -1 sentinel 值"""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except TypeError:
        pass
    # sentinel 值保留，调用方用 NULLIF(-1, -1) 转为 NULL
    return v


def _normalize_date(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str) and "T" in v:
        return v.split("T")[0]
    return v


def log_audit(conn, source: str, trade_date, total: int, written: int, skipped: int, status: str, error_msg: str = None, duration_ms: int = 0):
    """写入审计日志到 data_source_log 表"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO data_source_log
                    (source, trade_date, records_total, records_written, records_skipped,
                     status, error_message, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (source, _normalize_date(trade_date) if trade_date else None,
                  total, written, skipped, status,
                  error_msg[:500] if error_msg else None, duration_ms))
            conn.commit()
    except Exception as e:
        logger.error(f"审计日志写入失败: {e}")


# ── 公司 ────────────────────────────────────────────────────────

def get_company_id_map(conn) -> dict[str, int]:
    """返回 {code_stripped: id}，code 去掉 .SZ/.SH/.BJ 后缀"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM companies")
        return {row[0].split(".")[0]: row[1] for row in cur.fetchall()}


def batch_upsert_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("trade_date")
    with get_conn() as conn:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_price")),
                _nan_to_none(r.get("high_price")),
                _nan_to_none(r.get("low_price")),
                _nan_to_none(r.get("close_price")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("turnover_rate")),
                _nan_to_none(r.get("amplitude")),
                _nan_to_none(r.get("change_pct")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO daily_quotes
                        (company_id, trade_date, open_price, high_price, low_price,
                         close_price, pre_close, volume, amount, turnover_rate,
                         amplitude, change_pct, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (company_id, trade_date) DO UPDATE SET
                        open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
                        low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
                        pre_close=EXCLUDED.pre_close, volume=EXCLUDED.volume,
                        amount=EXCLUDED.amount, turnover_rate=EXCLUDED.turnover_rate,
                        amplitude=EXCLUDED.amplitude, change_pct=EXCLUDED.change_pct
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "quotes", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"行情入库:写入 {len(rows)}, 跳过 {skipped}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "quotes", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"行情入库失败: {e}")
            raise


def batch_upsert_financial(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("report_date")
    with get_conn() as conn:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                r.get("report_date"),
                r.get("report_type"),
                r.get("fiscal_year"),
                _nan_to_none(r.get("revenue")),
                _nan_to_none(r.get("cost_of_sales")),
                _nan_to_none(r.get("net_profit")),
                _nan_to_none(r.get("parent_net_profit")),
                _nan_to_none(r.get("total_assets")),
                _nan_to_none(r.get("total_liabilities")),
                _nan_to_none(r.get("total_equity")),
                _nan_to_none(r.get("operating_cf")),
                _nan_to_none(r.get("roa_raw")),
                _nan_to_none(r.get("debt_ratio_raw")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO financial_reports
                        (company_id, report_date, report_type, fiscal_year,
                         revenue, cost_of_sales, net_profit, parent_net_profit,
                         total_assets, total_liabilities, total_equity,
                         operating_cf, roa_raw, debt_ratio_raw, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (company_id, report_date, report_type) DO UPDATE SET
                        revenue=EXCLUDED.revenue, cost_of_sales=EXCLUDED.cost_of_sales,
                        net_profit=EXCLUDED.net_profit,
                        parent_net_profit=EXCLUDED.parent_net_profit,
                        total_assets=EXCLUDED.total_assets,
                        total_liabilities=EXCLUDED.total_liabilities,
                        total_equity=EXCLUDED.total_equity,
                        operating_cf=EXCLUDED.operating_cf,
                        roa_raw=EXCLUDED.roa_raw,
                        debt_ratio_raw=EXCLUDED.debt_ratio_raw
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "financial", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"财报入库: 写入 {len(rows)}, 跳过 {skipped}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "financial", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"财报入库失败: {e}")
            raise


def backfill_financial_assets(records: list[dict]) -> dict:
    """
    回填 financial_reports 表中缺失的 total_assets 和 total_liabilities。
    ON CONFLICT 时仅更新这两个字段，不触动已有数据。
    """
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("report_date")
    with get_conn() as conn:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rd = r.get("report_date")
            fiscal_year = rd.year if rd else None
            rows.append((
                cid,
                r.get("report_date"),
                r.get("report_type"),
                fiscal_year,
                _nan_to_none(r.get("total_assets")),
                _nan_to_none(r.get("total_liabilities")),
                _nan_to_none(r.get("roa_raw")),
                _nan_to_none(r.get("debt_ratio_raw")),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO financial_reports
                        (company_id, report_date, report_type, fiscal_year,
                         total_assets, total_liabilities, roa_raw, debt_ratio_raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (company_id, report_date, report_type) DO UPDATE SET
                        total_assets      = COALESCE(EXCLUDED.total_assets,      financial_reports.total_assets),
                        total_liabilities = COALESCE(EXCLUDED.total_liabilities, financial_reports.total_liabilities),
                        fiscal_year       = COALESCE(EXCLUDED.fiscal_year,       financial_reports.fiscal_year),
                        roa_raw           = COALESCE(EXCLUDED.roa_raw,           financial_reports.roa_raw),
                        debt_ratio_raw    = COALESCE(EXCLUDED.debt_ratio_raw,    financial_reports.debt_ratio_raw)
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "financial_assets", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"资产/负债回填: 写入 {len(rows)}, 跳过 {skipped}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "financial_assets", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"资产/负债回填失败: {e}")
            raise


def batch_upsert_news(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("published_at")
    with get_conn() as conn:
        code_map = get_company_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            raw_code = r.get("stock_code", "")
            code_key = raw_code.split(".")[0]
            cid = code_map.get(code_key)
            if cid is None:
                skipped += 1
                continue
            rows.append((
                cid,
                r.get("title", ""),
                str(r.get("content_summary", ""))[:500],
                r.get("source_name", ""),
                r.get("source_url", ""),
                r.get("published_at"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO news_articles
                        (company_id, title, content_summary, source_name, source_url, published_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "news", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"新闻入库: 写入 {len(rows)}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "news", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"新闻入库失败: {e}")
            raise


# ── 指数 ────────────────────────────────────────────────────────

def get_index_id_map(conn) -> dict[str, int]:
    """返回 {code: id} 映射"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM indices")
        return {row[0]: row[1] for row in cur.fetchall()}


def batch_upsert_index_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("trade_date")
    with get_conn() as conn:
        idx_map = get_index_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            idx_id = idx_map.get(r.get("index_code", ""))
            if idx_id is None:
                skipped += 1
                continue
            rows.append((
                idx_id,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_point")),
                _nan_to_none(r.get("high_point")),
                _nan_to_none(r.get("low_point")),
                _nan_to_none(r.get("close_point")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("change_pct")),
                _nan_to_none(r.get("amplitude")),
                r.get("source", "rsscast"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO index_quotes
                        (index_id, trade_date, open_point, high_point, low_point,
                         close_point, pre_close, volume, amount, change_pct, amplitude, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (index_id, trade_date) DO UPDATE SET
                        open_point=EXCLUDED.open_point, high_point=EXCLUDED.high_point,
                        low_point=EXCLUDED.low_point, close_point=EXCLUDED.close_point,
                        pre_close=EXCLUDED.pre_close, volume=EXCLUDED.volume,
                        amount=EXCLUDED.amount, change_pct=EXCLUDED.change_pct,
                        amplitude=EXCLUDED.amplitude
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "index_quotes", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"指数行情入库: 写入 {len(rows)}, 跳过 {skipped}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "index_quotes", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"指数行情入库失败: {e}")
            raise


# ── ETF ─────────────────────────────────────────────────────────

def get_etf_id_map(conn) -> dict[str, int]:
    """返回 {code: id} 映射"""
    with conn.cursor() as cur:
        cur.execute("SELECT code, id FROM etfs")
        return {row[0]: row[1] for row in cur.fetchall()}


def batch_upsert_etf_quotes(records: list[dict]) -> dict:
    if not records:
        return {"written": 0}
    start_time = time.time()
    trade_date = records[0].get("trade_date")
    with get_conn() as conn:
        etf_map = get_etf_id_map(conn)
        rows, skipped = [], 0
        for r in records:
            etf_id = etf_map.get(r.get("etf_code", ""))
            if etf_id is None:
                skipped += 1
                continue
            rows.append((
                etf_id,
                _normalize_date(r.get("trade_date")),
                _nan_to_none(r.get("open_price")),
                _nan_to_none(r.get("high_price")),
                _nan_to_none(r.get("low_price")),
                _nan_to_none(r.get("close_price")),
                _nan_to_none(r.get("pre_close")),
                _nan_to_none(r.get("iopv")),
                _nan_to_none(r.get("premium_rate")),
                _nan_to_none(r.get("discount_rate")),
                _nan_to_none(r.get("volume")),
                _nan_to_none(r.get("amount")),
                _nan_to_none(r.get("turnover_rate")),
                _nan_to_none(r.get("amplitude")),
                _nan_to_none(r.get("change_pct")),
                _nan_to_none(r.get("change_amount")),
                r.get("source", "akshare"),
            ))

        if not rows:
            return {"written": 0, "skipped": skipped}

        try:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    INSERT INTO etf_quotes
                        (etf_id, trade_date, open_price, high_price, low_price,
                         close_price, pre_close, iopv, premium_rate, discount_rate,
                         volume, amount, turnover_rate, amplitude, change_pct,
                         change_amount, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (etf_id, trade_date) DO UPDATE SET
                        open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
                        low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
                        volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                        pre_close=COALESCE(NULLIF(EXCLUDED.pre_close,-1), etf_quotes.pre_close),
                        iopv=COALESCE(NULLIF(EXCLUDED.iopv,-1), etf_quotes.iopv),
                        premium_rate=COALESCE(NULLIF(EXCLUDED.premium_rate,-1), etf_quotes.premium_rate),
                        discount_rate=COALESCE(NULLIF(EXCLUDED.discount_rate,-1), etf_quotes.discount_rate),
                        turnover_rate=COALESCE(NULLIF(EXCLUDED.turnover_rate,-1), etf_quotes.turnover_rate),
                        amplitude=COALESCE(NULLIF(EXCLUDED.amplitude,-1), etf_quotes.amplitude),
                        change_pct=COALESCE(NULLIF(EXCLUDED.change_pct,-1), etf_quotes.change_pct),
                        change_amount=COALESCE(NULLIF(EXCLUDED.change_amount,-1), etf_quotes.change_amount)
                    WHERE NOT (EXCLUDED.source = 'akshare-hist' AND etf_quotes.source = 'akshare-spot')
                """, rows)
            conn.commit()
            duration_ms = int((time.time() - start_time) * 1000)
            status = "success" if skipped == 0 else "partial"
            log_audit(conn, "etf_quotes", trade_date, len(records), len(rows), skipped, status, None, duration_ms)
            logger.info(f"ETF行情入库: 写入 {len(rows)}, 跳过 {skipped}")
            return {"written": len(rows), "skipped": skipped}
        except Exception as e:
            conn.rollback()
            duration_ms = int((time.time() - start_time) * 1000)
            log_audit(conn, "etf_quotes", trade_date, len(records), 0, skipped, "failed", str(e), duration_ms)
            logger.error(f"ETF行情入库失败: {e}")
            raise
